from __future__ import annotations

import re

import pytest

from src.editorial.analysis import metric
from src.editorial.text import count_headings, has_table

from editorial_fixtures import CRYSTAL_IDS, QUARTZ_IDS, make_article

_FORBIDDEN_PHRASES = (
    "10가지 평가 항목",
    "CPPI",
    "QDVI",
    "이 평가는 직접 사용 후기인가요?",
    "실제 사용 경험이 아닙니다",
    "평가 결과는",
    "이 글에서는",
    "무엇을 알아볼까요",
    "기능 수",
    "기능별 비용",
)

_SCORE_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*/\s*10")


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


def test_body_has_no_scores_or_reader_facing_evaluation():
    for blog, ids in (("crystal", CRYSTAL_IDS), ("quartz", QUARTZ_IDS)):
        for entry_id in ids:
            body = make_article(blog, entry_id).body_markdown
            for phrase in _FORBIDDEN_PHRASES:
                assert phrase not in body, (blog, entry_id, phrase)
            assert not _SCORE_PATTERN.search(body), (blog, entry_id)


def test_crystal_body_uses_narrative_risk_section():
    article = make_article("crystal", "adsense-blog")
    assert "## 수익 변동과 운영 부담" in article.body_markdown
    assert "## 광고 수익이 남는 구조" in article.body_markdown


def test_quartz_body_explains_problems_and_fit():
    article = make_article("quartz", "notion-plus")
    body = article.body_markdown
    assert "## 이 도구가 해결하는 업무" in body
    assert "## 지원 범위와 사용량" in body
    assert "## 어떤 팀에 맞고 어떤 팀에 과한가" in body


def test_scenarios_use_korean_labels():
    for blog, entry_id in (("crystal", "adsense-blog"), ("quartz", "notion-plus")):
        body = make_article(blog, entry_id).body_markdown
        section = body.split("## 시나리오 분석", 1)[1].split("\n## ", 1)[0]
        assert "보수적" in section
        assert "기준" in section
        assert "적극적" in section
        assert "conservative" not in section


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
    break_even = metric(article.analysis, "break_even_months")
    assert break_even is not None
    assert break_even.value is not None
    assert break_even.display == "4.9개월"
    assert "7.41,000" not in article.body_markdown


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
