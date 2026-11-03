from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

from src.collectors.base import BaseCollector, RawRecord
from src.config.settings import Settings
from src.models.news import NewsItem
from src.utils.cache import DiskCache
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)

_RSS_NS = {"atom": "http://www.w3.org/2005/Atom"}
_G = "{http://base.google.com/ns/1.0}"


class GoogleNewsRssCollector(BaseCollector):
    """키 없이 사용 가능한 Google News RSS 기반 뉴스 수집기.

    공식 RSS 피드를 그대로 사용하므로 무단 스크래핑이 아니다.
    """

    source_id = "google.news"
    source_name = "Google News"
    source_type = "news"

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; finance-research-blog/1.0)"})
        cfg = settings.sources_raw.get("news", {}).get("google_rss", {})
        self.base_url = cfg.get("base_url", "https://news.google.com/rss/search")
        self.lang = cfg.get("lang", "ko")
        self.country = cfg.get("country", "KR")
        self.max_items = int(cfg.get("max_items", 40))
        self.cache = DiskCache(str(settings.storage.path("cache")), ttl_seconds=1800)

    @retry(max_attempts=3, base_delay=3, max_delay=30, logger=logger)
    def _fetch_rss(self, query: str) -> bytes:
        cache_key = f"gnews_{self.lang}_{quote_plus(query)}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return bytes(cached["data"], "utf-8")
        params = {
            "q": query,
            "hl": self.lang,
            "gl": self.country,
            "ceid": f"{self.country}:{self.lang}",
        }
        resp = self.session.get(self.base_url, params=params, timeout=20)
        resp.raise_for_status()
        self.cache.set(cache_key, {"data": resp.text})
        return resp.text

    def search(self, query: str, max_items: int | None = 0) -> list[NewsItem]:
        limit = max_items or self.max_items
        content = self._fetch_rss(query)
        items: list[NewsItem] = []
        try:
            root = ET.fromstring(content)
            for entry in root.findall(".//item"):
                if len(items) >= limit * 2:
                    break
                raw = self._parse_item(entry)
                if raw:
                    items.append(raw)
        except ET.ParseError as e:
            logger.error("RSS parse error: %s", e)
        return items[:limit]

    def _parse_item(self, entry) -> NewsItem | None:
        title_el = entry.find("title")
        pub_el = entry.find("pubDate")
        source_el = entry.find(f"{_G}source")
        link_el = entry.find("link")
        if title_el is None or title_el.text is None:
            return None
        published = pub_el.text if pub_el is not None and pub_el.text else ""
        source_name = source_el.get("url") if source_el is not None and source_el.get("url") else "Google News"
        url = link_el.text if link_el is not None and link_el.text else ""
        return NewsItem(
            title=title_el.text.strip(),
            published_at=published,
            source=source_name,
            url=url,
            summary="",
            keywords=[],
            source_id=self.source_id,
        )

    def collect(self) -> list[RawRecord]:
        """기본 수집: 종목별 + 시장 전체 검색. 실패해도 전체 실패하지 않는다."""
        queries = ["코스피", "코스닥", "금융시장"]
        for item in self.settings.stocks_universe[:10]:
            queries.append(f"{item.name} 주가")
        records: list[RawRecord] = []
        for query in queries:
            try:
                items = self.search(query)
                for it in items:
                    records.append(
                        self.make_record(
                            data_type="news_item",
                            data=it.model_dump(),
                            original_url=it.url,
                            metadata={"query": query},
                        )
                    )
            except Exception as e:
                logger.warning("news collect failed for %r: %s", query, e)
        self.logger.info("collected %d news records", len(records))
        return records