from __future__ import annotations

import json
import random
from datetime import datetime, timedelta

from src.collectors.base import BaseCollector, RawRecord
from src.config.settings import Settings
from src.models.market_data import MarketSnapshot, PriceSeries, DailyPriceBar, SnapshotCollection
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MockStockCollector(BaseCollector):
    """API 키 없이 파이프라인을 시뮬레이션하는 Mock 주가 수집기."""

    source_id = "mock.stock"
    source_name = "Mock Stock Feed"
    source_type = "stock_price"

    def __init__(self, settings: Settings, seed: int | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.rng = random.Random(seed)
        self.days = min(90, settings.sources_raw.get("stocks", {}).get("price", {}).get("period_count", 90))

    def _gen_series(self, code: str, name: str) -> PriceSeries:
        today = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
        base = self.rng.choice([5000, 15000, 40000, 120000, 350000])
        trend = self.rng.uniform(-0.002, 0.002)
        trading_days = [
            d
            for i in range(self.days - 1, -1, -1)
            for d in [today - timedelta(days=i)]
            if d.weekday() < 5  # 주말 날짜 제외한 실거래일
        ]
        if not trading_days:
            trading_days = [today]
        # 돌발 변동(이벤트)을 가장 최근 거래일에 배치해 감지가 가능하도록 한다.
        spike = self.rng.random() < 0.6
        last_drift = self.rng.choice([0.13, -0.135, 0.08, -0.08]) if spike else self.rng.uniform(-0.02, 0.02)
        bars: list[DailyPriceBar] = []
        price = float(base)
        for idx, d in enumerate(trading_days):
            is_last = idx == len(trading_days) - 1
            if is_last:
                drift = last_drift
            else:
                drift = self.rng.uniform(-0.02, 0.02) + trend
            prev = price
            price = max(1000, price * (1 + drift))
            open_p = prev * (1 + self.rng.uniform(-0.008, 0.008))
            high = max(open_p, price) * (1 + self.rng.uniform(0, 0.01))
            low = min(open_p, price) * (1 - self.rng.uniform(0, 0.01))
            avg_vol = int(500_000 + self.rng.uniform(0, 1_500_000))
            if is_last and spike:
                vol = int(avg_vol * self.rng.uniform(3.5, 5.5))
            else:
                vol = int(avg_vol * self.rng.uniform(0.6, 1.2))
            bars.append(
                DailyPriceBar(
                    date=d.strftime("%Y-%m-%d"),
                    open=round(open_p, 1),
                    high=round(high, 1),
                    low=round(low, 1),
                    close=round(price, 1),
                    volume=vol,
                    amount=round(vol * price, 0),
                    change_pct=round(((price - prev) / prev * 100) if prev else 0.0, 2),
                )
            )
        bars.sort(key=lambda b: b.date)
        return PriceSeries(
            ticker=code,
            name=name,
            currency="KRW",
            bars=bars,
            source_id="mock.stock",
        )

    def collect(self) -> list[RawRecord]:
        records: list[RawRecord] = []
        for item in self.settings.stocks_universe:
            series = self._gen_series(item.code, item.name)
            records.append(
                self.make_record(
                    data_type="price_series",
                    data=series.model_dump(),
                    original_url="mock://stock",
                    metadata={"ticker": item.code, "name": item.name},
                )
            )
        self.logger.info("mock collected %d stock series", len(records))
        return records

    def build_snapshot(self) -> SnapshotCollection:
        snapshots: list[MarketSnapshot] = []
        for item in self.settings.stocks_universe:
            series = self._gen_series(item.code, item.name)
            snapshots.append(
                MarketSnapshot(
                    ticker=item.code,
                    name=item.name,
                    price_series=series,
                    foreign_net_buy=float(self.rng.randint(-50_000, 50_000)),
                    institution_net_buy=float(self.rng.randint(-50_000, 50_000)),
                    source_id="mock.stock",
                )
            )
        return SnapshotCollection(snapshots=snapshots)