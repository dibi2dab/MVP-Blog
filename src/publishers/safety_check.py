from __future__ import annotations

from pathlib import Path

from src.models.article import Article
from src.utils.logging import get_logger

logger = get_logger(__name__)

MIN_BODY_LENGTH = 200
MAX_TAGS = 10


class SafetyCheckResult:
    def __init__(self, ok: bool, issues: list[str]) -> None:
        self.ok = ok
        self.issues = issues

    def __bool__(self) -> bool:
        return self.ok


def run_pre_publish_checks(article: Article, content_categories: dict[str, str], images: list[str] | None = None) -> SafetyCheckResult:
    """발행 직전 안전 검사. 하나라도 실패하면 발행하지 않는다."""
    issues: list[str] = []

    if not article.title or not article.title.strip():
        issues.append("제목이 비어 있음")

    body = article.body_markdown or ""
    if not body.strip():
        issues.append("본문이 비어 있음")
    elif len(body.strip()) < MIN_BODY_LENGTH:
        issues.append(f"본문이 너무 짧음 ({len(body.strip())}자 < {MIN_BODY_LENGTH}자)")

    if not article.sources:
        issues.append("출처 목록이 없음")

    images = images or []
    for img in images:
        if not Path(img).exists():
            issues.append(f"차트 파일 없음: {img}")

    if len(article.tags) > MAX_TAGS:
        issues.append(f"태그가 {MAX_TAGS}개 초과 ({len(article.tags)}개)")

    if article.category and article.category not in content_categories:
        issues.append(f"카테고리 없음: {article.category}")

    result = SafetyCheckResult(ok=not issues, issues=issues)
    if not result.ok:
        logger.warning("[tistory] pre-publish checks failed: %s", issues)
    return result