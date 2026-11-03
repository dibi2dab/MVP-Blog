from __future__ import annotations

from pathlib import Path

from src.charts.analysis_chart_generator import AnalysisChartGenerator
from src.charts.chart_selector import ChartSelector
from src.charts.external_chart_provider import ExternalChartProvider, TradingViewChartProvider
from src.models.chart import ChartSpec
from src.models.event import Event
from src.models.research_packet import ResearchPacket
from src.models.source import EntityRef


def _packet(event, snapshot) -> ResearchPacket:
    return ResearchPacket(event=event, entity=event.entity, market_data=snapshot, news=[], disclosures=[])


class TestChartSelector:
    def test_surge_selects_price_and_volume(self):
        event = Event(event_id="e1", event_type="stock_surge", entity=EntityRef(name="T", ticker="000001"))
        charts = ChartSelector().select(event)
        types = [c.chart_type for c in charts]
        assert "price_volume" in types
        assert "volume_ratio" in types

    def test_earnings_includes_financial(self):
        event = Event(event_id="e1", event_type="earnings", entity=EntityRef(name="T"))
        types = [c.chart_type for c in ChartSelector().select(event)]
        assert "financial" in types


class TestChartGenerator:
    def test_price_volume_chart_created(self, settings, sample_snapshot):
        event = Event(event_id="e1", event_type="stock_surge", entity=EntityRef(name="테스트종목", ticker="000000"))
        gen = AnalysisChartGenerator(settings)
        spec = ChartSpec(chart_type="price_volume", title="주가", event_type="stock_surge", ticker="000000", name="테스트종목")
        chart = gen.generate(spec, _packet(event, sample_snapshot))
        assert chart is not None
        assert Path(chart.path).exists()
        assert chart.path.endswith(".png")

    def test_volume_ratio_chart(self, settings, sample_snapshot):
        event = Event(event_id="e1", event_type="stock_surge", entity=EntityRef(name="테스트종목", ticker="000000"))
        gen = AnalysisChartGenerator(settings)
        spec = ChartSpec(chart_type="volume_ratio", title="거래량", event_type="stock_surge", ticker="000000", name="테스트종목")
        chart = gen.generate(spec, _packet(event, sample_snapshot))
        assert chart is not None
        assert Path(chart.path).exists()

    def test_no_data_no_chart(self, settings, sample_snapshot):
        event = Event(event_id="e1", event_type="earnings", entity=EntityRef(name="T"))
        packet = ResearchPacket(event=event, entity=event.entity, market_data=None)
        gen = AnalysisChartGenerator(settings)
        spec = ChartSpec(chart_type="financial", title="실적", event_type="earnings", ticker="", name="T")
        chart = gen.generate(spec, packet)
        assert chart is None


class TestExternalChartProvider:
    def test_tradingview_embed(self):
        tv = TradingViewChartProvider()
        embed = tv.embed("005930", "삼성전자")
        assert embed.provider == "tradingview"
        assert "KRX:005930" in embed.widget
        assert "tradingview.com" in embed.widget
        assert "external-embedding" in embed.widget

    def test_provider_adapter(self):
        ep = ExternalChartProvider()
        embed = ep.embed("tradingview", "000660", "SK하이닉스")
        assert embed is not None
        assert embed.symbol == "KRX:000660"
        assert ep.embed("unknown", "1", "x") is None