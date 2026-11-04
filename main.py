from __future__ import annotations

"""

AI 기반 자동 금융·부동산·재테크 리서치 블로그 시스템

Events -> Research Packet -> AI 분석 -> 팩트 검증 -> 기사 생성 -> 게시

사용법:
    python main.py mock           # Mock 모드 전체 파이프라인
    python main.py collect
    python main.py detect
    python main.py research
    python main.py generate
    python main.py publish
    python main.py run             # collect ~ publish 한 번에 실행
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.collectors.collectors import Collectors
from src.config.settings import load_settings
from src.pipeline.collect_step import CollectStep
from src.pipeline.detect_step import DetectStep
from src.pipeline.generate_step import GenerateStep
from src.pipeline.publish_selector import select_articles
from src.pipeline.publish_step import PublishStep
from src.pipeline.research_step import ResearchStep
from src.storage.file_store import JsonStore
from src.utils.logging import setup_logging, get_logger


def main() -> int:
    parser = argparse.ArgumentParser(prog="mvp-blog")
    parser.add_argument(
        "command",
        choices=["mock", "collect", "detect", "research", "generate", "publish", "review", "run", "status"],
        help="실행할 단계",
    )
    parser.add_argument("--config-dir", default=None, help="config 디렉토리 경로")
    parser.add_argument("--publish-backend", default=None, help="publishing backend override")
    parser.add_argument("--date", default=None, help="snapshot 날짜 (YYYY-MM-DD)")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="이번 실행에서 발행할 최대 기사 수 (기본: publishing.daily_limit)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="이전 발행 실패(publish_failed) 기사도 다시 발행 시도",
    )
    args = parser.parse_args()

    import os

    if args.publish_backend:
        os.environ["PUBLISH_BACKEND"] = args.publish_backend

    settings = load_settings(args.config_dir)
    setup_logging(settings.app.log_level)
    logger = get_logger("main")

    if args.command == "mock":
        os.environ["MOCK_MODE"] = "true"
        os.environ["PUBLISH_BACKEND"] = os.environ.get("PUBLISH_BACKEND", "mock")
        settings = load_settings(args.config_dir)

    store = JsonStore(settings)

    if args.command in ("collect", "mock", "run"):
        collect = CollectStep(settings, store)
        result = collect.run()
        snapshots = result["snapshots"]
        news = result["news_items"]
        disclosures = result["disclosures"]
        logger.info("=== collect 완료: %d 스냅샷, %d 뉴스, %d 공시", len(snapshots.snapshots), len(news), len(disclosures))
        _persist_detection_inputs(store, settings, snapshots, news, disclosures)

    if args.command in ("detect", "mock", "run"):
        snapshots, news, disclosures = _load_detection_inputs(store, settings, args.date)
        detect = DetectStep(settings, store)
        events = detect.run(snapshots, news, disclosures)
        logger.info("=== detect 완료: %d 이벤트 선정", len(events))

    if args.command in ("research", "mock", "run"):
        snapshots, news, disc = _load_detection_inputs(store, settings, args.date)
        research = ResearchStep(settings, store, news_provider=Collectors(settings).news())
        failures = 0
        for event_id in _pending_events(store, commands=("detected",)):
            event = store.load_event(event_id)
            report = research.run([event], snapshots, news, disc).get(event_id)
            if report and report.fact_check.approved_claims:
                logger.info("=== research 완료: %s", report.event_id)
            else:
                failures += 1
                logger.warning("=== research 실패/심층필요: %s", event_id)
        logger.info("=== research 종료 (실패 %d)", failures)

    if args.command in ("generate", "mock", "run"):
        generated = 0
        for event_id in _pending_events(store, commands=("analyzing",)):
            event = store.load_event(event_id)
            packet = store.load_research_packet(f"packet_{event_id}")
            report = store.load_analysis(event_id)
            if not packet or not report:
                logger.warning("패킷/분석 없음 skip: %s", event_id)
                continue
            gen = GenerateStep(settings, store)
            article = gen.run(event, packet, report)
            if article:
                generated += 1
                logger.info("=== generate 완료: %s -> %s", article.article_id, article.slug)
        logger.info("=== generate 종료 (approved %d)", generated)

    if args.command in ("publish", "mock", "run"):
        selection = select_articles(
            settings,
            store,
            limit=args.limit,
            retry_failed=args.retry_failed,
        )
        logger.info(
            "=== publish 선정: 오늘 %d건 발행됨 / 한도 %d, 이번 선택 %d건",
            selection.published_today,
            selection.daily_limit,
            len(selection.selected),
        )
        for article_id, reason in selection.skipped[:20]:
            logger.info("=== publish 제외: %s (%s)", article_id, reason)

        publish = PublishStep(settings, store)
        published = []
        for candidate in selection.selected:
            result = publish.run(candidate.article)
            if result and result.ok:
                published.append(result.url)
        logger.info("=== publish 완료: %d건 게시", len(published))

    if args.command == "review":
        articles = store.load_all_articles()
        pending = [a for a in articles if a.status in ("needs_review", "quality_blocked", "publish_failed")]
        logger.info("=== review 대상: %d건", len(pending))
        for article in sorted(pending, key=lambda a: a.created_at, reverse=True):
            readiness = article.readiness or {}
            checks = readiness.get("checks") or {}
            failed = [name for name, ok in checks.items() if not ok]
            logger.info(
                "- %s [%s] quality=%.2f metrics=%d sources=%d",
                article.article_id,
                article.status,
                article.quality_score,
                len(article.data_metrics or {}),
                sum(1 for s in article.sources if "http" in (s or "")),
            )
            logger.info("  title: %s", article.title)
            if failed:
                logger.info("  readiness 실패: %s", ", ".join(failed))
            for note in (article.review_notes or [])[:5]:
                logger.info("  note: %s", note)

    if args.command == "status":
        events = store.load_all_events()
        by_status: dict[str, int] = {}
        for e in events:
            by_status[e.status] = by_status.get(e.status, 0) + 1
        articles = store.load_all_articles()
        logger.info("events: %s", by_status)
        logger.info("articles: %d", len(articles))
    return 0


def _pending_events(store: JsonStore, commands: tuple[str, ...]) -> list[str]:
    return [e.event_id for e in store.load_all_events() if e.status in commands]


def _persist_detection_inputs(store: JsonStore, settings, snapshots, news, disclosures) -> None:
    store.save_raw(
        "latest_pipeline",
        {
            "snapshots": snapshots.model_dump(),
            "news": [i.model_dump() for i in news],
            "disclosures": [d.model_dump() for d in disclosures],
            "date": snapshots.collected_at[:10],
        },
    )


def _load_detection_inputs(store: JsonStore, settings, date: str | None):
    from src.models.market_data import SnapshotCollection
    from src.models.news import NewsItem
    from src.models.disclosure import Disclosure
    import json

    path = settings.storage.path("raw") / "latest_pipeline.json"
    from src.utils.logging import get_logger as _lg

    lg = _lg("main")
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        lg.info("detection inputs 로드 (latest_pipeline, date=%s)", payload.get("date"))
        return (
            SnapshotCollection.model_validate(payload["snapshots"]),
            [NewsItem.model_validate(i) for i in payload["news"]],
            [Disclosure.model_validate(d) for d in payload["disclosures"]],
        )
    if date:
        ss = store.load_snapshots(date)
        if ss:
            return ss, [], []
    lg.warning("detection inputs 없음. 먼저 collect 실행.")
    return SnapshotCollection(), [], []


if __name__ == "__main__":
    raise SystemExit(main())