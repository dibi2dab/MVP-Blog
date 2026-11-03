from __future__ import annotations

from pathlib import Path

from src.charts.analysis_chart_generator import AnalysisChartGenerator
from src.charts.chart_selector import ChartSelector
from src.analyzers.ai_provider import ProviderFactory
from src.analyzers.quality_checker import QualityChecker
from src.config.settings import Settings
from src.models.analysis import AnalysisReport
from src.models.article import Article, ArticleImage
from src.models.event import Event
from src.models.research_packet import ResearchPacket
from src.scoring.evidence_scoring import EvidenceScorer, decide_publication_type
from src.storage.file_store import JsonStore
from src.utils.cache import DiskCache
from src.utils.logging import get_logger
from src.writers.article_writer import ArticleWriter
from src.writers.markdown_generator import MarkdownGenerator
from src.writers.seo_generator import SeoGenerator

logger = get_logger(__name__)

_IMAGE_POSITION = {
    "price_volume": "price_analysis",
    "volume_ratio": "volume_analysis",
    "financial": "financial_overview",
}

_DEFAULT_IMAGE_POSITION = "overview"


class GenerateStep:
    """차트 생성 -> 기사 작성 -> SEO -> Markdown -> 품질 검수.

    발행 유형(A/B/C)을 결정하고, 근거 부족 & 데이터 분석 가치도 없는 경우(Type C)는
    기사를 작성·발행하지 않는다.
    """

    def __init__(self, settings: Settings, store: JsonStore) -> None:
        self.settings = settings
        self.store = store
        cache = DiskCache(str(settings.storage.path("cache")), ttl_seconds=settings.ai.cache_ttl_seconds)
        self.provider = ProviderFactory(settings, cache=cache).build()
        self.article_writer = ArticleWriter(self.provider, settings)
        self.seo = SeoGenerator(banned_title_phrases=settings.content_quality.banned_title_phrases)
        self.md_gen = MarkdownGenerator(include_disclaimer=settings.markdown.include_disclaimer)
        self.quality = QualityChecker(self.provider, settings, include_disclaimer=settings.markdown.include_disclaimer)
        self.chart_gen = AnalysisChartGenerator(settings)
        self.chart_selector = ChartSelector()
        self.evidence = EvidenceScorer(settings)

    def run(self, event: Event, packet: ResearchPacket, report: AnalysisReport) -> Article | None:
        logger.info("[generate] writing article for %s", event.event_id)

        # 1) 근거 점수 + 발행 유형 결정
        ev_r = self.evidence.evaluate(packet)
        pub_type = decide_publication_type(
            event_score=event.event_score,
            evidence_score=ev_r.score,
            has_price_data=packet.market_data is not None,
            has_volume_data=packet.market_data is not None and packet.market_data.volume_ratio is not None,
            min_event_score=self.settings.scoring.minimum_research_score,
        )
        event.set_evidence(ev_r.score, pub_type)

        if pub_type == "C":
            logger.info(
                "[generate] type C reject %s (event=%d evid=%d) 근거/분석가치 부족",
                event.event_id,
                event.event_score,
                ev_r.score,
            )
            event.set_status("rejected")
            self.store.save_event(event)
            self.store.save_analysis(report)
            return None

        logger.info(
            "[generate] %s type=%s event=%d evid=%d (%s)",
            event.event_id,
            pub_type,
            event.event_score,
            ev_r.score,
            ev_r.detail,
        )

        # 2) 기사 작성 (발행 유형 + 근거 반영)
        article = self.article_writer.build(event, packet, report, publication_type=pub_type, evidence=ev_r)

        # 3) SEO (근거 기반 제목)
        title_evidence = {
            "latest_change_pct": packet.market_data.latest_change_pct if packet.market_data else None,
            "volume_ratio": packet.market_data.volume_ratio if packet.market_data else None,
        }
        article.title = self.seo.title(event, publication_type=pub_type, evidence=title_evidence)
        article.slug = self.seo.slug(article.title)
        article.tags = self.seo.tags(event)
        article.keywords = self.seo.keywords(event)
        article.description = self.seo.description(event, self._preview(packet, report))
        article.frontmatter = self.seo.frontmatter(article)

        # 4) 차트 생성 + 본문 이미지 메타데이터 저장 (로컬 경로, 최종 URL 아님)
        charts = []
        for spec in self.chart_selector.select(event):
            chart = self.chart_gen.generate(spec, packet)
            if chart:
                charts.append(chart)
                article.chart_paths.append(chart.path)
                article.external_chart_embeds.append(chart.rel_url)
                article.images.append(
                    ArticleImage(
                        local_path=chart.path,
                        alt=chart.caption or chart.title,
                        position=_IMAGE_POSITION.get(chart.chart_type, _DEFAULT_IMAGE_POSITION),
                    )
                )

        markdown = self.md_gen.to_markdown(article, charts=charts, external_embeds=None)
        article.body_markdown = markdown
        article.content_hash = _hash(markdown)

        # 5) 품질 검수
        qc = self.quality.check(article, markdown)
        if report.fact_check.verdict != "pass":
            logger.warning("[generate] article %s fact-check %s", article.article_id, report.fact_check.verdict)

        if qc.passed:
            logger.info("[generate] quality passed score=%.2f", qc.score)
            article.status = "approved"
            event.set_status("verified")
        else:
            logger.warning("[generate] quality issues: %s", qc.issues[:5])
            article.status = "quality_blocked"
            event.set_status("failed")
        report.quality_check = qc
        self.store.save_event(event)
        self.store.save_analysis(report)

        self.store.save_article(article)
        if article.status == "approved":
            self._write_markdown(article, markdown)
        return article if article.status == "approved" else None

    def _preview(self, packet: ResearchPacket, report: AnalysisReport) -> str:
        return " ".join(c.claim for c in report.actionable_claims()[:3]).strip()

    def _write_markdown(self, article: Article, markdown: str) -> None:
        category = self.settings.content.categories.get(article.category, article.category)
        out = Path(self.settings.content.output_dir) / category
        out.mkdir(parents=True, exist_ok=True)
        date = article.created_at[:10]
        path = out / f"{date}-{article.slug}.md"
        path.write_text(markdown, encoding="utf-8")
        logger.info("[generate] markdown saved: %s", path)


def _hash(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest()