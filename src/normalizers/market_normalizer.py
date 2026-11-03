from __future__ import annotations

from datetime import datetime, timezone

from src.collectors.base import RawRecord
from src.models.market_data import DailyPriceBar, MarketSnapshot, PriceSeries

KST_OFFSET = 9 * 3600  # Asia/Seoul = UTC+9


class PriceSeriesNormalizer:
    def normalize(self, record: RawRecord) -> MarketSnapshot | None:
        data = record.data
        ticker = record.metadata.get("ticker", "")
        name = record.metadata.get("name", "")
        if not ticker or not data.get("bars"):
            return None
        bars = [
            DailyPriceBar(
                date=b["date"],
                open=b.get("open"),
                high=b.get("high"),
                low=b.get("low"),
                close=b["close"],
                volume=b.get("volume", 0),
                amount=b.get("amount"),
                change_pct=b.get("change_pct"),
            )
            for b in data.get("bars", [])
        ]
        series = PriceSeries(
            ticker=ticker,
            name=name,
            currency=data.get("currency", "KRW"),
            bars=bars,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            source_id=record.source_id,
        )
        return MarketSnapshot(
            ticker=ticker,
            name=name,
            price_series=series,
            foreign_net_buy=data.get("foreign_net_buy"),
            institution_net_buy=data.get("institution_net_buy"),
            source_id=record.source_id,
        )


class NewsRecordNormalizer:
    def normalize(self, record: RawRecord) -> "NewsItem | None":
        from src.models.news import NewsItem

        data = record.data
        try:
            return NewsItem.model_validate(data)
        except Exception:
            return None


class DisclosureRecordNormalizer:
    def normalize(self, record: RawRecord) -> "Disclosure | None":
        from src.models.disclosure import Disclosure

        data = record.data
        try:
            return Disclosure.model_validate(
                {
                    **data,
                    "source_id": record.source_id,
                    "url": data.get("url", ""),
                    "published_at": data.get("published_at", ""),
                }
            )
        except Exception:
            return None