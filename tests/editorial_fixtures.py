from __future__ import annotations

"""Shared fixtures for the deterministic Crystal / Quartz editorial tests.

Everything here is offline: the real catalog files are parsed, and articles are
built with the deterministic generator. No network, no AI provider.
"""

from dataclasses import dataclass

from src.editorial.catalog import Catalog, CatalogEntryModel, load_catalog
from src.editorial.generator import build_article
from src.editorial.models import EditorialArticle
from src.editorial.profiles import BlogProfile, get_profile

CRYSTAL_IDS = (
    "adsense-blog",
    "gumroad-digital-product",
    "patreon-membership",
    "shopify-affiliate",
    "upwork-freelance",
)

QUARTZ_IDS = (
    "notion-plus",
    "zapier-pro",
    "github-copilot-pro",
    "claude-pro",
    "google-workspace-business-starter",
    "figma-professional",
    "slack-pro",
)


def get_catalog(blog: str) -> Catalog:
    return load_catalog(blog)


def get_entry(blog: str, entry_id: str) -> CatalogEntryModel:
    entry = get_catalog(blog).get(entry_id)
    assert entry is not None, f"catalog entry not found: {blog}/{entry_id}"
    return entry


def make_profile(blog: str) -> BlogProfile:
    return get_profile(blog)


def make_article(
    blog: str = "quartz",
    entry_id: str = "notion-plus",
    *,
    recent_records=(),
) -> EditorialArticle:
    return build_article(
        get_entry(blog, entry_id),
        get_profile(blog),
        recent_records=recent_records,
    )


def clone_article(article: EditorialArticle) -> EditorialArticle:
    return article.model_copy(deep=True)


@dataclass
class FakePublishResult:
    ok: bool = True
    url: str = "https://example.tistory.com/1"
    message: str = "ok"


class FakePublisher:
    """Minimal stand-in for ``EditorialTistoryPublisher``."""

    def __init__(self, *, ok: bool = True, url: str = "https://example.tistory.com/1") -> None:
        self.ok = ok
        self.url = url
        self.published: list[EditorialArticle] = []

    def publish(self, article: EditorialArticle) -> FakePublishResult:
        self.published.append(article)
        return FakePublishResult(
            ok=self.ok,
            url=self.url,
            message="ok" if self.ok else "발행에 실패했습니다.",
        )
