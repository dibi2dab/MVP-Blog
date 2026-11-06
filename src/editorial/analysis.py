from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.editorial.models import AnalysisDimension, OriginalAnalysis
from src.editorial.profiles import BlogProfile

FRAMEWORK_SPECS: dict[str, dict[str, Any]] = {
    "CPPI": {
        "name": "Crystal Practical Profitability Index (CPPI)",
        "dimensions": [
            (
                "Revenue Potential",
                0.25,
                ("revenue potential", "수익 잠재력", "수익성", "매출 잠재력"),
            ),
            (
                "Cost Efficiency",
                0.20,
                ("cost efficiency", "비용 효율", "비용 효율성", "원가 효율"),
            ),
            (
                "Time Efficiency",
                0.20,
                ("time efficiency", "시간 효율", "시간 효율성", "시간 대비"),
            ),
            (
                "Execution Feasibility",
                0.20,
                ("execution feasibility", "실행 가능성", "실행력", "실현 가능성"),
            ),
            (
                "Risk Management",
                0.15,
                ("risk management", "리스크 관리", "위험 관리", "위험성"),
            ),
        ],
    },
    "QDVI": {
        "name": "Quartz Digital Value Index (QDVI)",
        "dimensions": [
            (
                "Functional Capability",
                0.25,
                ("functional capability", "기능", "기능성", "기능 역량"),
            ),
            (
                "Ease of Use",
                0.20,
                ("ease of use", "사용성", "사용 편의성", "편의성"),
            ),
            (
                "Price-to-Value",
                0.20,
                ("price-to-value", "price to value", "가격 대비 가치", "가성비"),
            ),
            (
                "Integration & Scalability",
                0.15,
                (
                    "integration & scalability",
                    "integration and scalability",
                    "통합 및 확장성",
                    "통합·확장성",
                    "통합 확장성",
                    "확장성",
                ),
            ),
            (
                "Reliability & Transparency",
                0.20,
                (
                    "reliability & transparency",
                    "reliability and transparency",
                    "신뢰성 및 투명성",
                    "신뢰성·투명성",
                    "신뢰성",
                    "투명성",
                ),
            ),
        ],
    },
}


@dataclass
class AnalysisValidation:
    analysis: OriginalAnalysis
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _norm_name(value: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", (value or "").lower())


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dimension_lookup(raw_dimensions: Any) -> dict[str, dict[str, Any]]:
    """Accept either a list of dimension objects or a mapping."""

    lookup: dict[str, dict[str, Any]] = {}
    if isinstance(raw_dimensions, dict):
        for name, value in raw_dimensions.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("name", name)
            else:
                item = {"name": name, "score": value}
            lookup[_norm_name(str(name))] = item
        return lookup
    if isinstance(raw_dimensions, list):
        for item in raw_dimensions:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("dimension") or "")
            if name:
                lookup[_norm_name(name)] = item
    return lookup


def normalize_analysis(raw: dict[str, Any], profile: BlogProfile) -> AnalysisValidation:
    """Validate and recompute a CPPI/QDVI analysis.

    The model's own result is never trusted. We recompute it from the disclosed
    dimension scores and weights. If the disclosed result differs materially, the
    analysis is rejected as an incorrect calculation.
    """

    errors: list[str] = []
    warnings: list[str] = []
    framework = str(raw.get("framework") or profile.framework).strip().upper()
    expected = profile.framework.upper()
    if framework != expected:
        errors.append(f"분석 프레임워크 불일치: 기대={expected}, 실제={framework}")

    spec = FRAMEWORK_SPECS.get(expected)
    if spec is None:
        errors.append(f"지원하지 않는 프레임워크: {expected}")
        return AnalysisValidation(
            analysis=OriginalAnalysis(framework=expected),
            errors=errors,
            warnings=warnings,
        )

    lookup = _dimension_lookup(raw.get("dimensions"))
    dimensions: list[AnalysisDimension] = []
    for name, weight, aliases in spec["dimensions"]:
        item = None
        for alias in (name, *aliases):
            item = lookup.get(_norm_name(alias))
            if item is not None:
                break

        if item is None:
            dimensions.append(
                AnalysisDimension(
                    name=name,
                    score=None,
                    weight=weight,
                    rationale="제공된 자료로 평가할 수 없음",
                    unavailable=True,
                )
            )
            warnings.append(f"{name} 차원이 누락되어 가중치를 정규화합니다.")
            continue

        score = _as_float(item.get("score"))
        unavailable = bool(item.get("unavailable")) or score is None
        rationale = str(item.get("rationale") or item.get("reason") or "").strip()
        item_weight = _as_float(item.get("weight"))
        effective_weight = item_weight if item_weight is not None else weight
        if effective_weight <= 0:
            effective_weight = weight

        if not unavailable and (score is None or score < 0 or score > 10):
            errors.append(f"{name} 점수가 0~10 범위를 벗어났습니다: {score}")
            unavailable = True

        dimensions.append(
            AnalysisDimension(
                name=name,
                score=None if unavailable else round(float(score), 2),
                weight=effective_weight,
                rationale=rationale,
                unavailable=unavailable,
            )
        )

    available = [d for d in dimensions if not d.unavailable and d.score is not None]
    if len(available) < 3:
        errors.append(f"평가 가능한 차원이 {len(available)}개뿐입니다. 최소 3개가 필요합니다.")

    recomputed: float | None = None
    weight_sum = sum(d.weight for d in available)
    if available and weight_sum > 0:
        recomputed = sum(float(d.score) * d.weight for d in available) / weight_sum
        recomputed = round(recomputed, 2)

    disclosed = _as_float(raw.get("result"))
    if recomputed is not None and disclosed is not None:
        if abs(disclosed - recomputed) > 0.1:
            errors.append(
                "계산 결과 불일치: 공개된 결과 "
                f"{disclosed} vs 재계산 {recomputed}. 공식과 입력값을 확인해야 합니다."
            )
    elif recomputed is not None and disclosed is None:
        warnings.append("모델이 최종 점수를 공개하지 않아 재계산값을 사용합니다.")

    formula = str(raw.get("formula") or "").strip()
    if not formula:
        errors.append("계산 공식이 비어 있습니다.")
    elif expected not in formula.upper():
        warnings.append(f"공식 문자열에 {expected} 표기가 없습니다.")

    purpose = str(raw.get("purpose") or "").strip()
    if not purpose:
        errors.append("분석 목적이 비어 있습니다.")

    inputs = raw.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        errors.append("분석 입력값(inputs)이 비어 있습니다.")
        inputs = inputs if isinstance(inputs, dict) else {}

    data_sources = [str(item) for item in (raw.get("data_sources") or []) if str(item).strip()]
    if not data_sources:
        errors.append("분석 데이터 출처(data_sources)가 비어 있습니다.")

    steps = [str(item) for item in (raw.get("steps") or []) if str(item).strip()]
    if not steps:
        errors.append("계산 과정(steps)이 비어 있습니다.")

    limitations = [str(item) for item in (raw.get("limitations") or []) if str(item).strip()]
    if not limitations:
        errors.append("분석 한계(limitations)가 비어 있습니다.")

    interpretation = str(raw.get("interpretation") or "").strip()
    if not interpretation:
        errors.append("결과 해석(interpretation)이 비어 있습니다.")

    scenario_analysis = raw.get("scenario_analysis") or []
    if not isinstance(scenario_analysis, list):
        scenario_analysis = []
    scenario_analysis = [item for item in scenario_analysis if isinstance(item, dict)]

    analysis = OriginalAnalysis(
        framework=expected,
        purpose=purpose,
        formula=formula,
        dimensions=dimensions,
        inputs=inputs,
        data_sources=data_sources,
        steps=steps,
        result=recomputed if recomputed is not None else disclosed,
        interpretation=interpretation,
        limitations=limitations,
        scenario_analysis=scenario_analysis,
    )
    return AnalysisValidation(analysis=analysis, errors=errors, warnings=warnings)


def _escape_table(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def build_analysis_markdown(analysis: OriginalAnalysis, profile: BlogProfile) -> str:
    """Render the canonical, reproducible analysis section.

    The article body is generated by the model, but this section is generated
    deterministically from the validated analysis object. That guarantees the
    published numbers and the disclosed calculation cannot drift apart.
    """

    title = (
        "Crystal Practical Profitability Index (CPPI)"
        if profile.framework == "CPPI"
        else "Quartz Digital Value Index (QDVI)"
    )
    lines: list[str] = [
        f"## 원문 분석: {title}",
        "",
        "> 이 점수는 편집상 의사결정 프레임워크입니다. 실제 수익, 성과, 또는 제품의 절대적 우열을 보장하지 않습니다.",
        "",
        f"**목적:** {analysis.purpose or '해당 주제의 의사결정을 돕기 위한 분석'}",
        "",
        f"**공식:** {analysis.formula or '(공식 미기재)'}",
        "",
        "| 평가 차원 | 점수 (0~10) | 가중치 | 근거 |",
        "| --- | ---: | ---: | --- |",
    ]
    for dimension in analysis.dimensions:
        score = "평가 불가" if dimension.unavailable or dimension.score is None else f"{dimension.score:.1f}"
        lines.append(
            f"| {_escape_table(dimension.name)} | {score} | {dimension.weight:.2f} | "
            f"{_escape_table(dimension.rationale) or '-'} |"
        )
    lines.append("")

    if analysis.inputs:
        lines.extend(
            [
                "### 입력 변수와 데이터 출처",
                "",
                "| 입력 변수 | 값 |",
                "| --- | --- |",
            ]
        )
        for key, value in analysis.inputs.items():
            lines.append(f"| {_escape_table(key)} | {_escape_table(value)} |")
        lines.append("")

    if analysis.steps:
        lines.extend(["### 계산 과정", ""])
        for index, step in enumerate(analysis.steps, start=1):
            lines.append(f"{index}. {step}")
        lines.append("")

    if analysis.result is not None:
        lines.extend(
            [
                "### 계산 결과",
                "",
                f"**{profile.framework} = {analysis.result:.2f} / 10**",
                "",
            ]
        )

    if analysis.interpretation:
        lines.extend(["### 결과 해석", "", analysis.interpretation, ""])

    if analysis.scenario_analysis:
        lines.extend(
            [
                "### 시나리오 분석",
                "",
                "| 시나리오 | 가정 | 결과 |",
                "| --- | --- | --- |",
            ]
        )
        for scenario in analysis.scenario_analysis:
            lines.append(
                f"| {_escape_table(scenario.get('scenario'))} | "
                f"{_escape_table(scenario.get('assumptions'))} | "
                f"{_escape_table(scenario.get('result'))} |"
            )
        lines.append("")

    if analysis.limitations:
        lines.extend(["### 분석의 한계", ""])
        for limitation in analysis.limitations:
            lines.append(f"- {limitation}")
        lines.append("")

    if analysis.data_sources:
        lines.extend(
            [
                "### 분석에 사용한 출처",
                "",
                ", ".join(f"[{source_id}]" for source_id in analysis.data_sources),
                "",
            ]
        )

    return "\n".join(lines).strip()


def build_sources_markdown(sources: list[Any], profile: BlogProfile) -> str:
    lines = ["## 참고 자료", ""]
    for source in sources:
        date = source.published_at or "날짜 미상"
        publisher = source.publisher or "출처"
        lines.append(
            f"- [{source.source_id}] [{source.title}]({source.url}) — {publisher} ({date})"
        )
    lines.append("")
    if profile.framework == "CPPI":
        lines.extend(
            [
                "---",
                "",
                "*이 글은 공개 자료를 바탕으로 작성된 분석이며, 특정 상품이나 사업을 권유하지 않습니다. "
                "CPPI는 편집상 의사결정 프레임워크로 실제 수익을 보장하지 않습니다. "
                "수익·비용·시간은 독자의 상황에 따라 달라질 수 있습니다.*",
            ]
        )
    else:
        lines.extend(
            [
                "---",
                "",
                "*이 글은 공개 자료와 공식 문서를 바탕으로 작성된 평가이며, 특정 제품의 구매를 권유하지 않습니다. "
                "QDVI는 편집상 평가 프레임워크로 독립적인 과학적 측정값이 아닙니다. "
                "실제 사용 경험이 아닌 문서 기반 평가인 경우 본문에 명시했습니다.*",
            ]
        )
    return "\n".join(lines).strip()
