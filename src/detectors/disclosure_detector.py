from __future__ import annotations

import hashlib
import re
from datetime import datetime

from src.config.settings import Settings
from src.detectors.base import BaseDetector
from src.models.disclosure import Disclosure
from src.models.event import Event, EventReason
from src.models.source import EntityRef, utc_now_iso

_IMPORTANT_KEYWORDS = [
    "유상증자",
    "무상증자",
    "전환사채",
    "신주인수권부사채",
    "합병",
    "분할",
    "자사주",
    "최대주주",
    "소송",
    "상장폐지",
    "영업(잠정)",
    "영업잠정",
    "공급계약",
    "수주",
]


class DisclosureClassifier:
    """공시 중요도 자동 분류. Python 규칙 기반으로 AI 비용 사용하지 않음."""

    def classify(self, title: str) -> str:
        t = re.sub(r"\s+", "", title)
        if any(k in t for k in ("영업(잠정)", "영업잠정", "영업실적")):
            return "HIGH"
        if any(k in t for k in ("유상증자", "무상증자", "합병", "전환사채", "신주인수권부사채")):
            return "VERY_HIGH"
        if any(k in t for k in ("최대주주", "상장폐지", "자사주", "공급계약")):
            return "HIGH"
        if any(k in t for k in ("소송", "분할", "수주")):
            return "MEDIUM"
        if "기타시장" in t or "단순변경" in t:
            return "IGNORE"
        return "LOW"


def _did(ticker: str, rcept_no: str) -> str:
    raw = f"{ticker}|{rcept_no or 'na'}|disclosure".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


class DisclosureDetector(BaseDetector):
    """공시 이벤트 감지."""

    name = "disclosure"

    def __init__(self, settings: Settings, existing_events: list[Event] | None = None) -> None:
        self.settings = settings
        self.classifier = DisclosureClassifier()
        self.existing_events = existing_events or []

    def classify_disclosures(self, items: list[Disclosure]) -> list[Disclosure]:
        """공시를 정규화하고 중요도 자동 분류."""
        out = []
        for d in items:
            importance = self.classifier.classify(d.title)
            d.importance = importance
            d.requires_deep_research = importance in ("VERY_HIGH", "HIGH")
            out.append(d)
        return out

    def detect(self, disclosures: list[Disclosure]) -> list[Event]:
        events: list[Event] = []
        for d in disclosures:
            importance_score = {
                "VERY_HIGH": 5,
                "HIGH": 5,
                "MEDIUM": 2,
                "LOW": 0,
                "IGNORE": -1,
            }.get(d.importance, 0)
            if importance_score <= 0:
                continue
            event_id = _did(d.corp_code, d.rcept_no)
            if self._is_duplicate(event_id):
                continue
            event_type = "disclosure"
            if "영업" in d.title:
                event_type = "earnings"
            events.append(
                Event(
                    event_id=event_id,
                    event_type=event_type,
                    entity=EntityRef(name=d.corp_name or d.title, ticker="@disclosure"),
                    event_date=d.published_at[:10] if d.published_at else None,
                    event_score=importance_score,
                    reasons=[
                        EventReason(
                            code=f"disclosure_{d.importance}",
                            label=f"공시({d.importance}): {d.title[:40]}",
                            score_contribution=importance_score,
                            detail=d.summary,
                        )
                    ],
                    related_sources=[d.source_id] if d.source_id else [],
                    evidence={"rcept_no": d.rcept_no, "title": d.title},
                    summary=f"공시: {d.title}",
                    status="detected",
                )
            )
        return events

    def _is_duplicate(self, event_id: str) -> bool:
        for ex in self.existing_events:
            if ex.event_id == event_id and ex.status not in ("rejected", "failed"):
                return True
        return False