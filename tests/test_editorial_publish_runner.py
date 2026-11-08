from __future__ import annotations

from src.editorial.models import kst_now
from src.editorial.profiles import get_profile
from src.editorial.publish_runner import publish_ready, validate_metadata
from src.editorial.state import EditorialState

from editorial_fixtures import FakePublisher, get_catalog, make_article


def _state(tmp_path, blog="crystal"):
    return EditorialState(blog, base_dir=tmp_path, content_root=tmp_path / "content")


def test_dry_run_validates_without_publishing(tmp_path):
    state = _state(tmp_path)
    article = make_article("crystal", "adsense-blog")
    state.save_article(article)

    run = publish_ready(
        get_profile("crystal"),
        state,
        catalog=get_catalog("crystal"),
        dry_run=True,
    )
    assert run.published == 0
    assert len(run.results) == 1
    assert run.results[0].ok is True
    assert state.load_published() == []


def test_publish_records_state_and_archive(tmp_path):
    state = _state(tmp_path, "quartz")
    article = make_article("quartz", "notion-plus")
    state.save_article(article)
    publisher = FakePublisher(url="https://quar1z.tistory.com/123")

    run = publish_ready(
        get_profile("quartz"),
        state,
        catalog=get_catalog("quartz"),
        publisher=publisher,
    )

    assert run.published == 1
    assert len(publisher.published) == 1
    records = state.load_published()
    assert len(records) == 1
    assert records[0]["catalog_id"] == "notion-plus"
    assert records[0]["url"] == "https://quar1z.tistory.com/123"

    published = state.list_articles(status="published")
    assert len(published) == 1
    assert published[0].published_url == "https://quar1z.tistory.com/123"

    archives = list((tmp_path / "content" / "quartz").glob("*.md"))
    assert len(archives) == 1


def test_publish_failure_marks_article_failed(tmp_path):
    state = _state(tmp_path)
    article = make_article("crystal", "gumroad-digital-product")
    state.save_article(article)

    run = publish_ready(
        get_profile("crystal"),
        state,
        catalog=get_catalog("crystal"),
        publisher=FakePublisher(ok=False),
    )

    assert run.published == 0
    assert run.results[0].ok is False
    failed = state.list_articles(status="failed")
    assert len(failed) == 1
    assert "발행에 실패" in failed[0].failure_reason


def test_tampered_article_is_rejected_before_publish(tmp_path):
    state = _state(tmp_path, "quartz")
    article = make_article("quartz", "zapier-pro")
    article.analysis.metrics[0].value = 1.0
    state.save_article(article)

    run = publish_ready(
        get_profile("quartz"),
        state,
        catalog=get_catalog("quartz"),
        publisher=FakePublisher(),
    )

    assert run.published == 0
    assert run.results[0].ok is False
    failed = state.list_articles(status="failed")
    assert failed
    assert "계산" in failed[0].failure_reason


def test_daily_limit_skips_publish(tmp_path):
    state = _state(tmp_path)
    state.save_published(
        {
            "article_id": "crystal-adsense-blog",
            "catalog_id": "adsense-blog",
            "published_at": kst_now().isoformat(),
        }
    )
    article = make_article("crystal", "gumroad-digital-product")
    state.save_article(article)

    run = publish_ready(
        get_profile("crystal"),
        state,
        catalog=get_catalog("crystal"),
        publisher=FakePublisher(),
    )
    assert run.published == 0
    assert "일일 한도" in run.skipped_reason


def test_validate_metadata_flags_missing_fields():
    article = make_article("quartz", "slack-pro")
    problems = validate_metadata(article, get_profile("quartz"))
    assert problems == []

    article.catalog_id = ""
    article.slug = ""
    article.meta_description = ""
    problems = validate_metadata(article, get_profile("quartz"))
    assert any("카탈로그 ID" in problem for problem in problems)
    assert any("슬러그" in problem for problem in problems)
    assert any("메타 설명" in problem for problem in problems)
