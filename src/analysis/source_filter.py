from __future__ import annotations

"""이벤트와 직접 관련된 자료만 골라낸다.

뉴스 검색 결과에는 같은 산업의 다른 회사, 오래된 배경 기사, 검색어만 스친 기사가
섞여 들어온다. 이 모듈은 (1) 변동일 ±N일 이내의 '원인 후보'와
(2) 최대 90일 이내의 '배경 자료'를 분리하고, 출처 URL이 있는 인용 문자열을 만든다.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from src.config.settings import Settings
from src.models.disclosure import Disclosure
from src.models.event import Event
from src.models.news import NewsItem
from src.models.research_packet import ResearchPacket
from src.scoring.relevance_scoring import SourceRelevanceScorer

_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


@dataclass
class FilteredSources:
    cause_news: list[NewsItem] = field(default_factory=list)
    background_news: list[NewsItem] = field(default_factory=list)
    cause_disclosures: list[Disclosure] = field(default_factory=list)
    source_lines: list[str] = field(default_factory=list)

    @property
    def has_cause_news(self) -> bool:
        return bool(self.cause_news)

    @property
    def has_cause_disclosure(self) -> bool:
        return bool(self.cause_disclosures)

    @property
    def has_cause(self) -> bool:
        return self.has_cause_news or self.has_cause_disclosure

    def sources_with_url(self) -> list[str]:
        return [s for s in self.source_lines if "http" in s]


def parse_date(value: str | None) -> str:
    """RFC 2822, ISO 8601, YYYY-MM-DD 를 모두 YYYY-MM-DD 로 정규화한다."""
    if not value:
        return ""
    text = value.strip()
    match = _DATE_RE.search(text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:35], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def days_from_event(value: str | None, event_date: str | None) -> int | None:
    left = parse_date(value)
    right = parse_date(event_date)
    if not left or not right:
        return None
    try:
        a = datetime.strptime(left, "%Y-%m-%d")
        b = datetime.strptime(right, "%Y-%m-%d")
    except ValueError:
        return None
    return abs((a - b).days)


def _news_line(item: NewsItem) -> str:
    title = (item.title or "").strip() or "제목 없는 뉴스"
    source = (item.source or "뉴스").strip()
    date = parse_date(item.published_at)
    suffix = f" — {source}" + (f" ({date})" if date else "")
    if item.url:
        return f"[{title}]({item.url}){suffix}"
    return f"{title}{suffix}"


def _disclosure_line(item: Disclosure) -> str:
    title = (item.title or item.report_name or "공시").strip()
    date = parse_date(item.published_at)
    suffix = " — DART" + (f" ({date})" if date else "")
    if item.url:
        return f"[{title}]({item.url}){suffix}"
    return f"{title}{suffix}"


def _price_line(packet: ResearchPacket, event: Event) -> str:
    ticker = event.entity.ticker or ""
    date = ""
    if packet.market_data and packet.market_data.price_series.bars:
        date = packet.market_data.price_series.bars[-1].date
    if ticker and ticker != "@disclosure":
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        return f"[가격·거래량 데이터]({url}) — Naver Finance" + (f" ({date})" if date else "")
    return "가격·거래량 데이터 — 수집 원본" + (f" ({date})" if date else "")


def filter_sources(event: Event, packet: ResearchPacket, settings: Settings) -> FilteredSources:
    """관련성·시점 기준을 통과한 자료만 남긴다."""
    cfg = settings.publishing
    event_date = event.event_date
    scorer = SourceRelevanceScorer.from_event(event)
    out = FilteredSources()

    seen_news: set[str] = set()
    for item in packet.news:
        try:
            relevance = scorer.score_news(item)
        except Exception:
            continue
        if not relevance.include:
            continue
        key = (item.url or item.title or "").strip().lower()
        if not key or key in seen_news:
            continue
        days = days_from_event(item.published_at, event_date)
        if days is None:
            continue
        if days <= cfg.news_cause_window_days:
            seen_news.add(key)
            out.cause_news.append(item)
        elif days <= cfg.news_background_window_days:
            seen_news.add(key)
            out.background_news.append(item)

    out.cause_news.sort(key=lambda n: days_from_event(n.published_at, event_date) or 999)
    out.background_news.sort(key=lambda n: n.published_at or "", reverse=True)

    seen_disclosures: set[str] = set()
    for item in packet.disclosures:
        try:
            relevance = scorer.score_disclosure(item)
        except Exception:
            continue
        if not relevance.include:
            continue
        key = (item.rcept_no or item.url or item.title or "").strip().lower()
        if not key or key in seen_disclosures:
            continue
        days = days_from_event(item.published_at, event_date)
        if days is not None and days > cfg.news_background_window_days:
            continue
        seen_disclosures.add(key)
        out.cause_disclosures.append(item)
    out.cause_disclosures.sort(key=lambda d: d.published_at or "", reverse=True)

    lines: list[str] = []
    lines.extend(_news_line(n) for n in out.cause_news[:3])
    lines.extend(_disclosure_line(d) for d in out.cause_disclosures[:3])
    lines.extend(_news_line(n) for n in out.background_news[:3])
    lines.append(_price_line(packet, event))
    out.source_lines = list(dict.fromkeys(lines))
    return out
