from __future__ import annotations

from datetime import datetime, timezone

from src.analyzers.readiness import evaluate_readiness
from src.config.settings import Settings
from src.models.article import Article
from src.publishers.publisher import PublishDeduplicator, PublishResult
from src.publishers import PublisherFactory
from src.publishers.visibility import resolve_visibility
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

        # 기사별 공개 범위를 확정한다. 정책상 공개 불가면 private 으로 강제된다.
        #
        # 공개 정책을 켠 뒤에도, 이전 실행에서 생성된 기사는 public_ready=false 로
        # 저장되어 있을 수 있다. 발행 직전에 준비도를 다시 계산해 최신 정책을 적용한다.
        if self.settings.publishing.allow_public and not article.public_ready:
            report = self.store.load_analysis(article.event.event_id)
            if report is not None:
                others = [
                    a for a in self.store.load_all_articles() if a.article_id != article.article_id
                ]
                readiness = evaluate_readiness(
                    article, report, self.settings, recent_articles=others
                )
                article.public_ready = readiness.public_ready
                article.readiness = readiness.to_dict()
                self.store.save_article(article)

        article.visibility = resolve_visibility(
            article,
            self.settings,
            public_ready=bool(article.public_ready),
        )

        publisher = self.factory.build()
        image_paths = [img.local_path for img in article.images if img.local_path] or article.chart_paths
        result = publisher.publish(article, article.body_markdown, images=image_paths)
        if not result.ok:
            logger.error("[publish] failed: %s", result.message)
            article.status = "publish_failed"
            article.published_message = getattr(article, "published_message", "") or result.message
            self.store.save_article(article)
            return result

        article.published_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        article.published_url = result.url
        article.publish_backend = publisher.name
        article.published_visibility = article.visibility
        article.status = "published"
        self.store.save_article(article)
        self.dedup.mark(article, result, visibility=article.visibility)
        logger.info("[publish] done: %s (visibility=%s)", result.url, article.visibility)

        # 이벤트 상태 업데이트
        event = self.store.load_event(article.event.event_id)
        if event:
            event.set_status("published")
            self.store.save_event(event)
        return result
