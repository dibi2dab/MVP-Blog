from __future__ import annotations

from datetime import datetime

from src.analyzers.readiness import evaluate_readiness
from src.models.analysis import AnalysisReport, FactCheckResult
from src.models.article import Article, ArticleSection
from src.models.event import Event
from src.models.source import EntityRef
from src.publishers.visibility import resolve_visibility

_TODAY = datetime.now().strftime("%Y-%m-%d")


def _article(**overrides) -> Article:
    event = Event(
        event_id="e1",
        event_type="stock_crash",
        entity=EntityRef(name="코미팜", ticker="041960"),
        event_date=overrides.pop("event_date", _TODAY),
    )
    base = dict(
        article_id="a1",
        event=event,
        title="[2026년 9월 2일] 코미팜 5.37% 하락·거래량 3.10배·20일선 -4.20%",
        slug="komipharm",
        sections=[
            ArticleSection(heading="검색 의도에 대한 답", body="검색 의도에 대한 답변입니다. " * 30),
            ArticleSection(heading="시나리오와 확인 조건", body="시나리오와 확인 조건입니다. " * 20),
        ],
        body_markdown="검색 의도에 대한 답변입니다. " * 30,
        sources=["[뉴스](https://example.com/news)", "[가격](https://finance.naver.com/item/main.naver?code=041960)"],
        data_metrics={
            "change_pct": -5.37,
            "volume_ratio": 3.1,
            "distance_ma20_pct": -4.2,
            "return_5d": -6.1,
        },
        quality_score=0.8,
    )
    base.update(overrides)
    return Article(**base)


def _report(verdict: str = "pass", rejected: bool = False) -> AnalysisReport:
    return AnalysisReport(
        packet_id="packet_e1",
        event_id="e1",
        fact_check=FactCheckResult(
            verdict=verdict,
            rejected_claims=[],
            issue_notes=[],
        ),
    )


class TestReadiness:
    def test_ready_article_passes(self, settings):
        result = evaluate_readiness(_article(), _report(), settings)

        assert result.ready is True
        assert result.independent_metrics == 4
        assert result.sources_with_url == 2

    def test_missing_metrics_blocks(self, settings):
        result = evaluate_readiness(_article(data_metrics={"change_pct": 1.0}), _report(), settings)

        assert result.ready is False
        assert result.checks["independent_metrics"] is False

    def test_missing_url_source_blocks(self, settings):
        result = evaluate_readiness(_article(sources=["Google News"]), _report(), settings)

        assert result.ready is False
        assert result.checks["sources_with_url"] is False

    def test_rejected_claims_block(self, settings):
        report = _report()
        report.fact_check.rejected_claims.append(
            __import__("src.models.analysis", fromlist=["Claim"]).Claim(claim="패킷에 없는 수치")
        )

        result = evaluate_readiness(_article(), report, settings)

        assert result.ready is False
        assert result.checks["fact_check"] is False

    def test_old_event_blocks(self, settings):
        result = evaluate_readiness(_article(event_date="2020-01-01"), _report(), settings)

        assert result.ready is False
        assert result.checks["freshness"] is False

    def test_public_ready_requires_allow_public(self, settings):
        settings.publishing.allow_public = False
        assert evaluate_readiness(_article(), _report(), settings).public_ready is False

        settings.publishing.allow_public = True
        settings.publishing.public_min_quality_score = 0.85
        assert evaluate_readiness(_article(), _report(), settings).public_ready is False
        assert evaluate_readiness(_article(quality_score=0.9), _report(), settings).public_ready is True


class TestVisibility:
    def test_private_by_default(self, settings):
        settings.tistory = settings.tistory.model_copy(update={"default_visibility": "public"})
        settings.publishing.allow_public = False

        assert resolve_visibility(_article(), settings, public_ready=True) == "private"

    def test_public_requires_ready(self, settings):
        settings.tistory = settings.tistory.model_copy(update={"default_visibility": "public"})
        settings.publishing.allow_public = True

        assert resolve_visibility(_article(), settings, public_ready=False) == "private"
        assert resolve_visibility(_article(), settings, public_ready=True) == "public"

    def test_explicit_private_is_respected(self, settings):
        settings.tistory = settings.tistory.model_copy(update={"default_visibility": "private"})
        settings.publishing.allow_public = True

        assert resolve_visibility(_article(), settings, public_ready=True) == "private"
