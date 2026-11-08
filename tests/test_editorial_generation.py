from __future__ import annotations

import re

import pytest

from src.editorial.text import count_headings, has_table

from editorial_fixtures import CRYSTAL_IDS, QUARTZ_IDS, make_article


@pytest.mark.parametrize("entry_id", CRYSTAL_IDS)
def test_crystal_articles_are_publish_ready(entry_id):
    article = make_article("crystal", entry_id)
    assert article.status == "ready", article.quality.critical_failures
    assert article.decision == "PUBLISH"
    assert article.quality.total >= 85
    assert article.quality.critical_failures == []
    assert len(article.body_markdown) >= 1800
    assert count_headings(article.body_markdown) >= 5
    assert has_table(article.body_markdown)
    assert article.primary_keyword in article.title
    assert article.body_markdown.count(article.primary_keyword) >= 1
    assert 80 <= len(article.meta_description) <= 160
    assert article.catalog_id == entry_id


@pytest.mark.parametrize("entry_id", QUARTZ_IDS)
def test_quartz_articles_are_publish_ready(entry_id):
    article = make_article("quartz", entry_id)
    assert article.status == "ready", article.quality.critical_failures
    assert article.decision == "PUBLISH"
    assert article.quality.total >= 85
    assert article.quality.critical_failures == []
    assert len(article.body_markdown) >= 1800
    assert count_headings(article.body_markdown) >= 5
    assert has_table(article.body_markdown)
    assert article.primary_keyword in article.title
    assert article.body_markdown.count(article.primary_keyword) >= 1
    assert 80 <= len(article.meta_description) <= 160
    assert article.catalog_id == entry_id


@pytest.mark.parametrize("entry_id", ["adsense-blog", "zapier-pro"])
def test_generation_is_deterministic(entry_id):
    blog = "crystal" if entry_id == "adsense-blog" else "quartz"
    first = make_article(blog, entry_id)
    second = make_article(blog, entry_id)
    assert first.body_markdown == second.body_markdown
    assert first.quality.total == second.quality.total
    assert first.analysis.model_dump() == second.analysis.model_dump()


def test_titles_have_no_dates():
    pattern = re.compile(r"(\d{4}[-./년]\s*\d{1,2}[-./월]\s*\d{1,2}일?|\d{4}년|\b20\d{2}\b)")
    for blog, ids in (("crystal", CRYSTAL_IDS), ("quartz", QUARTZ_IDS)):
        for entry_id in ids:
            article = make_article(blog, entry_id)
            assert not pattern.search(article.title), article.title


def test_body_does_not_claim_firsthand_testing():
    for blog, ids in (("crystal", CRYSTAL_IDS), ("quartz", QUARTZ_IDS)):
        for entry_id in ids:
            article = make_article(blog, entry_id)
            assert "직접 사용해 보니" not in article.body_markdown
            assert "써 보니" not in article.body_markdown


def test_articles_cite_catalog_sources():
    article = make_article("crystal", "adsense-blog")
    cited = set(re.findall(r"\[S\d+\]", article.body_markdown))
    assert cited
    listed = {f"[{source.source_id}]" for source in article.sources}
    assert cited <= listed


def test_generator_marks_editorial_assumptions():
    article = make_article("quartz", "notion-plus")
    assert "편집상 가정" in article.body_markdown
    assert any(item.is_editorial for item in article.analysis.assumptions)


def test_generator_never_guarantees_income():
    article = make_article("crystal", "adsense-blog")
    assert "수익을 보장하지 않습니다" in article.body_markdown


def test_advertising_break_even_uses_actual_pageviews():
    article = make_article("crystal", "adsense-blog")
    assert "7.41,000" not in article.body_markdown
    assert "7,407방문" in article.body_markdown


def test_scenario_tables_do_not_leak_raw_floats():
    raw_float_cell = re.compile(r"\|\s*-?\d+\.\d+\s*\|")
    for blog, ids in (("crystal", CRYSTAL_IDS), ("quartz", QUARTZ_IDS)):
        for entry_id in ids:
            article = make_article(blog, entry_id)
            section = article.body_markdown.split("## 시나리오 분석", 1)[1]
            section = section.split("\n## ", 1)[0]
            assert not raw_float_cell.search(section), (blog, entry_id)


def test_assumption_rows_are_unique():
    for blog, ids in (("crystal", CRYSTAL_IDS), ("quartz", QUARTZ_IDS)):
        for entry_id in ids:
            article = make_article(blog, entry_id)
            names = [item.name for item in article.analysis.assumptions]
            assert len(names) == len(set(names)), (blog, entry_id, names)


def test_rating_paragraphs_use_natural_korean():
    article = make_article("crystal", "adsense-blog")
    assert "난이도은" not in article.body_markdown
    assert "수익 변동 위험 평가 결과는" in article.body_markdown
    assert "10로 평가" not in article.body_markdown
