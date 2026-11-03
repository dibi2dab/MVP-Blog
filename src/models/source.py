from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    NEWS = "news"
    DISCLOSURE = "disclosure"
    STOCK_PRICE = "stock_price"
    ECONOMY = "economy"
    REALESTATE = "realestate"
    RESEARCH = "research"
    OTHER = "other"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Source(BaseModel):
    """출처 모델. 모든 중요한 정보는 source_id 로 이 객체에 연결된다."""

    source_id: str
    name: str
    type: str
    url: str | None = None
    published_at: str | None = None
    accessed_at: str = Field(default_factory=utc_now_iso)
    original_id: str | None = None

    @property
    def display(self) -> str:
        return f"{self.name} ({self.published_at or self.accessed_at})"


class EntityRef(BaseModel):
    name: str
    ticker: str | None = None
    entity_type: str = "corp"
    extra: dict[str, Any] = Field(default_factory=dict)