from __future__ import annotations

"""티스토리 글쓰기 페이지 DOM 셀렉터.

티스토리 UI가 변경되면 이 파일의 셀렉터만 수정해 대응한다.
settings.yaml 의 tistory.selectors 로 상속/오버라이드할 수 있다.
"""

DEFAULT_SELECTORS: dict[str, str] = {
    # 글쓰기 페이지 제목 입력 (새 에디터: textarea#post-title-inp.textarea_tit / 구 에디터: input)
    "TITLE": 'textarea#post-title-inp, .textarea_tit, input[name="title"], .tt_editor_title_input, input.title-input, input[placeholder*="제목"]',
    # 에디터 HTML 모드 전환 버튼들 (여러 후보)
    "HTML_MODE_BUTTON": 'button#editor-mode-layer-btn-open, #editor-mode-layer-btn, button[data-mode="html"], .tt_html_btn, button:has-text("HTML"), #flip-editor-row button:has-text("HTML")',
    "VISUAL_MODE_BUTTON": 'button[data-mode="visual"], .tt_visual_btn, button:has-text("기본")',
    # HTML 모드용 textarea (새 에디터: 항상 존재하지만 숨김, HTML모드에서 활성화)
    "HTML_TEXTAREA": 'textarea#editor-tistory, textarea.tt_editor_html, textarea[name="html"]',
    # 비주얼 에디터 컨텐츠 영역 (새 에디터: iframe#editor-tistory_ifr, TinyMCE 계열)
    "VISUAL_EDITOR": 'iframe#editor-tistory_ifr, iframe.tox-edit-area__iframe, [contenteditable="true"], .tox-edit-area, .tt_editor_cont',
    # 이미지 업로드 파일 input (구 에디터 폴백용)
    "FILE_INPUT": 'input[type="file"].upload-editor-file, input[type="file"]#uploadedfile, .editor-upload input[type="file"], #fileupload input[type="file"], input[type="file"][accept*="image"], .attach input[type="file"]',
    # 새 에디터: 툴바 첨부 버튼(내부 button) + 사진 메뉴 (mce-i-image)
    "ATTACH_BUTTON": '.mce-btn:has(i.mce-i-image):visible button',
    "ATTACH_PHOTO_MENU": '.mce-menu-item:visible:has(.mce-i-image)',
    # 카테고리 (새 에디터: button#category-btn 가 레이어 열기)
    "CATEGORY_SELECT": 'select[name="categoryId"], select.select-category, .category-area select',
    "CATEGORY_DROPDOWN": 'button#category-btn, [data-role="category"], button:has-text("카테고리"), .category-dropdown',
    # 태그 입력 (새 에디터: input#tagText)
    "TAG_INPUT": 'input#tagText, input[name="tag"], input.editor-tag, input[placeholder*="태그"]',
    # 복원된 임시저장 글의 기존 태그 삭제 버튼
    "TAG_CHIP_DELETE": ".editor_tag .txt_tag a.btn_delete",
    # 공개 설정 (새 에디터: publish 레이어 내 radio/버튼)
    "VISIBILITY_SELECT": 'select[name="visibility"], select.visibility',
    "VISIBILITY_RADIO": 'input.form-radio[name="basicSet"], input[name="visibility"], input[data-name="visibility"]',
    # 발행 설정 패널 (공개/비공개/보호 + 발행 버튼) — ReactModal editor_layer
    "PUBLISH_PANEL": '.editor_layer, .inner_editor_layer, [class*="publish_editor"]',
    # 발행 확정 버튼 (패널 내부의 submit)
    "PUBLISH_CONFIRM_BUTTON": 'button[type="submit"], .btn-default[type="submit"]',
    # 발행 버튼 (새 에디터: button#publish-layer-btn 가 발행 레이어 열기)
    "PUBLISH_BUTTON": 'button#publish-layer-btn, .btn-publish, #publish-btn, button:has-text("발행")',
    "CANCEL_BUTTON": 'button:has-text("취소")',
    # 발행 성공/완료 표시
    "SUCCESS_CONTAINER": '.modal-content, .toast-container, [class*="post-complete"], [class*="success"]',
    "ENTRY_LINK": 'a[href*="/entry/"]',
    # 로그인 여부 확인 (관리자 영역 접근 시)
    "LOGIN_INDICATOR": '#kakaoGnbProfileImg, .tb_profile, .profile_box, a[href*="/manage"]',
    "LOGIN_FORM": 'input[name="login_id"], input[name="uid"], form[name="login"], #loginForm',
}


class TistorySelectors:
    """셀렉터 컬렉션. overrides 로 특정 키만 교체한다."""

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        values = dict(DEFAULT_SELECTORS)
        values.update(overrides or {})
        for key, selector in values.items():
            setattr(self, key, selector)
        self._keys = list(values)

    def get(self, key: str, default: str = "") -> str:
        return getattr(self, key, default)

    @classmethod
    def from_settings(cls, settings) -> "TistorySelectors":
        overrides = getattr(getattr(settings, "tistory", None), "selectors", None) or {}
        return cls(overrides)