from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.publishers.tistory_selectors import TistorySelectors
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

logger = get_logger(__name__)


class TistoryError(RuntimeError):
    error_code = "TISTORY_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TistorySessionExpiredError(TistoryError):
    error_code = "TISTORY_SESSION_EXPIRED"


class TistorySelectorError(TistoryError):
    error_code = "TISTORY_SELECTOR_MISSING"

    def __init__(self, selector_key: str, message: str = "") -> None:
        super().__init__(message or f"editor selector not found: {selector_key}")
        self.selector_key = selector_key


class TistoryBrokenImageError(TistoryError):
    error_code = "TISTORY_IMAGE_UPLOAD_FAILED"


class TistoryEditorAdapter:
    """티스토리 글쓰기 에디터 조작 어댑터.

    DOM 셀렉터 기반으로 동작하며, 티스토리 UI 변경 시 selector/상수만 교체하면
    어댑터 로직은 유지한다. 가능한 경우 에디터가 제공하는 HTML 모드(textarea)를
    활용해 HTML 콘텐츠를 삽입한다.
    """

    def __init__(self, page: "Page", selectors: TistorySelectors | None = None, timeout: int = 30000) -> None:
        self.page = page
        self.sel = selectors or TistorySelectors()
        self.timeout = timeout

    # ------------------------------------------------------------------ 유틸
    def _candidate(self, *keys: str) -> "Locator | None":
        for key in keys:
            selector = self.sel.get(key, "")
            if not selector:
                continue
            loc = self.page.locator(selector).first
            try:
                loc.wait_for(state="attached", timeout=self.timeout)
                return loc
            except Exception:
                continue
        return None

    def _require(self, key: str, *candidates: str) -> "Locator":
        loc = self._candidate(*([key] + list(candidates)))
        if loc is None:
            raise TistorySelectorError(key)
        return loc

    def _visible_locator(self, key: str, timeout: int = 5000) -> "bool":
        selector = self.sel.get(key, "")
        if not selector:
            return False
        loc = self.page.locator(selector).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    # -------------------------------------------------------------- 제목 입력
    def set_title(self, title: str) -> None:
        loc = self._require("TITLE")
        loc.clear()
        loc.fill(title)
        logger.info("[tistory] title set (%d chars)", len(title))

    # -------------------------------------------------------------- 본문 입력
    def set_content(self, html: str) -> None:
        # 새 티스토리 에디터는 iframe(시각)이 기본 표시 상태라 시각 주입을 우선한다.
        if self._try_visual_editor(html):
            return
        if self._try_html_mode(html):
            return
        raise TistorySelectorError("EDITOR")

    def _try_html_mode(self, html: str) -> bool:
        if self._visible_locator("HTML_TEXTAREA", timeout=2000):
            textarea = self._require("HTML_TEXTAREA")
            try:
                textarea.fill(html, timeout=3000)
            except Exception:
                # 숨김 textarea (CodeMirror 계열) 는 DOM 값 설정으로 우회한다.
                textarea.evaluate("(el, h) => { el.value = h; el.dispatchEvent(new Event('input', {bubbles: true})); }", html)
            value = textarea.input_value()
            if value == html:
                logger.info("[tistory] content inserted via HTML textarea (%d chars)", len(html))
                return True
            raise TistorySelectorError("HTML_TEXTAREA", "html textarea content mismatch")
        if self._visible_locator("HTML_MODE_BUTTON", timeout=2000):
            self._require("HTML_MODE_BUTTON").click()
            self.page.wait_for_load_state("domcontentloaded")
            textarea = self._require("HTML_TEXTAREA")
            try:
                textarea.fill(html, timeout=3000)
            except Exception:
                textarea.evaluate("(el, h) => { el.value = h; el.dispatchEvent(new Event('input', {bubbles: true})); }", html)
            logger.info("[tistory] content inserted via HTML mode toggle (%d chars)", len(html))
            return True
        return False

    def _try_visual_editor(self, html: str) -> bool:
        loc = self._candidate("VISUAL_EDITOR")
        if loc is None:
            return False
        tag = loc.evaluate("el => el.tagName.toLowerCase()")
        if tag == "iframe":
            fid = loc.get_attribute("id") or ""
            frame = next(
                (f for f in self.page.frames if f.name and fid and f.name == fid),
                None,
            )
            if frame is None:
                frame = next((f for f in self.page.frames if fid and fid in f.url and f != self.page.main_frame), None)
            if frame is None:
                return False
            frame.evaluate(
                "(h) => { const b = document.body; b.innerHTML = h; b.dispatchEvent(new Event('input', {bubbles: true})); }",
                html,
            )
        else:
            loc.evaluate("(el, html) => { el.innerHTML = html; el.dispatchEvent(new Event('input', {bubbles: true})); }", html)
        logger.info("[tistory] content inserted via visual editor DOM (%d chars)", len(html))
        return True

    # ------------------------------------------------------------ 이미지 업로드
    def upload_images(self, paths: list[str]) -> dict[str, str]:
        """로컬 차트를 에디터에 업로드.

        새 에디터는 툴바 '첨부' → '사진' 메뉴가 OS 파일 선택기를 열므로
        file_chooser(set_files) 경로로 업로드하고, 삽입된 <img> URL 을
        {파일명: 업로드URL} 매핑으로 반환한다. 구 에디터는 FILE_INPUT 폴백.
        """
        paths = [p for p in paths if Path(p).exists()]
        if not paths:
            return {}
        try:
            return self._upload_via_attach(paths)
        except Exception as e:
            logger.warning("[tistory] attach-based upload failed (%s); falling back to file input", e)
        return self._upload_via_file_input(paths)

    def _upload_via_attach(self, paths: list[str]) -> dict[str, str]:
        attach = self._require("ATTACH_BUTTON")
        attach.click(timeout=5000)
        self.page.wait_for_timeout(800)
        before = self._collected_editor_img_srcs()
        with self.page.expect_file_chooser(timeout=min(self.timeout, 20000)) as fc_info:
            self._require("ATTACH_PHOTO_MENU").first.click(timeout=5000)
        fc_info.value.set_files(paths)
        deadline = time.monotonic() + 60
        after: list[str] = []
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(1500)
            after = self._collected_editor_img_srcs()
            if len([u for u in after if u not in before]) >= len(paths):
                break
        new_srcs = [u for u in after if u not in before]
        if len(new_srcs) != len(paths):
            logger.warning("[tistory] uploaded images mismatch: files=%d inserted=%d", len(paths), len(new_srcs))
            if len(new_srcs) < len(paths):
                raise TistoryBrokenImageError(
                    f"image upload incomplete: {len(new_srcs)}/{len(paths)} "
                    f"(missing: {', '.join(Path(p).name for p in paths[len(new_srcs):])})"
                )
        ordered_files = [Path(p).name for p in paths]
        logger.info("[tistory] images uploaded via attach: %d", len(new_srcs))
        return {name: url for name, url in zip(ordered_files, new_srcs)}

    def _upload_via_file_input(self, paths: list[str]) -> dict[str, str]:
        if not self._visible_locator("VISUAL_EDITOR", timeout=3000):
            self._try_visual_mode_toggle()

        file_input = self._require("FILE_INPUT")
        inserted: list[str] = self._collected_img_srcs()
        file_input.set_input_files(paths)
        self.page.wait_for_timeout(1500)

        after: list[str] = self._collected_img_srcs()
        new_srcs = [u for u in after if u not in inserted]
        if len(new_srcs) != len(paths):
            logger.warning("[tistory] uploaded images mismatch: files=%d inserted=%d", len(paths), len(new_srcs))
            if len(new_srcs) < len(paths):
                raise TistoryBrokenImageError(
                    f"image upload incomplete: {len(new_srcs)}/{len(paths)} (missing: "
                    + ", ".join(Path(p).name for p in paths[len(new_srcs):])
                    + ")"
                )
        ordered_files = [Path(p).name for p in sorted(paths)]
        return {name: url for name, url in zip(ordered_files, new_srcs)}

    def _collected_editor_img_srcs(self) -> list[str]:
        frame = self._editor_frame()
        if frame is None:
            return self._collected_img_srcs()
        try:
            return frame.evaluate(
                """() => Array.from(document.querySelectorAll('img')).map(
                    i => i.src || '').filter(s => s.startsWith('http') || s.startsWith('/'))"""
            )
        except Exception:
            return self._collected_img_srcs()

    def _editor_frame(self):
        loc = self._candidate("VISUAL_EDITOR")
        if loc is None:
            return None
        if loc.evaluate("el => el.tagName.toLowerCase()") != "iframe":
            return None
        fid = loc.get_attribute("id") or ""
        for f in self.page.frames:
            if f.name and fid and f.name == fid:
                return f
        return next((f for f in self.page.frames if f != self.page.main_frame and fid and fid in f.url), None)

    def _collected_img_srcs(self) -> list[str]:
        return self.page.evaluate(
            """() => Array.from(document.querySelectorAll('img')).map(
                i => i.src || '').filter(s => s.startsWith('http') || s.startsWith('/'))"""
        )

    def _try_visual_mode_toggle(self) -> None:
        if self._visible_locator("VISUAL_MODE_BUTTON", timeout=2000):
            self._require("VISUAL_MODE_BUTTON").click()
            self.page.wait_for_load_state("domcontentloaded")

    # -------------------------------------------------------------- 카테고리
    def set_category(self, name: str) -> None:
        if not name:
            logger.info("[tistory] category not configured; 기본 카테고리 사용")
            return
        select = self._candidate("CATEGORY_SELECT")
        if select is not None:
            try:
                select.select_option(label=name)
                logger.info("[tistory] category set via select: %s", name)
                return
            except Exception:
                try:
                    select.select_option(index=0)
                    logger.info("[tistory] category matched by index 0")
                    return
                except Exception:
                    pass
        button = self._candidate("CATEGORY_DROPDOWN")
        if button is not None:
            button.click()
            self.page.wait_for_timeout(800)
            # 티스토리 새 에디터는 TinyMCE floatpanel 메뉴로 카테고리를 연다.
            # role=option 항목만이 실카테고리(기본모드/마크다운/HTML 등의 menuitem 제외).
            options = self.page.locator(".mce-menu-item[role='option']")
            try:
                options.first.wait_for(state="attached", timeout=5000)
            except Exception:
                pass
            target = self._pick_category_option(options, name)
            if target is None:
                logger.warning("[tistory] category '%s' not found in menu; 기본 카테고리 사용", name)
                self.page.keyboard.press("Escape")
                return
            target.click()
            self.page.wait_for_timeout(400)
            current = (button.inner_text() or "").strip().replace("\n", " ")
            logger.info("[tistory] category set via menu: %s (button=%s)", name, current)
            return
        logger.warning("[tistory] category selector not found; 사용 기본 카테고리")

    def _pick_category_option(self, options: "Locator", name: str) -> "Locator | None":
        norm = lambda s: re.sub(r"[\s-]+", "", s or "").replace("－", "")
        items = options.all()
        # 정확 일치 우선
        for it in items:
            try:
                if norm(it.inner_text()) == norm(name):
                    return it
            except Exception:
                continue
        for it in items:
            try:
                if norm(name) and norm(name) in norm(it.inner_text()):
                    return it
            except Exception:
                continue
        return None

    # ---------------------------------------------------------------- 태그
    def set_tags(self, tags: list[str]) -> None:
        # 임시저장 복원으로 이전 글 태그가 남아 최대 개수(10개)에 도달하면
        # 입력창 자체가 사라진다. 먼저 기존 태그를 지워 입력창을 되살린다.
        try:
            chip_selector = self.sel.get("TAG_CHIP_DELETE", "") or ".editor_tag .txt_tag a.btn_delete"
            chips = self.page.locator(chip_selector)
            for _ in range(20):
                if chips.count() == 0:
                    break
                chips.first.click(timeout=2000)
                self.page.wait_for_timeout(120)
        except Exception as exc:
            logger.warning("[tistory] 기존 태그 정리 실패: %s", exc)

        tag_input = self._candidate("TAG_INPUT")
        if tag_input is None:
            logger.warning("[tistory] 태그 입력창을 찾지 못해 태그 없이 발행합니다")
            return
        for tag in tags[:10]:
            tag_input.click()
            tag_input.fill("")
            tag_input.fill(tag)
            tag_input.press("Enter")
            self.page.wait_for_timeout(250)
        logger.info("[tistory] tags entered: %d", len(tags))

    # -------------------------------------------------------------- 공개 설정
    def set_visibility(self, visibility: str) -> None:
        target = str(visibility).lower()
        # 새 에디터: 발행 버튼이 공개 설정 레이어(editor_layer / publish_editor)를 연다.
        publish_btn = self._candidate("PUBLISH_BUTTON")
        if publish_btn is None:
            logger.warning("[tistory] publish button not found; visibility 기본값(private) 유지")
            return
        publish_btn.click()
        self.page.wait_for_timeout(1500)
        panel = self._candidate("PUBLISH_PANEL")
        if panel is None:
            logger.warning("[tistory] publish panel not visible; visibility 기본값(private) 유지")
            return
        # 실제 에디터 라디오 값: 20=공개, 15=보호, 0=비공개
        radio_value = {"protected": "15", "public": "20"}.get(target, "0")
        try:
            radio = panel.locator(f'input[type="radio"][value="{radio_value}"], input[name="basicSet"][value="{radio_value}"]').first
            radio.click(timeout=3000)
            self.page.wait_for_timeout(300)
            logger.info("[tistory] visibility set (panel): %s (radio=%s)", target, radio_value)
        except Exception:
            # 폴백: 동일 값 라벨 텍스트 클릭
            try:
                label_pick = {"protected": "보호", "public": "공개"}.get(target, "비공개")
                panel.get_by_text(label_pick, exact=False).first.click(timeout=2000)
                self.page.wait_for_timeout(300)
                logger.info("[tistory] visibility set (panel text): %s (%s)", target, label_pick)
            except Exception:
                logger.warning("[tistory] visibility radio not found in panel; 기본값(private) 유지")

    # ---------------------------------------------------------------- 발행
    def publish(self, publish_delay_seconds: int = 2, expect_url_slugs: list[str] | None = None) -> str:
        import time

        time.sleep(publish_delay_seconds)
        panel = self._candidate("PUBLISH_PANEL")
        if panel is not None:
            # 발행 레이어가 이미 열려 있으면 확정(제출) 버튼 클릭
            try:
                confirm = panel.locator("button[type='submit']").first
                confirm.click(timeout=5000)
                logger.info("[tistory] publish confirm (submit) clicked")
            except Exception:
                try:
                    panel.locator("button", has_text="발행").first.click(timeout=3000)
                    logger.info("[tistory] publish confirm (발행 text) clicked")
                except Exception:
                    logger.warning("[tistory] no publish confirm button in panel")
        else:
            button = self._require("PUBLISH_BUTTON")
            button.click()
        return self._extract_entry_url(expect_url_slugs or [])

    def _extract_entry_url(self, expect_url_slugs: list[str] | None = None) -> str:
        expect_url_slugs = expect_url_slugs or []
        # 발행 확정 후 글 관리(manage/posts) 목록으로 이동한다.
        try:
            self.page.wait_for_url(
                re.compile(r"/manage/(posts|post|entry)/"), timeout=min(self.timeout, 20000)
            )
        except Exception:
            pass
        if "/entry/" in self.page.url:
            return self.page.url
        if expect_url_slugs:
            # 목록 링크는 퍼센트 인코딩돼 있으므로 decode 후 슬러그로 매칭한다.
            try:
                href = self.page.evaluate(
                    """(slugs) => {
                        const els = Array.from(document.querySelectorAll('a[href*="/entry/"]'));
                        for (const a of els) {
                            for (const slug of slugs) {
                                try {
                                    if (decodeURIComponent(a.pathname).includes('/entry/' + slug)
                                            || a.pathname.includes('/entry/' + slug)) {
                                        return a.href;
                                    }
                                } catch (e) {}
                            }
                        }
                        return null;
                    }""",
                    expect_url_slugs,
                )
                if href:
                    return str(href)
            except Exception:
                pass
        link = self._candidate("ENTRY_LINK")
        if link is not None:
            href = link.get_attribute("href")
            if href and "/entry/" in href:
                return href if href.startswith("http") else (
                    f"https:{href}" if href.startswith("//") else f"https://www.tistory.com{href}"
                )
        m = re.search(r"https?://(?:www\.)?tistory\.com/(?:entry|post)/[^\"'\s)]+", self.page.content())
        if m:
            return m.group(0)
        m = re.search(r"https?://[^\"' ]*?/entry/\d+", self.page.content())
        if m:
            return m.group(0)
        return ""