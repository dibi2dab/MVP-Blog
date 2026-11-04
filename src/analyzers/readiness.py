from __future__ import annotations

"""발행 준비 상태 판정.

품질 검수(QualityChecker)는 '글이 깨졌는가'를 보고,
readiness 는 '이 글을 실제로 발행할 만큼 독립적인 데이터와 분석이 있는가'를 본다.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime

from src.analysis.source_filter import parse_date
from src.config.settings import Settings
from src.models.analysis import AnalysisReport
from src.models.article import Article
from src.utils.similarity import article_similarity

_SEVERE_FACT_ISSUES = ("패킷에 없는 수치", "rejected", "조작", "허위")


@dataclass
class ReadinessResult:
    ready: bool = False
    public_ready: bool = False
    issues: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    independent_metrics: int = 0
    sources_with_url: int = 0
    max_similarity: float = 0.0
    age_days: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _age_days(value: str | None) -> int | None:
    day = parse_date(value)
    if not day:
        return None
    try:
        return (datetime.now() - datetime.strptime(day, "%Y-%m-%d")).days
    except ValueError:
        return None


def _has_heading(article: Article, *keywords: str) -> bool:
    headings = " ".join(s.heading or "" for s in article.sections)
    return all(k in headings for k in keywords)


def evaluate_readiness(
    article: Article,
    report: AnalysisReport | None,
    settings: Settings,
    recent_articles: list[Article] | None = None,
) -> ReadinessResult:
    cfg = settings.publishing
    result = ReadinessResult()
    recent_articles = recent_articles or []

    metrics = article.data_metrics or {}
    result.independent_metrics = len(metrics)
    result.checks["independent_metrics"] = result.independent_metrics >= cfg.min_independent_metrics

    result.sources_with_url = sum(1 for s in article.sources if "http" in (s or ""))
    result.checks["sources_with_url"] = result.sources_with_url >= cfg.min_sources_with_url

    headings = " ".join(s.heading or "" for s in article.sections)
    body = article.body_markdown or ""
    result.checks["search_intent_answer"] = ("검색 의도" in headings or "검색 의도" in body) and len(body) > 300
    result.checks["analysis_structure"] = _has_heading(article, "시나리오") and _has_heading(article, "확인")

    fact_ok = True
    if report is not None:
        if report.fact_check.rejected_claims:
            fact_ok = False
        if any(any(marker in note for marker in _SEVERE_FACT_ISSUES) for note in report.fact_check.issue_notes):
            fact_ok = False
        if cfg.require_fact_check_pass and report.fact_check.verdict != "pass":
            fact_ok = False
    result.checks["fact_check"] = fact_ok

    result.checks["quality_score"] = article.quality_score >= cfg.min_quality_score

    age_source = article.event.event_date or article.created_at
    result.age_days = _age_days(age_source)
    result.checks["freshness"] = result.age_days is not None and result.age_days <= cfg.max_event_age_days

    similarity = 0.0
    for other in recent_articles:
        if other.article_id == article.article_id:
            continue
        similarity = max(similarity, article_similarity(article, other))
    result.max_similarity = round(similarity, 4)
    result.checks["recent_similarity"] = similarity < cfg.max_recent_similarity

    failed = [name for name, ok in result.checks.items() if not ok]
    result.ready = not failed
    if failed:
        result.issues = [f"readiness 미충족: {name}" for name in failed]

    # 공개는 별도 기준을 모두 통과해야 한다. 기본값 allow_public=false 이면 항상 False.
    result.public_ready = bool(
        result.ready
        and cfg.allow_public
        and article.quality_score >= cfg.public_min_quality_score
        and report is not None
        and report.fact_check.verdict == "pass"
    )
    return result
