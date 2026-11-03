from __future__ import annotations

from src.detectors.stock_detector import StockDetector

PARAM = [
    ("snap", [0.0] * 25 + [0.11], [1000] * 25 + [4000], "stock_surge"),
    ("snap", [0.0] * 25 + [-0.12], [1000] * 25 + [4000], "stock_crash"),
]


class TestStockDetector:
    def test_surge_detected(self, settings, sample_snapshot):
        detector = StockDetector(settings, existing_events=[])
        events = detector.detect_from(sample_snapshot)
        assert len(events) == 1
        assert events[0].event_type in ("stock_surge", "stock_breakout")
        assert events[0].event_score >= 5

    def test_duplicate_suppressed(self, settings, sample_snapshot):
        detector = StockDetector(settings, existing_events=[])
        first = detector.detect_from(sample_snapshot)
        detector2 = StockDetector(settings, existing_events=first)
        second = detector2.detect_from(sample_snapshot)
        assert len(second) == 0

    def test_flat_market_no_event(self, settings):
        from src.models.market_data import DailyPriceBar, MarketSnapshot, PriceSeries

        bars = [DailyPriceBar(date=f"2026-08-{i:02d}", close=100.0, volume=1000) for i in range(1, 31)]
        series = PriceSeries(ticker="T", name="T", currency="KRW", bars=bars)
        snap = MarketSnapshot(ticker="T", name="T", price_series=series)
        detector = StockDetector(settings, existing_events=[])
        assert detector.detect_from(snap) == []