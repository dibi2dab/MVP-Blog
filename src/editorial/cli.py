from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from src.config.settings import load_settings
from src.editorial.catalog import CatalogError, load_catalog
from src.editorial.generator import build_article
from src.editorial.models import EditorialArticle
from src.editorial.profiles import get_profile, list_profiles
from src.editorial.publish_runner import PublishRun, publish_ready
from src.editorial.queue import QueueSelection, select_next_entry
from src.editorial.state import EditorialState
from src.utils.logging import setup_logging

BLOG_CHOICES = ("crystal", "quartz", "all")


@dataclass
class GenerateResult:
    blog: str
    article_id: str = ""
    title: str = ""
    status: str = ""
    decision: str = ""
    quality_total: float = 0.0
    catalog_id: str = ""
    message: str = ""
    skipped: bool = False
    critical_failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crystal / Quartz deterministic editorial engine. "
            "Generation and publishing are separate commands; neither uses AI."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Generate articles from the catalog.")
    generate.add_argument("--blog", required=True, choices=BLOG_CHOICES)
    generate.add_argument(
        "--force",
        action="store_true",
        help="Ignore the per-blog daily limit (duplicate topics are still rejected).",
    )
    generate.add_argument("--limit", type=int, default=None, help="Maximum articles per blog.")
    generate.add_argument(
        "--signals",
        action="store_true",
        help="Use Google News RSS as a topic signal (optional, never used as a fact source).",
    )

    publish = sub.add_parser("publish", help="Publish validated ready articles.")
    publish.add_argument("--blog", required=True, choices=BLOG_CHOICES)
    publish.add_argument("--dry-run", action="store_true", help="Validate without publishing.")
    publish.add_argument("--force", action="store_true", help="Ignore the daily limit.")
    publish.add_argument("--limit", type=int, default=None, help="Maximum articles per blog.")

    status = sub.add_parser("status", help="Show per-blog queue and publication status.")
    status.add_argument("--blog", required=True, choices=BLOG_CHOICES)

    validate = sub.add_parser("validate", help="Validate the editorial catalog.")
    validate.add_argument("--blog", required=True, choices=BLOG_CHOICES)

    return parser.parse_args(argv)


def _blogs(value: str):
    if value == "all":
        return list_profiles()
    return [get_profile(value)]


def _load_signals(profile) -> list:
    from src.editorial.research import GoogleNewsResearchClient

    try:
        return GoogleNewsResearchClient(per_query=5, max_sources=20).fetch(profile.topic_queries)
    except Exception as exc:  # noqa: BLE001 - signals are optional
        print(f"[{profile.key}] 주제 신호를 가져오지 못했습니다: {exc}", file=sys.stderr)
        return []


def _generate_blog(profile, *, force: bool, limit: int | None, use_signals: bool) -> list[GenerateResult]:
    catalog = load_catalog(profile.key)
    state = EditorialState(profile.key)
    signals = _load_signals(profile) if use_signals else []
    results: list[GenerateResult] = []
    max_count = limit if limit is not None else profile.max_articles_per_day

    for _ in range(max(1, max_count)):
        selection: QueueSelection = select_next_entry(
            catalog,
            profile,
            state,
            force=force,
            signals=signals,
        )
        if selection.entry is None:
            results.append(GenerateResult(blog=profile.key, message=selection.reason, skipped=True))
            break
        article: EditorialArticle = build_article(
            selection.entry,
            profile,
            recent_records=state.recent_records(),
        )
        state.save_article(article)
        state.save_draft(article)
        state.save_run(
            {
                "kind": "generate",
                "blog": profile.key,
                "selection": {
                    "catalog_id": selection.entry.id,
                    "reason": selection.reason,
                    "published_today": selection.published_today,
                    "unused_count": selection.unused_count,
                },
                "article": article.to_report(),
            },
            run_id=f"{article.article_id}-generate",
        )
        results.append(
            GenerateResult(
                blog=profile.key,
                article_id=article.article_id,
                title=article.title,
                status=article.status,
                decision=article.decision,
                quality_total=article.quality.total,
                catalog_id=article.catalog_id,
                message=article.decision_reason,
                critical_failures=list(article.quality.critical_failures),
            )
        )
        if article.status != "ready":
            break
    return results


def _publish_blog(profile, *, dry_run: bool, force: bool, limit: int | None) -> PublishRun:
    state = EditorialState(profile.key)
    settings = None if dry_run else load_settings()
    run = publish_ready(
        profile,
        state,
        settings=settings,
        dry_run=dry_run,
        limit=limit,
        force=force,
    )
    state.save_run(
        {
            "kind": "publish",
            "blog": profile.key,
            "dry_run": dry_run,
            "force": force,
            "report": run.to_dict(),
        }
    )
    return run


def _status(profile) -> dict[str, Any]:
    state = EditorialState(profile.key)
    articles = state.list_articles()
    counts: dict[str, int] = {}
    for article in articles:
        counts[article.status] = counts.get(article.status, 0) + 1
    return {
        "blog": profile.key,
        "published_today": state.published_today(),
        "max_articles_per_day": profile.max_articles_per_day,
        "published_total": len(state.load_published()),
        "queue": counts,
        "recent": [
            {
                "title": record.get("title"),
                "published_at": record.get("published_at"),
                "catalog_id": record.get("catalog_id"),
                "url": record.get("url"),
            }
            for record in state.recent_records(5)
        ],
    }


def _validate(profile) -> dict[str, Any]:
    catalog = load_catalog(profile.key)
    entries = catalog.active_entries()
    return {
        "blog": profile.key,
        "catalog": str(catalog.path),
        "active_entries": len(entries),
        "ids": [entry.id for entry in entries],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging()
    try:
        if args.command == "generate":
            payload = [
                result.to_dict()
                for profile in _blogs(args.blog)
                for result in _generate_blog(
                    profile,
                    force=args.force,
                    limit=args.limit,
                    use_signals=args.signals,
                )
            ]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            failed = [result for result in payload if result["status"] == "failed"]
            return 1 if failed else 0

        if args.command == "publish":
            payload = [
                _publish_blog(
                    profile,
                    dry_run=args.dry_run,
                    force=args.force,
                    limit=args.limit,
                ).to_dict()
                for profile in _blogs(args.blog)
            ]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            failed = [
                result
                for run in payload
                for result in run["results"]
                if not result["ok"]
            ]
            return 1 if failed else 0

        if args.command == "status":
            print(
                json.dumps(
                    [_status(profile) for profile in _blogs(args.blog)],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.command == "validate":
            print(
                json.dumps(
                    [_validate(profile) for profile in _blogs(args.blog)],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    except CatalogError as exc:
        print(f"catalog error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
