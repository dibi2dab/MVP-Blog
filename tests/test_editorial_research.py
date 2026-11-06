from __future__ import annotations

from src.editorial.research import (
    GoogleNewsResearchClient,
    dedupe_sources,
    parse_google_news_rss,
    reindex_sources,
    select_sources_for_topic,
    source_relevance,
)

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>AI \xeb\x8f\x84\xea\xb5\xac \xeb\xb9\x84\xea\xb5\x90 - \xed\x85\x8c\xec\x8a\xa4\xed\x8a\xb8\xeb\x89\xb4\xec\x8a\xa4</title>
      <link>https://news.example.com/ai-tools</link>
      <pubDate>Fri, 06 Nov 2026 01:00:00 GMT</pubDate>
      <source url="https://news.example.com">\xed\x85\x8c\xec\x8a\xa4\xed\x8a\xb8\xeb\x89\xb4\xec\x8a\xa4</source>
      <description>&lt;p&gt;AI \xeb\x8f\x84\xea\xb5\xac \xec\x9a\x94\xec\x95\xbd&lt;/p&gt;</description>
    </item>
    <item>
      <title>AI \xeb\x8f\x84\xea\xb5\xac \xeb\xb9\x84\xea\xb5\x90 - \xeb\x8b\xa4\xeb\xa5\xb8 \xec\xb6\x9c\xec\xb2\x98</title>
      <link>https://news.example.com/ai-tools-copy</link>
      <pubDate>Thu, 05 Nov 2026 10:00:00 GMT</pubDate>
      <source url="https://other.example.com">\xeb\x8b\xa4\xeb\xa5\xb8 \xec\xb6\x9c\xec\xb2\x98</source>
      <description>AI \xeb\x8f\x84\xea\xb5\xac \xec\x9a\x94\xec\x95\xbd</description>
    </item>
    <item>
      <title>\xec\x83\x9d\xec\x82\xb0\xec\x84\xb1 \xec\x95\xb1</title>
      <link>https://news.example.com/productivity</link>
      <pubDate>Wed, 04 Nov 2026 03:00:00 GMT</pubDate>
      <source url="https://news.example.com">\xed\x85\x8c\xec\x8a\xa4\xed\x8a\xb8\xeb\x89\xb4\xec\x8a\xa4</source>
      <description>\xec\x83\x9d\xec\x82\xb0\xec\x84\xb1 \xeb\x8f\x84\xea\xb5\xac</description>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_strips_publisher_suffix_and_cleans_html():
    sources = parse_google_news_rss(RSS, query="AI 도구")
    assert len(sources) == 3
    first = sources[0]
    assert first.title == "AI 도구 비교"
    assert first.publisher == "테스트뉴스"
    assert first.publisher_url == "https://news.example.com"
    assert first.published_at == "2026-11-06"
    assert first.query == "AI 도구"
    assert "<p>" not in first.snippet
    assert first.url == "https://news.example.com/ai-tools"


def test_dedupe_by_normalized_title():
    sources = parse_google_news_rss(RSS)
    deduped = dedupe_sources(sources)
    assert len(deduped) == 2


def test_reindex_assigns_sequential_ids():
    sources = parse_google_news_rss(RSS)
    reindexed = reindex_sources(dedupe_sources(sources))
    assert [source.source_id for source in reindexed] == ["S1", "S2"]


def test_relevance_prefers_matching_topic():
    sources = reindex_sources(parse_google_news_rss(RSS))
    ai_source = next(source for source in sources if "AI" in source.title)
    other_source = next(source for source in sources if "AI" not in source.title)
    assert source_relevance(ai_source, "AI 도구") > source_relevance(other_source, "AI 도구")


def test_select_sources_keeps_required_ids():
    sources = reindex_sources(parse_google_news_rss(RSS))
    selected = select_sources_for_topic(sources, "AI 도구", max_sources=1, required_ids=["S2"])
    assert selected[0].source_id == "S2"


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int = 20) -> _FakeResponse:
        return _FakeResponse(self._content)


def test_client_fetch_dedupes_and_caps_sources():
    client = GoogleNewsResearchClient(
        session=_FakeSession(RSS),
        per_query=10,
        max_sources=1,
    )
    sources = client.fetch(["AI 도구", "생산성 앱"])
    assert len(sources) == 1
    assert sources[0].source_id == "S1"


def test_client_raises_when_every_query_fails():
    class _BrokenSession(_FakeSession):
        def get(self, url: str, timeout: int = 20):
            raise RuntimeError("network down")

    client = GoogleNewsResearchClient(session=_BrokenSession(b""), per_query=1)
    try:
        client.fetch(["AI 도구"])
    except RuntimeError as exc:
        assert "모든 Google News RSS" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")
