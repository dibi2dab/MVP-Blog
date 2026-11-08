from __future__ import annotations

from typing import Any, Iterable

from src.editorial.models import (
    AnalysisDimension,
    Assumption,
    EvaluationItem,
    MetricResult,
    OriginalAnalysis,
    ResearchSource,
)


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "/").replace("\n", " ").strip()


def _cite(source_ids: Iterable[str]) -> str:
    ids = [source_id for source_id in source_ids if source_id]
    if not ids:
        return ""
    return " " + "".join(f"[{source_id}]" for source_id in ids)


def _score(value: float | None) -> str:
    return "평가 불가" if value is None else f"{value:.1f} / 10"


def render_dimension_table(analysis: OriginalAnalysis) -> str:
    if not analysis.dimensions:
        return ""
    lines = [
        f"### {analysis.framework} 구성 차원",
        "",
        "| 차원 | 점수 | 가중치 | 구성 항목 |",
        "| --- | ---: | ---: | --- |",
    ]
    for dimension in analysis.dimensions:
        lines.append(
            "| {name} | {score} | {weight:.0%} | {rationale} |".format(
                name=_cell(dimension.name),
                score="평가 불가" if dimension.score is None else f"{dimension.score:.2f}",
                weight=dimension.weight,
                rationale=_cell(dimension.rationale),
            )
        )
    lines.append("")
    lines.append(
        f"종합 {analysis.framework} 점수는 "
        f"{'계산 불가' if analysis.result is None else f'{analysis.result:.2f} / 10'}입니다. "
        "이 점수는 10개 평가 항목을 묶어 계산한 보조 지표이며, 아래 항목별 근거를 함께 읽어야 합니다."
    )
    return "\n".join(lines)


def render_evaluation_table(analysis: OriginalAnalysis) -> str:
    if not analysis.evaluation_items:
        return ""
    lines = [
        "## 10가지 평가 항목",
        "",
        "아래 표는 이 글의 중심 분석입니다. 각 항목은 공개 자료, 계산 결과, 또는 명시된 편집상 가정을 근거로 평가했습니다.",
        "",
        "| 평가 항목 | 측정값 | 점수 | 판단 근거 |",
        "| --- | --- | ---: | --- |",
    ]
    for item in analysis.evaluation_items:
        lines.append(
            "| {name} | {value} | {score} | {basis}{cite} |".format(
                name=_cell(item.name),
                value=_cell(item.display or item.value),
                score=_score(item.score),
                basis=_cell(item.basis),
                cite=_cite(item.source_ids),
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_metrics_table(analysis: OriginalAnalysis) -> str:
    if not analysis.metrics:
        return ""
    lines = [
        "## 핵심 수치와 계산식",
        "",
        "| 지표 | 값 | 계산식 |",
        "| --- | ---: | --- |",
    ]
    for metric in analysis.metrics:
        reason = ""
        if metric.value is None and metric.unavailable_reason:
            reason = f" ({metric.unavailable_reason})"
        lines.append(
            "| {name} | {value}{reason} | {formula}{cite} |".format(
                name=_cell(metric.name),
                value=_cell(metric.display),
                reason=_cell(reason),
                formula=_cell(metric.formula),
                cite=_cite(metric.source_ids),
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_steps(analysis: OriginalAnalysis) -> str:
    if not analysis.steps:
        return ""
    lines = ["## 계산 과정", ""]
    for index, step in enumerate(analysis.steps, start=1):
        lines.append(f"{index}. {step}")
    lines.append("")
    return "\n".join(lines)


_SCENARIO_LABELS = {
    "monthly_revenue": "월 매출",
    "monthly_cost": "월 비용",
    "monthly_net_profit": "월 순이익",
    "hourly_net_profit": "시간당 순수익",
    "roi_percent": "ROI",
    "cost_per_task": "작업당 비용",
    "time_saved_hours": "월 절감 시간",
    "time_value": "절감 시간 가치",
    "net_time_value": "시간 절감 순가치",
}


def _scenario_cell(key: str, value: Any) -> str:
    """Format a scenario number with the same unit used in the summary."""

    if value is None:
        return "계산 불가"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _cell(value)
    if key == "roi_percent":
        return f"{number:,.1f}%"
    if key == "time_saved_hours":
        return f"{number:,.1f}시간"
    if key in {
        "monthly_revenue",
        "monthly_cost",
        "monthly_net_profit",
        "hourly_net_profit",
        "cost_per_task",
        "time_value",
        "net_time_value",
    }:
        return f"{number:,.0f}원"
    return _cell(value)


def render_scenarios(analysis: OriginalAnalysis) -> str:
    if not analysis.scenario_analysis:
        return ""
    numeric_keys: list[str] = []
    for row in analysis.scenario_analysis:
        for key, value in row.items():
            if key in _SCENARIO_LABELS and isinstance(value, (int, float)) and key not in numeric_keys:
                numeric_keys.append(key)
    header = ["시나리오", "가정", *(_SCENARIO_LABELS[key] for key in numeric_keys), "결과"]
    lines = [
        "## 시나리오 분석",
        "",
        "입력값이 바뀌면 결과가 어떻게 달라지는지 확인하기 위한 계산입니다. 아래 수치는 예측이 아니라 조건별 계산 결과입니다.",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in analysis.scenario_analysis:
        cells = [_cell(row.get("scenario")), _cell(row.get("assumptions"))]
        for key in numeric_keys:
            cells.append(_scenario_cell(key, row.get(key)))
        cells.append(_cell(row.get("result")))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def render_assumptions(analysis: OriginalAnalysis) -> str:
    if not analysis.assumptions:
        return ""
    lines = [
        "## 공식 자료와 편집상 가정",
        "",
        "이 글은 공식 자료에서 확인한 값과, 자료가 없는 부분에 대해 편집상 설정한 가정을 구분합니다. 가정은 실제 결과와 다를 수 있습니다.",
        "",
        "| 구분 | 항목 | 값 | 근거 |",
        "| --- | --- | ---: | --- |",
    ]
    for assumption in analysis.assumptions:
        lines.append(
            "| {kind} | {name} | {value}{unit} | {basis}{cite} |".format(
                kind="편집상 가정" if assumption.is_editorial else "공식 자료",
                name=_cell(assumption.name),
                value=_cell(assumption.value),
                unit=_cell(f" {assumption.unit}" if assumption.unit else ""),
                basis=_cell(assumption.basis),
                cite=_cite(assumption.source_ids),
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_comparison(analysis: OriginalAnalysis) -> str:
    if not analysis.comparison:
        return ""
    lines = [
        "## 가격과 기능 비교",
        "",
        "| 제품 | 월 비용 | 연 비용 | 기능 수 | 월 비용 차이 | 기능 수 차이 | 비고 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in analysis.comparison:
        lines.append(
            "| {name} | {monthly} | {annual} | {features} | {monthly_diff} | {feature_diff} | {notes} |".format(
                name=_cell(row.get("name")),
                monthly=_money(row.get("monthly_krw")),
                annual=_money(row.get("annual_krw")),
                features=_count(row.get("feature_count")),
                monthly_diff=_money(row.get("monthly_diff_krw"), signed=True),
                feature_diff=_count(row.get("feature_diff"), signed=True),
                notes=_cell(row.get("notes")),
            )
        )
    lines.append("")
    lines.append("비교표의 차이는 이 글에서 선택한 요금제를 기준으로 계산했습니다. 경쟁 제품의 가격과 기능은 공식 페이지가 바뀌면 달라질 수 있습니다.")
    lines.append("")
    return "\n".join(lines)


def _money(value: Any, *, signed: bool = False) -> str:
    if value is None:
        return "확인 불가"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "확인 불가"
    if signed:
        return f"{number:+,.0f}원"
    return f"{number:,.0f}원"


def _count(value: Any, *, signed: bool = False) -> str:
    if value is None:
        return "확인 불가"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "확인 불가"
    if signed:
        return f"{number:+d}개"
    return f"{number}개"


def render_sources(sources: Iterable[ResearchSource]) -> str:
    sources = list(sources)
    if not sources:
        return ""
    lines = ["## 출처", ""]
    for source in sources:
        date = source.published_at or source.retrieved_at[:10] or "날짜 미상"
        publisher = source.publisher or "출처"
        lines.append(
            f"- [{source.source_id}] [{source.title}]({source.url}) — {publisher} ({date})"
        )
    lines.append("")
    return "\n".join(lines)


def build_analysis_markdown(
    analysis: OriginalAnalysis,
    *,
    include_dimensions: bool = True,
) -> str:
    """Render the 10-item evaluation and the secondary CPPI/QDVI index."""

    blocks = [
        render_evaluation_table(analysis),
        render_metrics_table(analysis),
        render_steps(analysis),
        render_scenarios(analysis),
        render_assumptions(analysis),
        render_comparison(analysis),
        render_dimension_table(analysis) if include_dimensions else "",
    ]
    return "\n".join(block for block in blocks if block.strip())


def render_limitations(analysis: OriginalAnalysis) -> str:
    if not analysis.limitations:
        return ""
    lines = ["## 한계와 주의사항", ""]
    for item in analysis.limitations:
        lines.append(f"- {item}")
    lines.append("")
    lines.append(
        "이 글은 공개 자료와 계산 결과를 바탕으로 한 정보 제공 목적의 분석입니다. "
        "투자, 수익, 성과를 보장하지 않으며 최종 결정은 독자의 상황과 최신 공식 자료를 기준으로 해야 합니다."
    )
    lines.append("")
    return "\n".join(lines)


def format_dimension(analysis: OriginalAnalysis, name: str) -> AnalysisDimension | None:
    for dimension in analysis.dimensions:
        if dimension.name == name:
            return dimension
    return None


def metric(analysis: OriginalAnalysis, key: str) -> MetricResult | None:
    for item in analysis.metrics:
        if item.key == key:
            return item
    return None


def evaluation(analysis: OriginalAnalysis, key: str) -> EvaluationItem | None:
    for item in analysis.evaluation_items:
        if item.key == key:
            return item
    return None


def assumption(analysis: OriginalAnalysis, name: str) -> Assumption | None:
    for item in analysis.assumptions:
        if item.name == name:
            return item
    return None
