from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.models.source import utc_now_iso


class ResearchSource(BaseModel):
    """A single source collected before writing.

    ``source_id`` is the stable ID (``S1``, ``S2`` ...) used in prompts and in
    inline citations. ``url`` must be a real URL returned by the research step;
    the quality gate rejects URLs that are not in the research pool.
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
        date = self.published_at or "날짜 미상"
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


class AnalysisDimension(BaseModel):
    name: str
    score: float | None = None
    weight: float = 0.0
    rationale: str = ""
    unavailable: bool = False


class OriginalAnalysis(BaseModel):
    framework: str
    purpose: str = ""
    formula: str = ""
    dimensions: list[AnalysisDimension] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    data_sources: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    result: float | None = None
    interpretation: str = ""
    limitations: list[str] = Field(default_factory=list)
    scenario_analysis: list[dict[str, Any]] = Field(default_factory=list)


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


class SelfQuality(BaseModel):
    """The model's own QA estimate. It is a cross-check, never the authority."""

    factual_accuracy: float = 0.0
    originality: float = 0.0
    search_intent: float = 0.0
    source_quality: float = 0.0
    readability: float = 0.0
    seo_quality: float = 0.0
    total: float = 0.0
    critical_failures: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    scores: QualityScores = Field(default_factory=QualityScores)
    total: float = 0.0
    critical_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ai_self_total: float | None = None
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
    source_notes: list[dict[str, Any]] = Field(default_factory=list)
    self_quality: SelfQuality | None = None
    topic: TopicCandidate
    created_at: str = Field(default_factory=utc_now_iso)


class EditorialArticle(BaseModel):
    article_id: str
    blog: str
    title: str
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
    source_notes: list[dict[str, Any]] = Field(default_factory=list)
    topic: TopicCandidate
    quality: QualityReport
    decision: str = "DO NOT PUBLISH"
    decision_reason: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    published_at: str | None = None
    published_url: str | None = None

    def to_report(self) -> dict[str, Any]:
        """The A-F structured output required by the editorial master prompt."""

        return {
            "A. Article": {
                "title": self.title,
                "body_markdown": self.body_with_sources or self.body_markdown,
            },
            "B. SEO Metadata": {
                "seo_title": self.title,
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
            },
        }


def kst_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=9)))
