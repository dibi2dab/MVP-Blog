from __future__ import annotations

import re

from src.editorial.models import QualityReport, QualityScores
from src.editorial.profiles import get_profile
from src.editorial.quality import assess_quality, decide_publication

from editorial_fixtures import clone_article, get_entry, make_article


def _report(article, *, recent_records=()):
    entry = get_entry(article.blog, article.catalog_id)
    return assess_quality(
        article,
        get_profile(article.blog),
        recent_records=recent_records,
        entry=entry,
    )


def test_clean_article_passes():
    article = make_article("quartz", "notion-plus")
    report = _report(article)
    assert report.critical_failures == []
    assert report.total >= 85, report.warnings
    decision, status, _ = decide_publication(report, get_profile("quartz"))
    assert decision == "PUBLISH"
    assert status == "ready"


def test_tampered_metric_is_a_critical_failure():
    article = clone_article(make_article("crystal", "adsense-blog"))
    article.analysis.metrics[0].value = 999999.0
    report = _report(article)
    assert any("계산" in failure for failure in report.critical_failures)
    assert article.decision == "DO NOT PUBLISH"


def test_tampered_evaluation_score_is_a_critical_failure():
    article = clone_article(make_article("quartz", "zapier-pro"))
    article.analysis.evaluation_items[0].score = 1.0
    report = _report(article)
    assert any("평가 점수" in failure for failure in report.critical_failures)


def test_title_without_primary_keyword_is_rejected():
    article = clone_article(make_article("quartz", "notion-plus"))
    article.title = "협업 도구의 가격을 비교하면"
    report = _report(article)
    assert any("핵심 키워드" in failure for failure in report.critical_failures)


def test_missing_citations_are_rejected():
    article = clone_article(make_article("crystal", "gumroad-digital-product"))
    cleaned = re.sub(r"\[S\d+\]", "", article.body_markdown)
    article.body_markdown = cleaned
    article.body_with_sources = cleaned
    report = _report(article)
    assert any("출처 인용" in failure for failure in report.critical_failures)


def test_duplicate_catalog_id_is_rejected():
    article = make_article("quartz", "slack-pro")
    report = _report(
        article,
        recent_records=[{"catalog_id": article.catalog_id, "title": "이전 글"}],
    )
    assert any("이미 발행" in failure for failure in report.critical_failures)


def test_income_guarantee_phrase_is_rejected():
    article = clone_article(make_article("crystal", "patreon-membership"))
    extra = "\n이 방법은 월 500만 원 수익을 보장합니다.\n"
    article.body_markdown += extra
    article.body_with_sources = article.body_markdown
    report = _report(article)
    assert any("수익 보장" in failure for failure in report.critical_failures)


def test_firsthand_testing_claim_is_rejected():
    article = clone_article(make_article("quartz", "claude-pro"))
    extra = "\n직접 사용해 보니 정말 편리했습니다.\n"
    article.body_markdown += extra
    article.body_with_sources = article.body_markdown
    report = _report(article)
    assert any("직접 사용" in failure for failure in report.critical_failures)


def test_thresholds_and_critical_override():
    profile = get_profile("quartz")
    good = QualityReport(
        scores=QualityScores(
            factual_accuracy=25,
            originality=20,
            search_intent=20,
            source_quality=15,
            readability=10,
            seo_quality=10,
        ),
        total=100.0,
    )
    assert decide_publication(good, profile)[0] == "PUBLISH"

    revision = QualityReport(scores=QualityScores(), total=75.0)
    assert decide_publication(revision, profile)[0] == "NEEDS REVISION"

    rejected = QualityReport(scores=QualityScores(), total=60.0)
    assert decide_publication(rejected, profile)[0] == "DO NOT PUBLISH"

    critical = QualityReport(scores=QualityScores(), total=100.0, critical_failures=["검증 실패"])
    decision, status, reason = decide_publication(critical, profile)
    assert decision == "DO NOT PUBLISH"
    assert status == "failed"
    assert "치명적 결함" in reason
