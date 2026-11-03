from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from src.config.settings import Settings
from src.models.analysis import AnalysisReport
from src.models.article import Article
from src.models.event import Event
from src.models.market_data import SnapshotCollection
from src.models.research_packet import ResearchPacket
from src.utils.logging import get_logger

T = TypeVar("T", bound=BaseModel)
logger = get_logger(__name__)


class JsonStore:
    """data/ 디렉토리 대상 JSON 파일 저장소. 파일 단위로 상태 보존."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.base = settings.storage.base_path
        for key in (
            "raw",
            "normalized",
            "events",
            "research",
            "cache",
            "processed",
            "published",
        ):
            settings.storage.path(key).mkdir(parents=True, exist_ok=True)
        Path(settings.content.output_dir).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ raw
    def save_raw(self, key: str, payload: dict) -> Path:
        path = self.s.storage.path("raw") / f"{key}.json"
        return self._write(path, payload)

    # ------------------------------------------------------------ snapshots
    def save_snapshots(self, collection: SnapshotCollection) -> Path:
        date = collection.collected_at[:10]
        path = self.s.storage.path("processed") / f"snapshots_{date}.json"
        return self._write(path, collection.model_dump())

    def load_snapshots(self, date: str) -> SnapshotCollection | None:
        path = self.s.storage.path("processed") / f"snapshots_{date}.json"
        if not path.exists():
            return None
        return SnapshotCollection.model_validate(self._read(path))

    def save_individual_snapshot(self, collection: SnapshotCollection) -> None:
        for snapshot in collection.snapshots:
            path = self.s.storage.path("processed") / f"snapshot_{snapshot.ticker}.json"
            self._write(path, snapshot.model_dump())

    # --------------------------------------------------------------- events
    def save_event(self, event: Event) -> Path:
        path = self.s.storage.path("events") / f"{event.event_id}.json"
        return self._write(path, event.model_dump())

    def load_event(self, event_id: str) -> Event | None:
        path = self.s.storage.path("events") / f"{event_id}.json"
        if not path.exists():
            return None
        return Event.model_validate(self._read(path))

    def load_all_events(self) -> list[Event]:
        events = []
        for path in sorted(self.s.storage.path("events").glob("*.json")):
            try:
                events.append(Event.model_validate(self._read(path)))
            except Exception as e:
                logger.warning("skip broken event file %s: %s", path.name, e)
        return events

    def events_for_date(self, date: str) -> list[Event]:
        return [e for e in self.load_all_events() if (e.event_date or e.detected_at[:10]) == date]

    # -------------------------------------------------------------- research
    def save_research_packet(self, packet: ResearchPacket) -> Path:
        path = self.s.storage.path("research") / f"{packet.packet_id}.json"
        return self._write(path, packet.model_dump())

    def load_research_packet(self, packet_id: str) -> ResearchPacket | None:
        path = self.s.storage.path("research") / f"{packet_id}.json"
        if not path.exists():
            return None
        return ResearchPacket.model_validate(self._read(path))

    # -------------------------------------------------------------- analysis
    def save_analysis(self, report: AnalysisReport) -> Path:
        path = self.s.storage.path("research") / f"{report.event_id}_analysis.json"
        return self._write(path, report.model_dump())

    def load_analysis(self, event_id: str) -> AnalysisReport | None:
        path = self.s.storage.path("research") / f"{event_id}_analysis.json"
        if not path.exists():
            return None
        return AnalysisReport.model_validate(self._read(path))

    # -------------------------------------------------------------- articles
    def save_article(self, article: Article) -> Path:
        path = self.s.storage.path("processed") / f"article_{article.article_id}.json"
        return self._write(path, article.model_dump())

    def load_article(self, article_id: str) -> Article | None:
        path = self.s.storage.path("processed") / f"article_{article_id}.json"
        if not path.exists():
            return None
        return Article.model_validate(self._read(path))

    def load_all_articles(self) -> list[Article]:
        articles = []
        for path in self.s.storage.path("processed").glob("article_*.json"):
            try:
                articles.append(Article.model_validate(self._read(path)))
            except Exception as e:
                logger.warning("skip broken article %s: %s", path.name, e)
        return articles

    # ------------------------------------------------------------- published
    def save_published_marker(self, key: str, payload: dict) -> Path:
        path = self.s.storage.path("published") / f"{key}.json"
        return self._write(path, payload)

    def load_published_keys(self) -> list[str]:
        return [p.stem for p in self.s.storage.path("published").glob("*.json")]

    def published_exists(self, key: str) -> bool:
        return (self.s.storage.path("published") / f"{key}.json").exists()

    def load_published_marker(self, key: str) -> dict | None:
        path = self.s.storage.path("published") / f"{key}.json"
        if not path.exists():
            return None
        try:
            return self._read(path)
        except Exception as e:  # pragma: no cover - 손상된 마커 무시
            logger.warning("skip broken published marker %s: %s", path.name, e)
            return None

    # -------------------------------------------------------------- helpers
    def _read(self, path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, path: Path, payload: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(path)
        return path