from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from src.config.settings import PROJECT_ROOT
from src.editorial.models import ResearchSource

CATALOG_ROOT = PROJECT_ROOT / "data" / "editorial"

_DATE_IN_TITLE = re.compile(
    r"(\d{4}[-./년]\s*\d{1,2}[-./월]\s*\d{1,2}일?|\d{4}년|\b20\d{2}\b)"
)


class CatalogError(ValueError):
    pass


class CatalogSourceModel(BaseModel):
    id: str
    title: str
    url: str
    publisher: str = ""
    published_at: str = ""
    accessed_at: str = ""

    @model_validator(mode="after")
    def _check(self) -> "CatalogSourceModel":
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(f"source {self.id}: url must start with http(s)://")
        if not self.published_at and not self.accessed_at:
            raise ValueError(f"source {self.id}: published_at or accessed_at is required")
        return self


class RatingModel(BaseModel):
    score: float
    basis: str
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "RatingModel":
        if not (0 <= self.score <= 10):
            raise ValueError(f"rating score must be 0..10, got {self.score}")
        if not self.basis.strip():
            raise ValueError("rating basis is required")
        return self


class PlanModel(BaseModel):
    name: str
    monthly_krw: float | None = None
    annual_krw: float | None = None
    included_units: float | None = None
    unit: str = ""
    note: str = ""


class FeatureModel(BaseModel):
    name: str
    available: bool = True
    note: str = ""
    source_ids: list[str] = Field(default_factory=list)


class CompetitorModel(BaseModel):
    name: str
    monthly_krw: float | None = None
    annual_krw: float | None = None
    feature_count: int | None = None
    notes: str = ""
    source_ids: list[str] = Field(default_factory=list)


class AssumptionModel(BaseModel):
    name: str
    value: str
    unit: str = ""
    basis: str = "편집상 가정"
    source_ids: list[str] = Field(default_factory=list)


class CrystalModelSpec(BaseModel):
    type: Literal["advertising", "subscription", "affiliate", "digital_product", "service"]
    inputs: dict[str, Any] = Field(default_factory=dict)
    initial_investment_krw: float = 0
    fixed_monthly_krw: float = 0
    variable_cost_per_unit_krw: float = 0
    price_per_unit_krw: float | None = None
    units_per_month: float | None = None
    monthly_hours: float | None = None
    scenarios: dict[str, float] = Field(
        default_factory=lambda: {"conservative": 0.5, "base": 1.0, "optimistic": 1.5}
    )


class QuartzProductSpec(BaseModel):
    name: str
    vendor: str = ""
    plans: list[PlanModel] = Field(default_factory=list)
    selected_plan: str = ""
    tasks_per_month: float | None = None
    minutes_saved_per_task: float | None = None
    hourly_labor_cost_krw: float | None = None
    features: list[FeatureModel] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    usage_limits: str = ""
    ratings: dict[str, RatingModel] = Field(default_factory=dict)
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "QuartzProductSpec":
        if self.plans and self.selected_plan:
            if self.selected_plan not in {plan.name for plan in self.plans}:
                raise ValueError(
                    f"selected_plan {self.selected_plan!r} is not in plans "
                    f"{[plan.name for plan in self.plans]}"
                )
        return self


class CatalogEntryModel(BaseModel):
    id: str
    name: str
    category: str
    title: str
    meta_description: str
    primary_keyword: str
    secondary_keywords: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    summary: str
    why_now: str = ""
    model: CrystalModelSpec | None = None
    product: QuartzProductSpec | None = None
    competitors: list[CompetitorModel] = Field(default_factory=list)
    ratings: dict[str, RatingModel] = Field(default_factory=dict)
    sources: list[CatalogSourceModel] = Field(default_factory=list)
    sourced_inputs: dict[str, list[str]] = Field(default_factory=dict)
    assumptions: list[AssumptionModel] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    last_reviewed: str = ""
    status: Literal["active", "paused"] = "active"

    @model_validator(mode="after")
    def _check(self) -> "CatalogEntryModel":
        if not self.sources:
            raise ValueError(f"entry {self.id}: at least one source is required")
        if not self.title.strip() or not self.primary_keyword.strip():
            raise ValueError(f"entry {self.id}: title and primary_keyword are required")
        if _DATE_IN_TITLE.search(self.title):
            raise ValueError(f"entry {self.id}: title must not contain a date: {self.title!r}")
        ids = {source.id for source in self.sources}
        if len(ids) != len(self.sources):
            raise ValueError(f"entry {self.id}: duplicate source ids")
        for name, rating in {**self.ratings, **self._product_ratings()}.items():
            missing = sorted(set(rating.source_ids) - ids)
            if missing:
                raise ValueError(
                    f"entry {self.id}: rating {name} references unknown sources {missing}"
                )
        for name, source_ids in self.sourced_inputs.items():
            missing = sorted(set(source_ids) - ids)
            if missing:
                raise ValueError(
                    f"entry {self.id}: sourced_input {name} references unknown sources {missing}"
                )
        return self

    def _product_ratings(self) -> dict[str, RatingModel]:
        if self.product is None:
            return {}
        return dict(self.product.ratings)

    def source_records(self) -> list[ResearchSource]:
        records: list[ResearchSource] = []
        for source in self.sources:
            records.append(
                ResearchSource(
                    source_id=source.id,
                    title=source.title,
                    url=source.url,
                    publisher=source.publisher,
                    published_at=source.published_at,
                    retrieved_at=source.accessed_at or source.published_at,
                )
            )
        return records


class CatalogFileModel(BaseModel):
    version: int = 1
    blog: Literal["crystal", "quartz"]
    entries: list[CatalogEntryModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "CatalogFileModel":
        ids = [entry.id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("catalog contains duplicate entry ids")
        return self


class Catalog:
    def __init__(self, blog: str, entries: list[CatalogEntryModel], path: Path | None = None) -> None:
        self.blog = blog
        self.entries = entries
        self.path = path

    def active_entries(self) -> list[CatalogEntryModel]:
        return [entry for entry in self.entries if entry.status == "active"]

    def get(self, entry_id: str) -> CatalogEntryModel | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None


def catalog_path(blog: str, root: Path | str | None = None) -> Path:
    base = Path(root) if root else CATALOG_ROOT
    return base / blog / "catalog.yaml"


def load_catalog(blog: str, root: Path | str | None = None) -> Catalog:
    path = catalog_path(blog, root)
    if not path.exists():
        raise CatalogError(f"catalog not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"catalog read failed: {path}: {exc}") from exc
    try:
        parsed = CatalogFileModel.model_validate(raw)
    except ValidationError as exc:
        raise CatalogError(f"catalog validation failed: {path}: {exc}") from exc
    if parsed.blog != blog:
        raise CatalogError(f"catalog blog mismatch: expected {blog}, got {parsed.blog}")
    return Catalog(blog=blog, entries=parsed.entries, path=path)
