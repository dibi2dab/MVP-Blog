from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import datetime

from src.models.news import NewsItem

MAX_TITLE_SIMILARITY = 0.9


def normalize_title(title: str) -> str:
    """제목 유사도 비교 전 정규화 (특수문자/공백 제거, 소문자)."""
    import re

    s = title.strip().lower()
    s = re.sub(r"[^\w가-힣]", "", s)
    return s


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


@dataclass
class DedupDecision:
    is_duplicate: bool
    kept: NewsItem | None
    reason: str = ""


def is_duplicate_news(new: NewsItem, existing: list[NewsItem], threshold: float = 0.85) -> DedupDecision:
    """URL / 제목 유사도 / 발행 시간 근접 뉴스를 중복으로 판정."""
    for ex in existing:
        if new.url and ex.url and new.url.rstrip("/") == ex.url.rstrip("/"):
            return DedupDecision(True, ex, reason=f"same url: {new.url}")
        sim = title_similarity(new.title, ex.title)
        if sim >= threshold:
            t1 = _parse_ts(new.published_at)
            t2 = _parse_ts(ex.published_at)
            if t1 and t2 and abs((t1 - t2).total_seconds()) <= 12 * 3600:
                return DedupDecision(True, ex, reason=f"title sim={sim:.2f} near {ex.published_at}")
            if sim >= MAX_TITLE_SIMILARITY:
                return DedupDecision(True, ex, reason=f"title sim={sim:.2f}")
    return DedupDecision(False, None)


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


class NewsDeduper:
    """뉴스 중복 제거 + NewsCluster 생성."""

    def __init__(self, title_threshold: float = 0.85, cluster_tolerance_hours: float = 2.0) -> None:
        self.title_threshold = title_threshold
        self.cluster_tolerance_hours = cluster_tolerance_hours

    def dedupe(self, items: list[NewsItem]) -> list[NewsItem]:
        keep: list[NewsItem] = []
        for item in sorted(items, key=lambda x: x.published_at, reverse=True):
            decision = is_duplicate_news(item, keep, self.title_threshold)
            if not decision.is_duplicate:
                keep.append(item)
        return sorted(keep, key=lambda x: x.published_at)

    def cluster(self, items: list[NewsItem]) -> list[dict]:
        """같은 사건 그룹(cluster) 생성. 중심 뉴스 1개 + 유사 뉴스 묶음."""
        clusters: list[dict] = []
        seen = set()
        for item in sorted(items, key=lambda x: x.published_at):
            if item.content_hash in seen:
                continue
            seen.add(item.content_hash)
            members = []
            for other in items:
                if other.content_hash in seen or other.content_hash == item.content_hash:
                    continue
                if title_similarity(item.title, other.title) >= self.title_threshold:
                    members.append(other)
                    seen.add(other.content_hash)
            cluster = {
                "cluster_id": item.content_hash[:12],
                "headline": item.title,
                "items": [item] + members,
                "source_count": len({i.source for i in [item] + members}),
                "first_published": min(i.published_at for i in [item] + members),
                "last_published": max(i.published_at for i in [item] + members),
            }
            clusters.append(cluster)
        return clusters