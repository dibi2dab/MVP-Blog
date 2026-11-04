from __future__ import annotations

from datetime import datetime

from src.config.settings import Settings
from src.models.analysis import AnalysisReport
from src.models.article import Article
from src.models.disclosure import Disclosure
from src.models.event import Event
from src.models.market_data import MarketSnapshot, SnapshotCollection
from src.models.news import NewsCluster, NewsItem
from src.models.research_packet import HistoricalCase, ResearchPacket
from src.models.source import EntityRef, Source, utc_now_iso
from src.utils.deduplication import NewsDeduper
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ResearchPacketBuilder:
    """이벤트에 대한 Research Packet 생성. AI 는 이 패킷 기반으로만 분석한다.

    여기서 가능한 한 많은 근거 데이터를 수집/정리해 컨텍스트로 주입한다.
    """

    def __init__(
        self,
        settings: Settings,
        news_provider=None,
        snapshot_source: callable | None = None,
    ) -> None:
        self.settings = settings
        self.news_provider = news_provider  # search(query, max_items) 지원 객체
        self.snapshot_source = snapshot_source  # resource: dict[ticker -> SnapshotCollection]
        self.deduper = NewsDeduper(
            title_threshold=settings.news.dedupe_title_similarity,
            cluster_tolerance_hours=settings.news.cluster_tolerance_minutes / 60,
        )

    def build(
        self,
        event: Event,
        snapshots: SnapshotCollection | None = None,
        disclosures: list[Disclosure] | None = None,
    ) -> ResearchPacket:
        packet = ResearchPacket(
            event=event,
            entity=event.entity,
            packet_id=f"packet_{event.event_id}",
        )
        snapshot = self._find_snapshot(event, snapshots)
        if snapshot:
            packet.market_data = snapshot
            packet.price_data = self._price_data(snapshot)
            packet.volume_data = self._volume_data(snapshot)
            ticker = event.entity.ticker or snapshot.ticker
            price_url = (
                f"https://finance.naver.com/item/main.naver?code={ticker}"
                if ticker and ticker != "@disclosure"
                else ""
            )
            packet.add_source(
                Source(
                    source_id=snapshot.source_id,
                    name="가격/거래량 데이터",
                    type="stock_price",
                    url=price_url,
                )
            )

        self._collect_news(event, packet)
        self._collect_disclosures(event, packet, disclosures or [])
        self._collect_related(event, packet, snapshots)
        self._collect_historical(event, packet)
        return packet

    def _find_snapshot(self, event: Event, snapshots: SnapshotCollection | None) -> MarketSnapshot | None:
        if snapshots:
            by = snapshots.by_ticker(event.ticker) if event.ticker and event.ticker != "@disclosure" else None
            if by:
                return by
        if self.snapshot_source:
            try:
                return self.snapshot_source(event)
            except Exception:
                return None
        return None

    def _price_data(self, snapshot: MarketSnapshot) -> dict:
        series = snapshot.price_series
        bars = series.bars[-30:]
        return {
            "recent_bars": [b.model_dump() for b in bars],
            "latest_change_pct": series.latest_change_pct,
            "avg_volume_20d": series.avg_volume(20),
            "gain_5d": _pct_change(series, 5),
            "gain_20d": _pct_change(series, 20),
            "gain_60d": _pct_change(series, 60),
        }

    def _volume_data(self, snapshot: MarketSnapshot) -> dict:
        return {
            "latest_volume": snapshot.latest_volume,
            "avg_volume": snapshot.avg_volume,
            "volume_ratio": snapshot.volume_ratio,
            "latest_amount": snapshot.price_series.bars[-1].amount if snapshot.price_series.bars else None,
        }

    def _collect_news(self, event: Event, packet: ResearchPacket) -> None:
        if not self.news_provider:
            return
        queries = self._news_queries(event)
        collected: list[NewsItem] = []
        for query in queries:
            try:
                for item in self.news_provider.search(query, max_items=10):
                    collected.append(item)
            except Exception as e:
                logger.warning("news search %r failed: %s", query, e)
        collected = self.deduper.dedupe(collected)
        packet.news = collected[: self.settings.research.max_news_per_entity]
        clusters = self.deduper.cluster(packet.news)
        packet.news_clusters = [
            NewsCluster(**c) for c in clusters[: self.settings.research.max_news_clusters]
        ]
        for item in packet.news:
            packet.add_source(
                Source(
                    source_id=item.source_id or "news",
                    name=item.source,
                    type="news",
                    url=item.url,
                    published_at=item.published_at,
                )
            )

    def _news_queries(self, event: Event) -> list[str]:
        name = event.entity.name or ""
        ticker = event.entity.ticker or ""
        queries = [f"{name} 주가", f"{name} 뉴스"]
        if ticker and ticker != "@disclosure":
            queries.append(f"{name}")
        dictype_event = {
            "유상증자": f"{name} 유상증자",
            "실적": f"{name} 실적",
        }
        return queries

    def _collect_disclosures(
        self, event: Event, packet: ResearchPacket, disclosures: list[Disclosure]
    ) -> None:
        """이벤트와 관련된 공시를 패킷에 주입한다 (기업명/접수번호/출처 매칭)."""
        if not disclosures:
            return
        related: list[Disclosure] = []
        related_rcepts = set(event.evidence.get("rcept_no", "") or [])
        if isinstance(related_rcepts, str):
            related_rcepts = {related_rcepts} if related_rcepts else set()
        for d in disclosures:
            matched = bool(event.entity.name) and d.corp_name == event.entity.name
            if not matched and d.rcept_no in related_rcepts:
                matched = True
            if not matched and d.source_id and d.source_id in event.related_sources:
                matched = True
            if matched:
                related.append(d)
        # 관련 공시가 없으면 다른 회사 공시를 채워 넣지 않는다.
        # (다른 회사 공시가 본문에 섞이면 Source Relevance 위반)
        packet.disclosures = related[: self.settings.research.max_news_per_entity]
        for d in packet.disclosures:
            packet.add_source(
                Source(
                    source_id=d.source_id or "disclosure",
                    name=f"DART 공시: {d.title[:30]}",
                    type="disclosure",
                    url=d.url,
                    published_at=d.published_at,
                )
            )

    def _collect_related(self, event: Event, packet: ResearchPacket, snapshots: SnapshotCollection | None) -> None:
        """관련 종목들 (같은 지수 그룹) 스냅샷을 relationship 데이터로 추가."""
        related: list[EntityRef] = []
        if snapshots:
            for s in snapshots.snapshots[:5]:
                related.append(EntityRef(name=s.name, ticker=s.ticker))
        packet.related_entities = related[: self.settings.research.max_related_entities]

    def _collect_historical(self, event: Event, packet: ResearchPacket) -> None:
        """첫 Phase 에서는 빈 리스트. 이후 Phase 2 에서 채운다."""
        packet.historical_cases = []


def _pct_change(series, window: int) -> float | None:
    import statistics

    if len(series.bars) <= window:
        return None
    prev = series.bars[-(window + 1)]
    last = series.bars[-1]
    if not prev.close:
        return None
    return round((last.close - prev.close) / prev.close * 100, 2)