from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.disclosure import Disclosure
from src.models.event import Event
from src.models.market_data import MarketSnapshot
from src.models.news import NewsCluster, NewsItem
from src.models.source import EntityRef, Source, utc_now_iso


class HistoricalCase(BaseModel):
    """과거 유사 사례."""

    label: str
    ticker: str | None = None
    name: str | None = None
    date: str | None = None
    event_type: str = ""
    description: str = ""
    forward_return_day1: float | None = None
    forward_return_week: float | None = None
    forward_return_month: float | None = None
    similar: bool = True
    notes: str = ""


class ResearchPacket(BaseModel):
    """가장 중요한 데이터 구조. AI 는 이 패킷에 없는 구체적 사실을 만들 수 없다."""

    event: Event
    entity: EntityRef
    packet_id: str = Field(default="")
    market_data: MarketSnapshot | None = None
    price_data: dict = Field(default_factory=dict)
    volume_data: dict = Field(default_factory=dict)
    financial_data: dict = Field(default_factory=dict)
    disclosures: list[Disclosure] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    news_clusters: list[NewsCluster] = Field(default_factory=list)
    industry_data: dict = Field(default_factory=dict)
    related_entities: list[EntityRef] = Field(default_factory=list)
    historical_cases: list[HistoricalCase] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    built_at: str = Field(default_factory=utc_now_iso)
    status: str = "built"

    def add_source(self, source: Source) -> None:
        if not any(s.source_id == source.source_id for s in self.sources):
            self.sources.append(source)

    def source_by_id(self, source_id: str) -> Source | None:
        for s in self.sources:
            if s.source_id == source_id:
                return s
        return None

    def summary_stats(self) -> dict:
        return {
            "n_news": len(self.news),
            "n_clusters": len(self.news_clusters),
            "n_disclosures": len(self.disclosures),
            "n_sources": len(self.sources),
            "n_historical_cases": len(self.historical_cases),
            "n_related_entities": len(self.related_entities),
        }