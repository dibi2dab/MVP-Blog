from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.models.source import utc_now_iso


class ResearchSource(BaseModel):
    """A source used by the article.

    ``source_id`` is the stable ID (``S1``, ``S2`` ...) used in the body and in
    the source list. Catalog sources and Google News RSS sources share this
    shape so the renderer and quality gate can treat them identically.
    """

    source_id: str
    title: str
    url: str
    publisher: str = ""
    publisher_url: str = ""
    published_at: str = ""
    retrieved_at: str = Field(default_factory=utc_now_iso)
    query: str = ""
    snippet: str = ""

    def display(self) -> str:
        date = self.published_at or self.retrieved_at[:10] or "날짜 미상"
        publisher = self.publisher or "출처"
        return f"[{self.source_id}] {self.title} — {publisher} ({date})"


class TopicCandidate(BaseModel):
    topic: str
    search_intent: str = ""
    angle: str = ""
    why_now: str = ""
    source_ids: list[str] = Field(default_factory=list)
    primary_keyword: str = ""
    category: str = ""
    catalog_id: str = ""


class Rating(BaseModel):
    """An editorial rating derived from catalog evidence.

    Ratings are analysis, not facts. Every rating must explain its basis and
    point at the catalog sources that support the underlying facts.
    """

    score: float
    basis: str
    source_ids: list[str] = Field(default_factory=list)


class Assumption(BaseModel):
    name: str
    value: str
    unit: str = ""
    basis: str = "편집상 가정"
    source_ids: list[str] = Field(default_factory=list)

    @property
    def is_editorial(self) -> bool:
        return "가정" in self.basis or "assumption" in self.basis.lower()


class MetricResult(BaseModel):
    key: str
    name: str
    value: float | None = None
    display: str = ""
    unit: str = ""
    formula: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    assumption: bool = False
    source_ids: list[str] = Field(default_factory=list)
    unavailable_reason: str = ""


class EvaluationItem(BaseModel):
    key: str
    name: str
    value: float | str | None = None
    display: str = ""
    unit: str = ""
    score: float | None = None
    basis: str = ""
    assumption: bool = False
    source_ids: list[str] = Field(default_factory=list)


class AnalysisDimension(BaseModel):
    name: str
    score: float | None = None
    weight: float = 0.0
    rationale: str = ""
    unavailable: bool = False
    mapped_items: list[str] = Field(default_factory=list)


class OriginalAnalysis(BaseModel):
    framework: str
    framework_name: str = ""
    purpose: str = ""
    formula: str = ""
    dimensions: list[AnalysisDimension] = Field(default_factory=list)
    evaluation_items: list[EvaluationItem] = Field(default_factory=list)
    metrics: list[MetricResult] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[Assumption] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    result: float | None = None
    interpretation: str = ""
    limitations: list[str] = Field(default_factory=list)
    scenario_analysis: list[dict[str, Any]] = Field(default_factory=list)
    comparison: list[dict[str, Any]] = Field(default_factory=list)
    mapping: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    subject: str = ""


class QualityScores(BaseModel):
    factual_accuracy: float = 0.0
    originality: float = 0.0
    search_intent: float = 0.0
    source_quality: float = 0.0
    readability: float = 0.0
    seo_quality: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.factual_accuracy
            + self.originality
            + self.search_intent
            + self.source_quality
            + self.readability
            + self.seo_quality,
            2,
        )


class QualityReport(BaseModel):
    scores: QualityScores = Field(default_factory=QualityScores)
    total: float = 0.0
    critical_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EditorialDraft(BaseModel):
    blog: str
    title: str
    slug: str
    meta_description: str = ""
    primary_keyword: str = ""
    secondary_keywords: list[str] = Field(default_factory=list)
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    body_markdown: str = ""
    analysis: OriginalAnalysis
    sources: list[ResearchSource] = Field(default_factory=list)
    topic: TopicCandidate
    created_at: str = Field(default_factory=utc_now_iso)
    catalog_id: str = ""


class EditorialArticle(BaseModel):
    article_id: str
    blog: str
    title: str
    seo_title: str = ""
    slug: str
    meta_description: str = ""
    primary_keyword: str = ""
    secondary_keywords: list[str] = Field(default_factory=list)
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    body_markdown: str = ""
    body_with_sources: str = ""
    analysis: OriginalAnalysis
    sources: list[ResearchSource] = Field(default_factory=list)
    topic: TopicCandidate
    quality: QualityReport
    decision: str = "DO NOT PUBLISH"
    decision_reason: str = ""
    status: str = "draft"  # draft | ready | published | failed
    catalog_id: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    published_at: str | None = None
    published_url: str | None = None
    failure_reason: str = ""

    def to_report(self) -> dict[str, Any]:
        """The A-F structured output required by the editorial brief."""

        return {
            "A. Article": {
                "title": self.title,
                "body_markdown": self.body_with_sources or self.body_markdown,
            },
            "B. SEO Metadata": {
                "seo_title": self.seo_title or self.title,
                "meta_description": self.meta_description,
                "slug": self.slug,
                "primary_keyword": self.primary_keyword,
                "secondary_keywords": self.secondary_keywords,
                "category": self.category,
                "tags": self.tags,
            },
            "C. Original Analysis": self.analysis.model_dump(),
            "D. Sources": [source.model_dump() for source in self.sources],
            "E. Quality Report": self.quality.model_dump(),
            "F. Publication Decision": {
                "decision": self.decision,
                "reason": self.decision_reason,
                "status": self.status,
            },
        }


def kst_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=9)))
