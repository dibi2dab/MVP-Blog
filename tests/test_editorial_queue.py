from __future__ import annotations

from src.editorial.models import ResearchSource, kst_now
from src.editorial.profiles import get_profile
from src.editorial.queue import published_catalog_ids, select_next_entry
from src.editorial.state import EditorialState

from editorial_fixtures import get_catalog


def _state(tmp_path, blog="crystal"):
    return EditorialState(blog, base_dir=tmp_path, content_root=tmp_path / "content")


def test_selects_first_unused_entry(tmp_path):
    selection = select_next_entry(get_catalog("crystal"), get_profile("crystal"), _state(tmp_path))
    assert selection.entry is not None
    assert selection.entry.id == "adsense-blog"
    assert selection.unused_count == 5


def test_daily_limit_blocks_selection(tmp_path):
    state = _state(tmp_path)
    state.save_published(
        {
            "article_id": "crystal-adsense-blog",
            "catalog_id": "adsense-blog",
            "published_at": kst_now().isoformat(),
        }
    )
    selection = select_next_entry(get_catalog("crystal"), get_profile("crystal"), state)
    assert selection.entry is None
    assert "일일 한도" in selection.reason


def test_force_bypasses_daily_limit_but_not_duplicate_topics(tmp_path):
    state = _state(tmp_path)
    state.save_published(
        {
            "article_id": "crystal-adsense-blog",
            "catalog_id": "adsense-blog",
            "published_at": kst_now().isoformat(),
        }
    )
    selection = select_next_entry(
        get_catalog("crystal"),
        get_profile("crystal"),
        state,
        force=True,
    )
    assert selection.entry is not None
    assert selection.entry.id != "adsense-blog"


def test_published_catalog_ids_are_excluded(tmp_path):
    state = _state(tmp_path)
    state.save_published(
        {
            "article_id": "crystal-adsense-blog",
            "catalog_id": "adsense-blog",
            "published_at": "2020-01-01T00:00:00+09:00",
        }
    )
    assert published_catalog_ids(state) == {"adsense-blog"}
    selection = select_next_entry(get_catalog("crystal"), get_profile("crystal"), state)
    assert selection.entry is not None
    assert selection.entry.id == "gumroad-digital-product"


def test_signal_scoring_prefers_matching_entry(tmp_path):
    signal = ResearchSource(
        source_id="S1",
        title="Notion Plus 요금제 가격 비교",
        url="https://news.example.com/notion",
        published_at="2026-11-06",
    )
    selection = select_next_entry(
        get_catalog("quartz"),
        get_profile("quartz"),
        _state(tmp_path, "quartz"),
        signals=[signal],
    )
    assert selection.entry is not None
    assert selection.entry.id == "notion-plus"
    assert "신호" in selection.reason


def test_empty_catalog_reports_no_candidates(tmp_path):
    catalog = get_catalog("crystal")
    state = _state(tmp_path)
    for entry in catalog.entries:
        state.save_published(
            {
                "article_id": f"crystal-{entry.id}",
                "catalog_id": entry.id,
                "published_at": "2020-01-01T00:00:00+09:00",
            }
        )
    selection = select_next_entry(catalog, get_profile("crystal"), state)
    assert selection.entry is None
    assert "새 항목" in selection.reason
