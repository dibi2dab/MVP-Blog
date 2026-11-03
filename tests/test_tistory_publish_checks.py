from __future__ import annotations

from pathlib import Path

from src.models.article import Article, ArticleSection
from src.models.event import Event
from src.models.source import EntityRef
from src.publishers.safety_check import MIN_BODY_LENGTH, run_pre_publish_checks


def _article(body: str = "본문입니다." * 50, has_sources: bool = True, category: str = "stocks") -> Article:
    event = Event(event_id="e1", event_type="stock_surge", entity=EntityRef(name="삼성전자", ticker="005930"))
    return Article(
        article_id="a1",
        event=event,
        title="오늘 삼성전자는 왜 올랐을까",
        slug="why-samsung-up",
        sections=[ArticleSection(heading="본문", body=body)],
        sources=["Naver Finance"] if has_sources else [],
        category=category,
        body_markdown=f"## 본문\n\n{body}",
    )


def test_valid_article_passes(tmp_path):
    img = tmp_path / "c.png"
    img.write_bytes(b"x")
    result = run_pre_publish_checks(_article(), {"stocks": "stocks"}, images=[str(img)])
    assert result.ok
    assert not result.issues


def test_empty_title_fails():
    article = _article()
    article.title = ""
    assert not run_pre_publish_checks(article, {"stocks": "stocks"}).ok


def test_short_body_fails():
    article = _article(body="짧다.")
    result = run_pre_publish_checks(article, {"stocks": "stocks"})
    assert not result.ok
    assert any("본문" in i for i in result.issues)


def test_no_sources_fails():
    assert not run_pre_publish_checks(_article(has_sources=False), {"stocks": "stocks"}).ok


def test_missing_chart_file_fails(tmp_path):
    result = run_pre_publish_checks(_article(), {"stocks": "stocks"}, images=[str(tmp_path / "none.png")])
    assert not result.ok
    assert any("차트" in i for i in result.issues)


def test_too_many_tags_fails():
    article = _article()
    article.tags = [f"태그{i}" for i in range(11)]
    assert not run_pre_publish_checks(article, {"stocks": "stocks"}).ok


def test_unknown_category_fails():
    assert not run_pre_publish_checks(_article(category="foo"), {"stocks": "stocks"}).ok


def test_min_body_length_constant_sane():
    assert MIN_BODY_LENGTH >= 100