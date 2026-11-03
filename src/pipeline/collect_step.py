from __future__ import annotations

from src.collectors.collectors import Collectors
from src.config.settings import Settings
from src.models.market_data import SnapshotCollection
from src.models.news import NewsItem
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger

logger = get_logger(__name__)


class CollectStep:
    """Phase 1: 시장 데이터 / 뉴스 / 공시 수집."""

    def __init__(self, settings: Settings, store: JsonStore) -> None:
        self.settings = settings
        self.store = store

    def run(self) -> dict:
        collectors = Collectors(self.settings)
        stock = collectors.stock()
        logger.info("[collect] collecting stock data")
        snapshots = self._collect_stock(stock)
        logger.info("[collect] %d stock snapshots collected", len(snapshots.snapshots))

        news = collectors.news()
        logger.info("[collect] collecting news")
        news_items = self._collect_news(news)
        logger.info("[collect] %d news items collected", len(news_items))

        disclosures = []
        for dc in collectors.disclosures():
            logger.info("[collect] collecting disclosures via %s", dc.source_id)
            raw = dc.collect_pipeline()[1]
            from src.models.disclosure import Disclosure

            discussions = []
            for r in raw:
                # raw 은 normalizer 가 없으면 RawRecord 임 -> 직접 변환
                from src.normalizers.market_normalizer import DisclosureRecordNormalizer

                item = DisclosureRecordNormalizer().normalize(r)
                if item:
                    disclosures.append(item)
            logger.info("[collect] %d disclosure items", len(disclosures))
        return {
            "snapshots": snapshots,
            "news_items": news_items,
            "disclosures": disclosures,
        }

    def _collect_stock(self, collector) -> SnapshotCollection:
        snapshots = collector.build_snapshot()
        self.store.save_snapshots(snapshots)
        self.store.save_individual_snapshot(snapshots)
        return snapshots

    def _collect_news(self, collector) -> list[NewsItem]:
        from src.normalizers.market_normalizer import NewsRecordNormalizer

        records = collector.collect()
        items: list[NewsItem] = []
        normalizer = NewsRecordNormalizer()
        for record in records:
            item = normalizer.normalize(record)
            if item:
                items.append(item)
        self.store.save_raw("news", {"items": [i.model_dump() for i in items]})
        return items