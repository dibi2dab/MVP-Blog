from __future__ import annotations

import re
from typing import Any, Iterable

from src.editorial.analysis import metric
from src.editorial.catalog import CatalogEntryModel
from src.editorial.metrics import build_analysis
from src.editorial.models import (
    EditorialArticle,
    QualityReport,
    QualityScores,
)
from src.editorial.profiles import BlogProfile
from src.editorial.text import (
    average_sentence_length,
    body_fingerprint,
    count_headings,
    fingerprint_similarity,
    has_table,
    korean_ratio,
    title_similarity,
)

MIN_BODY_CHARS = 1200
TARGET_BODY_CHARS = 1800
MAX_TAGS = 10
PUBLISH_THRESHOLD = 85.0
REVISION_THRESHOLD = 70.0

_CITATION = re.compile(r"\[S(\d+)\]")
_INCOME_GUARANTEE = re.compile(
    r"(수익을?\s*보장|수익\s*보장|월\s*\d[\d,]*\s*(?:만)?\s*원\s*보장|"
    r"무조건\s*(?:벌|수익|돈)|확실히\s*(?:벌|수익|돈)|원금\s*보장)"
    r"(?!\s*(?:하지|되지|않|못|할\s*수\s*없))"
)
_TEST_CLAIM = re.compile(
    r"(직접\s*(?:사용|써|테스트|운영|비교)해\s*(?:보니|봤)|써\s*보니|"
    r"사용해\s*보니|테스트해\s*보니|직접\s*써본)"
)
_ASSUMPTION_WORD = re.compile(r"(편집상\s*가정|가정|추정)")


def _normalize_url(url: str) -> str:
    return (url or "").strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        if value and value not in found:
            found.append(value)
    return found


def _verify_calculations(
    article: EditorialArticle,
    entry: CatalogEntryModel,
    critical: list[str],
) -> list[str]:
    notes: list[str] = []
    try:
        recomputed = build_analysis(entry, article.blog)
    except Exception as exc:  # noqa: BLE001 - report, never crash the gate
        critical.append(f"분석 재계산에 실패했습니다: {exc}")
        return notes

    current = {item.key: item for item in article.analysis.metrics}
    for expected in recomputed.metrics:
        actual = current.get(expected.key)
        if actual is None:
            critical.append(f"계산 항목이 누락되었습니다: {expected.name}")
            continue
        if expected.value is None and actual.value is None:
            continue
        if expected.value is None or actual.value is None:
            critical.append(f"계산 결과가 카탈로그와 다릅니다: {expected.name}")
            continue
        if abs(float(expected.value) - float(actual.value)) > 0.01:
            critical.append(
                f"계산 검증 실패: {expected.name} "
                f"(기대 {expected.value:,.2f}, 본문 {actual.value:,.2f})"
            )
    notes.append("카탈로그 입력값으로 핵심 수치를 다시 계산해 대조했습니다.")

    item_scores = {item.key: item.score for item in article.analysis.evaluation_items}
    for expected in recomputed.evaluation_items:
        if expected.key not in item_scores:
            critical.append(f"평가 항목이 누락되었습니다: {expected.name}")
            continue
        actual = item_scores[expected.key]
        if expected.score is None and actual is None:
            continue
        if expected.score is None or actual is None:
            critical.append(f"평가 점수가 카탈로그와 다릅니다: {expected.name}")
            continue
        if abs(float(expected.score) - float(actual)) > 0.01:
            critical.append(f"평가 점수 검증 실패: {expected.name}")
    return notes


def _factual_accuracy(
    article: EditorialArticle,
    entry: CatalogEntryModel | None,
    critical: list[str],
    warnings: list[str],
    notes: list[str],
) -> float:
    score = 25.0
    body = article.body_with_sources or article.body_markdown
    source_ids = {source.source_id for source in article.sources}
    cited = _dedupe(f"S{match}" for match in _CITATION.findall(body))

    unknown = [source_id for source_id in cited if source_id not in source_ids]
    if unknown:
        critical.append(f"본문 인용이 출처 목록에 없습니다: {', '.join(unknown)}")
        score -= min(15.0, 5.0 * len(unknown))

    if not cited:
        critical.append("본문에 출처 인용이 없습니다.")
        score -= 10.0

    invalid_urls = [
        source.source_id
        for source in article.sources
        if not _normalize_url(source.url).startswith(("http://", "https://"))
    ]
    if invalid_urls:
        critical.append(f"출처 URL이 올바르지 않습니다: {', '.join(invalid_urls)}")
        score -= min(10.0, 3.0 * len(invalid_urls))

    undated = [source.source_id for source in article.sources if not (source.published_at or source.retrieved_at)]
    if undated:
        warnings.append(f"발행일 또는 확인일이 없는 출처가 있습니다: {', '.join(undated)}")
        score -= min(6.0, 1.5 * len(undated))

    if entry is None:
        warnings.append("카탈로그 항목과 연결되지 않아 데이터 출처를 완전히 검증하지 못했습니다.")
        score -= 5.0
    else:
        if article.catalog_id and article.catalog_id != entry.id:
            critical.append("카탈로그 ID와 분석 대상이 일치하지 않습니다.")
            score -= 10.0
        if article.analysis.subject and article.analysis.subject != entry.name:
            critical.append(
                f"데이터와 분석 대상이 일치하지 않습니다: {article.analysis.subject} != {entry.name}"
            )
            score -= 20.0
        if len(article.analysis.evaluation_items) < 10:
            critical.append("10가지 평가 항목이 모두 포함되지 않았습니다.")
            score -= 10.0
        notes.extend(_verify_calculations(article, entry, critical))

        if entry.product is not None:
            selected = entry.product.selected_plan
            plan_names = {plan.name for plan in entry.product.plans}
            if not selected or selected not in plan_names:
                critical.append("존재하지 않는 요금제를 분석 대상으로 사용했습니다.")
                score -= 15.0

    has_editorial_assumption = any(item.is_editorial for item in article.analysis.assumptions)
    if has_editorial_assumption and not _ASSUMPTION_WORD.search(body):
        critical.append("편집상 가정이 본문에서 공식 자료와 구분되지 않습니다.")
        score -= 10.0

    if _INCOME_GUARANTEE.search(body):
        critical.append("검증되지 않은 수익 보장 표현이 포함되어 있습니다.")
        score -= 25.0

    if _TEST_CLAIM.search(body):
        critical.append("검증되지 않은 직접 사용 후기 표현이 포함되어 있습니다.")
        score -= 10.0

    missing_displays = [
        item.name
        for item in article.analysis.metrics
        if item.value is not None and item.display and item.display not in body
    ]
    if missing_displays:
        warnings.append(f"본문에 표시되지 않은 계산 결과가 있습니다: {', '.join(missing_displays)}")
        score -= min(5.0, len(missing_displays))

    return max(0.0, min(25.0, score))


def _originality(article: EditorialArticle, critical: list[str], notes: list[str]) -> float:
    analysis = article.analysis
    score = 0.0
    calculated = [item for item in analysis.metrics if item.value is not None and item.formula]
    if len(calculated) >= 3:
        score += 6.0
    elif calculated:
        score += 3.0

    scored_items = [item for item in analysis.evaluation_items if item.score is not None]
    if len(scored_items) >= 8:
        score += 5.0
    elif len(scored_items) >= 5:
        score += 3.0

    if len(analysis.scenario_analysis) >= 2:
        score += 4.0
    elif analysis.scenario_analysis:
        score += 2.0

    if len(analysis.comparison) >= 2:
        score += 3.0
    elif len(analysis.steps) >= 3:
        score += 2.0

    if analysis.assumptions:
        score += 2.0

    score = min(20.0, score)
    if score < 5.0:
        critical.append("독자적 계산, 비교, 시나리오 분석이 부족합니다.")
    notes.append(f"독자 분석 점수: {score:.1f}/20 (계산 {len(calculated)}개, 평가 {len(scored_items)}개).")
    return score


def _search_intent(article: EditorialArticle, critical: list[str], warnings: list[str]) -> float:
    body = article.body_with_sources or article.body_markdown
    keyword = article.primary_keyword.strip()
    score = 0.0

    if keyword:
        if keyword in article.title:
            score += 6.0
        else:
            critical.append("제목에 핵심 키워드가 없어 검색 의도와 맞지 않습니다.")
        count = body.count(keyword)
        if count >= 3:
            score += 4.0
        elif count >= 1:
            score += 2.0
        else:
            critical.append("본문에 핵심 키워드가 없어 제목과 본문의 주제가 일치하지 않습니다.")
    else:
        critical.append("핵심 키워드가 비어 있습니다.")

    headings = count_headings(body)
    if headings >= 5:
        score += 3.0
    elif headings >= 3:
        score += 2.0
    else:
        warnings.append("소제목이 부족해 검색 사용자가 원하는 정보를 찾기 어렵습니다.")

    meta_length = len(article.meta_description.strip())
    if 80 <= meta_length <= 160:
        score += 4.0
    elif 50 <= meta_length <= 200:
        score += 2.0
    else:
        warnings.append("메타 설명 길이가 권장 범위(80~160자)를 벗어났습니다.")

    decision_markers = ("체크리스트", "적합", "판단 기준", "도입", "시작", "선택 기준")
    if any(marker in body for marker in decision_markers):
        score += 3.0
    else:
        warnings.append("실제 선택이나 실행에 도움이 되는 판단 기준이 부족합니다.")

    return max(0.0, min(20.0, score))


def _source_quality(
    article: EditorialArticle,
    profile: BlogProfile,
    entry: CatalogEntryModel | None,
    critical: list[str],
    warnings: list[str],
) -> float:
    score = 0.0
    sources = list(article.sources)
    required = max(3, profile.min_sources)
    if len(sources) >= required:
        score += 6.0
    elif sources:
        score += round(6.0 * len(sources) / required, 2)
        warnings.append(f"출처가 {required}개 미만입니다: {len(sources)}개.")
    else:
        critical.append("출처가 없습니다.")

    official_domains = tuple(domain.lower() for domain in profile.source_domains)
    official = [
        source
        for source in sources
        if "공식" in (source.publisher or "")
        or any(domain in (source.url or "").lower() for domain in official_domains)
    ]
    if len(official) >= 2:
        score += 4.0
    elif official:
        score += 2.0
    else:
        warnings.append("공식 문서나 1차 자료 출처가 확인되지 않았습니다.")

    dated = [source for source in sources if source.published_at or source.retrieved_at]
    if sources and len(dated) == len(sources):
        score += 3.0
    elif dated:
        score += 1.5
    else:
        warnings.append("출처 확인일이 없습니다.")

    if entry is not None and entry.last_reviewed:
        score += 2.0
    else:
        warnings.append("카탈로그 최종 검토일이 없어 자료의 최신성을 확인하기 어렵습니다.")

    return max(0.0, min(15.0, score))


def _readability(article: EditorialArticle, warnings: list[str]) -> float:
    body = article.body_markdown
    score = 0.0
    length = len(body)
    if length >= TARGET_BODY_CHARS:
        score += 4.0
    elif length >= MIN_BODY_CHARS:
        score += 2.0
    else:
        warnings.append(f"본문이 짧습니다: {length}자 (권장 {MIN_BODY_CHARS}자 이상).")

    if count_headings(body) >= 4:
        score += 2.0
    if has_table(body):
        score += 2.0
    if korean_ratio(body) >= 0.6:
        score += 1.0
    if 0 < average_sentence_length(body) <= 90:
        score += 1.0
    return max(0.0, min(10.0, score))


def _seo(article: EditorialArticle, warnings: list[str]) -> float:
    score = 0.0
    title_length = len(article.title.strip())
    if 20 <= title_length <= 60:
        score += 3.0
    elif 10 <= title_length <= 80:
        score += 1.0
    else:
        warnings.append("제목 길이가 검색 결과에 적합한 범위를 벗어났습니다.")

    meta_length = len(article.meta_description.strip())
    if 80 <= meta_length <= 160:
        score += 3.0
    elif 50 <= meta_length <= 200:
        score += 1.0

    if article.primary_keyword and article.primary_keyword in article.title:
        score += 2.0

    if 3 <= len(article.tags) <= MAX_TAGS:
        score += 1.0
    elif len(article.tags) > MAX_TAGS:
        warnings.append(f"태그가 너무 많습니다: {len(article.tags)}개 (최대 {MAX_TAGS}개).")

    if article.slug and len(article.slug) <= 80:
        score += 1.0
    return max(0.0, min(10.0, score))


def _duplicates(
    article: EditorialArticle,
    recent_records: Iterable[dict[str, Any]],
    critical: list[str],
) -> None:
    fingerprint = body_fingerprint(article.body_markdown)
    for record in recent_records:
        record_title = str(record.get("title") or "")
        record_catalog = str(record.get("catalog_id") or "")
        if article.catalog_id and record_catalog == article.catalog_id:
            critical.append(f"동일한 카탈로그 항목이 이미 발행되었습니다: {record_title}")
            return
        if record_title and title_similarity(article.title, record_title) >= 0.92:
            critical.append(f"이미 발행한 글과 제목이 유사합니다: {record_title}")
            return
        previous = record.get("body_fingerprint") or []
        if fingerprint and isinstance(previous, list) and previous:
            if fingerprint_similarity(fingerprint, previous) >= 0.55:
                critical.append(f"이미 발행한 글과 본문이 유사합니다: {record_title}")
                return


def decide_publication(
    report: QualityReport,
    profile: BlogProfile,
) -> tuple[str, str, str]:
    """Return ``(decision, status, reason)`` for a quality report."""

    if report.critical_failures:
        return (
            "DO NOT PUBLISH",
            "failed",
            "치명적 결함: " + "; ".join(report.critical_failures),
        )
    threshold = max(PUBLISH_THRESHOLD, profile.min_quality_score)
    if report.total >= threshold:
        return "PUBLISH", "ready", f"품질 점수 {report.total:.1f}점 (기준 {threshold:.0f}점 이상)."
    if report.total >= REVISION_THRESHOLD:
        return (
            "NEEDS REVISION",
            "draft",
            f"품질 점수 {report.total:.1f}점으로 수정이 필요합니다 (발행 기준 {threshold:.0f}점).",
        )
    return (
        "DO NOT PUBLISH",
        "failed",
        f"품질 점수 {report.total:.1f}점으로 발행 기준에 미달합니다 (발행 기준 {threshold:.0f}점).",
    )


def assess_quality(
    article: EditorialArticle,
    profile: BlogProfile,
    *,
    recent_records: Iterable[dict[str, Any]] = (),
    entry: CatalogEntryModel | None = None,
) -> QualityReport:
    """Score an article deterministically.

    The gate never trusts a model. It re-runs every calculation from the
    catalog, checks that citations exist, and rejects duplicate content.
    """

    critical: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    factual = _factual_accuracy(article, entry, critical, warnings, notes)
    originality = _originality(article, critical, notes)
    intent = _search_intent(article, critical, warnings)
    source_quality = _source_quality(article, profile, entry, critical, warnings)
    readability = _readability(article, warnings)
    seo = _seo(article, warnings)

    _duplicates(article, recent_records, critical)

    scores = QualityScores(
        factual_accuracy=round(factual, 2),
        originality=round(originality, 2),
        search_intent=round(intent, 2),
        source_quality=round(source_quality, 2),
        readability=round(readability, 2),
        seo_quality=round(seo, 2),
    )
    total = round(scores.total, 2)
    report = QualityReport(
        scores=scores,
        total=total,
        critical_failures=_dedupe(critical),
        warnings=_dedupe(warnings),
        notes=_dedupe(notes),
    )
    decision, status, reason = decide_publication(report, profile)
    article.quality = report
    article.decision = decision
    article.decision_reason = reason
    article.status = status
    return report
