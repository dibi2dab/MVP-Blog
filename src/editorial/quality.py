from __future__ import annotations

import re
from typing import Any, Iterable

from src.editorial.models import (
    EditorialDraft,
    QualityReport,
    QualityScores,
    ResearchSource,
)
from src.editorial.profiles import BlogProfile
from src.editorial.text import (
    average_sentence_length,
    body_fingerprint,
    count_headings,
    fingerprint_similarity,
    hangul_count,
    has_table,
    korean_ratio,
    title_similarity,
)

MIN_BODY_CHARS = 1000
TARGET_BODY_CHARS = 1500
MAX_TAGS = 10

_CITATION = re.compile(r"\[S(\d+)\]")
_URL = re.compile(r"https?://[^\s)\]>\"']+")
_NUMBER_CLAIM = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(%|퍼센트|원|달러|USD|KRW|배|시간|명|개월|년)"
)
_ATTRIBUTION = re.compile(r"(조사에 따르면|연구에 따르면|통계에 따르면|전문가들은|보고서에 따르면)")
_TEST_CLAIM = re.compile(
    r"(직접\s*(?:사용|써|테스트|비교|운영)해\s*보니|직접\s*(?:사용|써|테스트|비교|운영)해봤|"
    r"써보니|사용해\s*보니|테스트해\s*보니)"
)


def _normalize_url(url: str) -> str:
    return (url or "").strip().rstrip(".,;:)")


def _source_urls(sources: Iterable[ResearchSource]) -> set[str]:
    return {_normalize_url(source.url) for source in sources if source.url}


def _citation_ids(text: str) -> list[str]:
    return [f"S{number}" for number in _CITATION.findall(text or "")]


def _first_paragraph(text: str, limit: int = 400) -> str:
    for chunk in re.split(r"\n\s*\n", text or ""):
        chunk = chunk.strip()
        if chunk and not chunk.startswith("#"):
            return chunk[:limit]
    return (text or "")[:limit]


def _contains_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    haystack = re.sub(r"\s+", " ", (text or "").lower())
    needle = re.sub(r"\s+", " ", keyword.lower()).strip()
    return bool(needle) and needle in haystack


def _heading_text(text: str) -> str:
    return "\n".join(
        line for line in (text or "").splitlines() if re.match(r"^#{2,3}\s+", line)
    )


def _unsupported_numbers(body: str, allowed_text: str) -> list[str]:
    allowed = set()
    for match in re.finditer(r"\d+(?:[.,]\d+)?", allowed_text or ""):
        try:
            allowed.add(float(match.group(0).replace(",", "")))
        except ValueError:
            continue
    unsupported: list[str] = []
    for match in _NUMBER_CLAIM.finditer(body or ""):
        raw = match.group(1).replace(",", "")
        try:
            number = float(raw)
        except ValueError:
            continue
        # Years, months, small counts and round percentages are usually dates or
        # harmless context. We only flag values that look like data claims.
        if 2000 <= number <= 2100:
            continue
        if number <= 12:
            continue
        if number not in allowed:
            unsupported.append(match.group(0))
    return unsupported[:10]


def _attribution_without_citation(body: str) -> list[str]:
    issues: list[str] = []
    for chunk in re.split(r"\n\s*\n", body or ""):
        if _ATTRIBUTION.search(chunk) and not _CITATION.search(chunk):
            issues.append(chunk.strip()[:160])
    return issues[:5]


def _firsthand_test_claim(body: str) -> bool:
    for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", body or ""):
        if _TEST_CLAIM.search(sentence) and "않" not in sentence:
            return True
    return False


def _duplicate_matches(
    draft: EditorialDraft,
    recent_records: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    critical: list[str] = []
    warnings: list[str] = []
    new_fingerprint = body_fingerprint(draft.body_markdown)
    for record in recent_records:
        recent_title = str(record.get("title") or "")
        recent_fingerprint = record.get("body_fingerprint") or []
        title_score = title_similarity(draft.title, recent_title)
        body_score = fingerprint_similarity(new_fingerprint, recent_fingerprint)
        if title_score >= 0.80 or body_score >= 0.60:
            critical.append(
                f"최근 발행 글과 유사함 (제목 유사도 {title_score:.2f}, 본문 유사도 {body_score:.2f}): {recent_title}"
            )
            break
        if title_score >= 0.60 or body_score >= 0.40:
            warnings.append(
                f"최근 글과 일부 유사 (제목 {title_score:.2f}, 본문 {body_score:.2f}): {recent_title}"
            )
    return critical, warnings


def _primary_source_count(sources: list[ResearchSource], profile: BlogProfile) -> int:
    count = 0
    for source in sources:
        haystack = f"{source.url} {source.publisher_url}".lower()
        if any(domain in haystack for domain in profile.source_domains):
            count += 1
    return count


def assess_quality(
    draft: EditorialDraft,
    profile: BlogProfile,
    research_sources: list[ResearchSource],
    recent_records: list[dict[str, Any]] | None = None,
    *,
    analysis_errors: list[str] | None = None,
    analysis_warnings: list[str] | None = None,
    provider_name: str = "",
    raw_body: str | None = None,
) -> QualityReport:
    """Deterministic quality gate, independent of the model's self-assessment.

    ``raw_body`` lets the caller measure the AI-written body separately from the
    deterministic analysis/source sections that are appended afterwards. A short
    model body must not pass just because the appended analysis is long.
    """

    recent_records = recent_records or []
    critical: list[str] = []
    warnings: list[str] = list(analysis_warnings or [])
    notes: list[str] = []

    body = draft.body_markdown or ""
    measured_body = raw_body if raw_body is not None else body
    body_len = len(measured_body.strip())
    if body_len < MIN_BODY_CHARS:
        critical.append(f"본문이 너무 짧음 ({body_len}자 < {MIN_BODY_CHARS}자)")
    elif body_len < TARGET_BODY_CHARS:
        warnings.append(f"본문 길이가 권장치보다 짧음 ({body_len}자 < {TARGET_BODY_CHARS}자)")

    ratio = korean_ratio(body)
    hangul = hangul_count(body)
    if ratio < 0.25 or hangul < 400:
        critical.append(f"한국어 본문 비중이 부족함 (한글 비율 {ratio:.2f}, 한글 {hangul}자)")

    if not (draft.title or "").strip():
        critical.append("제목이 비어 있음")
    if not (draft.meta_description or "").strip():
        critical.append("메타 설명이 비어 있음")
    if not (draft.primary_keyword or "").strip():
        critical.append("대표 키워드가 비어 있음")
    if not (draft.slug or "").strip():
        warnings.append("슬러그가 비어 있음")
    if not (3 <= len(draft.tags) <= MAX_TAGS):
        warnings.append(f"태그 수가 권장 범위를 벗어남 ({len(draft.tags)}개, 3~{MAX_TAGS}개 권장)")

    # --- source integrity -------------------------------------------------
    source_count = len(draft.sources)
    if source_count < profile.min_sources:
        critical.append(f"출처가 부족함 ({source_count}개 < 최소 {profile.min_sources}개)")

    pool_urls = _source_urls(research_sources)
    for source in draft.sources:
        if not (source.url or "").strip():
            critical.append(f"출처 URL 누락: [{source.source_id}] {source.title}")
        elif _normalize_url(source.url) not in pool_urls:
            critical.append(f"리서치 풀에 없는 출처 URL: [{source.source_id}] {source.url}")
        if not source.published_at:
            warnings.append(f"출처 발행일 누락: [{source.source_id}] {source.title}")

    cited = _citation_ids(body)
    if not cited:
        critical.append("본문에 [S1] 형식의 출처 인용이 없음")
    known_ids = {source.source_id for source in draft.sources}
    unknown = sorted(set(cited) - known_ids)
    if unknown:
        critical.append(f"본문에 알 수 없는 출처 ID가 있음: {', '.join(unknown)}")

    body_urls = {_normalize_url(url) for url in _URL.findall(body)}
    allowed_urls = pool_urls | {f"https://{profile.blog_name}.tistory.com"}
    external = sorted(url for url in body_urls if url not in allowed_urls)
    if external:
        critical.append(f"본문에 리서치 풀 밖 URL이 있음: {', '.join(external[:3])}")

    # --- analysis integrity ----------------------------------------------
    if analysis_errors:
        critical.extend(analysis_errors)
    if draft.analysis.result is None:
        critical.append("분석 최종 점수가 없음")

    # --- self-assessment cross-check -------------------------------------
    self_quality = draft.self_quality
    self_total: float | None = None
    if self_quality is not None:
        component_total = round(
            self_quality.factual_accuracy
            + self_quality.originality
            + self_quality.search_intent
            + self_quality.source_quality
            + self_quality.readability
            + self_quality.seo_quality,
            2,
        )
        self_total = self_quality.total or component_total
        if component_total > 0 and abs(self_total - component_total) > 2:
            warnings.append(
                f"모델 자기평가 총점이 항목 합계와 다름 (총점 {self_total}, 합계 {component_total})"
            )
            self_total = component_total
        if self_quality.critical_failures:
            critical.extend(f"모델 자기평가 치명적 실패: {item}" for item in self_quality.critical_failures)
        if self_total < profile.min_quality_score:
            warnings.append(f"모델 자기평가 점수가 기준 미만 ({self_total:.1f} < {profile.min_quality_score:.1f})")
    else:
        warnings.append("모델 자기평가(self_quality)가 없음")

    # --- factual accuracy signals ----------------------------------------
    allowed_text = " ".join(
        [
            " ".join(source.title + " " + source.snippet for source in research_sources),
            str(draft.analysis.inputs),
            " ".join(draft.analysis.steps),
            str(draft.analysis.result or ""),
        ]
    )
    unsupported_numbers = _unsupported_numbers(body, allowed_text)
    if unsupported_numbers:
        warnings.append(f"출처·입력값에서 확인되지 않은 수치 표현: {', '.join(unsupported_numbers[:5])}")

    attribution_issues = _attribution_without_citation(body)
    if attribution_issues:
        warnings.append(f"인용 표기 없이 일반화된 근거 표현이 있음: {attribution_issues[0]}")

    if _firsthand_test_claim(body) and not bool(draft.analysis.inputs.get("tested")):
        critical.append("직접 테스트/사용 주장이 있으나 실제 테스트 여부가 확인되지 않음")

    if provider_name == "mock":
        critical.append("mock AI 결과는 발행할 수 없음")

    # --- duplicate content -------------------------------------------------
    duplicate_critical, duplicate_warnings = _duplicate_matches(draft, recent_records)
    critical.extend(duplicate_critical)
    warnings.extend(duplicate_warnings)

    # --- scoring -----------------------------------------------------------
    headings = count_headings(body)
    table = has_table(body)
    first_paragraph = _first_paragraph(body)
    heading_text = _heading_text(body)
    keyword = draft.primary_keyword

    factual = 10.0
    factual += min(6.0, source_count * 2.0)
    factual += min(4.0, float(len(set(cited))))
    dated = sum(1 for source in draft.sources if source.published_at)
    if source_count and dated == source_count:
        factual += 3.0
    elif source_count and dated >= max(1, source_count // 2):
        factual += 1.0
    if self_quality is not None and self_quality.factual_accuracy >= 20:
        factual += 3.0
    factual -= min(5.0, float(len(unsupported_numbers)))
    if attribution_issues:
        factual -= 2.0
    factual = max(0.0, min(25.0, factual))

    originality = 6.0
    if draft.analysis.result is not None:
        originality += 5.0
    if table:
        originality += 4.0
    if profile.framework.upper() in body.upper():
        originality += 3.0
    if draft.analysis.scenario_analysis:
        originality += 2.0
    if duplicate_warnings:
        originality -= 3.0
    originality = max(0.0, min(20.0, originality))

    search_intent = 8.0
    if _contains_keyword(draft.title, keyword):
        search_intent += 4.0
    if _contains_keyword(draft.meta_description, keyword):
        search_intent += 4.0
    if _contains_keyword(first_paragraph, keyword):
        search_intent += 2.0
    if _contains_keyword(heading_text, keyword):
        search_intent += 2.0
    search_intent = max(0.0, min(20.0, search_intent))

    primary_count = _primary_source_count(draft.sources, profile)
    source_quality = 6.0
    if source_count >= 3:
        source_quality += 3.0
    if source_count >= 5:
        source_quality += 3.0
    if primary_count >= 1:
        source_quality += 2.0
    if source_count and dated == source_count:
        source_quality += 1.0
    source_quality = max(0.0, min(15.0, source_quality))

    readability = 6.0
    if headings >= 4:
        readability += 2.0
    if 0 < average_sentence_length(body) <= 90:
        readability += 1.0
    if table or re.search(r"(?m)^\s*[-*]\s+\S", body):
        readability += 1.0
    readability = max(0.0, min(10.0, readability))

    seo = 5.0
    title_len = len((draft.title or "").strip())
    meta_len = len((draft.meta_description or "").strip())
    if 20 <= title_len <= 70:
        seo += 2.0
    else:
        warnings.append(f"제목 길이 권장 범위 밖 ({title_len}자, 20~70자 권장)")
    if 70 <= meta_len <= 160:
        seo += 1.0
    else:
        warnings.append(f"메타 설명 길이 권장 범위 밖 ({meta_len}자, 70~160자 권장)")
    if (draft.slug or "").strip():
        seo += 1.0
    if 3 <= len(draft.tags) <= MAX_TAGS:
        seo += 1.0
    seo = max(0.0, min(10.0, seo))

    scores = QualityScores(
        factual_accuracy=round(factual, 2),
        originality=round(originality, 2),
        search_intent=round(search_intent, 2),
        source_quality=round(source_quality, 2),
        readability=round(readability, 2),
        seo_quality=round(seo, 2),
    )

    if source_count < 5:
        warnings.append(f"출처가 5개 미만임 ({source_count}개)")
    if primary_count < 1:
        warnings.append("공식 문서/1차 자료로 분류되는 출처가 없음")
    if not table:
        warnings.append("비교 표가 없음")
    if headings < 4:
        warnings.append(f"H2/H3 섹션이 부족함 ({headings}개)")
    if not draft.analysis.scenario_analysis:
        warnings.append("시나리오 분석이 없음")
    notes.append(f"deterministic quality gate: {body_len}자, 출처 {source_count}개, 인용 {len(set(cited))}개")

    return QualityReport(
        scores=scores,
        total=scores.total,
        critical_failures=_unique(critical),
        warnings=_unique(warnings),
        ai_self_total=self_total,
        notes=notes,
    )


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def decide_publication(report: QualityReport, profile: BlogProfile) -> tuple[str, str]:
    if report.critical_failures:
        return "DO NOT PUBLISH", "치명적 품질 실패: " + "; ".join(report.critical_failures[:3])
    if report.total < profile.min_quality_score:
        return (
            "REQUIRES REVISION",
            f"품질 점수 {report.total:.1f} < 기준 {profile.min_quality_score:.1f}",
        )
    if report.ai_self_total is not None and report.ai_self_total < profile.min_quality_score:
        return (
            "REQUIRES REVISION",
            f"모델 자기평가 {report.ai_self_total:.1f} < 기준 {profile.min_quality_score:.1f}",
        )
    return "PUBLISH", f"품질 점수 {report.total:.1f} >= 기준 {profile.min_quality_score:.1f}"
