from __future__ import annotations

from typing import Any, Iterable

from src.editorial.analysis import (
    build_analysis_markdown,
    evaluation,
    metric,
    render_limitations,
    render_sources,
)
from src.editorial.catalog import CatalogEntryModel
from src.editorial.metrics import build_analysis
from src.editorial.models import (
    EditorialArticle,
    QualityReport,
    ResearchSource,
    TopicCandidate,
)
from src.editorial.profiles import BlogProfile
from src.editorial.quality import assess_quality
from src.editorial.text import safe_slug

_DEFAULT_CHECKLIST = {
    "crystal": [
        "초기 투자 비용과 월 고정비를 먼저 적어 두었는가",
        "매출이 0원인 달에도 버틸 수 있는 기간을 계산했는가",
        "수익이 발생하는 경로와 수수료 구조를 공식 자료로 확인했는가",
        "월 투입 시간을 실제로 확보할 수 있는가",
        "중단하거나 방향을 바꿀 기준을 정해 두었는가",
    ],
    "quartz": [
        "월 구독 비용과 연 구독 비용을 모두 확인했는가",
        "실제 업무량에서 작업당 비용이 합리적인가",
        "팀이 실제로 사용할 기능이 포함된 요금제인가",
        "필요한 플랫폼과 외부 연동을 지원하는가",
        "도입 후 검토·승인 절차와 중단 기준을 정했는가",
    ],
}


def _display(analysis: Any, key: str) -> str:
    item = metric(analysis, key)
    return item.display if item is not None and item.display else "계산 불가"


def _cite_first(sources: Iterable[ResearchSource]) -> str:
    for source in sources:
        source_id = getattr(source, "source_id", "") or getattr(source, "id", "")
        if source_id:
            return f" [{source_id}]"
    return ""


def _summary_table(rows: list[tuple[str, str, str]]) -> str:
    lines = ["## 한눈에 보는 결론", "", "| 항목 | 계산 결과 | 의미 |", "| --- | ---: | --- |"]
    for name, value, meaning in rows:
        lines.append(f"| {name} | {value} | {meaning} |")
    lines.append("")
    return "\n".join(lines)


def _faq(rows: list[tuple[str, str]]) -> str:
    lines = ["## 자주 묻는 질문", ""]
    for question, answer in rows:
        lines.append(f"### {question}")
        lines.append("")
        lines.append(answer)
        lines.append("")
    return "\n".join(lines)


def _list_block(title: str, items: Iterable[str]) -> str:
    items = [item for item in items if item]
    if not items:
        return ""
    lines = [f"## {title}", ""]
    for item in items:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _rating_paragraph(analysis: Any, key: str, heading: str) -> str:
    item = evaluation(analysis, key)
    if item is None:
        return ""
    basis = item.basis or "공개 자료와 편집상 가정을 기준으로 평가했습니다."
    display = item.display or "평가 근거 없음"
    return "\n".join(
        [
            f"## {heading}",
            "",
            f"{item.name}은 {display}로 평가했습니다. {basis}",
            "",
        ]
    )


def _crystal_body(entry: CatalogEntryModel, analysis: Any, sources: list[ResearchSource]) -> str:
    citation = _cite_first(sources)
    model = entry.model
    assert model is not None
    revenue = _display(analysis, "monthly_revenue")
    cost = _display(analysis, "monthly_operating_cost")
    net = _display(analysis, "monthly_net_profit")
    hourly = _display(analysis, "hourly_net_profit")
    roi = _display(analysis, "roi")
    break_even = _display(analysis, "break_even_months")
    cppi = "계산 불가" if analysis.result is None else f"{analysis.result:.2f} / 10"

    blocks: list[str] = []
    blocks.append(
        "\n".join(
            [
                f"## {entry.name}, 실제로 얼마가 남을까?",
                "",
                f"{entry.summary}{citation}",
                "",
                (
                    f"이 글은 {entry.name}의 수익 구조를 초기 투자, 월 운영 비용, 예상 매출, "
                    "예상 순이익, 손익분기, 시간당 순수익, ROI로 나누어 계산합니다. "
                    "공식 자료로 확인한 값과 자료가 없어 편집상 가정한 값을 구분해 표시했으며, "
                    "특정 수익을 보장하지 않습니다."
                ),
                "",
            ]
        )
    )
    blocks.append(
        _summary_table(
            [
                ("월 예상 매출", revenue, "입력한 방문자·판매량과 단가 기준"),
                ("월 운영 비용", cost, "고정비와 단위당 변동비 합계"),
                ("월 예상 순이익", net, "매출에서 운영 비용을 뺀 값"),
                ("손익분기 도달 기간", break_even, "초기 투자 회수에 걸리는 기간"),
                ("시간당 순수익", hourly, "월 순이익을 투입 시간으로 나눈 값"),
                ("ROI", roi, "월 순이익을 초기 투자로 나눈 비율"),
                (f"{analysis.framework} (보조 지표)", cppi, "10가지 항목을 묶은 종합 점수"),
            ]
        )
    )
    blocks.append(build_analysis_markdown(analysis))

    narrative = ["## 수익 구조 해석", ""]
    revenue_item = metric(analysis, "monthly_revenue")
    net_item = metric(analysis, "monthly_net_profit")
    if revenue_item is not None and revenue_item.value is not None:
        narrative.append(
            f"현재 입력값 기준 월 예상 매출은 {revenue}입니다. 계산식은 "
            f"'{revenue_item.formula}'이며, 입력값이 바뀌면 결과도 함께 바뀝니다."
        )
    else:
        narrative.append(
            "월 예상 매출을 계산할 입력값이 부족합니다. 이 경우 임의의 숫자를 넣지 않고 "
            "'계산 불가'로 표시했습니다."
        )
    if net_item is not None and net_item.value is not None:
        if net_item.value > 0:
            narrative.append(
                f"월 예상 순이익은 {net}입니다. 매출 {revenue}에서 운영 비용 {cost}을 뺀 값이며, "
                "이 금액은 세금과 본인이 정하지 않은 비용을 포함하지 않습니다."
            )
        else:
            narrative.append(
                f"현재 입력값에서는 월 예상 순이익이 {net}으로 0원 이하입니다. "
                "매출을 늘리거나 고정비를 줄이기 전에는 수익성이 나기 어렵습니다."
            )
    if model.initial_investment_krw:
        narrative.append(
            f"초기 투자 비용은 {model.initial_investment_krw:,.0f}원으로 기록했습니다. "
            f"월 순이익이 유지된다는 조건에서 손익분기 도달 기간은 {break_even}입니다."
        )
    else:
        narrative.append(
            "초기 투자 비용이 0원으로 기록되어 ROI를 정의하지 않았습니다. "
            "실제로는 도구, 도메인, 콘텐츠 제작 시간 같은 비용이 발생할 수 있습니다."
        )
    blocks.append("\n".join(narrative) + "\n")

    blocks.append(_rating_paragraph(analysis, "revenue_variability", "수익 변동 위험"))
    blocks.append(_rating_paragraph(analysis, "operational_difficulty", "운영 난이도"))
    blocks.append(_rating_paragraph(analysis, "long_term_sustainability", "장기 지속 가능성"))

    checklist = entry.checklist or _DEFAULT_CHECKLIST["crystal"]
    blocks.append(_list_block("시작 전 체크리스트", checklist))
    blocks.append(
        _faq(
            [
                (
                    "초기 투자 비용은 얼마인가요?",
                    f"카탈로그에 기록된 초기 투자 비용은 {model.initial_investment_krw:,.0f}원입니다. "
                    "도구 구독, 도메인, 콘텐츠 제작 비용 등 실제 지출 항목은 독자의 상황에 따라 달라질 수 있습니다.",
                ),
                (
                    "월 예상 순이익은 얼마인가요?",
                    f"입력값 기준 월 예상 순이익은 {net}입니다. 이 값은 매출과 비용 가정이 그대로 유지된다는 조건의 계산 결과이며, 실제 수익을 보장하지 않습니다.",
                ),
                (
                    "손익분기는 언제인가요?",
                    f"초기 투자와 월 순이익을 기준으로 계산한 손익분기 도달 기간은 {break_even}입니다. 매출이 줄거나 비용이 늘면 기간은 길어집니다.",
                ),
                (
                    "이 수익은 보장되나요?",
                    "아니요. 이 글의 숫자는 공개 자료와 명시된 가정으로 계산한 추정치입니다. 실제 결과는 실행 방식, 시장 상황, 플랫폼 정책에 따라 달라집니다.",
                ),
            ]
        )
    )
    blocks.append(render_limitations(analysis))
    return "\n".join(block for block in blocks if block.strip())


def _quartz_body(entry: CatalogEntryModel, analysis: Any, sources: list[ResearchSource]) -> str:
    citation = _cite_first(sources)
    product = entry.product
    assert product is not None
    monthly = _display(analysis, "monthly_subscription_cost")
    annual = _display(analysis, "annual_subscription_cost")
    per_task = _display(analysis, "cost_per_task")
    per_feature = _display(analysis, "cost_per_feature")
    saved = _display(analysis, "time_saved_hours")
    time_value = _display(analysis, "time_value")
    qdvi = "계산 불가" if analysis.result is None else f"{analysis.result:.2f} / 10"

    blocks: list[str] = []
    blocks.append(
        "\n".join(
            [
                f"## {entry.name}, 어떤 팀에 맞는 도구일까?",
                "",
                f"{entry.summary}{citation}",
                "",
                (
                    f"이 글은 {product.name}({product.vendor or '제조사 미상'})의 "
                    f"{product.selected_plan or '선택 요금제'} 요금제를 기준으로 월 구독 비용, "
                    "연 구독 비용, 작업당 비용, 기능별 비용, 절감 시간의 가치를 계산합니다. "
                    "공식 문서와 가격표를 우선 사용했으며, 직접 사용해 본 후기가 아닙니다."
                ),
                "",
            ]
        )
    )
    blocks.append(
        _summary_table(
            [
                ("월 구독 비용", monthly, "선택한 요금제의 월 가격"),
                ("연 구독 비용", annual, "연 결제 가격 또는 월 가격의 12배"),
                ("작업당 비용", per_task, "월 구독 비용을 월 작업 수로 나눈 값"),
                ("기능별 비용", per_feature, "월 구독 비용을 사용 가능 기능 수로 나눈 값"),
                ("월 절감 시간", saved, "월 작업 수와 작업당 절감 시간 기준"),
                ("절감 시간의 가치", time_value, "절감 시간에 시간당 인건비를 적용한 값"),
                (f"{analysis.framework} (보조 지표)", qdvi, "10가지 항목을 묶은 종합 점수"),
            ]
        )
    )
    blocks.append(build_analysis_markdown(analysis))

    feature_lines: list[str] = []
    for feature in product.features:
        if not feature.available:
            continue
        cite = "".join(f"[{source_id}]" for source_id in feature.source_ids)
        note = f" — {feature.note}" if feature.note else ""
        feature_lines.append(f"{feature.name}{note} {cite}".strip())
    blocks.append(_list_block("공식 문서에서 확인한 주요 기능", feature_lines))

    platform_lines = []
    if product.platforms:
        platform_lines.append("지원 플랫폼: " + ", ".join(product.platforms))
    if product.integrations:
        platform_lines.append("외부 연동: " + ", ".join(product.integrations))
    if product.usage_limits:
        platform_lines.append("사용량 제한: " + product.usage_limits)
    if not platform_lines:
        platform_lines.append("플랫폼과 연동 정보가 카탈로그에 충분히 기록되지 않았습니다.")
    blocks.append(_list_block("플랫폼·연동·사용량", platform_lines))

    narrative = ["## 가격과 시간 절감 해석", ""]
    monthly_item = metric(analysis, "monthly_subscription_cost")
    if monthly_item is not None and monthly_item.value is not None:
        narrative.append(
            f"선택한 {product.selected_plan} 요금제의 월 구독 비용은 {monthly}, "
            f"연 구독 비용은 {annual}입니다."
        )
    else:
        narrative.append("선택한 요금제의 가격 근거가 없어 비용을 계산하지 않았습니다.")
    if metric(analysis, "cost_per_task") is not None and metric(analysis, "cost_per_task").value is not None:
        narrative.append(
            f"월 {product.tasks_per_month:,.0f}건의 작업을 가정하면 작업당 비용은 {per_task}입니다. "
            "작업 수가 줄면 작업당 비용은 높아지고, 늘면 낮아집니다."
        )
    if metric(analysis, "net_time_value") is not None and metric(analysis, "net_time_value").value is not None:
        net_value = metric(analysis, "net_time_value")
        if net_value.value > 0:
            narrative.append(
                f"절감 시간의 가치에서 구독 비용을 뺀 시간 절감 순가치는 {net_value.display}입니다. "
                "이 값은 시간당 인건비와 작업당 절감 시간을 편집상 가정한 결과입니다."
            )
        else:
            narrative.append(
                f"시간 절감 순가치는 {net_value.display}으로, 현재 가정에서는 구독 비용을 정당화하기 어렵습니다."
            )
    blocks.append("\n".join(narrative) + "\n")

    checklist = entry.checklist or _DEFAULT_CHECKLIST["quartz"]
    blocks.append(_list_block("도입 판단 체크리스트", checklist))
    blocks.append(
        _faq(
            [
                (
                    f"{product.name}의 월 구독 비용은 얼마인가요?",
                    f"이 글에서 선택한 {product.selected_plan} 요금제 기준 월 구독 비용은 {monthly}입니다. 가격은 공식 가격표가 바뀌면 달라질 수 있으므로 도입 전 다시 확인해야 합니다.",
                ),
                (
                    "작업당 비용은 어떻게 계산했나요?",
                    f"월 구독 비용을 월 작업 수로 나누어 {per_task}로 계산했습니다. 실제 작업 수가 다르면 결과도 달라집니다.",
                ),
                (
                    "기능이 많을수록 좋은 도구인가요?",
                    "아닙니다. 기능 수보다 실제 업무에 필요한 기능이 포함되어 있는지, 사용량 제한과 연동 범위가 맞는지가 더 중요합니다.",
                ),
                (
                    "이 평가는 직접 사용 후기인가요?",
                    "아닙니다. 공식 문서와 공개 가격표를 바탕으로 한 문서 기반 평가이며, 실제 사용 경험을 대신하지 않습니다.",
                ),
            ]
        )
    )
    blocks.append(render_limitations(analysis))
    return "\n".join(block for block in blocks if block.strip())


def build_article(
    entry: CatalogEntryModel,
    profile: BlogProfile,
    *,
    recent_records: Iterable[dict[str, Any]] = (),
) -> EditorialArticle:
    """Build a deterministic article from a catalog entry.

    No network and no model call happen here. The same catalog entry always
    produces the same calculations and the same structure.
    """

    analysis = build_analysis(entry, profile.key)
    sources = entry.source_records()
    if profile.key == "crystal":
        body = _crystal_body(entry, analysis, sources)
    elif profile.key == "quartz":
        body = _quartz_body(entry, analysis, sources)
    else:
        raise ValueError(f"unknown editorial blog: {profile.key!r}")

    sources_markdown = render_sources(sources)
    body_with_sources = body + ("\n\n" + sources_markdown if sources_markdown else "")

    tags = []
    for tag in [*entry.tags, analysis.framework]:
        if tag and tag not in tags:
            tags.append(tag)
    tags = tags[:10]

    topic = TopicCandidate(
        topic=entry.title,
        search_intent=entry.summary,
        angle=entry.why_now or "공개 자료와 계산 결과를 같은 기준으로 정리합니다.",
        why_now=entry.why_now,
        source_ids=[source.source_id for source in sources],
        primary_keyword=entry.primary_keyword,
        category=entry.category or profile.default_category,
        catalog_id=entry.id,
    )
    article = EditorialArticle(
        article_id=f"{profile.key}-{entry.id}",
        blog=profile.key,
        title=entry.title,
        seo_title=entry.title,
        slug=safe_slug(f"{profile.key}-{entry.id}-{entry.primary_keyword}", fallback=f"{profile.key}-{entry.id}"),
        meta_description=entry.meta_description,
        primary_keyword=entry.primary_keyword,
        secondary_keywords=list(entry.secondary_keywords),
        category=entry.category or profile.default_category,
        tags=tags,
        body_markdown=body,
        body_with_sources=body_with_sources,
        analysis=analysis,
        sources=sources,
        topic=topic,
        quality=QualityReport(),
        catalog_id=entry.id,
    )
    assess_quality(article, profile, recent_records=recent_records, entry=entry)
    return article


def article_markdown(article: EditorialArticle) -> str:
    return f"# {article.title}\n\n{article.body_with_sources or article.body_markdown}\n"
