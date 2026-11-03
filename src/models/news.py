from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.source import utc_now_iso


class NewsItem(BaseModel):
    """정규화된 뉴스 항목."""

    title: str
    published_at: str
    source: str
    url: str
    summary: str = ""
    entities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)
    collected_at: str = Field(default_factory=utc_now_iso)
    source_id: str = Field(default="")
    original_id: str = Field(default="")

    @property
    def content_hash(self) -> str:
        import hashlib

        base = (self.title or "").strip().lower()
        return hashlib.sha1(base.encode("utf-8")).hexdigest()


class NewsCluster(BaseModel):
    """같은 사건을 다루는 뉴스 그룹 (교차 검증용)."""

    cluster_id: str
    headline: str
    items: list[NewsItem] = Field(default_factory=list)
    source_count: int = 0
    first_published: str = ""
    last_published: str = ""

    @property
    def n_items(self) -> int:
        return len(self.items)

    @property
    def unique_sources(self) -> set[str]:
        return {i.source for i in self.items}

    def sorted_items(self) -> list[NewsItem]:
        return sorted(self.items, key=lambda x: x.published_at, reverse=True)