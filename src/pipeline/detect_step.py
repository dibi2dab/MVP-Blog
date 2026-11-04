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

        # 개별 종목이 하루에 5% 이상 움직였다면 점수 조합과 무관하게 분석 가치가 있다.
        # (거래량 급증 없이 가격만 크게 움직인 날에도 데이터 기사가 나올 수 있도록 한다.
        #  뉴스/공시 이벤트에는 적용하지 않아 일반 헤드라인 유입을 막는다.)
        if event.event_type in ("stock_surge", "stock_crash", "stock_breakout", "price_event"):
            change = (event.evidence or {}).get("latest_change_pct")
            if change is not None and abs(float(change)) >= self.settings.detection.price_change_mid_threshold:
                return True

        # disclosure 이벤트는 score < threshold 여도 중요 공시면 통과
        if event.event_type in ("disclosure", "earnings") and any(
            d.requires_deep_research for d in disclosures if d.source_id in event.related_sources or d.corp_name == event.entity.name
        ):
            return True
        return False