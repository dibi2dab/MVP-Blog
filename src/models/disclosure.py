from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.models.source import utc_now_iso

DisclosureImportance = Literal["VERY_HIGH", "HIGH", "MEDIUM", "LOW", "IGNORE"]


class Disclosure(BaseModel):
    """기업 공시 항목 (DART 정규화 결과)."""

    title: str
    importance: DisclosureImportance = "LOW"
    summary: str = ""
    possible_market_impact: str = ""
    requires_deep_research: bool = False
    source_id: str = Field(default="")
    url: str = Field(default="")
    published_at: str = Field(default="")
    rcept_no: str = Field(default="")  # DART 접수번호 = 원본 식별자
    corp_code: str = Field(default="")
    corp_name: str = Field(default="")
    report_name: str = Field(default="")
    collected_at: str = Field(default_factory=utc_now_iso)

    @property
    def content_hash(self) -> str:
        import hashlib

        base = f"{self.rcept_no}|{self.corp_code}|{self.title}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()


class DisclosureAnalysis(BaseModel):
    """공시 분석 결과."""

    title: str
    importance: DisclosureImportance
    summary: str
    possible_market_impact: str
    requires_deep_research: bool
    source_id: str
    confidence: float = Field(default=0.9)