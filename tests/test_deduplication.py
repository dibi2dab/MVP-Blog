from __future__ import annotations

from src.models.news import NewsItem
from src.utils.deduplication import NewsDeduper, is_duplicate_news, title_similarity


def _news(title: str, published: str = "2026-09-01T09:00:00+09:00", url: str = "") -> NewsItem:
    return NewsItem(title=title, published_at=published, source="s", url=url or f"https://a/{title}")


class TestTitleSimilarity:
    def test_same_title(self):
        assert title_similarity("삼성전자 주가 상승", "삼성전자 주가 상승") == 1.0

    def test_different_titles(self):
        assert title_similarity("삼성전자 상승", "현대차 하락") < 0.4

    def test_whitespace_insensitive(self):
        assert title_similarity(" 삼성전자  주가 ", "삼성전자 주가") > 0.9


class TestNewsDeduper:
    def test_url_duplicate_removed(self):
        items = [
            _news("같은 기사", url="https://a/x"),
            _news("같은 기사", url="https://a/x"),
        ]
        deduper = NewsDeduper(title_threshold=0.85)
        out = deduper.dedupe(items)
        assert len(out) == 1

    def test_similar_title_removed(self):
        items = [
            _news("삼성전자, 2분기 실적 발표…영업이익 X% 증가"),
            _news("삼성전자, 2분기 실적 발표…영업이익 Y% 증가"),
        ]
        deduper = NewsDeduper(title_threshold=0.9)
        out = deduper.dedupe(items)
        assert len(out) == 1

    def test_distinct_titles_kept(self):
        items = [
            _news("삼성전자 2분기 실적 발표"),
            _news("SK하이닉스 반도체 공급 계약 체결"),
        ]
        deduper = NewsDeduper(title_threshold=0.9)
        out = deduper.dedupe(items)
        assert len(out) == 2


class TestIsDuplicateNews:
    def test_decision_fields(self):
        a = _news("동일 제목")
        b = _news("동일 제목", published="2026-09-01T09:30:00+09:00")
        decision = is_duplicate_news(b, [a], threshold=0.9)
        assert decision.is_duplicate
        assert decision.kept is a
        assert decision.reason


class TestClustering:
    def test_cluster_merges_similar(self):
        items = [
            _news("카카오, 인수 발표(1)", published="2026-09-01T09:00:00+09:00"),
            _news("카카오, 인수 발표(2)", published="2026-09-01T10:00:00+09:00"),
            _news("네이버, 수출 계약", published="2026-09-01T11:00:00+09:00"),
        ]
        deduper = NewsDeduper(title_threshold=0.8)
        clusters = deduper.cluster(items)
        big = [c for c in clusters if len(c["items"]) > 1]
        assert len(big) == 1
        assert big[0]["source_count"] >= 1