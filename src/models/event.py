from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.models.source import EntityRef, utc_now_iso

EventStatus = Literal[
    "detected",
    "researching",
    "analyzing",
    "verified",
    "published",
    "rejected",
    "failed",
]


class EventReason(BaseModel):
    code: str
    label: str
    score_contribution: int = 0
    detail: str = ""


class Event(BaseModel):
    """표준 이벤트 모델. 상태 머신으로 관리되어 실행 실패 시 재개 가능."""

    event_id: str
    event_type: str
    entity: EntityRef
    detected_at: str = Field(default_factory=utc_now_iso)
    event_date: str | None = None
    event_score: int = 0
    evidence_score: int = 0
    publication_type: str = ""   # A(Deep) | B(Data Brief) | C(Reject)
    reasons: list[EventReason] = Field(default_factory=list)
    related_sources: list[str] = Field(default_factory=list)
    status: EventStatus = "detected"
    evidence: dict = Field(default_factory=dict)
    summary: str = ""

    @property
    def ticker(self) -> str | None:
        return self.entity.ticker

    def update_score(self, score: int) -> None:
        self.event_score = score

    def set_evidence(self, evidence_score: int, publication_type: str) -> None:
        self.evidence_score = evidence_score
        self.publication_type = publication_type

    def add_reason(self, reason: EventReason) -> None:
        self.reasons.append(reason)
        self.event_score += reason.score_contribution

    def set_status(self, status: EventStatus) -> None:
        self.status = status

    def rows_key(self) -> tuple[str, str]:
        """중복 판단용 키: (entity,ticker) + event_type + date"""
        return (self.entity.name or self.entity.ticker or "", self.event_type, self.event_date or self.detected_at[:10])