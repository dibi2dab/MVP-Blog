from __future__ import annotations

import pytest

from src.editorial.profiles import get_profile, list_profiles

_BLOG_ENV = [
    "CRYSTAL_BLOG_NAME",
    "CRYSTAL_BLOG_URL",
    "CRYSTAL_STORAGE_STATE_PATH",
    "CRYSTAL_KAKAO_ID",
    "CRYSTAL_KAKAO_PASSWORD",
    "CRYSTAL_VISIBILITY",
    "CRYSTAL_TISTORY_CATEGORY",
    "QUARTZ_BLOG_NAME",
    "QUARTZ_BLOG_URL",
    "QUARTZ_STORAGE_STATE_PATH",
    "QUARTZ_KAKAO_ID",
    "QUARTZ_KAKAO_PASSWORD",
    "QUARTZ_VISIBILITY",
    "QUARTZ_TISTORY_CATEGORY",
    "TISTORY_KAKAO_ID",
    "TISTORY_KAKAO_PASSWORD",
    "TISTORY_VISIBILITY",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _BLOG_ENV:
        monkeypatch.delenv(name, raising=False)


def test_crystal_defaults():
    profile = get_profile("crystal")
    assert profile.blog_name == "rumbell"
    assert profile.blog_url == "https://rumbell.tistory.com"
    assert profile.framework == "CPPI"
    assert profile.max_articles_per_day == 1
    assert profile.min_quality_score == 85.0
    assert profile.default_category == "온라인 수익"
    assert "온라인 부업" in profile.topic_queries


def test_quartz_defaults():
    profile = get_profile("quartz")
    assert profile.blog_name == "quar1z"
    assert profile.blog_url == "https://quar1z.tistory.com"
    assert profile.framework == "QDVI"
    assert profile.default_category == "AI 도구"
    assert "AI 도구" in profile.topic_queries


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CRYSTAL_BLOG_NAME", "mycrystal")
    monkeypatch.setenv("CRYSTAL_STORAGE_STATE_PATH", ".state/custom.json")
    monkeypatch.setenv("CRYSTAL_KAKAO_ID", "crystal-id")
    monkeypatch.setenv("CRYSTAL_KAKAO_PASSWORD", "crystal-pw")
    monkeypatch.setenv("CRYSTAL_VISIBILITY", "private")
    monkeypatch.setenv("CRYSTAL_MAX_ARTICLES_PER_DAY", "2")

    profile = get_profile("crystal")
    assert profile.blog_name == "mycrystal"
    assert profile.storage_state_path == ".state/custom.json"
    assert profile.kakao_id == "crystal-id"
    assert profile.kakao_password == "crystal-pw"
    assert profile.visibility == "private"
    assert profile.max_articles_per_day == 2


def test_global_kakao_fallback(monkeypatch):
    monkeypatch.setenv("TISTORY_KAKAO_ID", "shared-id")
    monkeypatch.setenv("TISTORY_KAKAO_PASSWORD", "shared-pw")
    profile = get_profile("quartz")
    assert profile.kakao_id == "shared-id"
    assert profile.kakao_password == "shared-pw"


def test_blog_specific_kakao_wins(monkeypatch):
    monkeypatch.setenv("TISTORY_KAKAO_ID", "shared-id")
    monkeypatch.setenv("QUARTZ_KAKAO_ID", "quartz-id")
    assert get_profile("quartz").kakao_id == "quartz-id"


def test_unknown_blog_rejected():
    with pytest.raises(ValueError):
        get_profile("obsidian")

def test_list_profiles():
    profiles = {profile.key: profile for profile in list_profiles()}
    assert set(profiles) == {"crystal", "quartz"}
    assert profiles["crystal"].framework == "CPPI"
    assert profiles["quartz"].framework == "QDVI"
