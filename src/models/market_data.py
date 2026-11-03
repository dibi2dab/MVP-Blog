from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.source import Source, utc_now_iso


class DailyPriceBar(BaseModel):
    """주식 일봉 데이터."""

    date: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    volume: int = 0
    amount: float | None = None  # 거래대금 (KRW)
    change_pct: float | None = None


class PriceSeries(BaseModel):
    ticker: str
    name: str
    currency: str = "KRW"
    bars: list[DailyPriceBar] = Field(default_factory=list)
    fetched_at: str = Field(default_factory=utc_now_iso)
    source_id: str = ""

    @property
    def latest_close(self) -> float | None:
        return self.bars[-1].close if self.bars else None

    @property
    def prev_close(self) -> float | None:
        return self.bars[-2].close if len(self.bars) > 1 else None

    @property
    def latest_change_pct(self) -> float | None:
        if self.latest_close is None or self.prev_close is None or self.prev_close == 0:
            return None
        return (self.latest_close - self.prev_close) / self.prev_close

    @property
    def latest_volume(self) -> int:
        return self.bars[-1].volume if self.bars else 0

    def avg_volume(self, window: int) -> float | None:
        """window 일(직전 window 일, 오늘 제외) 평균 거래량."""
        if len(self.bars) <= window:
            return None
        chunk = self.bars[-(window + 1):-1]
        if not chunk:
            return None
        return sum(b.volume for b in chunk) / len(chunk)

    def percentile_high(self, window: int) -> bool:
        """오늘 종가가 최근 window 일 중 최고가면 True."""
        if len(self.bars) < window:
            return False
        chunk = self.bars[-window:]
        latest = chunk[-1]
        return latest.close == max(b.high or b.close for b in chunk)

    def percentile_low(self, window: int) -> bool:
        if len(self.bars) < window:
            return False
        chunk = self.bars[-window:]
        latest = chunk[-1]
        return latest.close == min(b.low or b.close for b in chunk)

    def to_daily_change_map(self) -> dict[str, float]:
        return {b.date: (b.change_pct or 0.0) for b in self.bars}


class MarketSnapshot(BaseModel):
    """특정 종목의 수집 시점 스냅샷. 이벤트 감지의 1차 입력."""

    ticker: str
    name: str
    price_series: PriceSeries
    foreign_net_buy: float | None = None
    institution_net_buy: float | None = None
    generated_at: str = Field(default_factory=utc_now_iso)
    source_id: str = Field(default="")

    def to_event_evidence(self) -> dict:
        return {
            "latest_change_pct": self.price_series.latest_change_pct,
            "volume_ratio": self.volume_ratio,
            "avg_volume": self.avg_volume,
            "new_high": self.new_high,
            "new_low": self.new_low,
            "gap_up": self.gap_up,
            "gap_down": self.gap_down,
        }

    @property
    def latest_change_pct(self) -> float | None:
        return self.price_series.latest_change_pct

    @property
    def latest_volume(self) -> int:
        return self.price_series.latest_volume

    @property
    def avg_volume(self) -> float | None:
        """전체 일봉 갯수 대비 기준 평균 거래량(최소 5일)."""
        return self.price_series.avg_volume(max(5, min(20, len(self.price_series.bars) // 2)))

    @property
    def volume_ratio(self) -> float | None:
        avg = self.avg_volume
        if not avg or avg <= 0:
            return None
        return self.latest_volume / avg

    @property
    def new_high(self) -> bool:
        return self.price_series.percentile_high(window=60)

    @property
    def new_low(self) -> bool:
        return self.price_series.percentile_low(window=60)

    @property
    def gap(self) -> float | None:
        """오늘 시가 대비 전일 종가 변화율 (갭)"""
        if len(self.price_series.bars) < 2:
            return None
        today, prev = self.price_series.bars[-1], self.price_series.bars[-2]
        if not today.open or not prev.close:
            return None
        return (today.open - prev.close) / prev.close

    @property
    def gap_up(self) -> bool:
        g = self.gap
        return g is not None and g >= 0.03

    @property
    def gap_down(self) -> bool:
        g = self.gap
        return g is not None and g <= -0.03


class SnapshotCollection(BaseModel):
    snapshots: list[MarketSnapshot] = Field(default_factory=list)
    collected_at: str = Field(default_factory=utc_now_iso)

    def by_ticker(self, ticker: str) -> MarketSnapshot | None:
        for s in self.snapshots:
            if s.ticker == ticker:
                return s
        return None