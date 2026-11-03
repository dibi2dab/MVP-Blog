from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.settings import Settings, load_settings, AppConfig, StorageConfig, AIConfig, ScoringConfig, DetectionConfig, NewsConfig, ResearchConfig


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    import os

    os.environ["MOCK_MODE"] = "true"
    cfg = Settings(
        app=AppConfig(mock_mode="true"),
        storage=StorageConfig(base_dir=str(tmp_path / "data")),
        ai=AIConfig(provider="mock"),
        scoring=ScoringConfig(
            minimum_research_score=3,
            weights={
                "price_change_10_percent": 5,
                "price_change_5_percent": 3,
                "price_change_3_percent": 1,
                "price_change_negative_10_percent": 5,
                "price_change_negative_5_percent": 3,
                "price_change_negative_3_percent": 1,
                "volume_increase_300_percent": 4,
                "volume_increase_100_percent": 2,
                "volume_increase_50_percent": 1,
                "new_high": 2,
                "new_low": 2,
                "gap_up": 2,
                "gap_down": 2,
                "important_disclosure": 5,
                "earnings": 5,
                "news_high": 4,
                "medium_news": 2,
            },
        ),
        detection=DetectionConfig(max_events_per_run=10),
        news=NewsConfig(),
        research=ResearchConfig(),
    )
    cfg.storage.base_path.mkdir(parents=True, exist_ok=True)
    for key in ("raw", "normalized", "events", "research", "cache", "processed", "published"):
        cfg.storage.path(key).mkdir(parents=True, exist_ok=True)
    cfg.content.output_dir = str(tmp_path / "content")
    cfg.content.output_dir = str(tmp_path / "content")
    cfg.charts.output_dir = str(tmp_path / "charts")
    cfg.publishing.content_dir = str(tmp_path / "content")
    Path(cfg.content.output_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.charts.output_dir).mkdir(parents=True, exist_ok=True)
    return cfg


@pytest.fixture
def sample_snapshot() -> "MarketSnapshot":
    from src.models.market_data import DailyPriceBar, MarketSnapshot, PriceSeries
    from datetime import datetime, timedelta

    today = datetime.now()
    bars = []
    price = 50000.0
    for i in range(40, 0, -1):
        dt = today - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        change = 0.05 if i == 1 else 0.0
        price = round(price * (1 + change), 1)
        bars.append(
            DailyPriceBar(
                date=dt.strftime("%Y-%m-%d"),
                open=round(price * 0.995, 1),
                high=round(price * 1.01, 1),
                low=round(price * 0.99, 1),
                close=price,
                volume=800_000 if i != 1 else 3_000_000,
                amount=800_000 * price if i != 1 else 3_000_000 * price,
                change_pct=round(change * 100, 2),
            )
        )
    bars.sort(key=lambda b: b.date)
    series = PriceSeries(ticker="000000", name="테스트종목", currency="KRW", bars=bars)
    return MarketSnapshot(ticker="000000", name="테스트종목", price_series=series, source_id="test")