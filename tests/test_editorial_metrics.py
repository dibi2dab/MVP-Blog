from __future__ import annotations

import pytest

from src.editorial.metrics import build_analysis

from editorial_fixtures import get_entry


def _metric(analysis, key):
    return next(item for item in analysis.metrics if item.key == key)


def _item(analysis, key):
    return next(item for item in analysis.evaluation_items if item.key == key)


def test_crystal_analysis_has_ten_items_and_metrics():
    analysis = build_analysis(get_entry("crystal", "adsense-blog"), "crystal")
    assert analysis.framework == "CPPI"
    assert len(analysis.evaluation_items) == 10
    assert analysis.result is not None
    assert 0 <= analysis.result <= 10
    keys = {item.key for item in analysis.evaluation_items}
    assert {
        "initial_investment",
        "monthly_operating_cost",
        "expected_revenue",
        "expected_net_profit",
        "break_even",
        "hourly_net_profit",
        "roi",
        "revenue_variability",
        "operational_difficulty",
        "long_term_sustainability",
    } <= keys


def test_quartz_analysis_has_ten_items_and_metrics():
    analysis = build_analysis(get_entry("quartz", "notion-plus"), "quartz")
    assert analysis.framework == "QDVI"
    assert len(analysis.evaluation_items) == 10
    assert analysis.result is not None
    keys = {item.key for item in analysis.evaluation_items}
    assert {
        "feature_diversity",
        "practicality",
        "price_value",
        "ease_of_use",
        "usage_limit",
        "platform_support",
        "integration",
        "scalability",
        "stability_transparency",
        "fit_for_purpose",
    } <= keys


def test_advertising_revenue_formula():
    analysis = build_analysis(get_entry("crystal", "adsense-blog"), "crystal")
    assert _metric(analysis, "monthly_revenue").value == pytest.approx(30000 / 1000 * 3000 * 0.9)
    assert _metric(analysis, "monthly_operating_cost").value == pytest.approx(20000)
    assert _metric(analysis, "monthly_net_profit").value == pytest.approx(61000)
    assert _metric(analysis, "roi").value == pytest.approx(61000 / 300000 * 100)


def test_digital_product_revenue_uses_platform_fee():
    analysis = build_analysis(get_entry("crystal", "gumroad-digital-product"), "crystal")
    revenue = _metric(analysis, "monthly_revenue").value
    assert revenue == pytest.approx(20000 * 0.9 * 20)
    assert _metric(analysis, "monthly_operating_cost").value == pytest.approx(700 * 20)
    assert _metric(analysis, "monthly_net_profit").value == pytest.approx(360000 - 14000)


def test_service_revenue_and_roi_are_undefined_without_investment():
    analysis = build_analysis(get_entry("crystal", "upwork-freelance"), "crystal")
    assert _metric(analysis, "monthly_revenue").value == pytest.approx(30000 * 40)
    assert _metric(analysis, "monthly_operating_cost").value == pytest.approx(21000 + 3000 * 40)
    assert _metric(analysis, "monthly_net_profit").value == pytest.approx(1200000 - 141000)
    assert _metric(analysis, "roi").value is None
    assert _metric(analysis, "roi").display == "계산 불가"


def test_quartz_cost_metrics():
    analysis = build_analysis(get_entry("quartz", "notion-plus"), "quartz")
    assert _metric(analysis, "monthly_subscription_cost").value == pytest.approx(14000)
    assert _metric(analysis, "annual_subscription_cost").value == pytest.approx(168000)
    assert _metric(analysis, "cost_per_task").value == pytest.approx(14000 / 200)
    assert _metric(analysis, "cost_per_feature").value == pytest.approx(14000 / 4)


def test_usage_limit_unscored_without_included_units():
    analysis = build_analysis(get_entry("quartz", "notion-plus"), "quartz")
    usage = _item(analysis, "usage_limit")
    assert usage.score is None
    assert "무제한" in usage.basis


def test_usage_limit_scored_when_plan_has_tasks():
    analysis = build_analysis(get_entry("quartz", "zapier-pro"), "quartz")
    usage = _item(analysis, "usage_limit")
    assert usage.score == pytest.approx(10.0)
    assert "750" in usage.display


def test_editorial_assumptions_are_distinguished_from_official_data():
    analysis = build_analysis(get_entry("quartz", "notion-plus"), "quartz")
    editorial = [item for item in analysis.assumptions if item.is_editorial]
    official = [item for item in analysis.assumptions if not item.is_editorial]
    assert editorial, "expected at least one editorial assumption"
    assert any(item.name == "선택 요금제" for item in official)


def test_comparison_includes_primary_and_competitor():
    analysis = build_analysis(get_entry("quartz", "zapier-pro"), "quartz")
    assert len(analysis.comparison) >= 2
    assert analysis.comparison[0]["is_primary"] is True
