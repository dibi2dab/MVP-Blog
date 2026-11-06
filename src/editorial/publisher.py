from __future__ import annotations

from pathlib import Path

from src.config.settings import Settings
from src.editorial.models import EditorialArticle
from src.publishers.base import PublishResult
from src.publishers.node_tistory_publisher import NodeTistoryPublisher, PublishTarget
from src.renderers.tistory_html_renderer import TistoryHtmlRenderer
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger

logger = get_logger(__name__)


class EditorialTistoryPublisher:
    """Publish an approved editorial article through the existing Node engine.

    Stock-specific checks are intentionally not used here. Editorial articles
    have already passed the deterministic CPPI/QDVI and quality gates.
    """

    def __init__(self, settings: Settings, target: PublishTarget) -> None:
        self.settings = settings
        self.target = target
        self.node = NodeTistoryPublisher(settings, JsonStore(settings), target=target)
        self.renderer = TistoryHtmlRenderer()

    def publish(self, article: EditorialArticle) -> PublishResult:
        if article.decision != "PUBLISH":
            return PublishResult(
                ok=False,
                url="",
                article_id=article.article_id,
                message=f"editorial decision is {article.decision}",
                error_code="EDITORIAL_NOT_APPROVED",
            )

        html = self.renderer.render(article.body_with_sources or article.body_markdown)
        html = NodeTistoryPublisher._strip_leading_title_heading(html, article.title)
        payload = {
            "title": article.title,
            "contentHtml": html,
            "tags": list(article.tags or [])[:10],
            "tistoryCategory": self.target.category_map.get(article.category, self.target.category_map.get("default", "")),
            "visibility": self.target.visibility or "public",
            "blogName": self.target.blog_name,
            "imagePaths": [],
            "debug": not (self.target.headless if self.target.headless is not None else True),
        }
        self.node._apply_target_overrides(payload)
        logger.info(
            "[editorial] publishing %s to %s (category=%r)",
            article.article_id,
            self.target.blog_name,
            payload.get("tistoryCategory"),
        )
        return self.node.publish_payload(payload, article_id=article.article_id)


def target_for_profile(profile, *, dry_run: bool = False) -> PublishTarget:
    """Build the publisher target from a blog profile and env overrides."""

    category = profile.tistory_category
    return PublishTarget(
        blog_name=profile.blog_name,
        storage_state_path=str(Path(profile.storage_state_path)),
        kakao_id=profile.kakao_id,
        kakao_password=profile.kakao_password,
        artifact_dir=f"artifacts/tistory-errors/{profile.key}",
        category_map={"default": category, **{name: category for name in profile.categories if category}},
        visibility=profile.visibility,
        headless=True,
        dry_run=dry_run,
    )
