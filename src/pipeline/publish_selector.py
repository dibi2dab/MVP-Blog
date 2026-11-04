from __future__ import annotations

"""자동 발행 기사 선정.

하루에 어떤 기사를 발행할지 명시적으로 결정한다. 단순히 파일 순서대로 발행하지 않고
(1) 발행 준비도, (2) 신선도, (3) 품질·데이터 독립성, (4) 최근 기사와의 유사도,
(5) 종목·이벤트 유형 다양성을 순서대로 적용한다.

일일 한도는 `data/published/event_*.json` 의 `published_at` 을 KST 날짜로 집계해
계산하므로, 워크플로가 하루에 여러 번 돌아도 5건을 넘지 않는다.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.config.settings import Settings
from src.models.article import Article
from src.publishers.base import PublishDeduplicator
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger
from src.utils.similarity import article_similarity

logger = get_logger(__name__)

KST = timezone(timedelta(hours=9))
_ELIGIBLE_STATUSES = {"approved"}
_RETRY_STATUSES = {"publish_failed"}


@dataclass
class PublishCandidate:
    article: Article
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class SelectionResult:
    selected: list[PublishCandidate] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    published_today: int = 0
    daily_limit: int = 5

    @property
    def remaining(self) -> int:
        return max(0, self.daily_limit - self.published_today)


def kst_date(value: str | None) -> str:
    """ISO 8601 문자열을 KST 날짜(YYYY-MM-DD)로 변환한다."""
    if not value:
        return ""
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10] if len(text) >= 10 else ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(KST).strftime("%Y-%m-%d")


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def published_today(store: JsonStore, day: str | None = None) -> list[dict]:
    """오늘(KST) 실제로 발행된 마커만 반환한다."""
    day = day or today_kst()
    markers: list[dict] = []
    for key in store.load_published_keys():
        if not key.startswith("event_"):
            continue
        payload = store.load_published_marker(key)
        if not payload:
            continue
        if kst_date(payload.get("published_at")) == day:
            markers.append(payload)
    return markers


def _event_age_days(article: Article) -> int | None:
    raw = article.event.event_date or article.created_at
    if not raw:
        return None
    try:
        event_day = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (datetime.now(KST).date() - event_day).days


def _sources_with_url(article: Article) -> int:
    return sum(1 for s in article.sources if "http" in (s or ""))


def _candidate_score(article: Article, age_days: int | None) -> float:
    metric_count = len(article.data_metrics or {})
    freshness = 0.0
    if age_days is not None:
        freshness = max(0, 7 - min(age_days, 7)) / 7.0
    score = (
        float(article.event.event_score or 0) * 1.0
        + float(article.event.evidence_score or 0) * 1.0
        + float(article.quality_score or 0.0) * 10.0
        + min(metric_count, 8) * 0.5
        + freshness * 2.0
    )
    return round(score, 3)


def select_articles(
    settings: Settings,
    store: JsonStore,
    *,
    limit: int | None = None,
    retry_failed: bool = False,
    day: str | None = None,
) -> SelectionResult:
    """오늘 발행할 기사를 순위·다양성 기준으로 선정한다."""
    cfg = settings.publishing
    day = day or today_kst()
    limit = cfg.daily_limit if limit is None else max(0, limit)
    result = SelectionResult(daily_limit=limit)

    markers = published_today(store, day)
    result.published_today = len(markers)
    if result.published_today >= limit:
        logger.info("[select] 일일 한도 도달: %d/%d", result.published_today, limit)
        return result

    dedup = PublishDeduplicator(store)
    all_articles = store.load_all_articles()
    recent_published = [a for a in all_articles if a.status == "published"]

    entity_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for marker in markers:
        entity = (marker.get("entity") or "").strip()
        event_type = (marker.get("event_type") or "").strip()
        if entity:
            entity_counts[entity] = entity_counts.get(entity, 0) + 1
        if event_type:
            type_counts[event_type] = type_counts.get(event_type, 0) + 1

    statuses = set(_ELIGIBLE_STATUSES)
    if retry_failed:
        statuses |= _RETRY_STATUSES

    pool: list[PublishCandidate] = []
    for article in all_articles:
        if article.status not in statuses:
            continue
        if dedup.is_published(article):
            result.skipped.append((article.article_id, "이미 발행됨"))
            continue

        readiness = article.readiness or {}
        if not readiness.get("ready", False):
            result.skipped.append((article.article_id, "readiness 미충족"))
            continue
        if len(article.data_metrics or {}) < cfg.min_independent_metrics:
            result.skipped.append((article.article_id, "계산 지표 부족"))
            continue
        if _sources_with_url(article) < cfg.min_sources_with_url:
            result.skipped.append((article.article_id, "URL 출처 부족"))
            continue
        if article.quality_score < cfg.min_quality_score:
            result.skipped.append((article.article_id, "품질 점수 미달"))
            continue

        age = _event_age_days(article)
        if age is None or age > cfg.max_event_age_days:
            result.skipped.append((article.article_id, f"이벤트 경과 {age}일"))
            continue

        # 최근 발행 기사와 실질적으로 같은 글인지 확인한다.
        max_similarity = 0.0
        for other in recent_published:
            max_similarity = max(max_similarity, article_similarity(article, other))
        if max_similarity >= cfg.max_recent_similarity:
            result.skipped.append((article.article_id, f"최근 기사 유사도 {max_similarity:.2f}"))
            continue

        score = _candidate_score(article, age)
        reasons = [
            f"event={article.event.event_score}",
            f"evidence={article.event.evidence_score}",
            f"quality={article.quality_score:.2f}",
            f"metrics={len(article.data_metrics or {})}",
            f"age={age}d",
        ]
        pool.append(PublishCandidate(article=article, score=score, reasons=reasons))

    pool.sort(key=lambda c: (c.score, c.article.created_at), reverse=True)

    for candidate in pool:
        if len(result.selected) >= result.remaining:
            result.skipped.append((candidate.article.article_id, "일일 한도"))
            continue
        entity = (candidate.article.event.entity.name or "").strip()
        event_type = (candidate.article.event.event_type or "").strip()

        if entity and entity_counts.get(entity, 0) >= cfg.max_per_entity_per_day:
            result.skipped.append((candidate.article.article_id, f"종목 중복({entity})"))
            continue
        if event_type and type_counts.get(event_type, 0) >= cfg.max_per_event_type_per_day:
            result.skipped.append((candidate.article.article_id, f"유형 중복({event_type})"))
            continue

        # 같은 배치 안에서도 최근 기사와 유사한 글은 제외한다.
        too_similar = False
        for chosen in result.selected:
            if article_similarity(candidate.article, chosen.article) >= cfg.max_recent_similarity:
                result.skipped.append((candidate.article.article_id, "선정 기사와 유사"))
                too_similar = True
                break
        if too_similar:
            continue

        result.selected.append(candidate)
        if entity:
            entity_counts[entity] = entity_counts.get(entity, 0) + 1
        if event_type:
            type_counts[event_type] = type_counts.get(event_type, 0) + 1

    logger.info(
        "[select] day=%s published=%d limit=%d selected=%d skipped=%d",
        day,
        result.published_today,
        limit,
        len(result.selected),
        len(result.skipped),
    )
    for candidate in result.selected:
        logger.info(
            "[select] + %s score=%.2f %s",
            candidate.article.article_id,
            candidate.score,
            " ".join(candidate.reasons),
        )
    return result
