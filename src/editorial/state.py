from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.settings import PROJECT_ROOT
from src.editorial.models import EditorialArticle, kst_now
from src.editorial.text import body_fingerprint


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _kst_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(kst_now().tzinfo).date().isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "-", value or "").strip()
    return cleaned or "article"


class EditorialState:
    """Per-blog publication history, generated queue, and run artifacts.

    Only ``published.json`` and the generated queue are meant to be committed.
    Run reports are ignored by git and uploaded as CI artifacts.
    """

    def __init__(
        self,
        blog: str,
        base_dir: Path | str | None = None,
        content_root: Path | str | None = None,
    ) -> None:
        self.blog = blog
        root = Path(base_dir) if base_dir else PROJECT_ROOT / "data"
        self.dir = root / "blogs" / blog
        self.published_path = self.dir / "published.json"
        self.runs_dir = self.dir / "runs"
        self.drafts_dir = self.dir / "drafts"
        self.queue_dir = self.dir / "queue"
        self.content_root = Path(content_root) if content_root else PROJECT_ROOT / "content"

    # ------------------------------------------------------------------ load
    def load_published(self) -> list[dict[str, Any]]:
        if not self.published_path.exists():
            return []
        try:
            payload = json.loads(self.published_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            posts = payload.get("posts")
            if isinstance(posts, list):
                return [item for item in posts if isinstance(item, dict)]
        return []

    def published_today(self, now: datetime | None = None) -> int:
        today = (now or kst_now()).date().isoformat()
        count = 0
        for record in self.load_published():
            date = _kst_date(record.get("published_at") or record.get("date"))
            if date == today:
                count += 1
        return count

    def recent_records(self, limit: int = 30) -> list[dict[str, Any]]:
        records = self.load_published()
        records.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
        return records[:limit]

    def recent_titles(self, limit: int = 30) -> list[str]:
        return [str(record.get("title") or "") for record in self.recent_records(limit) if record.get("title")]

    def recent_topics(self, limit: int = 30) -> list[str]:
        return [str(record.get("topic") or "") for record in self.recent_records(limit) if record.get("topic")]

    def published_catalog_ids(self) -> set[str]:
        return {
            str(record.get("catalog_id") or "")
            for record in self.load_published()
            if record.get("catalog_id")
        }

    # ------------------------------------------------------------------ queue
    def article_json_path(self, article_id: str) -> Path:
        return self.queue_dir / f"{_safe_name(article_id)}.json"

    def article_markdown_path(self, article_id: str) -> Path:
        return self.queue_dir / f"{_safe_name(article_id)}.md"

    def save_article(self, article: EditorialArticle) -> tuple[Path, Path]:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.article_json_path(article.article_id)
        markdown_path = self.article_markdown_path(article.article_id)
        self._write_json(json_path, article.model_dump(mode="json"))
        markdown_path.write_text(
            f"# {article.title}\n\n{article.body_with_sources or article.body_markdown}\n",
            encoding="utf-8",
        )
        return json_path, markdown_path

    def load_article(self, article_id: str) -> EditorialArticle | None:
        path = self.article_json_path(article_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            return EditorialArticle.model_validate(payload)
        except Exception:  # noqa: BLE001 - corrupted queue files are skipped
            return None

    def list_articles(self, *, status: str | None = None) -> list[EditorialArticle]:
        if not self.queue_dir.exists():
            return []
        articles: list[EditorialArticle] = []
        for path in sorted(self.queue_dir.glob("*.json")):
            article = self.load_article(path.stem)
            if article is None:
                continue
            if status is None or article.status == status:
                articles.append(article)
        articles.sort(key=lambda item: item.created_at)
        return articles

    def update_article(self, article: EditorialArticle) -> None:
        self.save_article(article)

    # ------------------------------------------------------------------ save
    def save_published(self, record: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        records = self.load_published()
        article_id = str(record.get("article_id") or "")
        if article_id:
            records = [
                existing
                for existing in records
                if str(existing.get("article_id") or "") != article_id
            ]
        records.append(record)
        self._write_json(self.published_path, records)

    def save_run(self, report: dict[str, Any], *, run_id: str | None = None) -> Path:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{run_id or _timestamp()}.json"
        self._write_json(path, report)
        return path

    def save_draft(self, article: EditorialArticle, *, run_id: str | None = None) -> tuple[Path, Path]:
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        stamp = run_id or _timestamp()
        base = f"{stamp}-{article.slug or article.article_id}"
        markdown_path = self.drafts_dir / f"{base}.md"
        json_path = self.drafts_dir / f"{base}.json"
        markdown_path.write_text(
            f"# {article.title}\n\n{article.body_with_sources or article.body_markdown}\n",
            encoding="utf-8",
        )
        self._write_json(json_path, article.to_report())
        return markdown_path, json_path

    def save_content_archive(
        self,
        article: EditorialArticle,
        *,
        content_root: Path | str | None = None,
    ) -> Path:
        root = Path(content_root) if content_root else self.content_root
        out_dir = root / self.blog
        out_dir.mkdir(parents=True, exist_ok=True)
        date = (article.published_at or article.created_at)[:10]
        slug = re.sub(r"[\\/:*?\"<>|]", "-", article.slug or article.article_id)
        path = out_dir / f"{date}-{slug}.md"
        frontmatter = {
            "title": article.title,
            "seo_title": article.seo_title or article.title,
            "blog": self.blog,
            "article_id": article.article_id,
            "catalog_id": article.catalog_id,
            "slug": article.slug,
            "primary_keyword": article.primary_keyword,
            "secondary_keywords": article.secondary_keywords,
            "category": article.category,
            "tags": article.tags,
            "meta_description": article.meta_description,
            "status": article.status,
            "decision": article.decision,
            "decision_reason": article.decision_reason,
            "quality_total": article.quality.total,
            "quality_scores": article.quality.scores.model_dump(),
            "critical_failures": article.quality.critical_failures,
            "framework": article.analysis.framework,
            "framework_result": article.analysis.result,
            "metrics": [metric.model_dump() for metric in article.analysis.metrics],
            "assumptions": [item.model_dump() for item in article.analysis.assumptions],
            "published_url": article.published_url,
            "published_at": article.published_at,
            "sources": [source.model_dump() for source in article.sources],
        }
        path.write_text(
            "---\n"
            + json.dumps(frontmatter, ensure_ascii=False, indent=2)
            + "\n---\n\n"
            + (article.body_with_sources or article.body_markdown)
            + "\n",
            encoding="utf-8",
        )
        return path

    def record_from_article(self, article: EditorialArticle, *, url: str = "") -> dict[str, Any]:
        return {
            "article_id": article.article_id,
            "catalog_id": article.catalog_id,
            "date": (article.published_at or article.created_at)[:10],
            "published_at": article.published_at or _iso_now(),
            "title": article.title,
            "url": url or article.published_url or "",
            "slug": article.slug,
            "topic": article.topic.topic,
            "primary_keyword": article.primary_keyword,
            "category": article.category,
            "status": article.status,
            "decision": article.decision,
            "framework": article.analysis.framework,
            "framework_result": article.analysis.result,
            "quality_total": article.quality.total,
            "quality_scores": article.quality.scores.model_dump(),
            "content_hash": hashlib.sha1(
                (article.body_with_sources or article.body_markdown).encode("utf-8")
            ).hexdigest(),
            "body_fingerprint": body_fingerprint(article.body_markdown),
            "sources": [
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "url": source.url,
                    "publisher": source.publisher,
                    "published_at": source.published_at,
                }
                for source in article.sources
            ],
        }

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
