from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.editorial.catalog import Catalog, CatalogEntryModel
from src.editorial.models import ResearchSource
from src.editorial.profiles import BlogProfile
from src.editorial.state import EditorialState


@dataclass
class QueueSelection:
    entry: CatalogEntryModel | None
    reason: str
    published_today: int = 0
    unused_count: int = 0


def published_catalog_ids(state: EditorialState) -> set[str]:
    return {
        str(record.get("catalog_id") or "")
        for record in state.load_published()
        if record.get("catalog_id")
    }


def _signal_score(entry: CatalogEntryModel, signals: Iterable[Any]) -> int:
    text = " ".join(
        f"{getattr(signal, 'title', '')} {getattr(signal, 'snippet', '')}"
        for signal in signals
    )
    if not text.strip():
        return 0
    score = 0
    if entry.primary_keyword and entry.primary_keyword in text:
        score += 3
    if entry.name and entry.name in text:
        score += 2
    for keyword in entry.secondary_keywords:
        if keyword and keyword in text:
            score += 1
    return score


def select_next_entry(
    catalog: Catalog,
    profile: BlogProfile,
    state: EditorialState,
    *,
    force: bool = False,
    signals: Iterable[ResearchSource] = (),
) -> QueueSelection:
    """Pick the next catalog entry without repeating a published topic.

    ``force`` only bypasses the daily publication limit. It never reuses an
    already published catalog entry, because duplicate topics are a critical
    quality failure.
    """

    published_today = state.published_today()
    if published_today >= profile.max_articles_per_day and not force:
        return QueueSelection(
            entry=None,
            reason=(
                f"오늘 이미 {published_today}개를 발행했습니다 "
                f"(일일 한도 {profile.max_articles_per_day}개)."
            ),
            published_today=published_today,
        )

    used = published_catalog_ids(state)
    candidates = [
        entry
        for entry in catalog.active_entries()
        if entry.id not in used
    ]
    if not candidates:
        return QueueSelection(
            entry=None,
            reason="발행하지 않은 활성 카탈로그 항목이 없습니다. 새 항목을 추가해야 합니다.",
            published_today=published_today,
            unused_count=0,
        )

    signals = list(signals)
    ranked = sorted(
        candidates,
        key=lambda entry: (
            -_signal_score(entry, signals),
            entry.last_reviewed or "0000-00-00",
            entry.id,
        ),
    )
    chosen = ranked[0]
    reason = "카탈로그에서 아직 발행하지 않은 항목을 선택했습니다."
    if signals and _signal_score(chosen, signals) > 0:
        reason = "최근 주제 신호와 일치하는 카탈로그 항목을 우선 선택했습니다."
    return QueueSelection(
        entry=chosen,
        reason=reason,
        published_today=published_today,
        unused_count=len(candidates),
    )
