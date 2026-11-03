from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.analysis import Claim
from src.models.event import Event
from src.models.market_data import DailyPriceBar
from src.models.news import NewsItem
from src.models.research_packet import ResearchPacket
from src.models.source import EntityRef, Source


class TestEventModel:
    def test_event_creation(self):
        event = Event(
            event_id="e1",
            event_type="stock_surge",
            entity=EntityRef(name="삼성전자", ticker="005930"),
            event_score=4,
            reasons=[],
        )
        assert event.ticker == "005930"
        assert event.status == "detected"

    def test_status_transition(self):
        from src.models.event import EventStatus

        event = Event(event_id="e1", event_type="a", entity=EntityRef(name="x"))
        for status in ("researching", "analyzing", "verified", "published", "failed"):
            event.set_status(status)  # type: ignore[arg-type]
            assert event.status == status


class TestClaimModel:
    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            Claim(claim="x", confidence=1.5)
        with pytest.raises(ValidationError):
            Claim(claim="x", confidence=-0.1)

    def test_claim_types(self):
        for t in ("fact", "hypothesis", "uncertain"):
            c = Claim(claim="x", type=t)  # type: ignore[arg-type]
            assert c.type == t


class TestNewsModel:
    def test_hash_stability(self):
        a = NewsItem(title="테스트 기사", published_at="2026-09-01", source="s", url="u")
        b = NewsItem(title=" 테스트 기사 ", published_at="2026-09-01", source="s", url="u")
        assert a.content_hash == b.content_hash


class TestPriceBarModel:
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            DailyPriceBar(date="2026-01-01")
        bar = DailyPriceBar(date="2026-01-01", close=100.0)
        assert bar.close == 100.0


class TestResearchPacket:
    def test_unique_sources(self):
        packet = ResearchPacket(
            event=Event(event_id="e", event_type="x", entity=EntityRef(name="n")),
            entity=EntityRef(name="n"),
        )
        s = Source(source_id="s1", name="a", type="news")
        packet.add_source(s)
        packet.add_source(s)
        assert len(packet.sources) == 1

    def test_summary_stats(self):
        packet = ResearchPacket(
            event=Event(event_id="e", event_type="x", entity=EntityRef(name="n")),
            entity=EntityRef(name="n"),
        )
        assert packet.summary_stats()["n_news"] == 0