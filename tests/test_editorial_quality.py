from __future__ import annotations

from src.editorial.models import QualityReport, QualityScores
from src.editorial.profiles import get_profile
from src.editorial.quality import assess_quality, decide_publication
from src.editorial.text import body_fingerprint

from editorial_fixtures import make_body, make_draft, make_sources


def _report(blog: str = "quartz", **kwargs):
    profile = get_profile(blog)
    sources = kwargs.pop("sources", make_sources(blog))
    draft = kwargs.pop("draft", make_draft(blog, sources=sources))
    return assess_quality(
        draft,
        profile,
        kwargs.pop("research_sources", sources),
        kwargs.pop("recent_records", []),
        provider_name=kwargs.pop("provider_name", "openai"),
        **kwargs,
    )


def test_clean_article_passes():
    report = _report("quartz")
    assert report.critical_failures == []
    assert report.total >= 85, report.warnings
    decision, _ = decide_publication(report, get_profile("quartz"))
    assert decision == "PUBLISH"


def test_body_is_long_enough_for_fixture():
    assert len(make_body("quartz")) >= 1000


def test_mock_provider_is_critical():
    report = _report("quartz", provider_name="mock")
    assert any("mock" in failure for failure in report.critical_failures)
    decision, _ = decide_publication(report, get_profile("quartz"))
    assert decision == "DO NOT PUBLISH"


def test_too_few_sources_is_critical():
    report = _report("quartz", sources=make_sources("quartz", 2))
    assert any("출처가 부족" in failure for failure in report.critical_failures)


def test_unknown_citation_is_critical():
    sources = make_sources("quartz", 5)
    body = make_body("quartz") + "\n\n[ S9 ] 대신 [S9] 인용을 추가합니다."
    report = _report("quartz", draft=make_draft("quartz", body=body, sources=sources), sources=sources)
    assert any("알 수 없는 출처 ID" in failure for failure in report.critical_failures)


def test_external_url_is_critical():
    sources = make_sources("quartz", 5)
    body = make_body("quartz") + "\n\n자세한 내용은 https://evil.example.com/page 에서 확인하세요."
    report = _report("quartz", draft=make_draft("quartz", body=body, sources=sources), sources=sources)
    assert any("리서치 풀 밖 URL" in failure for failure in report.critical_failures)


def test_source_url_must_exist_in_research_pool():
    sources = make_sources("quartz", 5)
    tampered = [source.model_copy() for source in sources]
    tampered[0].url = "https://not-in-pool.example.com/fake"
    report = _report("quartz", draft=make_draft("quartz", sources=tampered), sources=sources)
    assert any("리서치 풀에 없는 출처 URL" in failure for failure in report.critical_failures)


def test_missing_published_date_is_warning():
    sources = make_sources("quartz", 5)
    sources[0].published_at = ""
    report = _report("quartz", sources=sources)
    assert any("출처 발행일 누락" in warning for warning in report.warnings)


def test_duplicate_title_is_critical():
    sources = make_sources("quartz", 5)
    draft = make_draft("quartz", sources=sources)
    recent = [
        {
            "title": draft.title,
            "body_fingerprint": body_fingerprint(draft.body_markdown),
        }
    ]
    report = _report("quartz", draft=draft, sources=sources, recent_records=recent)
    assert any("최근 발행 글과 유사" in failure for failure in report.critical_failures)


def test_analysis_errors_are_critical():
    report = _report("quartz", analysis_errors=["계산 결과 불일치"])
    assert "계산 결과 불일치" in report.critical_failures


def test_firsthand_testing_claim_is_critical():
    sources = make_sources("quartz", 5)
    body = make_body("quartz") + "\n\n이 도구를 직접 사용해 보니 매우 편리했습니다."
    report = _report("quartz", draft=make_draft("quartz", body=body, sources=sources), sources=sources)
    assert any("직접 테스트" in failure for failure in report.critical_failures)


def test_short_body_is_critical():
    sources = make_sources("quartz", 5)
    report = _report(
        "quartz",
        draft=make_draft("quartz", body="짧은 본문입니다. [S1]", sources=sources),
        sources=sources,
    )
    assert any("본문이 너무 짧음" in failure for failure in report.critical_failures)


def test_low_score_requires_revision():
    report = QualityReport(scores=QualityScores(), total=50.0)
    decision, reason = decide_publication(report, get_profile("quartz"))
    assert decision == "REQUIRES REVISION"
    assert "50.0" in reason


def test_low_self_assessment_requires_revision():
    report = QualityReport(scores=QualityScores(), total=90.0, ai_self_total=70.0)
    decision, _ = decide_publication(report, get_profile("quartz"))
    assert decision == "REQUIRES REVISION"


def test_critical_overrides_high_score():
    report = QualityReport(scores=QualityScores(), total=99.0, critical_failures=["fabricated source"])
    decision, _ = decide_publication(report, get_profile("quartz"))
    assert decision == "DO NOT PUBLISH"
