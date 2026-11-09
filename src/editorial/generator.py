from __future__ import annotations

from typing import Any, Iterable

from src.editorial.analysis import (
    evaluation,
    metric,
    render_assumptions,
    render_comparison,
    render_scenarios,
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

_CRYSTAL_DRIVER = {
    "advertising": (
        "광고 수익은 방문자 수, RPM, 광고 채움률의 곱으로 결정됩니다. "
        "방문자가 늘어도 RPM이나 채움률이 떨어지면 매출은 같은 비율로 늘지 않습니다. "
        "고정비는 방문자 수와 무관하게 나가므로, 매출이 줄어드는 달에는 순이익 감소 폭이 더 커집니다."
    ),
    "digital_product": (
        "디지털 상품 매출은 판매가와 판매량의 곱이고, 여기서 플랫폼 수수료와 건당 결제 비용이 빠집니다. "
        "판매량이 절반으로 줄면 매출도 줄지만, 제작에 들어간 시간은 그대로 남습니다. "
        "그래서 순이익은 매출보다 더 큰 폭으로 흔들릴 수 있습니다."
    ),
    "subscription": (
        "구독 매출은 가입자 수와 월 회비의 곱입니다. 신규 가입이 멈추면 매출도 멈추고, "
        "해지가 늘면 기존 매출이 줄어듭니다. 결제 수수료와 환불은 실제 입금액을 추가로 줄입니다."
    ),
    "affiliate": (
        "제휴 수익은 클릭 수, 전환율, 건당 수수료의 곱으로 계산됩니다. "
        "전환율이 조금만 떨어져도 수익은 비례 이상으로 줄 수 있고, 제휴 조건이 바뀌면 같은 클릭에서도 수익이 달라집니다."
    ),
    "service": (
        "서비스 수익은 시간당 단가와 청구 가능 시간의 곱입니다. "
        "플랫폼 수수료와 연결 비용을 빼야 실제 시간당 수익이 보이고, 청구하지 못한 준비 시간은 수익에 반영되지 않습니다."
    ),
}

_CRYSTAL_HEADINGS = {
    "advertising": "광고 수익이 남는 구조",
    "digital_product": "상품 판매 수익과 수수료",
    "subscription": "구독 수익과 이탈 위험",
    "affiliate": "제휴 수수료가 남는 조건",
    "service": "서비스 단가와 작업 시간",
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


def _with_citation(text: str, citation: str) -> str:
    text = (text or "").strip()
    if not citation:
        return text
    if text.endswith("."):
        return text[:-1] + citation + "."
    return text + citation


def _table(headers: list[str], rows: list[tuple[str, ...]], *, align_right: set[int] | None = None) -> str:
    align_right = align_right or set()
    sep = ["---:" if index in align_right else "---" for index in range(len(headers))]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
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


def _basis(analysis: Any, key: str) -> str:
    item = evaluation(analysis, key)
    if item is None or not item.basis:
        return ""
    return item.basis.strip()


def _crystal_body(entry: CatalogEntryModel, analysis: Any, sources: list[ResearchSource]) -> str:
    citation = _cite_first(sources)
    model = entry.model
    assert model is not None

    blocks: list[str] = []
    blocks.append(
        "\n".join(
            [
                f"{_with_citation(entry.summary, citation)}",
                "",
                _with_citation(entry.why_now, ""),
                "",
            ]
        )
    )

    rows = [
        ("초기 투자", _display(analysis, "initial_investment"), "카탈로그에 기록된 시작 비용"),
        ("월 예상 매출", _display(analysis, "monthly_revenue"), "입력한 방문자·판매량·단가 기준"),
        ("월 운영 비용", _display(analysis, "monthly_operating_cost"), "고정비와 단위당 변동비 합계"),
        ("월 예상 순이익", _display(analysis, "monthly_net_profit"), "매출에서 운영 비용을 뺀 값"),
        ("손익분기 도달 기간", _display(analysis, "break_even_months"), "초기 투자 회수에 걸리는 기간"),
        ("시간당 순수익", _display(analysis, "hourly_net_profit"), "월 순이익을 투입 시간으로 나눈 값"),
        ("ROI", _display(analysis, "roi"), "월 순이익을 초기 투자로 나눈 비율"),
    ]
    blocks.append("## 수익 구조 요약\n\n" + _table(["항목", "값", "기준"], rows, align_right={1}))

    heading = _CRYSTAL_HEADINGS.get(model.type, "수익이 남는 조건")
    narrative = [f"## {heading}", _CRYSTAL_DRIVER.get(model.type, "")]
    initial = metric(analysis, "initial_investment")
    if initial is not None and initial.value:
        narrative.append(
            f"초기 투자는 {initial.display}입니다. 월 순이익이 유지된다는 전제에서만 표의 손익분기 기간이 성립하며, "
            "매출이 줄거나 비용이 늘면 회수 기간은 그만큼 길어집니다."
        )
    else:
        narrative.append(
            "초기 투자가 0원으로 기록되어 ROI를 정의하지 않았습니다. 실제로는 도구, 도메인, 콘텐츠 제작 시간 같은 비용이 발생할 수 있습니다."
        )
    net = metric(analysis, "monthly_net_profit")
    if net is not None and net.value is not None:
        if net.value <= 0:
            narrative.append(
                "현재 입력값에서는 월 순이익이 0원 이하입니다. 매출을 늘리거나 고정비를 줄이기 전에는 수익성이 나기 어렵습니다."
            )
        else:
            narrative.append(
                "월 순이익이 플러스로 계산됐더라도 세금, 환불, 본인이 정하지 않은 비용은 포함되지 않았습니다. "
                "실제 입금액은 정산 주기와 수수료 구조를 한 번 더 확인해야 합니다."
            )
    blocks.append("\n\n".join(narrative) + "\n")

    risk = _basis(analysis, "revenue_variability")
    difficulty = _basis(analysis, "operational_difficulty")
    sustainability = _basis(analysis, "long_term_sustainability")
    if risk or difficulty or sustainability:
        lines = [
            "## 수익 변동과 운영 부담",
            "이 수익 구조에서 먼저 봐야 할 것은 수익이 흔들릴 때의 영향과 운영에 드는 시간입니다.",
            *(item for item in (risk, difficulty, sustainability) if item),
        ]
        blocks.append("\n\n".join(lines) + "\n")

    blocks.append(render_scenarios(analysis))
    blocks.append(render_assumptions(analysis))
    blocks.append(_list_block("시작 전 확인할 점", entry.checklist))

    limits = ["## 이 계산의 한계", ""]
    limits.extend(f"- {item}" for item in entry.limitations)
    limits.append("")
    limits.append("이 글의 수치는 명시한 가정에 따른 계산 결과이며, 특정 수익을 보장하지 않습니다.")
    limits.append("")
    blocks.append("\n".join(limits))

    return "\n".join(block for block in blocks if block and block.strip())


def _quartz_body(entry: CatalogEntryModel, analysis: Any, sources: list[ResearchSource]) -> str:
    citation = _cite_first(sources)
    product = entry.product
    assert product is not None

    blocks: list[str] = []
    blocks.append(
        "\n".join(
            [
                f"{_with_citation(entry.summary, citation)}",
                "",
                _with_citation(entry.why_now, ""),
                "",
            ]
        )
    )

    feature_lines: list[str] = []
    for feature in product.features:
        if not feature.available:
            continue
        cite = "".join(f"[{source_id}]" for source_id in feature.source_ids)
        note = (feature.note or "").strip().rstrip(".")
        if note:
            line = f"- **{feature.name}** — {note}"
        else:
            line = f"- **{feature.name}**"
        feature_lines.append(line + (f" {cite}" if cite else ""))
    if feature_lines:
        blocks.append(
            "\n".join(
                [
                    "## 이 도구가 해결하는 업무",
                    "",
                    "공식 문서에서 확인되는 기능과 용도는 다음과 같습니다.",
                    "",
                    *feature_lines,
                ]
            )
            + "\n"
        )

    support: list[str] = []
    if product.platforms:
        support.append("지원 플랫폼은 " + ", ".join(product.platforms) + "입니다.")
    if product.integrations:
        support.append("외부 연동은 다음과 같습니다: " + ", ".join(product.integrations) + ".")
    if product.usage_limits:
        support.append("공식 요금제의 사용량 조건은 다음과 같습니다. " + product.usage_limits)
    if support:
        blocks.append("## 지원 범위와 사용량\n\n" + "\n\n".join(support) + "\n")

    rows = [
        ("선택 요금제", product.selected_plan or "확인 불가", "공식 가격표 기준"),
        ("월 구독 비용", _display(analysis, "monthly_subscription_cost"), "선택한 요금제의 월 가격"),
        ("연 구독 비용", _display(analysis, "annual_subscription_cost"), "연 결제 가격 또는 월 가격의 12배"),
    ]
    if product.tasks_per_month is not None:
        rows.append(("월 작업 수", f"{product.tasks_per_month:,.0f}건", "편집상 가정"))
    rows.extend(
        [
            ("작업당 비용", _display(analysis, "cost_per_task"), "월 구독 비용을 월 작업 수로 나눈 값"),
            ("월 절감 시간", _display(analysis, "time_saved_hours"), "월 작업 수와 작업당 절감 시간 기준"),
            ("시간 절감 순가치", _display(analysis, "net_time_value"), "절감 시간 가치에서 구독 비용을 뺀 값"),
        ]
    )
    blocks.append("## 요금제와 실제 지출\n\n" + _table(["항목", "값", "기준"], rows, align_right={1}))

    price_notes = [
        "## 작업량에 따른 비용 변화",
        "작업당 비용은 월 구독료를 월 작업 수로 나눈 값입니다. 실제 작업 수가 표의 가정보다 적으면 작업당 비용은 높아지고, 많으면 낮아집니다.",
        "시간 절감 순가치는 절감 시간에 시간당 인건비를 적용한 값에서 구독료를 뺀 것입니다. "
        "인건비가 낮거나 절감 시간이 짧으면 같은 구독료라도 정당화하기 어려울 수 있습니다.",
    ]
    if product.notes:
        price_notes.append(product.notes)
    blocks.append("\n\n".join(price_notes) + "\n")

    blocks.append(render_scenarios(analysis))

    fit_keys = (
        ("practicality", "기능의 실용성"),
        ("ease_of_use", "사용 편의성"),
        ("fit_for_purpose", "실제 사용 목적 적합성"),
        ("scalability", "확장성"),
        ("stability_transparency", "안정성 및 신뢰성"),
    )
    fit_sentences = [f"**{label}** — {_basis(analysis, key)}" for key, label in fit_keys if _basis(analysis, key)]
    if fit_sentences:
        blocks.append(
            "\n\n".join(
                [
                    "## 어떤 팀에 맞고 어떤 팀에 과한가",
                    "이 도구가 모든 팀에 맞는 것은 아닙니다. 공식 문서와 요금제 구성을 기준으로 보면 다음과 같습니다.",
                    *fit_sentences,
                ]
            )
            + "\n"
        )

    blocks.append(render_comparison(analysis))
    blocks.append(_list_block("도입 전 확인할 점", entry.checklist))

    limits = ["## 이 분석의 한계", ""]
    limits.extend(f"- {item}" for item in entry.limitations)
    limits.append("")
    limits.append("가격과 기능은 공식 페이지가 바뀌면 달라질 수 있으므로 도입 전 다시 확인해야 합니다.")
    limits.append("")
    blocks.append("\n".join(limits))

    return "\n".join(block for block in blocks if block and block.strip())


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

    tags: list[str] = []
    for tag in entry.tags:
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
