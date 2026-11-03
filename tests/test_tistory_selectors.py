from __future__ import annotations

from src.publishers.tistory_selectors import DEFAULT_SELECTORS, TistorySelectors


def test_defaults_present():
    sel = TistorySelectors()
    for key in ("TITLE", "HTML_TEXTAREA", "VISUAL_EDITOR", "FILE_INPUT", "TAG_INPUT", "VISIBILITY_SELECT", "PUBLISH_BUTTON"):
        assert sel.get(key) == DEFAULT_SELECTORS[key]
        assert sel.get(key) != ""


def test_override():
    sel = TistorySelectors({"TITLE": "custom"})
    assert sel.get("TITLE") == "custom"
    assert sel.get("TAG_INPUT") == DEFAULT_SELECTORS["TAG_INPUT"]


def test_from_settings():
    from src.config.settings import Settings

    settings = Settings.model_validate({"tistory": {"selectors": {"TITLE": "x"}}})
    sel = TistorySelectors.from_settings(settings)
    assert sel.get("TITLE") == "x"