from __future__ import annotations

from src.models.event import Event
from src.models.market_data import SnapshotCollection
from src.models.source import EntityRef
from src.researchers.research_packet_builder import ResearchPacketBuilder


class TestResearchPacketBuilder:
    def test_packet_with_no_provider(self, settings):
        event = Event(
            event_id="e1",
            event_type="stock_surge",
            entity=EntityRef(name="테스트종목", ticker="000000"),
            event_score=5,
        )
        builder = ResearchPacketBuilder(settings, news_provider=None)
        packet = builder.build(event, None)
        assert packet.packet_id == "packet_e1"
        assert packet.event.event_id == "e1"
        assert packet.news == []
        assert packet.disclosures == []

    def test_packet_attaches_snapshot(self, settings, sample_snapshot):
        event = Event(
            event_id="e2",
            event_type="stock_surge",
            entity=EntityRef(name="테스트종목", ticker="000000"),
        )
        builder = ResearchPacketBuilder(settings, news_provider=None)
        collection = SnapshotCollection(snapshots=[sample_snapshot])
        packet = builder.build(event, collection)
        assert packet.market_data is not None
        assert packet.price_data["latest_change_pct"] is not None
        assert packet.volume_data["volume_ratio"] is not None
        assert packet.market_data.ticker == "000000"

    def test_packet_with_mock_news_provider(self, settings, sample_snapshot):
        from src.collectors.news.mock_news_collector import MockNewsCollector
        from src.config.settings import SourceItemConfig

        settings.stocks_universe = [SourceItemConfig(code="000001", name="테스트주")]
        event = Event(
            event_id="e3",
            event_type="stock_surge",
            entity=EntityRef(name="테스트종목", ticker="000000"),
        )
        provider = MockNewsCollector(settings, seed=3)
        builder = ResearchPacketBuilder(settings, news_provider=provider)
        packet = builder.build(event, SnapshotCollection(snapshots=[sample_snapshot]))
        assert any(n.title for n in packet.news)
        assert packet.sources