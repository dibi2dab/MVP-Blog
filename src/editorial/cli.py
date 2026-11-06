from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.config.settings import load_settings
from src.editorial.pipeline import EditorialPipeline, EditorialRunResult
from src.editorial.profiles import get_profile
from src.utils.logging import setup_logging


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crystal / Quartz editorial pipeline (Korean articles, CPPI/QDVI quality gate).",
    )
    parser.add_argument(
        "--blog",
        required=True,
        choices=["crystal", "quartz", "all"],
        help="Which blog to run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate, validate, and score, but do not publish.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the per-blog daily limit (quality gates still apply).",
    )
    parser.add_argument(
        "--allow-mock",
        action="store_true",
        help="Allow a mock AI provider for pipeline testing. Mock results are never published.",
    )
    parser.add_argument(
        "--max-sources",
        type=int,
        default=None,
        help="Override the research client's maximum source count.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the JSON run summary.",
    )
    return parser.parse_args(argv)


def _run_one(key: str, args: argparse.Namespace, settings) -> EditorialRunResult:
    profile = get_profile(key)
    research_client = None
    if args.max_sources is not None:
        from src.editorial.research import GoogleNewsResearchClient

        research_client = GoogleNewsResearchClient(max_sources=max(5, args.max_sources))

    pipeline = EditorialPipeline(profile, settings, research_client=research_client)
    return pipeline.run(
        dry_run=args.dry_run,
        force=args.force,
        allow_mock=args.allow_mock,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = load_settings()
    setup_logging(settings.app.log_level)

    keys = ["crystal", "quartz"] if args.blog == "all" else [args.blog]
    results: list[EditorialRunResult] = []
    for key in keys:
        result = _run_one(key, args, settings)
        results.append(result)
        if not args.json:
            print(
                f"[{result.blog}] decision={result.decision} "
                f"quality={result.quality_total:.1f} "
                f"url={result.url or '-'} "
                f"reason={result.reason}"
            )
            if result.report_path:
                print(f"  report: {result.report_path}")
            if result.draft_path:
                print(f"  draft:  {result.draft_path}")

    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))

    errors = [result for result in results if result.error]
    if errors:
        for result in errors:
            print(f"[{result.blog}] ERROR: {result.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
