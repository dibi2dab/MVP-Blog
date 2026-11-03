from __future__ import annotations

import os


def test_env_interpolation(monkeypatch):
    from src.config.settings import _interpolate_env

    monkeypatch.setenv("TISTORY_BLOG_URL", "https://myblog.tistory.com")
    out = _interpolate_env({"tistory": {"blog_url": "${TISTORY_BLOG_URL}"}})
    assert out["tistory"]["blog_url"] == "https://myblog.tistory.com"


def test_env_interpolation_missing_keeps_placeholder():
    from src.config.settings import _interpolate_env

    out = _interpolate_env({"a": "${NOT_DEFINED_XYZ}"})
    assert out["a"] == "${NOT_DEFINED_XYZ}"


def test_effective_backend_priority(monkeypatch):
    from src.config.settings import Settings

    monkeypatch.delenv("PUBLISH_BACKEND", raising=False)
    s = Settings(publisher={"type": "tistory"}, publishing={"backend": "local"})
    assert s.effective_backend == "tistory"

    monkeypatch.setenv("PUBLISH_BACKEND", "mock")
    assert s.effective_backend == "mock"


def test_tistory_visibility_value():
    from src.config.settings import TistoryBrowserConfig

    assert TistoryBrowserConfig(default_visibility="private").visibility_value() == 0
    assert TistoryBrowserConfig(default_visibility="protected").visibility_value() == 1
    assert TistoryBrowserConfig(default_visibility="public").visibility_value() == 3


def test_tistory_config_env_override(monkeypatch):
    from src.config.settings import Settings

    monkeypatch.delenv("PUBLISH_BACKEND", raising=False)
    s = Settings().resolve()
    s.tistory = s.tistory.model_copy(update={"default_visibility": "public"})
    assert s.tistory.default_visibility == "public"