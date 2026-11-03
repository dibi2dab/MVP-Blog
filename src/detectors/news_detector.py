from __future__ import annotations

import hashlib

from src.config.settings import Settings
from src.detectors.base import BaseDetector
from src.models.event import Event, EventReason
from src.models.news import NewsItem
from src.models.source import EntityRef, utc_now_iso

_BIG_KEYWORDS = ["인수", "매각", "합병", "상장", "유증", "공급계약", "수주", "검찰", "사퇴"]


class NewsDetector(BaseDetector):
    """뉴스 기반 이벤트. 키워드 기반 대형 뉴스 감지 (AI 비용 절감)."""

    name = "news"

    def __init__(self, settings: Settings, existing_events: list[Event] | None = None) -> None:
        self.settings = settings
        self.existing_events = existing_events or []

    def detect(self, news_items: list[NewsItem]) -> list[Event]:
        events: list[Event] = []
        for item in news_items:
            score = self._score_title(item.title)
            if score <= 0:
                continue
            entity = self._guess_entity(item)
            event_id = self._event_id(item)
            if self._is_duplicate(event_id):
                continue
            events.append(
                Event(
                    event_id=event_id,
                    event_type="news_event",
                    entity=entity,
                    event_date=item.published_at[:10] if item.published_at else None,
                    event_score=score,
                    reasons=[
                        EventReason(
                            code="news_high",
                            label=f"뉴스: {item.title[:50]}",
                            score_contribution=score,
                            detail="대형 이슈 키워드 감지",
                        )
                    ],
                    related_sources=[item.source_id] if item.source_id else [],
                    evidence={"url": item.url, "title": item.title},
                    summary=f"뉴스: {item.title}",
                    status="detected",
                )
            )
        return events

    def _score_title(self, title: str) -> int:
        if any(k in title for k in _BIG_KEYWORDS):
            return 4
        return 0

    def _guess_entity(self, item: NewsItem) -> EntityRef:
        name = item.entities[0] if item.entities else item.title[:20]
        return EntityRef(name=name, ticker=None)

    def _event_id(self, item: NewsItem) -> str:
        entity = item.entities[0] if item.entities else item.title[:20]
        base = f"news|{entity}|{item.published_at[:10]}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

    def _is_duplicate(self, event_id: str) -> bool:
        for ex in self.existing_events:
            if ex.event_id == event_id and ex.status not in ("rejected", "failed"):
                return True
        return False