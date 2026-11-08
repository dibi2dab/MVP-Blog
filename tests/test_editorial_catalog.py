from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.editorial.catalog import (
    CatalogEntryModel,
    CatalogFileModel,
    CatalogSourceModel,
    RatingModel,
    load_catalog,
)

from editorial_fixtures import CRYSTAL_IDS, QUARTZ_IDS


def _source(source_id: str = "S1") -> CatalogSourceModel:
    return CatalogSourceModel(
        id=source_id,
        title="Official pricing",
        url="https://example.com/pricing",
        publisher="Example 공식",
        accessed_at="2026-11-07",
    )


def _entry(**overrides) -> CatalogEntryModel:
    payload = {
        "id": "sample-entry",
        "name": "샘플 도구",
        "category": "AI 도구",
        "title": "샘플 도구의 가격과 기능을 비교하면",
        "meta_description": "샘플 도구의 월 비용과 기능을 공식 자료로 비교하고 실제 업무에서의 작업당 비용과 시간 절감 가치를 계산한 편집상 분석입니다.",
        "primary_keyword": "샘플",
        "summary": "샘플 도구의 가격과 기능을 정리합니다.",
        "sources": [_source()],
        "last_reviewed": "2026-11-07",
    }
    payload.update(overrides)
    return CatalogEntryModel.model_validate(payload)


def test_crystal_catalog_loads_expected_entries():
    catalog = load_catalog("crystal")
    ids = [entry.id for entry in catalog.active_entries()]
    assert ids == list(CRYSTAL_IDS)


def test_quartz_catalog_loads_expected_entries():
    catalog = load_catalog("quartz")
    ids = [entry.id for entry in catalog.active_entries()]
    assert ids == list(QUARTZ_IDS)


@pytest.mark.parametrize("blog", ["crystal", "quartz"])
def test_catalog_entries_meet_publishing_requirements(blog):
    catalog = load_catalog(blog)
    for entry in catalog.active_entries():
        assert 20 <= len(entry.title) <= 60, entry.id
        assert 80 <= len(entry.meta_description) <= 160, entry.id
        assert entry.primary_keyword in entry.title, entry.id
        assert entry.primary_keyword in entry.summary, entry.id
        assert 3 <= len(entry.tags) <= 10, entry.id
        assert len(entry.sources) >= 3, entry.id
        assert entry.last_reviewed, entry.id
        assert all(source.url.startswith("https://") for source in entry.sources), entry.id
        assert all(source.published_at or source.accessed_at for source in entry.sources), entry.id


def test_crystal_entries_use_models_and_quartz_entries_use_products():
    for entry in load_catalog("crystal").active_entries():
        assert entry.model is not None, entry.id
        assert entry.product is None, entry.id
    for entry in load_catalog("quartz").active_entries():
        assert entry.product is not None, entry.id
        assert entry.model is None, entry.id
        plan_names = {plan.name for plan in entry.product.plans}
        assert entry.product.selected_plan in plan_names, entry.id


def test_titles_must_not_contain_dates():
    with pytest.raises(ValidationError):
        _entry(title="2026년 샘플 도구 가격 비교")
    with pytest.raises(ValidationError):
        _entry(title="샘플 도구 비교 2026-11-07")


def test_duplicate_entry_ids_are_rejected():
    with pytest.raises(ValidationError):
        CatalogFileModel.model_validate(
            {
                "version": 1,
                "blog": "quartz",
                "entries": [
                    _entry().model_dump(),
                    _entry().model_dump(),
                ],
            }
        )


def test_rating_cannot_reference_unknown_source():
    with pytest.raises(ValidationError):
        _entry(
            ratings={
                "fit_for_purpose": RatingModel(
                    score=8,
                    basis="공식 자료 기준",
                    source_ids=["S9"],
                )
            }
        )


def test_source_requires_http_url_and_date():
    with pytest.raises(ValidationError):
        CatalogSourceModel(id="S1", title="bad", url="ftp://example.com", accessed_at="2026-11-07")
    with pytest.raises(ValidationError):
        CatalogSourceModel(id="S1", title="bad", url="https://example.com")


def test_quartz_selected_plan_must_exist():
    with pytest.raises(ValidationError):
        _entry(
            product={
                "name": "샘플",
                "plans": [{"name": "Free", "monthly_krw": 0}],
                "selected_plan": "Pro",
            }
        )
