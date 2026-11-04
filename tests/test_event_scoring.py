from __future__ import annotations

from src.scoring.event_scoring import EventScorer
from src.models.market_data import DailyPriceBar, MarketSnapshot, PriceSeries


def _make_snapshot(changes: list[float], volumes: list[int]) -> MarketSnapshot:
    price = 10000.0
    bars = []
    for i, chg in enumerate(changes):
        price = round(price * (1 + chg), 2)
        bars.append(
            DailyPriceBar(
                date=f"2026-08-{10+i:02d}",
                close=price,
                volume=volumes[i],
                change_pct=round(chg * 100, 2),
            )
        )
    return MarketSnapshot(
        ticker="000001",
        name="T",
        price_series=PriceSeries(ticker="000001", name="T", currency="KRW", bars=bars),
    )


class TestEventScoring:
    def test_mild_no_event(self, settings):
        changes = [0.0] * 25 + [0.001]
        vols = [1000] * 25 + [1000]
        snap = _make_snapshot(changes, vols)
        scorer = EventScorer(settings)
        res = scorer.score_snapshot(snap)
        assert scorer.total_score(res) == 0

    def test_high_change_gets_score(self, settings):
        changes = [0.0] * 25 + [0.11]
        vols = [1000] * 25 + [1000]
        snap = _make_snapshot(changes, vols)
        scorer = EventScorer(settings)
        res = scorer.score_snapshot(snap)
        assert scorer.total_score(res) >= 5

    def test_volume_surge_score(self, settings):
        changes = [0.0] * 25 + [0.02]
        vols = [1000] * 25 + [4000]
        snap = _make_snapshot(changes, vols)
        scorer = EventScorer(settings)
        res = scorer.score_snapshot(snap)
        assert scorer.total_score(res) >= 4

    def test_combined_score(self, settings):
        changes = [0.0] * 25 + [0.11]
        vols = [1000] * 25 + [4000]
        snap = _make_snapshot(changes, vols)
        scorer = EventScorer(settings)
        res = scorer.score_snapshot(snap)
        assert scorer.total_score(res) >= 9

    def test_selection_threshold(self, settings):
        settings.scoring.minimum_research_score = 7
        settings.stocks_universe = []
        scorer = EventScorer(settings)
        low = _make_snapshot([0.0] * 25 + [0.02], [1000] * 25 + [1600])
        high = _make_snapshot([0.0] * 25 + [0.10], [1000] * 25 + [4000])
        results = [scorer.score_snapshot(low), scorer.score_snapshot(high)]
        selected = scorer.select_for_research(results)
        assert len(selected) == 1
        assert selected[0].ticker == high.ticker

    def test_five_percent_move_is_selected_even_below_score_threshold(self, settings):
        settings.scoring.minimum_research_score = 7
        scorer = EventScorer(settings)
        # -7.7% 급락 + 거래량 평균 이하 => 점수는 낮지만 분석 가치는 있다.
        moved = _make_snapshot([0.0] * 25 + [-0.077], [1000] * 25 + [800])

        selected = scorer.select_for_research([scorer.score_snapshot(moved)])

        assert len(selected) == 1