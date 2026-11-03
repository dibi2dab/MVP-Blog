from __future__ import annotations

from src.config.settings import Settings
from src.detectors.disclosure_detector import DisclosureDetector
from src.detectors.news_detector import NewsDetector
from src.detectors.stock_detector import StockDetector
from src.models.disclosure import Disclosure
from src.models.event import Event
from src.models.market_data import SnapshotCollection
from src.models.news import NewsItem
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DetectStep:
    """Phase 1: 이벤트 감지 + 점수 + 분석 대상 선정."""

    def __init__(self, settings: Settings, store: JsonStore) -> None:
        self.settings = settings
        self.store = store

    def run(
        self,
        snapshots: SnapshotCollection,
        news_items: list[NewsItem],
        disclosures: list[Disclosure],
    ) -> list[Event]:
        existing = self.store.load_all_events()
        logger.info("[detect] %d existing events loaded", len(existing))

        events: list[Event] = []

        stock_detector = StockDetector(self.settings, existing_events=existing)
        stock_events = stock_detector.detect(snapshots)
        logger.info("[detect] %d stock events detected", len(stock_events))
        events.extend(stock_events)

        if disclosures:
            disc_detector = DisclosureDetector(self.settings, existing_events=existing)
            classified = disc_detector.classify_disclosures(disclosures)
            disc_events = disc_detector.detect(classified)
            logger.info("[detect] %d disclosure events detected", len(disc_events))
            events.extend(disc_events)

        if news_items:
            news_detector = NewsDetector(self.settings, existing_events=existing)
            news_events = news_detector.detect(news_items)
            logger.info("[detect] %d news events detected", len(news_events))
            events.extend(news_events)

        selected: list[Event] = []
        for event in events:
            if not self._is_research_worthy(event, snapshots, disclosures):
                event.set_status("rejected")
                self.store.save_event(event)
                logger.info("[detect] rejected event %s score=%d", event.event_id, event.event_score)
                continue
            selected.append(event)
            self.store.save_event(event)
            logger.info(
                "[detect] selected event %s (%s/%s) score=%d",
                event.event_id,
                event.entity.name,
                event.event_type,
                event.event_score,
            )
        return selected

    def _is_research_worthy(
        self,
        event: Event,
        snapshots: SnapshotCollection,
        disclosures: list[Disclosure],
    ) -> bool:
        if event.event_score >= self.settings.scoring.minimum_research_score:
            return True
        # disclosure 이벤트는 score < threshold 여도 중요 공시면 통과
        if event.event_type in ("disclosure", "earnings") and any(
            d.requires_deep_research for d in disclosures if d.source_id in event.related_sources or d.corp_name == event.entity.name
        ):
            return True
        return False