from __future__ import annotations

from src.analysis.quant_metrics import compute_quant_metrics, detect_patterns
from src.models.event import Event
from src.models.research_packet import ResearchPacket
from src.models.source import EntityRef


def _packet(snapshot) -> ResearchPacket:
    event = Event(
        event_id="e1",
        event_type="stock_surge",
        entity=EntityRef(name=snapshot.name, ticker=snapshot.ticker),
        event_date=snapshot.price_series.bars[-1].date,
    )
    return ResearchPacket(event=event, entity=event.entity, market_data=snapshot)


class TestQuantMetrics:
    def test_computes_independent_metrics(self, sample_snapshot):
        metrics = compute_quant_metrics(_packet(sample_snapshot))

        assert metrics.latest_date == sample_snapshot.price_series.bars[-1].date
        assert metrics.change_pct is not None
        assert metrics.volume_ratio is not None and metrics.volume_ratio > 1.5
        assert metrics.ma20 is not None
        assert metrics.distance_ma20_pct is not None
        assert len(metrics.available_metrics()) >= 4

    def test_volume_zscore_with_varied_history(self):
        from src.models.market_data import DailyPriceBar, MarketSnapshot, PriceSeries

        bars = []
        for i in range(30):
            volume = 800_000 + (i % 5) * 120_000
            bars.append(
                DailyPriceBar(
                    date=f"2026-08-{i + 1:02d}",
                    open=50_000,
                    high=51_000,
                    low=49_000,
                    close=50_000,
                    volume=volume,
                    amount=volume * 50_000,
                    change_pct=((i % 5) - 2) * 0.5,
                )
            )
        bars.append(
            DailyPriceBar(
                date="2026-09-01",
                open=50_500,
                high=53_000,
                low=50_000,
                close=52_500,
                volume=3_000_000,
                amount=3_000_000 * 52_500,
                change_pct=5.0,
            )
        )
        series = PriceSeries(ticker="000000", name="테스트종목", bars=bars)
        snapshot = MarketSnapshot(ticker="000000", name="테스트종목", price_series=series)

        metrics = compute_quant_metrics(_packet(snapshot))

        assert metrics.volume_zscore is not None and metrics.volume_zscore > 2.0
        assert metrics.return_zscore is not None

    def test_handles_missing_price_data(self):
        event = Event(event_id="e2", event_type="stock_surge", entity=EntityRef(name="없음"))
        metrics = compute_quant_metrics(ResearchPacket(event=event, entity=event.entity))

        assert metrics.data_quality == "없음"
        assert metrics.available_metrics() == {}

    def test_detects_volume_and_price_patterns(self, sample_snapshot):
        metrics = compute_quant_metrics(_packet(sample_snapshot))
        patterns = detect_patterns(metrics, has_cause_news=False, has_cause_disclosure=False)

        codes = {p.code for p in patterns}
        assert "volume_spike" in codes
        assert "volume_price_relation" in codes
        assert all(p.interpretation and p.limitation and p.confirmation for p in patterns)
