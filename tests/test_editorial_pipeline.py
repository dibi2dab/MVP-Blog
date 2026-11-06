from __future__ import annotations

from pathlib import Path

import pytest

from src.editorial.models import kst_now
from src.editorial.pipeline import EditorialPipeline
from src.editorial.profiles import get_profile
from src.editorial.state import EditorialState
from src.publishers.base import PublishResult

from editorial_fixtures import make_article_payload, make_sources, make_topic


class FakeProvider:
    name = "openai"

    def __init__(self, article: dict) -> None:
        self.article = article
        self.prompts: list[str] = []

    def chat_json(self, system: str, prompt: str, temperature: float = 0.2) -> dict:
        self.prompts.append(prompt)
        if "Select today's article topic" in prompt:
            return make_topic("quartz")
        return self.article


class FakeMockProvider(FakeProvider):
    name = "mock"


class FakeResearch:
    def __init__(self, sources) -> None:
        self.sources = sources
        self.calls = 0

    def fetch(self, queries):
        self.calls += 1
        return self.sources


class FakePublisher:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.published = []

    def publish(self, article):
        self.published.append(article)
        return PublishResult(
            ok=self.ok,
            url="https://quar1z.tistory.com/123" if self.ok else "",
            article_id=article.article_id,
            message="" if self.ok else "publish failed",
            error_code="" if self.ok else "TISTORY_PUBLISH_FAILED",
        )


def _pipeline(tmp_path: Path, provider, research, publisher) -> EditorialPipeline:
    profile = get_profile("quartz")
    state = EditorialState(
        "quartz",
        base_dir=tmp_path / "data",
        content_root=tmp_path / "content",
    )
    return EditorialPipeline(
        profile,
        settings=None,
        provider=provider,
        research_client=research,
        state=state,
        publisher=publisher,
    )


def test_successful_run_publishes_and_records_state(tmp_path: Path):
    sources = make_sources("quartz")
    provider = FakeProvider(make_article_payload("quartz"))
    research = FakeResearch(sources)
    publisher = FakePublisher()

    pipeline = _pipeline(tmp_path, provider, research, publisher)
    result = pipeline.run()

    assert result.error == ""
    assert result.decision == "PUBLISH", result.reason
    assert result.quality_total >= 85
    assert result.url == "https://quar1z.tistory.com/123"
    assert len(publisher.published) == 1

    state = EditorialState("quartz", base_dir=tmp_path / "data", content_root=tmp_path / "content")
    records = state.load_published()
    assert len(records) == 1
    assert records[0]["title"] == result.title
    assert records[0]["url"] == result.url
    assert records[0]["framework"] == "QDVI"
    assert records[0]["body_fingerprint"]

    archive = tmp_path / "content" / "quartz"
    assert list(archive.glob("*.md"))
    assert Path(result.report_path).exists()
    assert Path(result.draft_path).exists()


def test_daily_limit_skips_without_calling_ai(tmp_path: Path):
    state = EditorialState("quartz", base_dir=tmp_path / "data", content_root=tmp_path / "content")
    state.save_published(
        {
            "title": "이미 발행한 글",
            "published_at": kst_now().isoformat(),
            "date": kst_now().date().isoformat(),
        }
    )
    provider = FakeProvider(make_article_payload("quartz"))
    research = FakeResearch(make_sources("quartz"))
    publisher = FakePublisher()

    pipeline = EditorialPipeline(
        get_profile("quartz"),
        settings=None,
        provider=provider,
        research_client=research,
        state=state,
        publisher=publisher,
    )
    result = pipeline.run()

    assert result.skipped is True
    assert publisher.published == []
    assert provider.prompts == []
    assert research.calls == 0


def test_force_bypasses_daily_limit(tmp_path: Path):
    state = EditorialState("quartz", base_dir=tmp_path / "data", content_root=tmp_path / "content")
    state.save_published(
        {
            "title": "이미 발행한 글",
            "published_at": kst_now().isoformat(),
            "date": kst_now().date().isoformat(),
        }
    )
    pipeline = EditorialPipeline(
        get_profile("quartz"),
        settings=None,
        provider=FakeProvider(make_article_payload("quartz")),
        research_client=FakeResearch(make_sources("quartz")),
        state=state,
        publisher=FakePublisher(),
    )
    result = pipeline.run(force=True)
    assert result.decision == "PUBLISH"
    assert len(state.load_published()) == 2


def test_mock_provider_is_rejected_before_research(tmp_path: Path):
    research = FakeResearch(make_sources("quartz"))
    pipeline = _pipeline(
        tmp_path,
        FakeMockProvider(make_article_payload("quartz")),
        research,
        FakePublisher(),
    )
    result = pipeline.run()
    assert "mock" in result.error
    assert research.calls == 0


def test_allow_mock_still_never_publishes(tmp_path: Path):
    publisher = FakePublisher()
    pipeline = _pipeline(
        tmp_path,
        FakeMockProvider(make_article_payload("quartz")),
        FakeResearch(make_sources("quartz")),
        publisher,
    )
    result = pipeline.run(allow_mock=True)
    assert result.decision == "DO NOT PUBLISH"
    assert publisher.published == []


def test_quality_failure_blocks_publish(tmp_path: Path):
    article = make_article_payload("quartz")
    article["body_markdown"] = "짧은 본문입니다. [S1]"
    publisher = FakePublisher()
    pipeline = _pipeline(
        tmp_path,
        FakeProvider(article),
        FakeResearch(make_sources("quartz")),
        publisher,
    )
    result = pipeline.run()
    assert result.decision == "DO NOT PUBLISH"
    assert publisher.published == []


def test_publish_failure_is_reported(tmp_path: Path):
    publisher = FakePublisher(ok=False)
    pipeline = _pipeline(
        tmp_path,
        FakeProvider(make_article_payload("quartz")),
        FakeResearch(make_sources("quartz")),
        publisher,
    )
    result = pipeline.run()
    assert result.decision == "PUBLISH"
    assert result.error
    state = EditorialState("quartz", base_dir=tmp_path / "data")
    assert state.load_published() == []


def test_dry_run_does_not_publish(tmp_path: Path):
    publisher = FakePublisher()
    pipeline = _pipeline(
        tmp_path,
        FakeProvider(make_article_payload("quartz")),
        FakeResearch(make_sources("quartz")),
        publisher,
    )
    result = pipeline.run(dry_run=True)
    assert result.decision == "PUBLISH"
    assert "dry run" in result.reason
    assert publisher.published == []
