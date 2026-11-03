from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import Settings
from src.models.article import Article, ArticleToPublish
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger

logger = get_logger(__name__)


class PublishResult:
    def __init__(self, ok: bool, url: str, message: str = "", article_id: str = "", error_code: str = "") -> None:
        self.ok = ok
        self.url = url
        self.message = message
        self.article_id = article_id
        self.error_code = error_code


class BasePublisher(ABC):
    name: str = "base"

    def __init__(self, settings: Settings, store: JsonStore) -> None:
        self.settings = settings
        self.store = store

    @abstractmethod
    def publish(self, article: Article, markdown: str, images: list[str] | None = None) -> PublishResult:
        raise NotImplementedError


class PublishDeduplicator:
    """같은 이벤트/해시 재게시 방지."""

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def is_published(self, article: Article) -> bool:
        if self.store.published_exists(f"event_{article.event.event_id}"):
            return True
        if self.store.published_exists(f"hash_{article.content_hash}"):
            return True
        return False

    def mark(self, article: Article, result: PublishResult) -> None:
        self.store.save_published_marker(
            f"event_{article.event.event_id}",
            {
                "event_id": article.event.event_id,
                "entity": article.event.entity.name,
                "ticker": article.event.entity.ticker,
                "event_type": article.event.event_type,
                "date": article.created_at[:10],
                "article_id": article.article_id,
                "content_hash": article.content_hash,
                "url": result.url,
                "published_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.store.save_published_marker(
            f"hash_{article.content_hash}",
            {"event_id": article.event.event_id, "url": result.url},
        )


class LocalPublisher(BasePublisher):
    """content/ 디렉토리에 Markdown으로 저장하는 로컬 게시 (기본, 배포 전 검수용)."""

    name = "local"

    def publish(self, article: Article, markdown: str, images: list[str] | None = None) -> PublishResult:
        category_dir = Path(article.category) if not Path(article.category).is_absolute() else Path("stocks")
        out = Path(self.settings.publishing.content_dir) / category_dir.name
        out.mkdir(parents=True, exist_ok=True)
        date = (article.published_at or article.created_at)[:10]
        slug = article.slug or f"post-{article.article_id}"
        path = out / f"{date}-{slug}.md"
        path.write_text(markdown, encoding="utf-8")
        return PublishResult(ok=True, url=str(path), message="saved locally", article_id=article.article_id)


class MockPublisher(BasePublisher):
    """게시를 시뮬레이션 (키 없이 파이프라인 검증용)."""

    name = "mock"

    def publish(self, article: Article, markdown: str, images: list[str] | None = None) -> PublishResult:
        slug = article.slug or article.article_id
        return PublishResult(
            ok=True,
            url=f"https://mock.blog/entry/{slug}",
            message="mock publish",
            article_id=article.article_id,
        )


def content_hash(markdown: str) -> str:
    return hashlib.sha1(markdown.encode("utf-8")).hexdigest()