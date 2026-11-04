from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.config.settings import Settings
from src.models.article import Article
from src.publishers.base import BasePublisher, PublishResult
from src.publishers.safety_check import run_pre_publish_checks
from src.publishers.tistory_editor_adapter import (
    TistoryBrokenImageError,
    TistoryEditorAdapter,
    TistoryError,
    TistorySelectorError,
    TistorySessionExpiredError,
)
from src.publishers.tistory_selectors import TistorySelectors
from src.renderers.tistory_html_renderer import TistoryHtmlRenderer
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from playwright.sync_api import Page, sync_playwright

logger = get_logger(__name__)

_ARTIFACT_DIR = Path("artifacts") / "tistory-errors"
_LOGIN_URL_PATTERN = re.compile(r"(auth/login|login\.tistory|login_id)", re.IGNORECASE)


class TistoryPublisher(BasePublisher):
    """Playwright 로그인 세션 기반 티스토리 자동 발행.

    - Tistory Open API / Access Token 을 사용하지 않는다.
    - 첫 로그인은 scripts/tistory_login.py 로 생성한 storage_state 를 재사용한다.
    - 기본 전략: 비공개(private) 발행 -> URL/본문 검증 -> 선택적으로 공개 처리(설정).
    """

    name = "tistory"

    def __init__(
        self,
        settings: Settings,
        store: JsonStore,
        blog_url: str | None = None,
        storage_state: str | None = None,
    ) -> None:
        super().__init__(settings, store)
        self.blog_url = blog_url or settings.tistory.blog_url or ""
        self.storage_state = storage_state
        self.renderer = TistoryHtmlRenderer()

    # ------------------------------------------------------------------ 상태
    @property
    def connected(self) -> bool:
        if os.environ.get("TISTORY_STORAGE_STATE"):
            return True
        if self.storage_state and Path(self.storage_state).exists():
            return True
        return Path(self.settings.tistory.storage_state_path).exists()

    @property
    def dry_run(self) -> bool:
        return bool(self.settings.tistory.dry_run)

    def _session_file(self) -> Path:
        env_state = os.environ.get("TISTORY_STORAGE_STATE", "").strip()
        if env_state:
            out = Path(self.settings.tistory.storage_state_path)
            self._decode_session_env(env_state, out)
            return out
        if self.storage_state and Path(self.storage_state).exists():
            return Path(self.storage_state)
        return Path(self.settings.tistory.storage_state_path)

    @staticmethod
    def _decode_session_env(encoded: str, out: Path) -> None:
        try:
            raw = base64.b64decode(encoded)
            json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise TistoryError(f"TISTORY_STORAGE_STATE decode failed: {e}") from e
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)

    # ------------------------------------------------------------ 발행 진입
    def publish(self, article: Article, markdown: str, images: list[str] | None = None) -> PublishResult:
        self._set_status(article, "READY")

        check = run_pre_publish_checks(article, self.settings.content.categories, images or [])
        if not check.ok:
            self._set_status(article, "FAILED", error_code="TISTORY_PRE_CHECK_FAILED", message="; ".join(check.issues))
            return PublishResult(ok=False, url="", article_id=article.article_id, message="; ".join(check.issues), error_code="TISTORY_PRE_CHECK_FAILED")

        if not self.connected:
            self._set_status(article, "FAILED", error_code="TISTORY_SESSION_REQUIRED", message="storage state not found")
            return PublishResult(ok=False, url="", article_id=article.article_id, message="storage state not found", error_code="TISTORY_SESSION_REQUIRED")

        adopted = self._recover_existing_url(article)
        if adopted:
            self._set_status(article, "PUBLISHED", url=adopted)
            return PublishResult(ok=True, url=adopted, article_id=article.article_id, message="recovered already published")

        if self.dry_run:
            return self._dry_run(article, markdown, images)

        self._set_status(article, "PUBLISHING")
        try:
            url = self._publish_with_retry(article, markdown, images or [])
        except TistoryError as e:
            self._set_status(article, "FAILED", error_code=e.error_code, message=e.message)
            return PublishResult(ok=False, url="", article_id=article.article_id, message=e.message, error_code=e.error_code)
        except Exception as e:
            self._set_status(article, "FAILED", error_code="TISTORY_UNKNOWN", message=str(e))
            return PublishResult(ok=False, url="", article_id=article.article_id, message=str(e), error_code="TISTORY_UNKNOWN")

        self._set_status(article, "PUBLISHED", url=url)
        return PublishResult(
            ok=True,
            url=url,
            article_id=article.article_id,
            message=json.dumps({"status": "published", "platform": "tistory", "article_id": article.article_id, "url": url, "published_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False),
        )

    # ------------------------------------------------------------ Dry Run
    def _dry_run(self, article: Article, markdown: str, images: list[str] | None) -> PublishResult:
        logger.info("[tistory] DRY RUN: %s", article.article_id)
        self._set_status(article, "DRY_RUN")
        try:
            self._browser_flow(article, markdown, images or [], dry_run=True)
        except TistoryError as e:
            logger.warning("[tistory] dry run failed: %s %s", e.error_code, e.message)
            return PublishResult(ok=False, url="", article_id=article.article_id, message=f"dry-run {e.error_code}: {e.message}", error_code=e.error_code)
        return PublishResult(ok=False, url="", article_id=article.article_id, message="dry run (no publish)", error_code="TISTORY_DRY_RUN")

    # ------------------------------------------------------------ 재시도 정책
    def _publish_with_retry(self, article: Article, markdown: str, images: list[str]) -> str:
        max_attempts = 1 + int(self.settings.tistory.max_retries)
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self._browser_flow(article, markdown, images, dry_run=False)
            except (TistorySessionExpiredError, TistorySelectorError, TistoryBrokenImageError, TistoryError) as e:
                raise  # 세션 만료 / 셀렉터 / 이미지 오류는 재시도하지 않는다.
            except Exception as e:
                last_error = e
                logger.warning("[tistory] publish attempt %d/%d failed (transient): %s", attempt, max_attempts, e)
                time.sleep(2 * attempt)
        raise TistoryError(f"transient publish failure after {max_attempts} attempts: {last_error}")

    # ------------------------------------------------------------ 브라우저 흐름
    def _browser_flow(self, article: Article, markdown: str, images: list[str], dry_run: bool) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.settings.tistory.headless)
            try:
                context = browser.new_context(storage_state=str(self._session_file()))
                page = context.new_page()
                page.set_default_timeout(self.settings.tistory.timeout)
                # 네이티브 confirm/alert (예: "이어서 작성하시겠습니까?") 는 수락한다.
                page.on("dialog", lambda d: d.accept())
                try:
                    url = self._run_in_page(page, article, markdown, images)
                    if url:
                        self._verify_published(page, url, article, images)
                    return url
                except Exception:
                    if self.settings.tistory.screenshot_on_error:
                        self._save_error_artifacts(page, article)
                    raise
                finally:
                    context.close()
            finally:
                browser.close()

    def _run_in_page(self, page: "Page", article: Article, markdown: str, images: list[str]) -> str:
        self._goto_editor(page)
        adapter = TistoryEditorAdapter(page, TistorySelectors.from_settings(self.settings), timeout=self.settings.tistory.timeout)

        adapter.set_title(article.title)

        image_map: dict[str, str] = {}
        if images and not self.dry_run:
            image_map = adapter.upload_images(images)
        html = self.renderer.resolve_local_images(markdown, image_map)
        adapter.set_content(html)

        if not self.dry_run:
            raw_cat = article.category if article.category in self.settings.content.categories else ""
            category = self.settings.tistory.category_map.get(raw_cat, raw_cat)
            adapter.set_category(category)
            if article.tags:
                adapter.set_tags(article.tags)
            adapter.set_visibility(article.visibility or self.settings.tistory.default_visibility)
            candidates = self._entry_slug_candidates(article)
            return adapter.publish(self.settings.tistory.publish_delay_seconds, expect_url_slugs=candidates)
        return ""

    def _goto_editor(self, page: "Page") -> None:
        url = self._editor_url()
        page.goto(url, wait_until="domcontentloaded", timeout=self.settings.tistory.timeout)
        self._ensure_logged_in(page)

    def _entry_slug_candidates(self, article) -> list[str]:
        title = article.title or article.slug or ""
        raw = "-".join(re.sub(r"[^0-9A-Za-z가-힣 ]", "", title).strip().split())
        seo = (article.slug or "").strip("-").replace(" ", "-")
        seen: list[str] = []
        for s in (raw, seo):
            if s and s not in seen:
                seen.append(s)
        return seen

    def _editor_url(self) -> str:
        if self.settings.tistory.editor_url:
            return self.settings.tistory.editor_url
        blog = self._blog_sub()
        if blog:
            # 새 티스토리 에디터: https://{blog}.tistory.com/manage/post (글로 리다이렉트됨)
            return f"https://{blog}.tistory.com/manage/post"
        return "https://www.tistory.com/manage/post"

    def _blog_sub(self) -> str:
        m = re.search(r"https?://([A-Za-z0-9_-]+)\.tistory\.com", self.blog_url or "")
        if m:
            return m.group(1)
        return (self.blog_url or "").strip().rstrip("/")

    def _ensure_logged_in(self, page: "Page") -> None:
        if _LOGIN_URL_PATTERN.search(page.url):
            raise TistorySessionExpiredError(f"redirected to login page: {page.url}")
        page.wait_for_load_state("domcontentloaded")
        sel = TistorySelectors.from_settings(self.settings)
        login_form = page.locator(sel.get("LOGIN_FORM", "")).first if sel.get("LOGIN_FORM", "") else None
        if login_form is not None:
            try:
                login_form.wait_for(state="attached", timeout=3000)
                raise TistorySessionExpiredError("login form detected (session expired)")
            except TistorySessionExpiredError:
                raise
            except Exception:
                pass
        logger.info("[tistory] logged-in session OK (url=%s)", page.url)

    # ------------------------------------------------------------ 발행 검증
    def _verify_published(self, page: "Page", url: str, article: Article, images: list[str]) -> None:
        if not url or "/entry/" not in url:
            raise TistoryError(f"published URL not confirmed (url={url!r})")
        page.goto(url, wait_until="domcontentloaded")
        title = page.title() or ""
        if article.title and article.title[:10] not in title:
            logger.warning("[tistory] published title mismatch: %s", title)
        body_len = len(page.locator("body").inner_text() or "")
        if body_len < 100:
            raise TistoryError(f"published page looks empty (body={body_len} chars)")
        if images:
            visible = page.locator("img").count()
            if visible < 1:
                logger.warning("[tistory] published page has no images")
        logger.info("[tistory] verified: %s (%d chars)", url, body_len)

    # ------------------------------------------------------------ 오류 아티팩트
    def _save_error_artifacts(self, page: "Page", article: Article) -> None:
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = article.slug or article.article_id
            out = _ARTIFACT_DIR
            out.mkdir(parents=True, exist_ok=True)
            img = out / f"publish_failed_{ts}_{slug}.png"
            page.screenshot(path=str(img), full_page=True)
            html = out / f"publish_failed_{ts}_{slug}.html"
            html.write_text(page.content(), encoding="utf-8")
            err = out / f"publish_failed_{ts}_{slug}.txt"
            err.write_text(f"article_id={article.article_id}\nurl={page.url}\n", encoding="utf-8")
            logger.info("[tistory] error artifacts saved: %s", out)
        except Exception as e:  # pragma: no cover - 아티팩트 저장 실패는 치명적이지 않다
            logger.warning("[tistory] failed to save error artifacts: %s", e)

    # ------------------------------------------------------------ 상태 마커
    def _set_status(self, article: Article, status: str, url: str = "", error_code: str = "", message: str = "") -> None:
        payload = {
            "article_id": article.article_id,
            "event_id": article.event.event_id,
            "content_hash": article.content_hash,
            "publish_status": status,
            "platform": "tistory",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if url:
            payload["url"] = url
        if error_code:
            payload["error_code"] = error_code
        if message:
            payload["error_message"] = message
        self.store.save_published_marker(f"status_{article.article_id}", payload)
        logger.info("[tistory] publish_status=%s %s", status, article.article_id)

    # ------------------------------------------------------------ 세션 복구
    def _recover_existing_url(self, article: Article) -> str | None:
        marker = self.store.load_published_marker(f"status_{article.article_id}")
        if not marker or marker.get("publish_status") != "PUBLISHING":
            return None
        logger.info("[tistory] found PUBLISHING marker, checking for existing post: %s", article.title)
        existing = self._find_existing_by_title(article.title)
        if existing:
            logger.info("[tistory] recovered existing post: %s", existing)
            return existing
        return None

    def _find_existing_by_title(self, title: str) -> str | None:
        if not self.blog_url:
            return None
        rss_url = f"{self.blog_url}/rss"
        import urllib.request

        try:
            req = urllib.request.Request(rss_url, headers={"User-Agent": "fin-research-blog/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning("[tistory] rss fetch failed: %s", e)
            return None
        target = self._normalize_title(title)
        m = re.finditer(r"<item>.*?</item>", body, re.DOTALL)
        for item in m:
            chunk = item.group(0)
            title_m = re.search(r"<title>(.*?)</title>", chunk, re.DOTALL)
            link_m = re.search(r"<link>(.*?)</link>", chunk, re.DOTALL)
            if title_m and self._normalize_title(self._unescape(title_m.group(1))) == target and link_m:
                return self._unescape(link_m.group(1)).strip()
        return None

    @staticmethod
    def _normalize_title(title: str) -> str:
        return re.sub(r"\s+", "", title or "")

    @staticmethod
    def _unescape(text: str) -> str:
        import html

        return html.unescape(text)