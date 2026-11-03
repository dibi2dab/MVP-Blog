from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.models.source import utc_now_iso

ClaimType = Literal["fact", "hypothesis", "uncertain"]


class Claim(BaseModel):
    """AI 분석의 단위 주장. confidence 가 minimum_confidence 미만이면 기사에서 제외."""

    claim: str
    type: ClaimType = "fact"
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    source_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""


class AnalystOutput(BaseModel):
    """Research Analyst (Agent 1) 결과."""

    facts: list[Claim] = Field(default_factory=list)
    hypotheses: list[Claim] = Field(default_factory=list)
    key_drivers: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    summary: str = ""


class FactCheckResult(BaseModel):
    """Skeptic / Fact Checker (Agent 2) 결과."""

    approved_claims: list[Claim] = Field(default_factory=list)
    rejected_claims: list[Claim] = Field(default_factory=list)
    replaced_claims: list[Claim] = Field(default_factory=list)
    issue_notes: list[str] = Field(default_factory=list)
    verdict: str = "pass"


class QualityCheckResult(BaseModel):
    """Quality Editor (Agent 4) 결과."""

    passed: bool = True
    score: float = 0.0
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    """전체 분석 파이프라인 최종 산출물."""

    packet_id: str
    event_id: str
    analyst_output: AnalystOutput = Field(default_factory=AnalystOutput)
    fact_check: FactCheckResult = Field(default_factory=FactCheckResult)
    quality_check: QualityCheckResult | None = None
    generated_at: str = Field(default_factory=utc_now_iso)

    def actionable_claims(self) -> list[Claim]:
        ids = {c.claim for c in self.fact_check.replaced_claims}
        out = [c for c in self.fact_check.approved_claims if c.claim not in ids]
        for c in self.fact_check.replaced_claims:
            out.append(c)
        return out