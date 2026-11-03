from __future__ import annotations

import json

from src.analyzers.ai_provider import ProviderFactory
from src.analyzers.fact_checker import FactChecker
from src.analyzers.research_analyst import ResearchAnalyst
from src.config.settings import Settings
from src.models.analysis import AnalysisReport
from src.models.event import Event
from src.models.market_data import SnapshotCollection
from src.models.news import NewsItem
from src.models.research_packet import ResearchPacket
from src.researchers.research_packet_builder import ResearchPacketBuilder
from src.storage.file_store import JsonStore
from src.utils.cache import DiskCache
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ResearchStep:
    """Research Packet 생성 -> Research Analyst -> Fact Checker."""

    def __init__(self, settings: Settings, store: JsonStore, news_provider=None) -> None:
        self.settings = settings
        self.store = store
        self.cache = DiskCache(str(settings.storage.path("cache")), ttl_seconds=settings.ai.cache_ttl_seconds)
        self.provider = ProviderFactory(settings, cache=self.cache).build()
        self.news_provider = news_provider

    def run(
        self,
        events: list[Event],
        snapshots: SnapshotCollection | None = None,
        news_items: list[NewsItem] | None = None,
        disclosures: list | None = None,
    ) -> dict[str, AnalysisReport]:
        analyst = ResearchAnalyst(self.provider, self.settings)
        fact_checker = FactChecker(self.provider, self.settings)
        reports: dict[str, AnalysisReport] = {}

        for event in events:
            logger.info("[research] building research packet for %s (%s)", event.event_id, event.entity.name)
            event.set_status("researching")
            self.store.save_event(event)

            builder = ResearchPacketBuilder(self.settings, news_provider=self.news_provider)
            packet = builder.build(event, snapshots, disclosures)
            packet.packet_id = f"packet_{event.event_id}"
            self.store.save_research_packet(packet)
            logger.info("[research] packet %s: %s", packet.packet_id, packet.summary_stats())

            logger.info("[research] running research analyst")
            output = analyst.analyze(packet)
            logger.info("[research] analyst: %d facts, %d hypotheses", len(output.facts), len(output.hypotheses))

            logger.info("[research] running fact checker")
            check = fact_checker.check(packet, output)
            report = AnalysisReport(
                packet_id=packet.packet_id,
                event_id=event.event_id,
                analyst_output=output,
                fact_check=check,
            )
            self.store.save_analysis(report)

            if check.verdict == "needs_review":
                logger.warning("[research] fact-check needs_review for %s (n=%d)", event.event_id, len(check.issue_notes))
            event.set_status("analyzing" if check.approved_claims else "failed")
            self.store.save_event(event)
            reports[event.event_id] = report
        return reports