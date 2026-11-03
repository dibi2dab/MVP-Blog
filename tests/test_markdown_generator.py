from __future__ import annotations

from src.models.article import Article, ArticleSection
from src.models.event import Event
from src.models.source import EntityRef
from src.writers.markdown_generator import MarkdownGenerator


def _article(**kwargs) -> Article:
    event = Event(event_id="e1", event_type="stock_surge", entity=EntityRef(name="삼성전자", ticker="005930"))
    sections = [
        ArticleSection(heading="오늘의 주가 움직임", body="삼성전자 종가가 변동했다."),
        ArticleSection(heading="확인된 핵심 사건", body="확인된 단일 원인은 없다."),
    ]
    return Article(
        article_id="a1",
        event=event,
        title="오늘 삼성전자는 왜 올랐을까",
        slug="why-samsung-up",
        sections=sections,
        sources=kwargs.pop("sources", ["Naver Finance", "DART"]),
        **kwargs,
    )


class TestMarkdownGenerator:
    def test_basic_structure(self):
        md = MarkdownGenerator().to_markdown(_article())
        assert md.startswith("# ")
        assert "## 오늘의 주가 움직임" in md
        assert "## 참고 자료" in md
        assert "- Naver Finance" in md

    def test_source_section_absent_when_no_sources(self):
        md = MarkdownGenerator().to_markdown(_article(sources=[]))
        assert "## 참고 자료" not in md

    def test_disclaimer_included_by_default(self):
        md = MarkdownGenerator(include_disclaimer=True).to_markdown(_article(sources=[]))
        assert "투자 판단" in md

    def test_charts_embedded(self):
        from src.models.chart import GeneratedChart

        chart = GeneratedChart(chart_key="pv", chart_type="price_volume", title="주가 추이", path="static/charts/x.png", rel_url="charts/x.png", caption="주가와 거래량")
        md = MarkdownGenerator().to_markdown(_article(), charts=[chart])
        assert "![" in md
        assert "charts/x.png" in md