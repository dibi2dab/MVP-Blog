from __future__ import annotations

from src.config.settings import Settings
from src.models.article import Article
from src.publishers.publisher import PublishDeduplicator, PublishResult
from src.publishers import PublisherFactory
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger

logger = get_logger(__name__)


class PublishStep:
    """중복 게시 방지 -> 실제 게시 (Tistory / local / mock) -> 이벤트 상태 갱신."""

    def __init__(self, settings: Settings, store: JsonStore) -> None:
        self.settings = settings
        self.store = store
        self.dedup = PublishDeduplicator(store)
        self.factory = PublisherFactory(settings, store)

    def run(self, article: Article) -> PublishResult | None:
        logger.info("[publish] article %s -> backend=%s", article.article_id, self.settings.effective_backend)
        if self.dedup.is_published(article):
            logger.info("[publish] already published: %s", article.event.event_id)
            article.status = "already_published"
            self.store.save_article(article)
            return None

        publisher = self.factory.build()
        image_paths = [img.local_path for img in article.images if img.local_path] or article.chart_paths
        result = publisher.publish(article, article.body_markdown, images=image_paths)
        if not result.ok:
            logger.error("[publish] failed: %s", result.message)
            article.status = "publish_failed"
            article.published_message = getattr(article, "published_message", "") or result.message
            self.store.save_article(article)
            return result

        article.published_at = article.created_at
        article.published_url = result.url
        article.publish_backend = publisher.name
        article.status = "published"
        self.store.save_article(article)
        self.dedup.mark(article, result)
        logger.info("[publish] done: %s", result.url)

        # 이벤트 상태 업데이트
        event = self.store.load_event(article.event.event_id)
        if event:
            event.set_status("published")
            self.store.save_event(event)
        return result