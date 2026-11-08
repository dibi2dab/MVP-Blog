from __future__ import annotations

from src.editorial.analysis import (
    assumption,
    build_analysis_markdown,
    evaluation,
    format_dimension,
    metric,
    render_assumptions,
    render_comparison,
    render_dimension_table,
    render_evaluation_table,
    render_limitations,
    render_metrics_table,
    render_scenarios,
    render_sources,
    render_steps,
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


def test_evaluation_table_contains_all_items():
    analysis = _crystal()
    table = render_evaluation_table(analysis)
    assert "10가지 평가 항목" in table
    for item in analysis.evaluation_items:
        assert item.name in table


def test_metrics_table_and_steps_render():
    analysis = _crystal()
    metrics = render_metrics_table(analysis)
    assert "핵심 수치와 계산식" in metrics
    assert "월 예상 매출" in metrics
    steps = render_steps(analysis)
    assert "계산 과정" in steps
    assert "1." in steps


def test_scenarios_and_assumptions_render():
    analysis = _crystal()
    scenarios = render_scenarios(analysis)
    assert "시나리오 분석" in scenarios
    assert "conservative" in scenarios
    assumptions = render_assumptions(analysis)
    assert "공식 자료와 편집상 가정" in assumptions
    assert "편집상 가정" in assumptions


def test_quartz_comparison_renders_prices():
    analysis = _quartz()
    comparison = render_comparison(analysis)
    assert "가격과 기능 비교" in comparison
    assert "Zapier" in comparison
    assert "n8n Starter" in comparison


def test_dimension_table_reports_secondary_index():
    analysis = _crystal()
    table = render_dimension_table(analysis)
    assert "CPPI 구성 차원" in table
    assert "보조 지표" in table


def test_full_analysis_markdown_has_core_sections():
    analysis = _quartz()
    markdown = build_analysis_markdown(analysis)
    for heading in (
        "10가지 평가 항목",
        "핵심 수치와 계산식",
        "계산 과정",
        "시나리오 분석",
        "공식 자료와 편집상 가정",
        "가격과 기능 비교",
        "QDVI 구성 차원",
    ):
        assert heading in markdown
    assert build_analysis_markdown(analysis, include_dimensions=False).count("QDVI 구성 차원") == 0


def test_sources_and_limitations_render():
    entry = get_entry("quartz", "slack-pro")
    sources = render_sources(entry.source_records())
    assert "## 출처" in sources
    assert "https://slack.com/pricing" in sources
    assert "[S1]" in sources

    analysis = build_analysis(entry, "quartz")
    limitations = render_limitations(analysis)
    assert "한계와 주의사항" in limitations
    assert "보장하지" in limitations
