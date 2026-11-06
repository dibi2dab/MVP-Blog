from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import requests

from src.editorial.models import ResearchSource

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
)

_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")

_STOPWORDS = {
    "그리고",
    "그러나",
    "하지만",
    "또는",
    "대한",
    "위한",
    "있는",
    "없는",
    "것으로",
    "한다",
    "했다",
    "이번",
    "관련",
    "오늘",
    "지금",
    "최신",
    "뉴스",
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "about",
    "how",
    "what",
    "why",
    "your",
    "you",
    "are",
    "was",
    "were",
    "will",
    "can",
    "new",
}


def _clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = _HTML_TAG.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def _parse_pub_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _strip_publisher_suffix(title: str, publisher: str) -> str:
    title = _clean_text(title)
    publisher = _clean_text(publisher)
    if publisher and title.endswith(f" - {publisher}"):
        return title[: -(len(publisher) + 3)].strip()
    return title


def _stable_id(url: str) -> str:
    return hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:10]


def parse_google_news_rss(xml_bytes: bytes, *, query: str = "") -> list[ResearchSource]:
    """Parse a Google News RSS document into source records.

    The parser is intentionally tolerant: a malformed item is skipped instead of
    failing the whole research run.
    """

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Google News RSS XML 파싱 실패: {exc}") from exc

    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall(".//item")

    sources: list[ResearchSource] = []
    for item in items:
        try:
            title = _clean_text(item.findtext("title"))
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue

            source_el = item.find("source")
            publisher = _clean_text(source_el.text if source_el is not None else "")
            publisher_url = (source_el.get("url") if source_el is not None else "") or ""
            published_at = _parse_pub_date(item.findtext("pubDate"))
            snippet = _clean_text(item.findtext("description"))[:500]

            sources.append(
                ResearchSource(
                    source_id=f"src-{_stable_id(link)}",
                    title=_strip_publisher_suffix(title, publisher),
                    url=link,
                    publisher=publisher,
                    publisher_url=publisher_url,
                    published_at=published_at,
                    query=query,
                    snippet=snippet,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad item must not kill research
            logger.debug("Skipping malformed RSS item: %s", exc)
            continue
    return sources


def dedupe_sources(sources: Iterable[ResearchSource]) -> list[ResearchSource]:
    seen: set[str] = set()
    result: list[ResearchSource] = []
    for source in sources:
        key = _dedupe_key(source)
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result


def _dedupe_key(source: ResearchSource) -> str:
    normalized_title = re.sub(r"[^가-힣A-Za-z0-9]", "", source.title.lower())
    if normalized_title:
        return normalized_title[:120]
    return source.url


def reindex_sources(sources: Iterable[ResearchSource]) -> list[ResearchSource]:
    """Assign readable S1..Sn IDs after dedupe/sorting."""

    result: list[ResearchSource] = []
    for index, source in enumerate(sources, start=1):
        result.append(source.model_copy(update={"source_id": f"S{index}"}))
    return result


class GoogleNewsResearchClient:
    """Small, dependency-free Google News RSS client.

    It uses the public RSS endpoint, so no API key is required. Every returned
    record keeps its original link and publication date. The editorial quality
    gate rejects citations that are not in this returned pool.
    """

    def __init__(
        self,
        *,
        timeout: int = 20,
        per_query: int = 8,
        max_sources: int = 40,
        session: requests.Session | None = None,
        rss_url: str = GOOGLE_NEWS_RSS,
    ) -> None:
        self.timeout = timeout
        self.per_query = per_query
        self.max_sources = max_sources
        self.session = session or requests.Session()
        self.rss_url = rss_url
        self.session.headers.setdefault(
            "User-Agent",
            "MVP-Blog-Editorial/1.0 (+https://github.com/dibi2dab/MVP-Blog)",
        )

    def fetch(self, queries: Iterable[str]) -> list[ResearchSource]:
        collected: list[ResearchSource] = []
        failures = 0
        queries = list(queries)
        for query in queries:
            try:
                collected.extend(self._fetch_query(query))
            except Exception as exc:  # noqa: BLE001 - keep other queries alive
                failures += 1
                logger.warning("Google News RSS 실패 (%s): %s", query, exc)
        if failures == len(queries) and not collected:
            raise RuntimeError("모든 Google News RSS 요청이 실패했습니다.")

        sources = dedupe_sources(collected)
        sources.sort(key=lambda item: item.published_at or "", reverse=True)
        sources = sources[: self.max_sources]
        return reindex_sources(sources)

    def _fetch_query(self, query: str) -> list[ResearchSource]:
        url = self.rss_url.format(query=quote_plus(query))
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        parsed = parse_google_news_rss(response.content, query=query)
        return parsed[: self.per_query]


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN.findall(text or "")
        if token.lower() not in _STOPWORDS
    }


def source_relevance(source: ResearchSource, topic: str) -> float:
    topic_tokens = _tokens(topic)
    if not topic_tokens:
        return 0.0
    source_tokens = _tokens(f"{source.title} {source.snippet}")
    if not source_tokens:
        return 0.0
    overlap = len(topic_tokens & source_tokens)
    return overlap / max(1, len(topic_tokens))


def select_sources_for_topic(
    sources: Iterable[ResearchSource],
    topic: str,
    *,
    max_sources: int = 12,
    required_ids: Iterable[str] | None = None,
) -> list[ResearchSource]:
    """Rank sources by relevance, keeping the topic-selection sources first."""

    required = set(required_ids or [])
    ranked: list[tuple[float, str, ResearchSource]] = []
    for source in sources:
        relevance = source_relevance(source, topic)
        if source.source_id in required:
            relevance += 1.0
        ranked.append((relevance, source.published_at or "", source))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = [item[2] for item in ranked[:max_sources]]
    return selected


def build_source_list(sources: Iterable[ResearchSource], *, max_chars: int = 12000) -> str:
    """Format the source pool for a prompt without exceeding a sane size."""

    lines: list[str] = []
    total = 0
    for source in sources:
        line = (
            f"[{source.source_id}] {source.title}\n"
            f"  - publisher: {source.publisher or '미상'}\n"
            f"  - published: {source.published_at or '미상'}\n"
            f"  - url: {source.url}\n"
            f"  - snippet: {source.snippet[:400]}\n"
        )
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
