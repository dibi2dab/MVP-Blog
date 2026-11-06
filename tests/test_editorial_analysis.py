from __future__ import annotations

import pytest

from src.editorial.analysis import (
    build_analysis_markdown,
    build_sources_markdown,
    normalize_analysis,
)
from src.editorial.profiles import get_profile

from editorial_fixtures import make_analysis, make_sources


def _valid_analysis(blog: str = "quartz") -> dict:
    return make_analysis(blog)


def test_cppi_valid_calculation():
    validation = normalize_analysis(_valid_analysis("crystal"), get_profile("crystal"))
    assert validation.ok, validation.errors
    assert validation.analysis.framework == "CPPI"
    assert validation.analysis.result == pytest.approx(7.3)
    assert len(validation.analysis.dimensions) == 5
    assert all(dimension.score is not None for dimension in validation.analysis.dimensions)


def test_qdvi_valid_calculation():
    validation = normalize_analysis(_valid_analysis("quartz"), get_profile("quartz"))
    assert validation.ok, validation.errors
    assert validation.analysis.result == pytest.approx(7.65)


def test_result_is_recomputed_not_trusted():
    raw = _valid_analysis("quartz")
    raw["result"] = 9.9
    validation = normalize_analysis(raw, get_profile("quartz"))
    assert not validation.ok
    assert any("계산 결과 불일치" in error for error in validation.errors)
    # Even on mismatch the recomputed value is retained, never the disclosed one.
    assert validation.analysis.result == pytest.approx(7.65)


def test_framework_mismatch_is_rejected():
    raw = _valid_analysis("quartz")
    raw["framework"] = "CPPI"
    validation = normalize_analysis(raw, get_profile("quartz"))
    assert not validation.ok
    assert any("프레임워크 불일치" in error for error in validation.errors)


def test_missing_dimension_normalizes_weights():
    raw = _valid_analysis("quartz")
    raw["dimensions"] = [item for item in raw["dimensions"] if item["name"] != "Functional Capability"]
    raw["result"] = 7.53
    validation = normalize_analysis(raw, get_profile("quartz"))
    assert validation.ok, validation.errors
    missing = [d for d in validation.analysis.dimensions if d.unavailable]
    assert len(missing) == 1
    assert validation.analysis.result == pytest.approx(7.53)
    assert any("가중치를 정규화" in warning for warning in validation.warnings)


def test_too_few_dimensions_is_rejected():
    raw = _valid_analysis("quartz")
    raw["dimensions"] = raw["dimensions"][:2]
    validation = normalize_analysis(raw, get_profile("quartz"))
    assert not validation.ok
    assert any("최소 3개" in error for error in validation.errors)


def test_missing_required_fields_are_reported():
    raw = _valid_analysis("quartz")
    for key in ("purpose", "formula", "inputs", "data_sources", "steps", "limitations", "interpretation"):
        raw.pop(key, None)
    validation = normalize_analysis(raw, get_profile("quartz"))
    assert not validation.ok
    joined = " ".join(validation.errors)
    assert "분석 목적" in joined
    assert "계산 공식" in joined
    assert "입력값" in joined
    assert "데이터 출처" in joined
    assert "계산 과정" in joined
    assert "분석 한계" in joined
    assert "결과 해석" in joined


def test_analysis_markdown_is_canonical():
    validation = normalize_analysis(_valid_analysis("crystal"), get_profile("crystal"))
    markdown = build_analysis_markdown(validation.analysis, get_profile("crystal"))
    assert "Crystal Practical Profitability Index (CPPI)" in markdown
    assert "CPPI = " in markdown
    assert "7.30 / 10" in markdown
    assert "### 시나리오 분석" in markdown
    assert "### 분석의 한계" in markdown
    assert "평가 불가" not in markdown


def test_unavailable_dimension_rendered_as_unavailable():
    raw = _valid_analysis("quartz")
    raw["dimensions"] = [item for item in raw["dimensions"] if item["name"] != "Ease of Use"]
    raw["result"] = 7.56
    validation = normalize_analysis(raw, get_profile("quartz"))
    markdown = build_analysis_markdown(validation.analysis, get_profile("quartz"))
    assert "평가 불가" in markdown


def test_sources_markdown_contains_url_and_date():
    sources = make_sources("quartz", 3)
    markdown = build_sources_markdown(sources, get_profile("quartz"))
    assert "## 참고 자료" in markdown
    for source in sources:
        assert source.url in markdown
        assert source.published_at in markdown
    assert "QDVI" in markdown
