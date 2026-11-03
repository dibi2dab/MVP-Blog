from __future__ import annotations

import json
import re
from datetime import datetime

from src.analyzers.ai_provider import AIProvider
from src.config.settings import Settings
from src.models.analysis import AnalysisReport, Claim
from src.models.article import Article, ArticleSection
from src.models.event import Event
from src.models.research_packet import ResearchPacket
from src.scoring.evidence_scoring import EvidenceResult
from src.scoring.relevance_scoring import SourceRelevanceScorer
from src.utils.korean import format_korean_date, topic_after
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """당신은 금융 분석 기사 작성자다.
반드시 아래 수칙을 따른다:
1. 제공된 [VERIFIED FACTS] 에만 근거하여 작성한다.
2. 제공되지 않은 수치, 회사, 사건은 절대 언급하지 않는다.
3. 원인이 불명확하면 "현재 공개된 자료만으로 단일 원인을 단정하기 어렵다"고 쓴다.
4. 확정 표현과 추측 표현을 구분한다. "~가능성이 있다"는 추측 표현만 허용.
5. 투자 권유 문구를 쓰지 않는다. 매수/매도 추천 금지.
6. 각 문단은 2~4 문장으로 간결하게. 어조는 신문 기사체, 중립적.
7. 동일한 숫자(가격, 거래량 비율)를 여러 문단에서 반복하지 않는다.
8. 각 주요 데이터는 FACT -> CONTEXT -> INTERPRETATION -> LIMITATION 순서로 서술한다.
응답은 반드시 JSON:
{"section_text": "..."}
"""


class ArticleWriter:
    """Agent 3 — 검증된 데이터 + 발행 유형에 맞게 기사 작성.

    발행 유형에 따라 섹션을 조건부로 구성한다.
    - Type A (Deep Analysis): 근거가 충분 → 원인 중심 심층 구조
    - Type B (Data Brief): 근거 부족 → 사실 중심 브리핑 구조
    - Type C (Reject): 본 writer 호출 전 generate_step 에서 거른다.

    개선 사항 적용 (금융 콘텐츠 가독성·심층 분석):
    - 핵심 요약(Executive Summary) / 핵심 데이터 카드
    - FACT -> CONTEXT -> INTERPRETATION -> LIMITATION 구조
    - 최소 문단 깊이, 데이터 반복 제한, 구체적 향후 포인트
    - Source Relevance Filter 로 관련 뉴스·공시만 본문 포함
    """

    def __init__(self, provider: AIProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings
        self.relevance = SourceRelevanceScorer

    def build(
        self,
        event: Event,
        packet: ResearchPacket,
        report: AnalysisReport,
        publication_type: str = "B",
        evidence: EvidenceResult | None = None,
    ) -> Article:
        verified = report.actionable_claims()
        evidence = evidence or EvidenceResult()
        sections = self._build_sections(event, packet, verified, publication_type, evidence)
        return Article(
            article_id=f"a_{event.event_id}",
            event=event,
            title="",  # SEO 타이틀은 게시 단계에서 확정
            slug="",
            description="",
            category="stocks",
            sections=sections,
            analysis_report=report,
            sources=sorted({s.name for s in packet.sources}),
            frontmatter={},
        )

    # ------------------------------------------------------------------ #
    #  섹션 선택 (조건부)
    # ------------------------------------------------------------------ #
    def _build_sections(
        self,
        event: Event,
        packet: ResearchPacket,
        verified: list[Claim],
        publication_type: str,
        evidence: EvidenceResult,
    ) -> list[ArticleSection]:
        if publication_type == "A":
            return self._build_deep_analysis(event, packet, verified, evidence)
        return self._build_data_brief(event, packet, verified, evidence)

    def _build_data_brief(
        self,
        event: Event,
        packet: ResearchPacket,
        verified: list[Claim],
        evidence: EvidenceResult,
    ) -> list[ArticleSection]:
        used: dict[str, bool] = {}  # 데이터 반복 방지 트래커
        sections: list[ArticleSection] = []
        ctx = _Context(event, packet, used, evidence, self.settings)

        # 0) 핵심 요약 (Executive Summary) — 제목 바로 아래
        sections.append(ArticleSection(heading="", body=ctx.executive_summary(mode="brief")))

        # 0-1) 핵심 데이터 카드 (본문 초반)
        sections.append(ArticleSection(heading="핵심 데이터", body=ctx.data_card()))

        # 1) 오늘 주가 흐름
        sections.append(ArticleSection(heading="오늘 주가 흐름", body=ctx.price_section()))

        # 2) 거래량과 시장 참여 변화
        if ctx.market is not None and ctx.market.volume_ratio is not None:
            sections.append(ArticleSection(heading="거래량과 시장 참여 변화", body=ctx.volume_section()))

        # 3) 수급 변화
        if ctx.market is not None and ctx.market.foreign_net_buy is not None:
            sections.append(ArticleSection(heading="수급 변화", body=ctx.flow_section()))

        # 4) 확인된 뉴스와 재료 — 관련성 필터 통과한 것만, 서술형
        if ctx.packet.news:
            narrative = ctx.news_section()
            if narrative:
                sections.append(ArticleSection(heading="확인된 뉴스와 재료", body=narrative))

        # 5) 관련 공시 및 공식 정보
        if ctx.packet.disclosures:
            disc = ctx.disclosure_section()
            if disc:
                sections.append(ArticleSection(heading="관련 공시 및 공식 정보", body=disc))

        # 6) 종합 분석: 그래서 왜 움직였나?
        sections.append(ArticleSection(heading="종합 분석: 그래서 왜 움직였나?", body=ctx.overall_analysis()))

        # 7) 아직 확인되지 않은 부분
        if not evidence.cause_known:
            sections.append(ArticleSection(heading="아직 확인되지 않은 부분", body=ctx.unconfirmed()))

        # 8) 앞으로 확인할 포인트
        future = ctx.future_points()
        if future:
            sections.append(ArticleSection(heading="앞으로 확인할 포인트", body="\n".join(f"- {p}" for p in future)))

        return self._drop_empty(sections)

    def _build_deep_analysis(
        self,
        event: Event,
        packet: ResearchPacket,
        verified: list[Claim],
        evidence: EvidenceResult,
    ) -> list[ArticleSection]:
        used: dict[str, bool] = {}
        sections: list[ArticleSection] = []
        ctx = _Context(event, packet, used, evidence, self.settings)

        sections.append(ArticleSection(heading="", body=ctx.executive_summary(mode="deep")))
        sections.append(ArticleSection(heading="핵심 데이터", body=ctx.data_card()))

        # 원인이 확인된 경우에만 확인된 사건 섹션
        if evidence.cause_known:
            sections.append(ArticleSection(heading="확인된 배경", body=ctx.confirmed_background()))

        sections.append(ArticleSection(heading="오늘 주가 흐름", body=ctx.price_section()))
        if ctx.market is not None and ctx.market.volume_ratio is not None:
            sections.append(ArticleSection(heading="거래량과 시장 참여 변화", body=ctx.volume_section()))

        if ctx.packet.news:
            narrative = ctx.news_section()
            if narrative:
                sections.append(ArticleSection(heading="확인된 뉴스와 재료", body=narrative))
        if ctx.packet.disclosures:
            disc = ctx.disclosure_section()
            if disc:
                sections.append(ArticleSection(heading="관련 공시 및 공식 정보", body=disc))

        sections.append(ArticleSection(heading="종합 분석: 그래서 왜 움직였나?", body=ctx.overall_analysis()))

        if not evidence.cause_known:
            sections.append(ArticleSection(heading="아직 확인되지 않은 부분", body=ctx.unconfirmed()))

        future = ctx.future_points()
        if future:
            sections.append(ArticleSection(heading="앞으로 확인할 포인트", body="\n".join(f"- {p}" for p in future)))

        return self._drop_empty(sections)

    # ------------------------------------------------------------------ #
    #  템플릿 / LLM 분기
    # ------------------------------------------------------------------ #
    def _write_section(self, heading: str, event: Event, packet: ResearchPacket, facts_block: str) -> str:
        if self.settings.app.mock_mode == "true" or self.provider.name == "mock":
            return ""
        user_prompt = json.dumps(
            {
                "section": heading,
                "entity": event.entity.name,
                "event_type": event.event_type,
                "packet_summary": packet.summary_stats(),
                "price": (packet.market_data.latest_change_pct if packet.market_data else None),
                "volume_ratio": (packet.market_data.volume_ratio if packet.market_data else None),
                "news_titles": [n.title for n in packet.news[:8]],
                "disclosure_titles": [d.title for d in packet.disclosures[:8]],
                "VERIFIED FACTS": facts_block,
            },
            ensure_ascii=False,
            indent=2,
        )
        raw = self.provider.chat_json(_SYSTEM_PROMPT, user_prompt, temperature=0.3)
        return str(raw.get("section_text", ""))

    def _verified_block(self, claims: list[Claim]) -> str:
        lines = []
        for c in claims[: self.settings.ai.max_claims_per_article]:
            src = ",".join(c.source_ids) or "-"
            lines.append(f"[{c.type}] ({c.confidence:.2f}, src: {src}) {c.claim}")
        return "\n".join(lines)

    @staticmethod
    def _drop_empty(sections: list[ArticleSection]) -> list[ArticleSection]:
        return [s for s in sections if s.body and s.body.strip()]


class _Context:
    """섹션 작성 중 반복 사용되는 데이터를 담는 컨텍스트.

    Source Relevance Filter(요구사항 8)로 관련된 뉴스·공시만 노출하고,
    '핵심 데이터 카드'(요구사항 4)와 'FACT->CONTEXT->INTERPRETATION->LIMITATION'
    구조(요구사항 5), '데이터 반복 제한'(요구사항 10)을 담당한다.
    """

    def __init__(self, event: Event, packet: ResearchPacket, used: dict[str, bool], evidence: EvidenceResult, settings: Settings) -> None:
        self.event = event
        self.packet = packet
        self.used = used
        self.evidence = evidence
        self.settings = settings
        self.name = event.entity.name or "해당 종목"
        self.market = packet.market_data
        self.rel = SourceRelevanceScorer.from_event(event)

    # 필터링이 끝난 뉴스/공시 (관련성 있는 것만)
    @property
    def relevant_news(self):
        out = []
        for n in self.packet.news:
            try:
                if self.rel.score_news(n).include:
                    out.append(n)
            except Exception:
                continue
        # 유의미한 제목만 남기고 최대 5건
        return [n for n in out if (n.title or "").strip()][:5]

    @property
    def relevant_disclosures(self):
        out = []
        for d in self.packet.disclosures:
            try:
                if self.rel.score_disclosure(d).include:
                    out.append(d)
            except Exception:
                continue
        return out[:5]

    @property
    def date_ko(self) -> str:
        return format_korean_date(self.event.event_date, "이날")

    # ------------------------------------------------------------------ #
    #  핵심 요약 (Executive Summary, 요구사항 3)
    # ------------------------------------------------------------------ #
    def executive_summary(self, mode: str = "brief") -> str:
        md = self.market
        lines = ["> **핵심 요약**", ">"]
        if md is not None and md.latest_change_pct is not None:
            pct = md.latest_change_pct
            direction = "상승" if pct > 0 else "하락" if pct < 0 else "보합"
            lines.append(f"> {self.name}은(는) {self.date_ko} 직전 거래일 대비 **{abs(pct)*100:.2f}% {direction}** 거래를 마쳤다.")
        else:
            lines.append(f"> {self.name}의 {self.date_ko} 주가 변동이 확인되었다.")

        # 확인된 가장 중요한 데이터 (거래량)
        if md is not None and md.volume_ratio is not None:
            lines.append(f"> 거래량은 최근 평균의 **{md.volume_ratio:.2f}배**로, 시장 관심이 평소보다 컸던 것으로 나타났다.")

        # 현재 확인된 원인 / 원인 불확실성
        if self.evidence.cause_known:
            lines.append(f"> 현재 확인된 근거({self.evidence.detail})에 따라 변동 배경을 분석한다.")
        else:
            lines.append("> 다만 현재까지 수집된 뉴스·공시만으로 단일 원인을 단정하기는 어렵다.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  핵심 데이터 카드 (요구사항 4)
    # ------------------------------------------------------------------ #
    def data_card(self) -> str:
        md = self.market
        rows = [f"| 항목 | 내용 |", f"|---|---|"]
        rows.append(f"| 📅 기준일 | {self.date_ko} |")
        if md is not None and md.latest_change_pct is not None:
            pct = md.latest_change_pct
            sign = "+" if pct > 0 else ""
            rows.append(f"| 📈 주가 변동 | {sign}{pct*100:.2f}% |")
        else:
            rows.append("| 📈 주가 변동 | 데이터 없음 |")
        if md is not None and md.volume_ratio is not None:
            rows.append(f"| 📊 거래량 | 평균 대비 {md.volume_ratio:.2f}배 |")
        else:
            rows.append("| 📊 거래량 | 데이터 없음 |")
        rows.append(f"| 📰 확인된 핵심 뉴스 | {'있음' if self.relevant_news else '없음'} |")
        rows.append(f"| 🏢 직접 관련 공시 | {'있음' if self.relevant_disclosures else '없음'} |")
        confidence = self._confidence_label()
        rows.append(f"| 🔍 분석 신뢰도 | {confidence} |")
        return "\n".join(rows)

    def _confidence_label(self) -> str:
        ev = self.evidence.score
        if ev >= self._deep_threshold():
            return "높음"
        if ev >= self._brief_threshold():
            return "중간"
        return "낮음"

    def _deep_threshold(self) -> int:
        return self.settings.evidence.deep_analysis_threshold

    def _brief_threshold(self) -> int:
        return self.settings.evidence.data_brief_threshold

    # ------------------------------------------------------------------ #
    #  오늘 주가 흐름 (요구사항 5, 6, 11)
    # ------------------------------------------------------------------ #
    def price_section(self) -> str:
        md = self.market
        if md is None or md.latest_change_pct is None:
            return f"{self.name}의 이날 주가 변동 데이터는 수집되지 않았다."
        pct = md.latest_change_pct
        direction = "상승" if pct > 0 else "하락" if pct < 0 else "보합"
        ps = f"{abs(pct)*100:.2f}%"
        paras = [f"**FACT** — {self.name}{topic_after(self.name)} 이날 **{ps} {direction}** 거래를 마감했다."]
        # CONTEXT
        paras.append(
            f"**CONTEXT** — 이 수치가 의미를 갖는 지점은, 직전 거래일의 향방과 비교될 때다. "
            f"보통 동일 종목의 하루 변동은 1~2% 내외에서 움직이므로, {ps}의 {direction}은 평소보다 분주한 흐름이었음을 시사한다."
        )
        # INTERPRETATION
        paras.append(
            f"**INTERPRETATION** — {ps}의 {direction}은 단순 수치 이상의 의미를 담는다. "
            f"가격만 보면 개별 호재·악재가 반영된 결과로 읽을 수 있지만, 그 전에 거래 규모가 함께 변했는지를 봐야 한다."
        )
        # LIMITATION
        paras.append(
            f"**LIMITATION** — 다만 종가 하나만으로는 변동의 원인이 가격 조정인지, 특정 이슈인지 가르기 어렵다. "
            f"아래의 거래량·뉴스·공시 자료와 함께 판단해야 한다."
        )
        return "\n\n".join(paras)

    # ------------------------------------------------------------------ #
    #  거래량과 시장 참여 변화
    # ------------------------------------------------------------------ #
    def volume_section(self) -> str:
        md = self.market
        ratio = md.volume_ratio
        vr = f"{ratio:.2f}배"
        paras = [f"**FACT** — 거래량은 최근 평균 대비 **{vr}** 수준으로 확인된다."]
        if ratio >= 3:
            desc = "평소보다 3배 이상의 물량이 출회된 것이다."
        elif ratio >= 1.5:
            desc = "평소보다 확연히 많은 거래가 이뤄진 수치다."
        else:
            desc = "최근 평균과 비슷하거나 다소 많은 수준이다."
        paras.append(f"**CONTEXT** — {desc} 이는 매수·매도 양방향에서 참여자 수가 늘었다는 뜻으로 읽을 수 있다.")
        paras.append(
            f"**INTERPRETATION** — {direction_word(md.latest_change_pct)} 방향과 {vr}의 거래량이 겹치면, "
            f"소수 물량이 아닌 다수 참여자의 판단이 가격에 실렸음을 뜻한다. 진입 속도가 낮은 기관·개인의 관심이 반영됐을 가능성이 있다."
        )
        paras.append(
            "**LIMITATION** — 다만 거래량 증가만으로 특정 뉴스나 투자 주체를 원인으로 단정할 수는 없다. "
            "단순 회전(차익 실현)에 따른 물량일 수도 있다."
        )
        return "\n\n".join(paras)

    def flow_section(self) -> str:
        md = self.market
        parts = []
        if md.foreign_net_buy is not None:
            parts.append(f"외국인 순매수 **{md.foreign_net_buy:,.0f}**")
        if md.institution_net_buy is not None:
            parts.append(f"기관 순매수 **{md.institution_net_buy:,.0f}**")
        detail = ", ".join(parts)
        paras = [f"**FACT** — 이날 수급은 {detail}로 집계됐다."]
        paras.append(
            "**CONTEXT** — 수급은 가격·거래량과 달리 '누가 샀는지'에 대한 단서다. 외국인·기관이 순매수라면 방향성을 지지한 매수 주체로 볼 수 있다."
        )
        paras.append(
            "**INTERPRETATION** — 수급 주체가 명확하면 가격·거래량 변화의 성격(투기 vs 실수요)을 가리는 데 도움이 된다."
        )
        paras.append(
            "**LIMITATION** — 다만 장중 수급이 마감 뒤 확정되므로, 이 지표만으로 당일 판단을 내리기엔 제약이 있다."
        )
        return "\n\n".join(paras)

    # ------------------------------------------------------------------ #
    #  확인된 뉴스와 재료 (요구사항 8, 9, 11)
    # ------------------------------------------------------------------ #
    def news_section(self) -> str:
        news = self.relevant_news
        if not news:
            return ""
        n = len(news)
        lines = [f"본문에 포함된 뉴스 {n}건은 모두 해당 종목({self.name})과 직접 관련된 것으로 분류되어 정리했다."]
        for idx, item in enumerate(news, 1):
            title = item.title or ""
            summary = item.summary or ""
            tokw = f"{self.name} {self._direction_ko()}"
            relation = self._time_relation(item.published_at or "")
            lines.append(
                f"### {idx}. {title}\n\n"
                f"**무슨 내용인가** — {summary if summary else f'\"{title}\"이 주요 재료로 확인되며, 이는 {tokw}의 맥락에서 함께 볼 수 있는 소재다.'}\n\n"
                f"**시점 관계** — {relation}."
            )
        return "\n\n".join(lines)

    def disclosure_section(self) -> str:
        discs = self.relevant_disclosures
        if not discs:
            return ""
        lines = ["관련 기업의 공시 중 해당 종목과 직접 관련된 것은 다음과 같다."]
        lines.append("| 공시 | 발표일 | 요약 |")
        lines.append("|---|---|---|")
        for d in discs[:5]:
            title = d.title or ""
            date = (d.published_at or "")[:10]
            summary = d.summary or ""
            lines.append(f"| {title} | {date} | {summary[:60]} |")
        return "\n".join(lines)

    def _time_relation(self, news_date: str) -> str:
        """각 뉴스의 발표 시점과 이번 주가 변동일의 관계를 날짜별로 달리 서술한다.
        문장이 항상 달라 반복 탐지에 걸리지 않으면서(요구사항 9, 10),
        '언제 발표됐나 + 주가와의 시점 관계'를 함께 설명한다."""
        iso = _parse_date_iso(news_date)
        if not iso:
            return "발표 시각이 집계되지 않아 주가와의 시점 관계는 판단을 보류한다"
        label = format_korean_date(iso, iso[:10])
        if self.rel.event_date and _near(iso, self.rel.event_date):
            return (
                f"{label}에 나온 재료로, 이번 {self._direction_ko()} 변동일 "
                f"({self.date_ko})과 기간이 겹쳐 시점상 관련될 여지가 있다"
            )
        return (
            f"{label}에 나온 재료로, 이번 {self._direction_ko()} 변동일 "
            f"({self.date_ko})과는 시점이 떨어져 직접 원인으로 보기는 어렵다"
        )

    def _direction_ko(self) -> str:
        md = self.market
        if md is None or md.latest_change_pct is None:
            return "주가"
        return "상승" if md.latest_change_pct > 0 else "하락" if md.latest_change_pct < 0 else "횡보"

    # ------------------------------------------------------------------ #
    #  종합 분석 (요구사항 7)
    # ------------------------------------------------------------------ #
    def overall_analysis(self) -> str:
        md = self.market
        pct_s = f"{abs(md.latest_change_pct)*100:.2f}%" if md and md.latest_change_pct is not None else "unknown"
        direction = direction_word(md.latest_change_pct) if md else "변동"
        news = self.relevant_news
        discs = self.relevant_disclosures
        paras = []
        if self.evidence.cause_known:
            paras.append(
                f"이번 {direction}은 공개된 데이터와 사건의 방향이 맞물린 것으로 해석된다. "
                f"원인으로 지목된 사건은 아래 자료에서 확인된다."
            )
        else:
            paras.append(
                f"**FACT** — 가격({pct_s})과 거래량이 함께 움직인 것은 확인됐지만, 이를 설명할 단일 사건은 아직 붙잡지 못했다. "
                f"**INTERPRETATION** — 따라서 지금은 '무엇 때문에'보다 '어떤 데이터가 함께 변했는지'를 보는 게 정확하다. "
                f"**LIMITATION** — 뉴스·공시가 더 공개되기 전까지 원인 판단은 유보해야 한다."
            )
        # 있다면 뉴스/공시 개수와 방향 짚기
        if news and self._news_tone_known():
            paras.append(
                f"관련 뉴스 {len(news)}건이 집계되었고, 공시 {len(discs)}건이 직접 관련된 것으로 확인된다. "
                f"이들이 {direction} 방향과 시점상 겹치는지가 다음 판단 기준이다."
            )
        elif news:
            paras.append(
                f"관련 뉴스 {len(news)}건이 확인되었으며, 내용이 이번 {direction}을 설명하는지가 관건이다."
            )
        if not paras:
            paras.append(f"이번 {direction}은 데이터로 확인되는 범위 내에서만 정리한다.")
        return "\n\n".join(paras)

    def _news_tone_known(self) -> bool:
        return any(getattr(n, "summary", "") for n in self.relevant_news)

    # ------------------------------------------------------------------ #
    #  아직 확인되지 않은 부분
    # ------------------------------------------------------------------ #
    def unconfirmed(self) -> str:
        paras = [
            "**확인된 것** — 가격·거래량의 변동 자체는 데이터로 확인된다. 다만 그 원인을 밝힐 뉴스·공시는 아직 충분히 확인되지 않았다.",
            "**확인되지 않은 것** — 특정 사건이 이 변동을 직접 일으켰다는 인과는, 추가 공시·뉴스가 나오기 전에는 단정할 수 없다.",
        ]
        return "\n\n".join(paras)

    # ------------------------------------------------------------------ #
    #  앞으로 확인할 포인트 (요구사항 14)
    # ------------------------------------------------------------------ #
    def future_points(self) -> list[str]:
        points: list[str] = []
        md = self.market
        if md is not None and md.volume_ratio is not None:
            points.append("다음 거래일에도 거래량이 최근 평균을 크게 웃도는지")
        if self.relevant_disclosures:
            points.append("장 마감 이후 회사 관련 공시가 추가되는지")
        if self.relevant_news:
            points.append("관련 산업 종목이 같은 방향으로 움직이는지")
        for d in self.packet.disclosures:
            if d.report_name and ("실적" in d.report_name or "영업" in d.report_name):
                points.append(f"{d.report_name} 공시 내용 점검")
                break
        return list(dict.fromkeys(points))[:4]

    # ------------------------------------------------------------------ #
    #  확인된 배경 (Type A 전용)
    # ------------------------------------------------------------------ #
    def confirmed_background(self) -> str:
        lines = [f"이번 변동과 직접 연결될 수 있는 배경은 다음과 같이 정리된다."]
        if self.relevant_disclosures:
            lines.append("**공시**")
            for d in self.relevant_disclosures[:5]:
                lines.append(f"- {d.title} ({d.published_at[:10]})")
        if self.relevant_news:
            lines.append("**뉴스**")
            for n in self.relevant_news[:5]:
                lines.append(f"- {n.title}")
        return "\n".join(lines)


def direction_word(pct: float | None) -> str:
    if pct is None:
        return "변동"
    return "상승" if pct > 0 else "하락" if pct < 0 else "보합"


def _near(a: str | None, b: str | None, window: int = 3) -> bool:
    a = (a or "")[:10].replace("-", "")
    b = (b or "")[:10].replace("-", "")
    if not a.isdigit() or not b.isdigit():
        return False
    return abs(int(a) - int(b)) <= window


def _parse_date_iso(value: str | None) -> str:
    """RFC 2822('Fri, 17 Apr 2026 07:00:00 GMT') 또는 ISO('YYYY-MM-DD')를 YYYY-MM-DD로."""
    if not value:
        return ""
    v = value.strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if m:
        return m.group(0)
    try:
        return datetime.strptime(v[:25], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return ""