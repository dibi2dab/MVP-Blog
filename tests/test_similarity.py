from __future__ import annotations

from src.models.article import Article
from src.models.event import Event
from src.models.source import EntityRef
from src.utils.similarity import article_similarity


def _article(article_id: str, name: str, event_type: str, title: str, metrics: dict) -> Article:
    event = Event(
        event_id=article_id,
        event_type=event_type,
        entity=EntityRef(name=name, ticker=name),
        event_date="2026-09-02",
    )
    return Article(
        article_id=article_id,
        event=event,
        title=title,
        slug=article_id,
        data_metrics=metrics,
    )


class TestArticleSimilarity:
    def test_identical_articles_are_near_one(self):
        a = _article("a1", "코미팜", "stock_crash", "코미팜 5% 하락", {"change_pct": -5.0, "volume_ratio": 3.0})
        b = _article("a2", "코미팜", "stock_crash", "코미팜 5% 하락", {"change_pct": -5.0, "volume_ratio": 3.0})

        assert article_similarity(a, b) > 0.95

    def test_different_entities_are_low(self):
        a = _article("a1", "코미팜", "stock_crash", "코미팜 5% 하락", {"change_pct": -5.0, "volume_ratio": 3.0})
        b = _article("a2", "삼성전자", "stock_surge", "삼성전자 2% 상승", {"change_pct": 2.0, "volume_ratio": 1.2})

        assert article_similarity(a, b) < 0.55

    def test_metric_bucket_handles_missing_values(self):
        a = _article("a1", "코미팜", "stock_crash", "코미팜 5% 하락", {})
        b = _article("a2", "코미팜", "stock_crash", "코미팜 5% 하락", {})

        assert article_similarity(a, b) > 0.7
