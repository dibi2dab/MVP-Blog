from __future__ import annotations

import hashlib
from datetime import datetime

from src.config.settings import Settings
from src.detectors.base import BaseDetector
from src.models.event import Event, EventReason
from src.models.market_data import MarketSnapshot, SnapshotCollection
from src.models.source import EntityRef
from src.scoring.event_scoring import DETECTION_REASONS, DetectionResult, EventScorer


def _event_id(ticker: str, event_type: str, date: str) -> str:
    raw = f"{ticker}|{event_type}|{date}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


class StockDetector(BaseDetector):
    """주가/거래량 감지. 감지 전에 이미 보유한 이벤트와 중복 판단."""

    name = "stock"

    def __init__(self, settings: Settings, existing_events: list[Event] | None = None) -> None:
        self.settings = settings
        self.scorer = EventScorer(settings)
        self.existing_events = existing_events or []

    def detect(self, snapshots: SnapshotCollection) -> list[Event]:
        results = [self.scorer.score_snapshot(s) for s in snapshots.snapshots]
        selected = self.scorer.select_for_research(results)
        events: list[Event] = []
        for result in selected:
            event = self._build_event(result)
            if self._is_duplicate(event.event_id):
                continue
            events.append(event)
        return events

    def detect_from(self, snapshot: MarketSnapshot) -> list[Event]:
        return self.detect(SnapshotCollection(snapshots=[snapshot]))

    def all_detections(self, snapshots: SnapshotCollection) -> list[DetectionResult]:
        return [self.scorer.score_snapshot(s) for s in snapshots.snapshots]

    def _build_event(self, result: DetectionResult) -> Event:
        score = self.scorer.total_score(result)
        main_type = "price_event"
        up_reasons = [c for c, _ in result.reasons if c.startswith("price_up")]
        down_reasons = [c for c, _ in result.reasons if c.startswith("price_down")]
        if up_reasons and not down_reasons:
            main_type = "stock_surge"
        elif down_reasons and not up_reasons:
            main_type = "stock_crash"
        elif any(c in result.reasons for c in ("new_high", "gap_up")):
            main_type = "stock_breakout"

        reasons: list[EventReason] = [
            EventReason(code=code, label=DETECTION_REASONS.get(code, code), score_contribution=s)
            for code, s in result.reasons
        ]
        return Event(
            event_id=_event_id(result.ticker, main_type, result.event_date or ""),
            event_type=main_type,
            entity=EntityRef(name=result.name, ticker=result.ticker),
            event_date=result.event_date,
            event_score=score,
            reasons=reasons,
            evidence=result.evidence,
            summary=f"{result.name} 주가 변동 {result.evidence.get('latest_change_pct', '?')}% / 거래량 비율 {result.evidence.get('volume_ratio', '?')}",
            status="detected",
        )

    def _is_duplicate(self, event_id: str) -> bool:
        for ex in self.existing_events:
            if ex.event_id == event_id and ex.status not in ("rejected", "failed"):
                return True
        return False

    def score_known(self, snapshot, event_type: str) -> int:
        return self.scorer.total_score(self.scorer.score_snapshot(snapshot))