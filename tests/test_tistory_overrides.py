from __future__ import annotations

from pathlib import Path

from src.editorial.publisher import target_for_profile
from src.editorial.profiles import get_profile
from src.models.article import Article, ArticleSection
from src.models.event import Event
from src.models.source import EntityRef
from src.publishers.node_tistory_publisher import NodeTistoryPublisher, PublishTarget
from src.storage.file_store import JsonStore


def _article(category: str = "stocks") -> Article:
    event = Event(
        event_id="e1",
        event_type="stock_crash",
        entity=EntityRef(name="테스트종목", ticker="000000"),
    )
    return Article(
        article_id="a1",
        event=event,
        title="[2026년 11월 6일] 테스트종목 분석",
        slug="test-article",
        sections=[ArticleSection(heading="본문", body="본문입니다. " * 200)],
        sources=["Google News"],
        category=category,
        tags=["테스트"],
        body_markdown="## 본문\n\n" + ("본문입니다. " * 200),
    )


def test_payload_uses_target_overrides(settings, tmp_path: Path):
    storage_state = tmp_path / "crystal_storage_state.json"
    storage_state.write_text("{}", encoding="utf-8")
    target = PublishTarget(
        blog_name="rumbell",
        storage_state_path=str(storage_state),
        kakao_id="crystal-id",
        kakao_password="crystal-pw",
        artifact_dir=str(tmp_path / "artifacts"),
        category_map={"stocks": "온라인 수익"},
        visibility="public",
        headless=True,
    )
    publisher = NodeTistoryPublisher(settings, JsonStore(settings), target=target)
    article = _article()
    payload = publisher._build_payload(article, article.body_markdown, [])

    assert payload["blogName"] == "rumbell"
    assert payload["storageStatePath"] == str(storage_state)
    assert payload["kakaoId"] == "crystal-id"
    assert payload["kakaoPassword"] == "crystal-pw"
    assert payload["artifactDir"] == str(tmp_path / "artifacts")
    assert payload["tistoryCategory"] == "온라인 수익"
    assert payload["visibility"] == "public"
    assert payload["headless"] is True


def test_apply_target_overrides_is_idempotent(settings):
    target = PublishTarget(blog_name="quar1z", visibility="private", headless=False)
    publisher = NodeTistoryPublisher(settings, JsonStore(settings), target=target)
    payload = {"blogName": "eneru", "visibility": "public"}
    publisher._apply_target_overrides(payload)
    publisher._apply_target_overrides(payload)
    assert payload["blogName"] == "quar1z"
    assert payload["visibility"] == "private"
    assert payload["headless"] is False


def test_connected_uses_target_storage_state(settings, tmp_path: Path):
    storage_state = tmp_path / "quartz_storage_state.json"
    publisher = NodeTistoryPublisher(
        settings,
        JsonStore(settings),
        target=PublishTarget(storage_state_path=str(storage_state)),
    )
    assert publisher.connected is False
    storage_state.write_text("{}", encoding="utf-8")
    assert publisher.connected is True


def test_publish_payload_dry_run_does_not_launch_node(settings):
    publisher = NodeTistoryPublisher(
        settings,
        JsonStore(settings),
        target=PublishTarget(dry_run=True),
    )
    result = publisher.publish_payload({"title": "테스트"}, article_id="a1")
    assert result.ok is False
    assert result.error_code == "TISTORY_DRY_RUN"


def test_target_for_profile_maps_blog_identity(settings, monkeypatch):
    monkeypatch.setenv("QUARTZ_STORAGE_STATE_PATH", ".state/quartz_storage_state.json")
    profile = get_profile("quartz")
    target = target_for_profile(profile)

    assert target.blog_name == "quar1z"
    assert target.storage_state_path.endswith("quartz_storage_state.json")
    assert target.visibility == "public"
    assert target.headless is True
    assert target.artifact_dir.endswith("quartz")
    assert target.dry_run is False
