from __future__ import annotations

from src.analysis.source_filter import days_from_event, filter_sources, parse_date
from src.models.disclosure import Disclosure
from src.models.event import Event
from src.models.news import NewsItem
from src.models.research_packet import ResearchPacket
from src.models.source import EntityRef


def _packet(news=None, disclosures=None) -> ResearchPacket:
    event = Event(
        event_id="e1",
        event_type="stock_crash",
        entity=EntityRef(name="코미팜", ticker="041960"),
        event_date="2026-09-02",
    )
    return ResearchPacket(
        event=event,
        entity=event.entity,
        news=news or [],
        disclosures=disclosures or [],
    )


def _news(title: str, date: str, url: str | None = None) -> NewsItem:
    return NewsItem(
        title=title,
        published_at=date,
        source="테스트뉴스",
        url=url or f"https://example.com/{abs(hash(title))}",
    )


class TestSourceFilter:
    def test_parses_dates_and_day_distance(self):
        assert parse_date("Wed, 02 Sep 2026 09:00:00 +0900") == "2026-09-02"
        assert parse_date("2026-09-02T09:00:00+09:00") == "2026-09-02"
        assert days_from_event("2026-09-01", "2026-09-02") == 1

    def test_separates_cause_and_background(self, settings):
        packet = _packet(
            news=[
                _news("코미팜 급락…거래량 급증", "2026-09-01"),
                _news("코미팜 신제품 허가 배경", "2026-07-01"),
                _news("삼성전자 신제품 출시", "2026-09-01"),
                _news("코미팜 아주 오래된 기사", "2025-01-01"),
            ],
            disclosures=[
                Disclosure(title="코미팜 주요사항보고서", corp_name="코미팜", published_at="2026-09-02"),
                Disclosure(title="삼성전자 유상증자", corp_name="삼성전자", published_at="2026-09-02"),
            ],
        )

        filtered = filter_sources(packet.event, packet, settings)

        assert [n.title for n in filtered.cause_news] == ["코미팜 급락…거래량 급증"]
        assert [n.title for n in filtered.background_news] == ["코미팜 신제품 허가 배경"]
        assert [d.corp_name for d in filtered.cause_disclosures] == ["코미팜"]
        assert any("finance.naver.com" in line for line in filtered.sources_with_url())

    def test_source_lines_include_urls(self, settings):
        packet = _packet(news=[_news("코미팜 급락", "2026-09-02", "https://example.com/a")])

        filtered = filter_sources(packet.event, packet, settings)

        assert len(filtered.sources_with_url()) >= 2  # 뉴스 1 + 가격 데이터 1
