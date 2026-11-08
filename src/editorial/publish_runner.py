from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config.settings import Settings
from src.editorial.catalog import Catalog, load_catalog
from src.editorial.models import EditorialArticle, kst_now
from src.editorial.profiles import BlogProfile
from src.editorial.publisher import EditorialTistoryPublisher, target_for_profile
from src.editorial.quality import PUBLISH_THRESHOLD, assess_quality
from src.editorial.state import EditorialState
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PublishSummary:
    article_id: str
    title: str
    ok: bool
    status: str
    url: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "ok": self.ok,
            "status": self.status,
            "url": self.url,
            "message": self.message,
        }


@dataclass
class PublishRun:
    blog: str
    results: list[PublishSummary] = field(default_factory=list)
    skipped_reason: str = ""

    @property
    def published(self) -> int:
        return sum(1 for item in self.results if item.ok and item.status == "published")

    def to_dict(self) -> dict[str, Any]:
        return {
            "blog": self.blog,
            "published": self.published,
            "skipped_reason": self.skipped_reason,
            "results": [item.to_dict() for item in self.results],
        }


def _now_iso() -> str:
    return kst_now().replace(microsecond=0).isoformat()


def validate_metadata(article: EditorialArticle, profile: BlogProfile) -> list[str]:
    problems: list[str] = []
    if article.status != "ready":
        problems.append(f"status가 ready가 아닙니다: {article.status}")
    if article.decision != "PUBLISH":
        problems.append(f"발행 결정이 PUBLISH가 아닙니다: {article.decision}")
    threshold = max(PUBLISH_THRESHOLD, profile.min_quality_score)
    if article.quality.total < threshold:
        problems.append(f"품질 점수가 기준 미달입니다: {article.quality.total:.1f} < {threshold:.0f}")
    if article.quality.critical_failures:
        problems.append("치명적 품질 결함이 남아 있습니다: " + "; ".join(article.quality.critical_failures))
    if not article.title.strip():
        problems.append("제목이 비어 있습니다.")
    if article.primary_keyword and article.primary_keyword not in article.title:
        problems.append("제목에 핵심 키워드가 없습니다.")
    if not (article.body_with_sources or article.body_markdown).strip():
        problems.append("본문이 비어 있습니다.")
    if not article.slug.strip():
        problems.append("슬러그가 비어 있습니다.")
    if not article.meta_description.strip():
        problems.append("메타 설명이 비어 있습니다.")
    if not article.catalog_id:
        problems.append("카탈로그 ID가 없습니다.")
    if len(article.sources) < max(1, profile.min_sources):
        problems.append(f"출처가 부족합니다: {len(article.sources)}개")
    return problems


def _mark_failed(article: EditorialArticle, state: EditorialState, reason: str) -> None:
    article.status = "failed"
    article.failure_reason = reason
    state.update_article(article)


def publish_ready(
    profile: BlogProfile,
    state: EditorialState,
    *,
    settings: Settings | None = None,
    publisher: Any | None = None,
    catalog: Catalog | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    force: bool = False,
) -> PublishRun:
    """Publish generated articles after re-validating files and metadata.

    Publishing never generates content and never calls an AI provider. It
    re-runs the deterministic quality gate against the catalog so a stale or
    tampered queue file cannot be published.
    """

    run = PublishRun(blog=profile.key)
    if not force and state.published_today() >= profile.max_articles_per_day:
        run.skipped_reason = (
            f"오늘 이미 {state.published_today()}개를 발행했습니다 "
            f"(일일 한도 {profile.max_articles_per_day}개)."
        )
        return run

    ready = state.list_articles(status="ready")
    if not ready:
        run.skipped_reason = "발행 대기 중인 ready 글이 없습니다."
        return run

    catalog = catalog or load_catalog(profile.key)
    max_count = limit if limit is not None else profile.max_articles_per_day
    if not force:
        remaining = max(0, profile.max_articles_per_day - state.published_today())
        max_count = min(max_count, remaining)

    if publisher is None and not dry_run:
        if settings is None:
            raise ValueError("publish_ready requires settings or a publisher")
        publisher = EditorialTistoryPublisher(
            settings,
            target_for_profile(profile, dry_run=dry_run),
        )

    for article in ready[:max_count]:
        entry = catalog.get(article.catalog_id)
        if entry is None:
            reason = f"카탈로그 항목을 찾을 수 없습니다: {article.catalog_id}"
            _mark_failed(article, state, reason)
            run.results.append(
                PublishSummary(article.article_id, article.title, False, "failed", message=reason)
            )
            continue

        report = assess_quality(
            article,
            profile,
            recent_records=state.recent_records(),
            entry=entry,
        )
        problems = validate_metadata(article, profile)
        if problems or article.decision != "PUBLISH":
            reason = "; ".join(problems) or article.decision_reason
            if article.status != "draft":
                _mark_failed(article, state, reason)
            else:
                state.update_article(article)
            run.results.append(
                PublishSummary(
                    article.article_id,
                    article.title,
                    False,
                    article.status,
                    message=reason,
                )
            )
            continue

        if dry_run:
            state.update_article(article)
            run.results.append(
                PublishSummary(
                    article.article_id,
                    article.title,
                    True,
                    article.status,
                    message="dry run: 메타데이터와 품질 검증만 수행했습니다.",
                )
            )
            continue

        try:
            result = publisher.publish(article)
        except Exception as exc:  # noqa: BLE001 - keep other articles alive
            reason = f"발행 중 예외가 발생했습니다: {exc}"
            logger.exception("[editorial] publish failed: %s", article.article_id)
            _mark_failed(article, state, reason)
            run.results.append(
                PublishSummary(article.article_id, article.title, False, "failed", message=reason)
            )
            continue

        if not getattr(result, "ok", False):
            reason = getattr(result, "message", "") or "발행에 실패했습니다."
            _mark_failed(article, state, reason)
            run.results.append(
                PublishSummary(article.article_id, article.title, False, "failed", message=reason)
            )
            continue

        article.status = "published"
        article.published_at = _now_iso()
        article.published_url = getattr(result, "url", "") or ""
        article.failure_reason = ""
        state.save_published(state.record_from_article(article, url=article.published_url))
        state.update_article(article)
        state.save_content_archive(article)
        run.results.append(
            PublishSummary(
                article.article_id,
                article.title,
                True,
                "published",
                url=article.published_url,
                message="발행했습니다.",
            )
        )

    return run
