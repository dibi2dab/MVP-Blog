from __future__ import annotations

from datetime import datetime, timezone

from src.models.article import Article, ArticleSection
from src.models.event import Event
from src.models.source import EntityRef
from src.pipeline.publish_selector import kst_date, published_today, select_articles, today_kst
from src.storage.file_store import JsonStore


def _article(
    article_id: str,
    name: str,
    event_type: str,
    *,
    status: str = "approved",
    ready: bool = True,
    metrics: int = 4,
    event_date: str | None = None,
    title: str | None = None,
    quality: float = 0.8,
) -> Article:
    event = Event(
        event_id=f"e_{article_id}",
        event_type=event_type,
        entity=EntityRef(name=name, ticker=name),
        event_date=event_date or datetime.now().strftime("%Y-%m-%d"),
        event_score=5,
        evidence_score=3,
    )
    # 기사마다 계산 지표가 달라야 유사도 필터에 걸리지 않는다.
    offset = sum(ord(c) for c in article_id) % 20
    data_metrics = {f"m{i}": float(i) + offset for i in range(metrics)}
    return Article(
        article_id=article_id,
        event=event,
        title=title or f"{name} {event_type} 분석 {article_id}",
        slug=article_id,
        status=status,
        sections=[
            ArticleSection(heading="검색 의도에 대한 답", body="답변 " * 100),
            ArticleSection(heading="시나리오와 확인 조건", body="조건 " * 100),
        ],
        sources=["[뉴스](https://example.com/news)"],
        data_metrics=data_metrics,
        quality_score=quality,
        readiness={"ready": ready, "checks": {"independent_metrics": ready}},
    )


def _store(settings) -> JsonStore:
    return JsonStore(settings)


class TestPublishSelector:
    def test_daily_limit_caps_selection(self, settings):
        store = _store(settings)
        types = ["stock_surge", "stock_crash", "disclosure", "earnings", "stock_breakout", "news"]
        for i, event_type in enumerate(types):
            store.save_article(_article(f"a{i}", f"종목{i}", event_type))

        result = select_articles(settings, store, limit=5)

        assert len(result.selected) == 5
        assert result.daily_limit == 5

    def test_counts_already_published_today(self, settings):
        store = _store(settings)
        store.save_published_marker(
            "event_old",
            {
                "event_id": "old",
                "entity": "기존종목",
                "event_type": "stock_surge",
                "published_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        for i in range(3):
            store.save_article(_article(f"a{i}", f"종목{i}", f"type{i}"))

        result = select_articles(settings, store, limit=5)

        assert result.published_today == 1
        assert result.remaining == 4
        assert len(result.selected) == 3

    def test_entity_diversity(self, settings):
        store = _store(settings)
        store.save_article(_article("a1", "코미팜", "stock_crash", title="코미팜 5% 하락"))
        store.save_article(_article("a2", "코미팜", "disclosure", title="코미팜 신제품 공시"))

        result = select_articles(settings, store, limit=5)

        assert len(result.selected) == 1
        assert any("종목 중복" in reason for _, reason in result.skipped)

    def test_event_type_diversity(self, settings):
        store = _store(settings)
        titles = [
            "코미팜 급락 배경과 거래량 해석",
            "삼성전자 실적 발표 이후 수급 변화",
            "현대차 신차 출시와 외국인 순매수",
            "NAVER 커머스 매출 구조 점검",
        ]
        names = ["코미팜", "삼성전자", "현대차", "NAVER"]
        for i in range(4):
            store.save_article(
                _article(f"a{i}", names[i], "stock_surge", title=titles[i])
            )

        result = select_articles(settings, store, limit=5)

        assert len(result.selected) == 2
        assert sum(1 for _, reason in result.skipped if "유형 중복" in reason) == 2

    def test_skips_not_ready_or_stale(self, settings):
        store = _store(settings)
        store.save_article(_article("a1", "준비안됨", "stock_crash", ready=False))
        store.save_article(_article("a2", "오래됨", "stock_surge", event_date="2020-01-01"))
        store.save_article(_article("a3", "지표부족", "disclosure", metrics=1))
        store.save_article(_article("a4", "정상", "earnings"))

        result = select_articles(settings, store, limit=5)

        assert [c.article.article_id for c in result.selected] == ["a4"]
        reasons = {article_id: reason for article_id, reason in result.skipped}
        assert "readiness" in reasons["a1"]
        assert "경과" in reasons["a2"]
        assert "지표" in reasons["a3"]

    def test_skips_already_published_article(self, settings):
        store = _store(settings)
        article = _article("a1", "코미팜", "stock_crash")
        store.save_article(article)
        store.save_published_marker("event_e_a1", {"event_id": "e_a1", "published_at": "2020-01-01T00:00:00+00:00"})

        result = select_articles(settings, store, limit=5)

        assert result.selected == []
        assert any("이미 발행" in reason for _, reason in result.skipped)


class TestKstDate:
    def test_utc_to_kst(self):
        assert kst_date("2026-11-03T16:00:00+00:00") == "2026-11-04"

    def test_today_matches_kst(self):
        assert len(today_kst()) == 10
