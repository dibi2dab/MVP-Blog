from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from src.editorial.catalog import CatalogEntryModel, CrystalModelSpec, QuartzProductSpec, RatingModel
from src.editorial.models import (
    AnalysisDimension,
    Assumption,
    EvaluationItem,
    MetricResult,
    OriginalAnalysis,
)

FRAMEWORK_SPECS: dict[str, dict[str, Any]] = {
    "CPPI": {
        "name": "Crystal Practical Profitability Index (CPPI)",
        "purpose": "온라인 수익 모델의 수익성, 비용 효율, 시간 효율, 실행 가능성, 위험 관리를 같은 기준으로 비교한다.",
        "formula": (
            "CPPI = (Revenue Potential x 0.25) + (Cost Efficiency x 0.20) + "
            "(Time Efficiency x 0.20) + (Execution Feasibility x 0.20) + (Risk Management x 0.15)"
        ),
        "dimensions": [
            ("Revenue Potential", 0.25),
            ("Cost Efficiency", 0.20),
            ("Time Efficiency", 0.20),
            ("Execution Feasibility", 0.20),
            ("Risk Management", 0.15),
        ],
    },
    "QDVI": {
        "name": "Quartz Digital Value Index (QDVI)",
        "purpose": "디지털 제품의 기능, 사용성, 가격 대비 가치, 통합·확장성, 신뢰성·투명성을 같은 기준으로 비교한다.",
        "formula": (
            "QDVI = (Functional Capability x 0.25) + (Ease of Use x 0.20) + "
            "(Price-to-Value x 0.20) + (Integration & Scalability x 0.15) + "
            "(Reliability & Transparency x 0.20)"
        ),
        "dimensions": [
            ("Functional Capability", 0.25),
            ("Ease of Use", 0.20),
            ("Price-to-Value", 0.20),
            ("Integration & Scalability", 0.15),
            ("Reliability & Transparency", 0.20),
        ],
    },
}

CRYSTAL_MAPPING = {
    "Revenue Potential": ["expected_revenue", "expected_net_profit", "roi"],
    "Cost Efficiency": ["initial_investment", "monthly_operating_cost", "break_even"],
    "Time Efficiency": ["hourly_net_profit"],
    "Execution Feasibility": ["operational_difficulty"],
    "Risk Management": ["revenue_variability", "long_term_sustainability"],
}

QUARTZ_MAPPING = {
    "Functional Capability": ["feature_diversity", "practicality", "fit_for_purpose"],
    "Ease of Use": ["ease_of_use"],
    "Price-to-Value": ["price_value", "usage_limit"],
    "Integration & Scalability": ["platform_support", "integration", "scalability"],
    "Reliability & Transparency": ["stability_transparency"],
}

CRYSTAL_RATING_KEYS = {
    "revenue_variability": "revenue_variability_risk",
    "operational_difficulty": "operational_difficulty",
    "long_term_sustainability": "long_term_sustainability",
}

QUARTZ_RATING_KEYS = {
    "feature_diversity": "feature_diversity",
    "practicality": "practicality",
    "price_value": "price_value",
    "ease_of_use": "ease_of_use",
    "scalability": "scalability",
    "stability_transparency": "stability_transparency",
    "fit_for_purpose": "fit_for_purpose",
}


# --------------------------------------------------------------------- helpers
def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return max(low, min(high, value))


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _krw(value: float | None) -> str:
    if value is None:
        return "계산 불가"
    return f"{value:,.0f}원"


def _pct(value: float | None) -> str:
    if value is None:
        return "계산 불가"
    return f"{value:,.1f}%"


def _hours(value: float | None) -> str:
    if value is None:
        return "계산 불가"
    return f"{value:,.1f}시간"


def _units_display(value: float | None, driver: "_CrystalDriver") -> str:
    """Render a driver-unit quantity using its real-world unit.

    Advertising revenue is modelled per 1,000 pageviews, so a break-even
    quantity of 7.4 driver units means 7,400 actual pageviews. Displaying the
    driver unit directly produced values like "7.41,000 방문".
    """

    if value is None:
        return "계산 불가"
    scaled = value * driver.unit_scale
    label = driver.unit_display or driver.unit_label
    decimals = 0 if driver.unit_scale > 1 else 1
    return f"{scaled:,.{decimals}f}{label}"


def _positive_score(value: float | None, low: float, high: float) -> float | None:
    """0 at/below ``low``, 10 at/above ``high``, linear in between."""

    if value is None:
        return None
    if high <= low:
        return None
    return round(_clamp((value - low) / (high - low) * 10), 2)


def _inverse_score(value: float | None, best: float, worst: float) -> float | None:
    """10 at ``best``, 0 at ``worst``, linear in between (lower is better)."""

    if value is None:
        return None
    if worst <= best:
        return None
    return round(_clamp((worst - value) / (worst - best) * 10), 2)


def _rating(entry: CatalogEntryModel, key: str) -> RatingModel | None:
    if key in entry.ratings:
        return entry.ratings[key]
    if entry.product is not None and key in entry.product.ratings:
        return entry.product.ratings[key]
    return None


def _rating_item(
    entry: CatalogEntryModel,
    *,
    item_key: str,
    name: str,
    rating_key: str,
    invert: bool = False,
) -> EvaluationItem:
    rating = _rating(entry, rating_key)
    if rating is None:
        return EvaluationItem(
            key=item_key,
            name=name,
            value=None,
            display="평가 근거 없음",
            score=None,
            basis="카탈로그에 이 항목의 평가 근거가 없습니다.",
        )
    score = 10 - rating.score if invert else rating.score
    return EvaluationItem(
        key=item_key,
        name=name,
        value=rating.score,
        display=f"{rating.score:.1f} / 10",
        unit="점",
        score=round(_clamp(score), 2),
        basis=rating.basis,
        source_ids=list(rating.source_ids),
    )


def _source_ids(entry: CatalogEntryModel, *keys: str) -> list[str]:
    found: list[str] = []
    for key in keys:
        for source_id in entry.sourced_inputs.get(key, []):
            if source_id not in found:
                found.append(source_id)
    return found


def _assumption_flag(entry: CatalogEntryModel, *keys: str) -> bool:
    return not any(entry.sourced_inputs.get(key) for key in keys)


def _catalog_assumptions(entry: CatalogEntryModel) -> list[Assumption]:
    """Convert catalog assumption models into analysis assumptions."""

    return [Assumption(**item.model_dump()) for item in entry.assumptions]


_CRYSTAL_INPUT_KEYS = {
    "advertising": ("monthly_pageviews", "rpm_krw", "fill_rate"),
    "subscription": ("price_per_unit_krw", "units_per_month"),
    "affiliate": ("monthly_clicks", "conversion_rate", "commission_krw"),
    "digital_product": ("price_per_unit_krw", "units_per_month", "platform_fee_rate"),
    "service": ("hourly_rate_krw", "billable_hours_per_month"),
}


def _crystal_input_keys(spec: CrystalModelSpec) -> tuple[str, ...]:
    return _CRYSTAL_INPUT_KEYS.get(spec.type, ())


def _dimensions(
    framework: str,
    items: list[EvaluationItem],
    mapping: dict[str, list[str]],
) -> tuple[list[AnalysisDimension], float | None, list[str]]:
    spec = FRAMEWORK_SPECS[framework]
    by_key = {item.key: item for item in items}
    dimensions: list[AnalysisDimension] = []
    warnings: list[str] = []
    for name, weight in spec["dimensions"]:
        mapped = mapping.get(name, [])
        scores = [
            by_key[key].score
            for key in mapped
            if key in by_key and by_key[key].score is not None
        ]
        if scores:
            score = round(sum(scores) / len(scores), 2)
            dimensions.append(
                AnalysisDimension(
                    name=name,
                    score=score,
                    weight=weight,
                    rationale=", ".join(
                        f"{by_key[key].name} {by_key[key].score:.1f}"
                        for key in mapped
                        if key in by_key and by_key[key].score is not None
                    ),
                    mapped_items=mapped,
                )
            )
        else:
            dimensions.append(
                AnalysisDimension(
                    name=name,
                    score=None,
                    weight=weight,
                    rationale="제공된 자료로 평가할 수 없음",
                    unavailable=True,
                    mapped_items=mapped,
                )
            )
            warnings.append(f"{name} 차원을 평가할 수 없어 가중치를 정규화합니다.")
    available = [dimension for dimension in dimensions if dimension.score is not None]
    weight_sum = sum(dimension.weight for dimension in available)
    result = None
    if available and weight_sum > 0:
        result = round(
            sum(dimension.score * dimension.weight for dimension in available) / weight_sum,
            2,
        )
    return dimensions, result, warnings


def _interpretation(framework: str, result: float | None, entry: CatalogEntryModel) -> str:
    if result is None:
        return "평가 가능한 항목이 부족해 종합 점수를 계산하지 않았습니다."
    if framework == "CPPI":
        if result >= 8:
            level = "수익성과 실행 가능성이 모두 높은 편"
        elif result >= 6.5:
            level = "수익성과 위험의 균형이 무난한 편"
        elif result >= 5:
            level = "일부 조건이 맞아야 수익성이 나오는 편"
        else:
            level = "비용·위험 부담이 커 신중한 검토가 필요한 편"
        return (
            f"{entry.name}의 CPPI는 {result:.2f}/10으로, {level}으로 해석됩니다. "
            "이 점수는 공개 자료와 명시된 가정으로 계산한 편집상 의사결정 지표이며, "
            "실제 수익을 보장하지 않습니다."
        )
    if result >= 8:
        level = "기능과 가격 대비 가치가 모두 높은 편"
    elif result >= 6.5:
        level = "기능과 가격의 균형이 무난한 편"
    elif result >= 5:
        level = "특정 사용 목적에 맞을 때 가치가 있는 편"
    else:
        level = "가격이나 기능 제약을 먼저 확인해야 하는 편"
    return (
        f"{entry.name}의 QDVI는 {result:.2f}/10으로, {level}으로 해석됩니다. "
        "이 점수는 공식 문서와 공개 가격표를 바탕으로 한 편집상 평가이며, "
        "독립적인 과학적 측정값이 아닙니다."
    )


def _base_analysis(entry: CatalogEntryModel, framework: str) -> OriginalAnalysis:
    spec = FRAMEWORK_SPECS[framework]
    return OriginalAnalysis(
        framework=framework,
        framework_name=spec["name"],
        purpose=spec["purpose"],
        formula=spec["formula"],
        subject=entry.name,
    )


# ---------------------------------------------------------------------- Crystal
@dataclass
class _CrystalDriver:
    revenue: float | None
    units: float | None
    price_per_unit: float | None
    variable_per_unit: float
    unit_label: str
    formula: str
    unit_scale: float = 1.0
    unit_display: str = ""
    missing: list[str] = field(default_factory=list)


def _crystal_driver(spec: CrystalModelSpec, multiplier: float = 1.0) -> _CrystalDriver:
    inputs = spec.inputs
    variable = spec.variable_cost_per_unit_krw
    if spec.type == "advertising":
        views = _num(inputs.get("monthly_pageviews"))
        rpm = _num(inputs.get("rpm_krw"))
        fill = _num(inputs.get("fill_rate")) or 1.0
        missing = [name for name, value in (("monthly_pageviews", views), ("rpm_krw", rpm)) if value is None]
        revenue = None if views is None or rpm is None else views * multiplier / 1000 * rpm * fill
        units = None if views is None else views * multiplier / 1000
        price = None if rpm is None else rpm * fill
        return _CrystalDriver(
            revenue=revenue,
            units=units,
            price_per_unit=price,
            variable_per_unit=variable,
            unit_label="1,000 방문",
            formula="월 매출 = 월 방문자 수 / 1,000 × RPM × 광고 채움률",
            unit_scale=1000.0,
            unit_display="방문",
            missing=missing,
        )
    if spec.type == "subscription":
        price = _num(spec.price_per_unit_krw if spec.price_per_unit_krw is not None else inputs.get("price_per_unit_krw"))
        base_units = _num(spec.units_per_month if spec.units_per_month is not None else inputs.get("units_per_month"))
        missing = [name for name, value in (("price_per_unit_krw", price), ("units_per_month", base_units)) if value is None]
        units = None if base_units is None else base_units * multiplier
        revenue = None if price is None or units is None else price * units
        return _CrystalDriver(
            revenue=revenue,
            units=units,
            price_per_unit=price,
            variable_per_unit=variable,
            unit_label="구독자",
            formula="월 매출 = 단가 × 월 구독자 수",
            missing=missing,
        )
    if spec.type == "affiliate":
        clicks = _num(inputs.get("monthly_clicks"))
        conversion = _num(inputs.get("conversion_rate"))
        commission = _num(inputs.get("commission_krw"))
        missing = [
            name
            for name, value in (
                ("monthly_clicks", clicks),
                ("conversion_rate", conversion),
                ("commission_krw", commission),
            )
            if value is None
        ]
        revenue = (
            None
            if clicks is None or conversion is None or commission is None
            else clicks * multiplier * conversion * commission
        )
        units = None if clicks is None else clicks * multiplier
        price = None if conversion is None or commission is None else conversion * commission
        return _CrystalDriver(
            revenue=revenue,
            units=units,
            price_per_unit=price,
            variable_per_unit=variable,
            unit_label="클릭",
            formula="월 매출 = 월 클릭 수 × 전환율 × 건당 수수료",
            missing=missing,
        )
    if spec.type == "digital_product":
        price = _num(spec.price_per_unit_krw if spec.price_per_unit_krw is not None else inputs.get("price_per_unit_krw"))
        base_units = _num(spec.units_per_month if spec.units_per_month is not None else inputs.get("units_per_month"))
        fee = _num(inputs.get("platform_fee_rate")) or 0.0
        missing = [name for name, value in (("price_per_unit_krw", price), ("units_per_month", base_units)) if value is None]
        units = None if base_units is None else base_units * multiplier
        net_price = None if price is None else price * (1 - fee)
        revenue = None if net_price is None or units is None else net_price * units
        return _CrystalDriver(
            revenue=revenue,
            units=units,
            price_per_unit=net_price,
            variable_per_unit=variable,
            unit_label="판매",
            formula="월 매출 = 판매가 × (1 - 플랫폼 수수료율) × 월 판매 수량",
            missing=missing,
        )
    # service
    rate = _num(inputs.get("hourly_rate_krw"))
    hours = _num(inputs.get("billable_hours_per_month"))
    missing = [name for name, value in (("hourly_rate_krw", rate), ("billable_hours_per_month", hours)) if value is None]
    units = None if hours is None else hours * multiplier
    revenue = None if rate is None or units is None else rate * units
    return _CrystalDriver(
        revenue=revenue,
        units=units,
        price_per_unit=rate,
        variable_per_unit=variable,
        unit_label="시간",
        formula="월 매출 = 시간당 단가 × 월 청구 가능 시간",
        missing=missing,
    )


def _crystal_metric(
    key: str,
    name: str,
    value: float | None,
    display: str,
    unit: str,
    formula: str,
    entry: CatalogEntryModel,
    *input_keys: str,
    assumption: bool | None = None,
    unavailable_reason: str = "",
) -> MetricResult:
    return MetricResult(
        key=key,
        name=name,
        value=value,
        display=display,
        unit=unit,
        formula=formula,
        inputs={},
        assumption=_assumption_flag(entry, *input_keys) if assumption is None else assumption,
        source_ids=_source_ids(entry, *input_keys),
        unavailable_reason=unavailable_reason if value is None else "",
    )


def build_crystal_analysis(entry: CatalogEntryModel) -> OriginalAnalysis:
    spec = entry.model
    if spec is None:
        raise ValueError(f"crystal entry {entry.id} is missing model")
    analysis = _base_analysis(entry, "CPPI")
    driver = _crystal_driver(spec)
    fixed = spec.fixed_monthly_krw
    units = driver.units
    total_cost = None if units is None else fixed + driver.variable_per_unit * units
    net = None if driver.revenue is None or total_cost is None else driver.revenue - total_cost
    annual_net = None if net is None else net * 12
    initial = spec.initial_investment_krw
    roi = _safe_div(net, initial) if initial and initial > 0 else None
    roi = None if roi is None else roi * 100
    hours = spec.monthly_hours
    hourly = _safe_div(net, hours)
    contribution = (
        None
        if driver.price_per_unit is None
        else driver.price_per_unit - driver.variable_per_unit
    )
    break_even_units = None
    if contribution is not None and contribution > 0:
        break_even_units = fixed / contribution
    break_even_months = None
    if net is not None and net > 0:
        break_even_months = initial / net
    elif initial == 0:
        break_even_months = 0.0

    metrics = [
        _crystal_metric(
            "monthly_revenue",
            "월 예상 매출",
            driver.revenue,
            _krw(driver.revenue),
            "원",
            driver.formula,
            entry,
            "monthly_pageviews",
            "rpm_krw",
            "price_per_unit_krw",
            "units_per_month",
            "monthly_clicks",
            "conversion_rate",
            "commission_krw",
            "hourly_rate_krw",
            "billable_hours_per_month",
            unavailable_reason=", ".join(driver.missing) + " 입력값이 없습니다.",
        ),
        _crystal_metric(
            "monthly_operating_cost",
            "월 운영 비용",
            total_cost,
            _krw(total_cost),
            "원",
            "월 운영 비용 = 고정비 + 단위당 변동비 × 월 처리량",
            entry,
            "fixed_monthly_krw",
            "variable_cost_per_unit_krw",
        ),
        _crystal_metric(
            "monthly_net_profit",
            "월 예상 순이익",
            net,
            _krw(net),
            "원",
            "순이익 = 월 매출 - 월 운영 비용",
            entry,
        ),
        _crystal_metric(
            "annual_net_profit",
            "연간 예상 순이익",
            annual_net,
            _krw(annual_net),
            "원",
            "연간 순이익 = 월 순이익 × 12",
            entry,
        ),
        _crystal_metric(
            "initial_investment",
            "초기 투자 비용",
            initial,
            _krw(initial),
            "원",
            "카탈로그에 기록된 초기 투자 비용",
            entry,
            "initial_investment_krw",
        ),
        _crystal_metric(
            "roi",
            "투자수익률(ROI)",
            roi,
            _pct(roi),
            "%",
            "ROI = 월 순이익 / 초기 투자 비용 × 100",
            entry,
            unavailable_reason="초기 투자 비용이 0이어서 ROI를 정의할 수 없습니다.",
        ),
        _crystal_metric(
            "hourly_net_profit",
            "시간당 순수익",
            hourly,
            _krw(hourly),
            "원/시간",
            "시간당 순수익 = 월 순이익 / 월 투입 시간",
            entry,
            "monthly_hours",
            unavailable_reason="월 투입 시간이 없거나 0입니다.",
        ),
        _crystal_metric(
            "break_even_units",
            "손익분기 처리량",
            break_even_units,
            _units_display(break_even_units, driver),
            driver.unit_label,
            "손익분기 처리량 = 고정비 / (단위당 판매가 - 단위당 변동비)",
            entry,
            unavailable_reason="단위당 공헌이익이 0 이하입니다.",
        ),
        _crystal_metric(
            "break_even_months",
            "손익분기 도달 기간",
            break_even_months,
            "계산 불가" if break_even_months is None else f"{break_even_months:,.1f}개월",
            "개월",
            "손익분기 도달 기간 = 초기 투자 비용 / 월 순이익",
            entry,
            unavailable_reason="월 순이익이 0 이하입니다.",
        ),
    ]

    def metric(key: str) -> MetricResult:
        return next(item for item in metrics if item.key == key)

    risk = _rating_item(
        entry,
        item_key="revenue_variability",
        name="수익 변동 위험",
        rating_key=CRYSTAL_RATING_KEYS["revenue_variability"],
        invert=True,
    )
    difficulty = _rating_item(
        entry,
        item_key="operational_difficulty",
        name="운영 난이도",
        rating_key=CRYSTAL_RATING_KEYS["operational_difficulty"],
        invert=True,
    )
    sustainability = _rating_item(
        entry,
        item_key="long_term_sustainability",
        name="장기 지속 가능성",
        rating_key=CRYSTAL_RATING_KEYS["long_term_sustainability"],
    )

    monthly_revenue = metric("monthly_revenue").value
    monthly_cost = metric("monthly_operating_cost").value
    monthly_net = metric("monthly_net_profit").value
    hourly_value = metric("hourly_net_profit").value
    roi_value = metric("roi").value
    be_units = metric("break_even_units").value
    be_months = metric("break_even_months").value

    break_even_item = EvaluationItem(
        key="break_even",
        name="손익분기점",
        value=be_months if be_months is not None else be_units,
        display=(
            f"{be_months:,.1f}개월"
            if be_months is not None
            else _units_display(be_units, driver)
        ),
        unit="개월" if be_months is not None else driver.unit_label,
        score=(
            _inverse_score(be_months, 1, 24)
            if be_months is not None
            else (
                _inverse_score(be_units, 0, (units or 0) * 3)
                if be_units is not None and units
                else None
            )
        ),
        basis="손익분기 도달 기간이 짧을수록 높은 점수(1개월=10, 24개월=0).",
        source_ids=metric("break_even_months").source_ids,
    )

    items = [
        EvaluationItem(
            key="initial_investment",
            name="초기 투자 비용",
            value=initial,
            display=_krw(initial),
            unit="원",
            score=_inverse_score(initial, 0, 5_000_000),
            basis="초기 투자 비용이 낮을수록 높은 점수(0원=10, 500만원 이상=0).",
            assumption=_assumption_flag(entry, "initial_investment_krw"),
            source_ids=_source_ids(entry, "initial_investment_krw"),
        ),
        EvaluationItem(
            key="monthly_operating_cost",
            name="월간 운영 비용",
            value=monthly_cost,
            display=_krw(monthly_cost),
            unit="원",
            score=_inverse_score(monthly_cost, 0, 1_000_000),
            basis="월 운영 비용이 낮을수록 높은 점수(0원=10, 100만원 이상=0).",
            assumption=_assumption_flag(entry, "fixed_monthly_krw", "variable_cost_per_unit_krw"),
            source_ids=_source_ids(entry, "fixed_monthly_krw", "variable_cost_per_unit_krw"),
        ),
        EvaluationItem(
            key="expected_revenue",
            name="예상 매출",
            value=monthly_revenue,
            display=_krw(monthly_revenue),
            unit="원",
            score=_positive_score(monthly_revenue, 0, 5_000_000),
            basis="월 매출이 클수록 높은 점수(0원=0, 500만원 이상=10).",
            assumption=_assumption_flag(entry, *_crystal_input_keys(spec)),
            source_ids=metric("monthly_revenue").source_ids,
        ),
        EvaluationItem(
            key="expected_net_profit",
            name="예상 순이익",
            value=monthly_net,
            display=_krw(monthly_net),
            unit="원",
            score=(
                None
                if monthly_net is None
                else (0.0 if monthly_net <= 0 else round(_clamp(5 + 5 * monthly_net / 3_000_000), 2))
            ),
            basis="월 순이익이 0 이하이면 0, 300만원 이상이면 10.",
            assumption=_assumption_flag(entry, *_crystal_input_keys(spec)),
            source_ids=metric("monthly_net_profit").source_ids,
        ),
        break_even_item,
        EvaluationItem(
            key="hourly_net_profit",
            name="시간당 순수익",
            value=hourly_value,
            display=_krw(hourly_value),
            unit="원/시간",
            score=_positive_score(hourly_value, 0, 50_000),
            basis="시간당 순수익이 클수록 높은 점수(0원=0, 5만원 이상=10).",
            assumption=_assumption_flag(entry, "monthly_hours"),
            source_ids=metric("hourly_net_profit").source_ids,
        ),
        EvaluationItem(
            key="roi",
            name="투자수익률(ROI)",
            value=roi_value,
            display=_pct(roi_value),
            unit="%",
            score=_positive_score(roi_value, 0, 100),
            basis="ROI가 높을수록 높은 점수(0%=0, 100% 이상=10).",
            source_ids=metric("roi").source_ids,
        ),
        risk,
        difficulty,
        sustainability,
    ]

    dimensions, result, warnings = _dimensions("CPPI", items, CRYSTAL_MAPPING)
    analysis.evaluation_items = items
    analysis.metrics = metrics
    analysis.dimensions = dimensions
    analysis.result = result
    analysis.mapping = CRYSTAL_MAPPING
    analysis.interpretation = _interpretation("CPPI", result, entry)
    analysis.data_sources = _collect_sources(entry, items)
    analysis.inputs = _crystal_inputs(spec)
    analysis.assumptions = _crystal_assumptions(entry, spec, driver)
    analysis.steps = _crystal_steps(metric, driver, spec)
    analysis.limitations = list(entry.limitations) + [
        "실제 수익은 방문자 수, 광고 단가, 수수료 변화에 따라 계산 결과와 달라질 수 있습니다.",
        "가격, 수수료, 광고 단가는 변경될 수 있으므로 의사결정 전 최신 자료를 다시 확인해야 합니다.",
    ]
    analysis.scenario_analysis = _crystal_scenarios(entry, spec)
    analysis.warnings = warnings
    return analysis


def _collect_sources(entry: CatalogEntryModel, items: Iterable[EvaluationItem]) -> list[str]:
    found: list[str] = []
    for item in items:
        for source_id in item.source_ids:
            if source_id not in found:
                found.append(source_id)
    for source in entry.sources:
        if source.id not in found:
            found.append(source.id)
    return found


def _crystal_inputs(spec: CrystalModelSpec) -> dict[str, Any]:
    rows: dict[str, Any] = {"사업 유형": spec.type}
    for key, value in spec.inputs.items():
        rows[key] = value
    if spec.price_per_unit_krw is not None:
        rows["price_per_unit_krw"] = spec.price_per_unit_krw
    if spec.units_per_month is not None:
        rows["units_per_month"] = spec.units_per_month
    if spec.monthly_hours is not None:
        rows["monthly_hours"] = spec.monthly_hours
    rows["initial_investment_krw"] = spec.initial_investment_krw
    rows["fixed_monthly_krw"] = spec.fixed_monthly_krw
    rows["variable_cost_per_unit_krw"] = spec.variable_cost_per_unit_krw
    return rows


def _crystal_assumptions(
    entry: CatalogEntryModel,
    spec: CrystalModelSpec,
    driver: _CrystalDriver,
) -> list[Assumption]:
    assumptions: list[Assumption] = []
    labels = {
        "monthly_pageviews": ("월 방문자 수", "명"),
        "rpm_krw": ("1,000회 노출당 수익(RPM)", "원"),
        "fill_rate": ("광고 채움률", "비율"),
        "price_per_unit_krw": ("단위당 판매가", "원"),
        "units_per_month": ("월 판매·구독 수량", "건"),
        "monthly_clicks": ("월 클릭 수", "회"),
        "conversion_rate": ("전환율", "비율"),
        "commission_krw": ("건당 수수료", "원"),
        "platform_fee_rate": ("플랫폼 수수료율", "비율"),
        "hourly_rate_krw": ("시간당 단가", "원"),
        "billable_hours_per_month": ("월 청구 가능 시간", "시간"),
    }
    for key, value in spec.inputs.items():
        name, unit = labels.get(key, (key, ""))
        sourced = _source_ids(entry, key)
        assumptions.append(
            Assumption(
                name=name,
                value=f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value),
                unit=unit,
                basis="공식 자료" if sourced else "편집상 가정",
                source_ids=sourced,
            )
        )
    if spec.price_per_unit_krw is not None and "price_per_unit_krw" not in spec.inputs:
        sourced = _source_ids(entry, "price_per_unit_krw")
        assumptions.append(
            Assumption(
                name="단위당 판매가",
                value=_krw(spec.price_per_unit_krw),
                unit="원",
                basis="공식 자료" if sourced else "편집상 가정",
                source_ids=sourced,
            )
        )
    if spec.units_per_month is not None and "units_per_month" not in spec.inputs:
        sourced = _source_ids(entry, "units_per_month")
        assumptions.append(
            Assumption(
                name="월 판매·구독 수량",
                value=f"{spec.units_per_month:,.1f}",
                unit="건",
                basis="공식 자료" if sourced else "편집상 가정",
                source_ids=sourced,
            )
        )
    sourced_hours = _source_ids(entry, "monthly_hours")
    assumptions.append(
        Assumption(
            name="월 투입 시간",
            value=f"{spec.monthly_hours:,.1f}" if spec.monthly_hours is not None else "미입력",
            unit="시간",
            basis="공식 자료" if sourced_hours else "편집상 가정",
            source_ids=sourced_hours,
        )
    )
    seen = {item.name for item in assumptions}
    for item in _catalog_assumptions(entry):
        if item.name not in seen:
            assumptions.append(item)
            seen.add(item.name)
    return assumptions


def _crystal_steps(
    metric: Any,
    driver: _CrystalDriver,
    spec: CrystalModelSpec,
) -> list[str]:
    steps = [driver.formula + "."]
    monthly_revenue = metric("monthly_revenue")
    monthly_cost = metric("monthly_operating_cost")
    monthly_net = metric("monthly_net_profit")
    roi = metric("roi")
    hourly = metric("hourly_net_profit")
    be_units = metric("break_even_units")
    be_months = metric("break_even_months")
    if monthly_revenue.value is not None:
        steps.append(f"월 예상 매출 = {monthly_revenue.display}.")
    if monthly_cost.value is not None:
        steps.append(f"월 운영 비용 = {monthly_cost.display}.")
    if monthly_net.value is not None:
        steps.append(f"월 예상 순이익 = {monthly_revenue.display} - {monthly_cost.display} = {monthly_net.display}.")
    if roi.value is not None:
        steps.append(
            f"ROI = 월 순이익 {monthly_net.display} / "
            f"초기 투자 {_krw(spec.initial_investment_krw)} × 100 = {roi.display}."
        )
    if hourly.value is not None:
        steps.append(
            f"시간당 순수익 = 월 순이익 {monthly_net.display} / 월 투입 시간 "
            f"{spec.monthly_hours:,.1f}시간 = {hourly.display}."
        )
    if be_units.value is not None:
        steps.append(f"손익분기 처리량 = 고정비 / 단위당 공헌이익 = {be_units.display}.")
    if be_months.value is not None:
        steps.append(f"손익분기 도달 기간 = 초기 투자 / 월 순이익 = {be_months.display}.")
    steps.append("각 항목을 0~10점으로 정규화한 뒤 CPPI 가중치로 종합한다.")
    return steps


def _crystal_scenarios(entry: CatalogEntryModel, spec: CrystalModelSpec) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for name, multiplier in spec.scenarios.items():
        driver = _crystal_driver(spec, multiplier)
        if driver.revenue is None or driver.units is None:
            scenarios.append(
                {
                    "scenario": name,
                    "assumptions": f"처리량 배수 {multiplier:.2f}",
                    "result": "입력값이 부족해 계산할 수 없음",
                }
            )
            continue
        total_cost = spec.fixed_monthly_krw + driver.variable_per_unit * driver.units
        net = driver.revenue - total_cost
        hourly = _safe_div(net, spec.monthly_hours)
        roi = _safe_div(net, spec.initial_investment_krw) if spec.initial_investment_krw else None
        scenarios.append(
            {
                "scenario": name,
                "assumptions": f"기준 처리량의 {multiplier:.2f}배, 고정비 {_krw(spec.fixed_monthly_krw)} 유지",
                "monthly_revenue": round(driver.revenue, 2),
                "monthly_cost": round(total_cost, 2),
                "monthly_net_profit": round(net, 2),
                "hourly_net_profit": None if hourly is None else round(hourly, 2),
                "roi_percent": None if roi is None else round(roi * 100, 2),
                "result": f"월 순이익 {_krw(net)}, 시간당 {_krw(hourly)}",
            }
        )
    return scenarios


# ----------------------------------------------------------------------- Quartz
def _quartz_plan_cost(product: QuartzProductSpec) -> tuple[float | None, float | None, Any]:
    plan = next((item for item in product.plans if item.name == product.selected_plan), None)
    if plan is None:
        return None, None, None
    monthly = plan.monthly_krw
    annual = plan.annual_krw
    if monthly is None and annual is not None:
        monthly = annual / 12
    if annual is None and monthly is not None:
        annual = monthly * 12
    return monthly, annual, plan


def build_quartz_analysis(entry: CatalogEntryModel) -> OriginalAnalysis:
    product = entry.product
    if product is None:
        raise ValueError(f"quartz entry {entry.id} is missing product")
    analysis = _base_analysis(entry, "QDVI")
    monthly, annual, plan = _quartz_plan_cost(product)
    tasks = product.tasks_per_month
    minutes = product.minutes_saved_per_task
    hourly_labor = product.hourly_labor_cost_krw
    features = [feature for feature in product.features if feature.available]
    feature_count = len(features)
    cost_per_task = _safe_div(monthly, tasks)
    cost_per_feature = _safe_div(monthly, feature_count)
    time_saved_hours = _safe_div(tasks * minutes, 60) if tasks is not None and minutes is not None else None
    time_value = time_saved_hours * hourly_labor if time_saved_hours is not None and hourly_labor is not None else None
    net_time_value = time_value - monthly if time_value is not None and monthly is not None else None

    metrics = [
        MetricResult(
            key="monthly_subscription_cost",
            name="월 구독 비용",
            value=monthly,
            display=_krw(monthly),
            unit="원/월",
            formula="선택 요금제의 월 구독료",
            assumption=_assumption_flag(entry, "selected_plan"),
            source_ids=_source_ids(entry, "selected_plan"),
            unavailable_reason="" if monthly is not None else "선택 요금제의 월 가격이 없습니다.",
        ),
        MetricResult(
            key="annual_subscription_cost",
            name="연 구독 비용",
            value=annual,
            display=_krw(annual),
            unit="원/년",
            formula="선택 요금제의 연 구독료(없으면 월 구독료 × 12)",
            assumption=_assumption_flag(entry, "selected_plan"),
            source_ids=_source_ids(entry, "selected_plan"),
            unavailable_reason="" if annual is not None else "선택 요금제의 연 가격이 없습니다.",
        ),
        MetricResult(
            key="cost_per_task",
            name="작업당 비용",
            value=cost_per_task,
            display=_krw(cost_per_task),
            unit="원/작업",
            formula="작업당 비용 = 월 구독 비용 / 월 작업 수",
            assumption=_assumption_flag(entry, "tasks_per_month"),
            source_ids=_source_ids(entry, "tasks_per_month"),
            unavailable_reason="" if cost_per_task is not None else "월 작업 수가 없거나 0입니다.",
        ),
        MetricResult(
            key="feature_count",
            name="사용 가능 기능 수",
            value=float(feature_count),
            display=f"{feature_count}개",
            unit="개",
            formula="카탈로그에 사용 가능으로 기록된 기능 수",
            assumption=False,
            source_ids=_feature_sources(features),
            unavailable_reason="" if feature_count else "사용 가능한 기능이 기록되지 않았습니다.",
        ),
        MetricResult(
            key="cost_per_feature",
            name="기능별 비용",
            value=cost_per_feature,
            display=_krw(cost_per_feature),
            unit="원/기능",
            formula="기능별 비용 = 월 구독 비용 / 사용 가능 기능 수",
            assumption=_assumption_flag(entry, "selected_plan"),
            source_ids=_source_ids(entry, "selected_plan"),
            unavailable_reason="" if cost_per_feature is not None else "월 비용이나 기능 수가 없습니다.",
        ),
        MetricResult(
            key="time_saved_hours",
            name="월 절감 시간",
            value=time_saved_hours,
            display=_hours(time_saved_hours),
            unit="시간/월",
            formula="월 절감 시간 = 월 작업 수 × 작업당 절감 분 / 60",
            assumption=_assumption_flag(entry, "tasks_per_month", "minutes_saved_per_task"),
            source_ids=_source_ids(entry, "tasks_per_month", "minutes_saved_per_task"),
            unavailable_reason="" if time_saved_hours is not None else "월 작업 수나 작업당 절감 시간이 없습니다.",
        ),
        MetricResult(
            key="time_value",
            name="절감 시간의 가치",
            value=time_value,
            display=_krw(time_value),
            unit="원/월",
            formula="절감 시간 가치 = 월 절감 시간 × 시간당 인건비",
            assumption=_assumption_flag(entry, "hourly_labor_cost_krw", "minutes_saved_per_task"),
            source_ids=_source_ids(entry, "hourly_labor_cost_krw", "minutes_saved_per_task"),
            unavailable_reason="" if time_value is not None else "시간당 인건비나 절감 시간이 없습니다.",
        ),
        MetricResult(
            key="net_time_value",
            name="시간 절감 순가치",
            value=net_time_value,
            display=_krw(net_time_value),
            unit="원/월",
            formula="시간 절감 순가치 = 절감 시간 가치 - 월 구독 비용",
            assumption=_assumption_flag(entry, "hourly_labor_cost_krw", "minutes_saved_per_task"),
            source_ids=_source_ids(entry, "hourly_labor_cost_krw", "minutes_saved_per_task"),
            unavailable_reason="" if net_time_value is not None else "계산에 필요한 입력값이 없습니다.",
        ),
    ]

    def metric(key: str) -> MetricResult:
        return next(item for item in metrics if item.key == key)

    def rating_item(item_key: str, name: str, rating_key: str) -> EvaluationItem:
        return _rating_item(
            entry,
            item_key=item_key,
            name=name,
            rating_key=rating_key,
        )

    usage_score = None
    usage_display = product.usage_limits or "사용량 정보 없음"
    usage_value = None
    usage_basis = "요금제에 포함된 사용량이 월 작업 수를 충분히 덮는지 평가합니다."
    if plan is not None and plan.included_units is not None and tasks:
        usage_value = plan.included_units
        if plan.included_units >= tasks:
            usage_score = 10.0
            usage_display = f"월 {plan.included_units:,.0f}{plan.unit or '단위'} 포함 (충분)"
        else:
            usage_score = round(_clamp(10 * plan.included_units / tasks), 2)
            usage_display = f"월 {plan.included_units:,.0f}{plan.unit or '단위'} 포함 (부족)"
    elif plan is not None and plan.included_units is None:
        usage_basis = (
            "공식 요금제에 포함 사용량 수치가 없어 점수를 매기지 않았습니다. "
            "무제한이라는 의미가 아니므로 공식 문서에서 확인해야 합니다."
        )
    else:
        usage_basis = "요금제 사용량 정보가 없어 평가할 수 없습니다."

    items = [
        rating_item("feature_diversity", "기능의 다양성", QUARTZ_RATING_KEYS["feature_diversity"]),
        rating_item("practicality", "기능의 실용성", QUARTZ_RATING_KEYS["practicality"]),
        rating_item("price_value", "가격 대비 가치", QUARTZ_RATING_KEYS["price_value"]),
        rating_item("ease_of_use", "사용 편의성", QUARTZ_RATING_KEYS["ease_of_use"]),
        EvaluationItem(
            key="usage_limit",
            name="사용량 제한",
            value=usage_value,
            display=usage_display,
            unit=plan.unit if plan is not None else "",
            score=usage_score,
            basis=usage_basis,
            source_ids=_source_ids(entry, "selected_plan"),
        ),
        EvaluationItem(
            key="platform_support",
            name="플랫폼 지원",
            value=float(len(product.platforms)),
            display=f"{len(product.platforms)}개 플랫폼",
            unit="개",
            score=round(_clamp(len(product.platforms) / 5 * 10), 2),
            basis="공식 문서에 지원된다고 명시된 플랫폼 수(5개 이상=10).",
            source_ids=_source_ids(entry, "platforms"),
        ),
        EvaluationItem(
            key="integration",
            name="외부 서비스 연동",
            value=float(len(product.integrations)),
            display=f"{len(product.integrations)}개 연동",
            unit="개",
            score=round(_clamp(len(product.integrations) / 10 * 10), 2),
            basis="공식 문서에 명시된 외부 연동 수(10개 이상=10).",
            source_ids=_source_ids(entry, "integrations"),
        ),
        rating_item("scalability", "확장성", QUARTZ_RATING_KEYS["scalability"]),
        rating_item("stability_transparency", "안정성 및 신뢰성", QUARTZ_RATING_KEYS["stability_transparency"]),
        rating_item("fit_for_purpose", "실제 사용 목적 적합성", QUARTZ_RATING_KEYS["fit_for_purpose"]),
    ]

    dimensions, result, warnings = _dimensions("QDVI", items, QUARTZ_MAPPING)
    analysis.evaluation_items = items
    analysis.metrics = metrics
    analysis.dimensions = dimensions
    analysis.result = result
    analysis.mapping = QUARTZ_MAPPING
    analysis.interpretation = _interpretation("QDVI", result, entry)
    analysis.data_sources = _collect_sources(entry, items)
    analysis.inputs = _quartz_inputs(product, plan, monthly, annual, tasks, minutes, hourly_labor)
    analysis.assumptions = _quartz_assumptions(entry, product, plan, tasks, minutes, hourly_labor)
    analysis.steps = _quartz_steps(metric, product, plan, tasks, minutes, hourly_labor)
    analysis.limitations = list(entry.limitations) + [
        "기능과 사용량 조건은 요금제 개편에 따라 달라질 수 있습니다.",
        "가격과 기능은 변경될 수 있으므로 도입 전 공식 페이지에서 최신 정보를 확인해야 합니다.",
    ]
    analysis.scenario_analysis = _quartz_scenarios(entry, product, monthly, tasks, minutes, hourly_labor)
    analysis.comparison = _quartz_comparison(entry, product, monthly, annual, feature_count)
    analysis.warnings = warnings
    return analysis


def _feature_sources(features: Iterable[Any]) -> list[str]:
    found: list[str] = []
    for feature in features:
        for source_id in getattr(feature, "source_ids", []):
            if source_id not in found:
                found.append(source_id)
    return found


def _quartz_inputs(
    product: QuartzProductSpec,
    plan: Any,
    monthly: float | None,
    annual: float | None,
    tasks: float | None,
    minutes: float | None,
    hourly_labor: float | None,
) -> dict[str, Any]:
    rows: dict[str, Any] = {
        "제품": product.name,
        "벤더": product.vendor,
        "선택 요금제": product.selected_plan,
        "월 구독 비용": monthly,
        "연 구독 비용": annual,
        "월 작업 수": tasks,
        "작업당 절감 분": minutes,
        "시간당 인건비": hourly_labor,
    }
    if plan is not None:
        rows["포함 사용량"] = plan.included_units
        rows["사용량 단위"] = plan.unit
    return rows


def _quartz_assumptions(
    entry: CatalogEntryModel,
    product: QuartzProductSpec,
    plan: Any,
    tasks: float | None,
    minutes: float | None,
    hourly_labor: float | None,
) -> list[Assumption]:
    assumptions: list[Assumption] = []
    rows = [
        ("월 작업 수", tasks, "건", "tasks_per_month"),
        ("작업당 절감 시간", minutes, "분", "minutes_saved_per_task"),
        ("시간당 인건비", hourly_labor, "원", "hourly_labor_cost_krw"),
    ]
    for name, value, unit, key in rows:
        sourced = _source_ids(entry, key)
        assumptions.append(
            Assumption(
                name=name,
                value="미입력" if value is None else f"{value:,.2f}".rstrip("0").rstrip("."),
                unit=unit,
                basis="공식 자료" if sourced else "편집상 가정",
                source_ids=sourced,
            )
        )
    if plan is not None:
        sourced = _source_ids(entry, "selected_plan")
        assumptions.append(
            Assumption(
                name="선택 요금제",
                value=plan.name,
                unit="",
                basis="공식 자료" if sourced else "편집상 가정",
                source_ids=sourced,
            )
        )
    seen = {item.name for item in assumptions}
    for item in _catalog_assumptions(entry):
        if item.name not in seen:
            assumptions.append(item)
            seen.add(item.name)
    return assumptions


def _quartz_steps(
    metric: Any,
    product: QuartzProductSpec,
    plan: Any,
    tasks: float | None,
    minutes: float | None,
    hourly_labor: float | None,
) -> list[str]:
    steps: list[str] = []
    monthly = metric("monthly_subscription_cost")
    annual = metric("annual_subscription_cost")
    per_task = metric("cost_per_task")
    per_feature = metric("cost_per_feature")
    saved = metric("time_saved_hours")
    value = metric("time_value")
    net = metric("net_time_value")
    steps.append(f"월 구독 비용 = {monthly.display} ({product.selected_plan} 요금제).")
    steps.append(f"연 구독 비용 = {annual.display}.")
    if per_task.value is not None:
        steps.append(f"작업당 비용 = {monthly.display} / 월 {tasks:,.0f}건 = {per_task.display}.")
    if per_feature.value is not None:
        steps.append(f"기능별 비용 = {monthly.display} / {metric('feature_count').display} = {per_feature.display}.")
    if saved.value is not None:
        steps.append(
            f"월 절감 시간 = 월 {tasks:,.0f}건 × {minutes:,.1f}분 / 60 = {saved.display}."
        )
    if value.value is not None:
        steps.append(f"절감 시간 가치 = {saved.display} × 시간당 {_krw(hourly_labor)} = {value.display}.")
    if net.value is not None:
        steps.append(f"시간 절감 순가치 = {value.display} - {monthly.display} = {net.display}.")
    steps.append("각 항목을 0~10점으로 정규화한 뒤 QDVI 가중치로 종합한다.")
    return steps


def _quartz_scenarios(
    entry: CatalogEntryModel,
    product: QuartzProductSpec,
    monthly: float | None,
    tasks: float | None,
    minutes: float | None,
    hourly_labor: float | None,
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for name, multiplier in (("보수적", 0.5), ("기준", 1.0), ("적극적", 1.5)):
        if tasks is None or minutes is None or hourly_labor is None or monthly is None:
            scenarios.append(
                {
                    "scenario": name,
                    "assumptions": f"월 작업 수의 {multiplier:.1f}배",
                    "result": "입력값이 부족해 계산할 수 없음",
                }
            )
            continue
        scenario_tasks = tasks * multiplier
        saved_hours = scenario_tasks * minutes / 60
        time_value = saved_hours * hourly_labor
        net_value = time_value - monthly
        cost_per_task = monthly / scenario_tasks if scenario_tasks else None
        scenarios.append(
            {
                "scenario": name,
                "assumptions": f"월 작업 수 {scenario_tasks:,.0f}건, 월 구독 비용 {_krw(monthly)} 유지",
                "cost_per_task": None if cost_per_task is None else round(cost_per_task, 2),
                "time_saved_hours": round(saved_hours, 2),
                "time_value": round(time_value, 2),
                "net_time_value": round(net_value, 2),
                "result": f"작업당 {_krw(cost_per_task)}, 시간 절감 순가치 {_krw(net_value)}",
            }
        )
    return scenarios


def _quartz_comparison(
    entry: CatalogEntryModel,
    product: QuartzProductSpec,
    monthly: float | None,
    annual: float | None,
    feature_count: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "name": product.name,
            "monthly_krw": monthly,
            "annual_krw": annual,
            "feature_count": feature_count,
            "is_primary": True,
        }
    ]
    for competitor in entry.competitors:
        rows.append(
            {
                "name": competitor.name,
                "monthly_krw": competitor.monthly_krw,
                "annual_krw": competitor.annual_krw,
                "feature_count": competitor.feature_count,
                "notes": competitor.notes,
                "is_primary": False,
            }
        )
    for row in rows:
        row["monthly_diff_krw"] = (
            None
            if monthly is None or row.get("monthly_krw") is None
            else round(monthly - row["monthly_krw"], 2)
        )
        row["feature_diff"] = (
            None
            if row.get("feature_count") is None
            else feature_count - row["feature_count"]
        )
    return rows


# ------------------------------------------------------------------- dispatcher
def build_analysis(entry: CatalogEntryModel, blog: str) -> OriginalAnalysis:
    if blog == "crystal":
        return build_crystal_analysis(entry)
    if blog == "quartz":
        return build_quartz_analysis(entry)
    raise ValueError(f"unknown editorial blog: {blog!r}")
