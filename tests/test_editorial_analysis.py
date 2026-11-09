from __future__ import annotations

import src.editorial.analysis as analysis_module
from src.editorial.analysis import (
    assumption,
    evaluation,
    format_dimension,
    metric,
    render_assumptions,
    render_comparison,
    render_limitations,
    render_metrics_table,
    render_scenarios,
    render_sources,
)
from src.editorial.metrics import build_analysis

from editorial_fixtures import get_entry


def _crystal():
    return build_analysis(get_entry("crystal", "adsense-blog"), "crystal")


def _quartz():
    return build_analysis(get_entry("quartz", "zapier-pro"), "quartz")


def test_metric_and_evaluation_lookup():
    analysis = _crystal()
    assert metric(analysis, "monthly_revenue") is not None
    assert evaluation(analysis, "expected_net_profit") is not None
    assert assumption(analysis, "월 투입 시간") is not None
    assert format_dimension(analysis, "Revenue Potential") is not None
    assert metric(analysis, "missing-key") is None


def test_metrics_table_renders_values_and_formulas():
    analysis = _crystal()
    table = render_metrics_table(analysis)
    assert "핵심 수치와 계산식" in table
    assert "월 예상 매출" in table
    assert "| 지표 | 값 | 계산식 |" in table


def test_scenarios_render_korean_names_and_no_raw_floats():
    analysis = _crystal()
    scenarios = render_scenarios(analysis)
    assert "시나리오 분석" in scenarios
    assert "보수적" in scenarios
    assert "기준" in scenarios
    assert "적극적" in scenarios
    assert "conservative" not in scenarios


def test_assumptions_separate_official_and_editorial():
    analysis = _crystal()
    assumptions = render_assumptions(analysis)
    assert "공식 자료와 편집상 가정" in assumptions
    assert "편집상 가정" in assumptions
    assert "공식 자료 없음" in assumptions


def test_quartz_comparison_renders_prices_without_feature_counts():
    analysis = _quartz()
    comparison = render_comparison(analysis)
    assert "경쟁 도구와 가격 비교" in comparison
    assert "Zapier" in comparison
    assert "n8n Starter" in comparison
    assert "기능 수" not in comparison
    assert "기능별" not in comparison


def test_sources_and_limitations_render():
    entry = get_entry("quartz", "slack-pro")
    sources = render_sources(entry.source_records())
    assert "## 출처" in sources
    assert "https://slack.com/pricing" in sources
    assert "[S1]" in sources

    analysis = build_analysis(entry, "quartz")
    limitations = render_limitations(analysis)
    assert "## 이 계산의 한계" in limitations
    assert "실제 사용 경험이 아닙니다" not in limitations


def test_removed_reader_facing_renderers_are_gone():
    for name in (
        "render_evaluation_table",
        "render_dimension_table",
        "render_steps",
        "build_analysis_markdown",
    ):
        assert not hasattr(analysis_module, name), name
