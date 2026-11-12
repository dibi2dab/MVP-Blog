from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import Settings
from src.models.article import Article
from src.publishers.base import BasePublisher, PublishResult
from src.publishers.safety_check import run_pre_publish_checks
from src.renderers.tistory_html_renderer import TistoryHtmlRenderer
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger

logger = get_logger(__name__)

_RESULT_SENTINEL = "__PUBLISH_RESULT__"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_NODE_SCRIPT = _PROJECT_ROOT / "src" / "publishCli.js"
_NODE_TIMEOUT_SECONDS = 300


@dataclass
class PublishTarget:
    """Per-blog publishing overrides.

    The default Obsidian pipeline keeps using the global env/settings. The new
    editorial pipeline passes one of these so Crystal and Quartz can use their
    own blog name, session file, Kakao credentials, and error-artifact folder.
    """

    blog_name: str = ""
    storage_state_path: str = ""
    kakao_id: str = ""
    kakao_password: str = ""
    artifact_dir: str = ""
    category_map: dict[str, str] = field(default_factory=dict)
    visibility: str = ""
    headless: bool | None = None
    dry_run: bool | None = None


class NodeTistoryPublisher(BasePublisher):
    """생성된 기사(제목 + HTML)를 Node/Playwright 발행 엔진으로 넘겨 발행한다.

    - 콘텐츠 생성은 기존 Python 파이프라인(주식 데이터)이 담당한다.
    - 실제 티스토리 에디터 조작은 src/publishTistory.js 가 담당한다.
    - 기존 Python Playwright 발행기(src.publishers.tistory_publisher)는 폴백으로 남겨둔다.
    """

    name = "tistory-node"

    def __init__(self, settings: Settings, store: JsonStore, target: PublishTarget | None = None) -> None:
        super().__init__(settings, store)
        self.target = target or PublishTarget()
        self.renderer = TistoryHtmlRenderer()

    # ------------------------------------------------------------------ 상태
    @property
    def connected(self) -> bool:
        if self.target.storage_state_path:
            return Path(self.target.storage_state_path).exists()
        if os.environ.get("TISTORY_STORAGE_STATE"):
            return True
        return Path(self.settings.tistory.storage_state_path).exists()

    @property
    def dry_run(self) -> bool:
        if self.target.dry_run is not None:
            return bool(self.target.dry_run)
        return bool(self.settings.tistory.dry_run)

    # ------------------------------------------------------------ 발행 진입
    def publish(self, article: Article, markdown: str, images: list[str] | None = None) -> PublishResult:
        check = run_pre_publish_checks(article, self.settings.content.categories, images or [])
        if not check.ok:
            message = "; ".join(check.issues)
            return PublishResult(
                ok=False,
                url="",
                article_id=article.article_id,
                message=message,
                error_code="TISTORY_PRE_CHECK_FAILED",
            )

        payload = self._build_payload(article, markdown, images or [])
        return self.publish_payload(payload, article_id=article.article_id)

    def publish_payload(self, payload: dict, article_id: str = "") -> PublishResult:
        """Publish an already-built payload.

        Editorial articles use this path because their safety checks and quality
        gates live in ``src.editorial.quality`` rather than the stock-specific
        pre-publish checks.
        """

        if self.dry_run:
            logger.info("[tistory-node] DRY RUN: %s", article_id or payload.get("title", ""))
            return PublishResult(
                ok=False,
                url="",
                article_id=article_id,
                message="dry run (no publish)",
                error_code="TISTORY_DRY_RUN",
            )

        node = shutil.which("node")
        if not node:
            return PublishResult(
                ok=False,
                url="",
                article_id=article_id,
                message="node 실행 파일을 찾을 수 없습니다. Node.js 를 설치하세요.",
                error_code="TISTORY_NODE_MISSING",
            )

        result = self._run_node(node, payload)
        if not result.get("ok"):
            message = str(result.get("error") or "node publish failed")
            error_code = str(result.get("errorCode") or "TISTORY_PUBLISH_FAILED")
            logger.error("[tistory-node] publish failed (%s): %s", error_code, message)
            return PublishResult(
                ok=False,
                url="",
                article_id=article_id,
                message=message,
                error_code=error_code,
            )

        url = str(result.get("publishedUrl") or "")
        logger.info("[tistory-node] published: %s", url)
        return PublishResult(
            ok=True,
            url=url,
            article_id=article_id,
            message=json.dumps(
                {
                    "status": "published",
                    "platform": "tistory",
                    "engine": "node",
                    "article_id": article_id,
                    "url": url,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            ),
        )

    # ------------------------------------------------------------- payload
    def _build_payload(self, article: Article, markdown: str, images: list[str]) -> dict:
        html = self._strip_leading_title_heading(self.renderer.render(markdown), article.title)
        image_paths = [str(Path(p).resolve()) for p in images if p and Path(p).exists()]
        raw_category = article.category if article.category in self.settings.content.categories else ""
        category = self.target.category_map.get(raw_category)
        if category is None:
            category = self.settings.tistory.category_map.get(raw_category, raw_category)
        payload = {
            "title": article.title,
            "contentHtml": html,
            "tags": list(article.tags or []),
            "tistoryCategory": category or "",
            "visibility": self.target.visibility or article.visibility or self.settings.tistory.default_visibility,
            "blogName": self._blog_sub(),
            "imagePaths": image_paths,
            "debug": not self.settings.tistory.headless,
        }
        self._apply_target_overrides(payload)
        return payload

    def _apply_target_overrides(self, payload: dict) -> None:
        target = self.target
        if target.blog_name:
            payload["blogName"] = target.blog_name
        if target.storage_state_path:
            payload["storageStatePath"] = target.storage_state_path
        if target.kakao_id:
            payload["kakaoId"] = target.kakao_id
        if target.kakao_password:
            payload["kakaoPassword"] = target.kakao_password
        if target.artifact_dir:
            payload["artifactDir"] = target.artifact_dir
        if target.headless is not None:
            payload["headless"] = bool(target.headless)
        if target.visibility:
            payload["visibility"] = target.visibility

    @staticmethod
    def _strip_leading_title_heading(html: str, title: str) -> str:
        """본문 맨 앞의 <h1>제목</h1> 이 글 제목과 같으면 제거한다.

        티스토리에는 별도 제목 필드가 있으므로 본문 H1과 중복되는 것을 막는다.
        """
        match = re.match(r"^\s*<h1[^>]*>(?P<text>.*?)</h1>\s*", html, flags=re.DOTALL)
        if not match:
            return html
        text = re.sub(r"<[^>]+>", "", match.group("text")).replace("&amp;", "&").strip()
        if text == (title or "").strip():
            return html[match.end():]
        return html

    def _run_node(self, node: str, payload: dict) -> dict:
        fd, payload_path = tempfile.mkstemp(prefix="tistory_payload_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            proc = subprocess.run(
                [node, str(_NODE_SCRIPT), payload_path],
                cwd=str(_PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_NODE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "node publish timed out", "errorCode": "TISTORY_TIMEOUT"}
        finally:
            try:
                os.unlink(payload_path)
            except OSError:
                pass

        stderr = (proc.stderr or "").strip()
        # 발행 중 Node 쪽 경고(임시저장 태그 정리 등)는 성공 시에도 남겨 디버깅에 쓴다.
        for line in stderr.splitlines():
            if line.startswith("[tistory]"):
                logger.warning(line)

        for line in reversed((proc.stdout or "").splitlines()):
            if _RESULT_SENTINEL in line:
                raw = line.split(_RESULT_SENTINEL, 1)[1].strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    break

        logger.warning("[tistory-node] no result sentinel (exit=%s): %s", proc.returncode, stderr[-800:])
        return {
            "ok": False,
            "error": stderr[-800:] or f"node exited with {proc.returncode}",
            "errorCode": "TISTORY_NODE_ERROR",
        }

    def _blog_sub(self) -> str:
        if self.target.blog_name:
            return self.target.blog_name
        blog_url = self.settings.tistory.blog_url or ""
        match = re.search(r"https?://([A-Za-z0-9_-]+)\.tistory\.com", blog_url)
        if match:
            return match.group(1)
        return blog_url.strip().rstrip("/")
