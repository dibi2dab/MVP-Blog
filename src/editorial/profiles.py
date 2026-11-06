from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BlogProfile:
    """Editorial identity and runtime wiring for one blog.

    The profile deliberately does not touch Obsidian. Obsidian keeps its own
    pipeline, categories and topic strategy.
    """

    key: str
    display_name: str
    blog_name: str
    blog_url: str
    framework: str
    framework_name: str
    editorial_direction: str
    topic_queries: tuple[str, ...]
    categories: tuple[str, ...]
    default_category: str
    storage_state_path: str
    kakao_id: str = ""
    kakao_password: str = ""
    tistory_category: str = ""
    visibility: str = "public"
    max_articles_per_day: int = 1
    min_quality_score: float = 85.0
    min_sources: int = 3
    recent_window: int = 30
    language: str = "ko"

    @property
    def slug_prefix(self) -> str:
        return self.key

    @property
    def source_domains(self) -> tuple[str, ...]:
        return (
            "docs.",
            "developer.",
            "support.",
            "openai.com",
            "anthropic.com",
            "google.com",
            "microsoft.com",
            "github.com",
            "stripe.com",
            "shopify.com",
            "notion.so",
            "aws.amazon.com",
            "cloud.google.com",
            ".go.kr",
            ".gov",
        )


_CRYSTAL_QUERIES = (
    "온라인 부업",
    "블로그 수익화",
    "제휴 마케팅",
    "디지털 상품 판매",
    "사이드 프로젝트 수익",
    "콘텐츠 수익화",
    "웹사이트 수익",
    "AI 부업",
)

_QUARTZ_QUERIES = (
    "AI 도구",
    "AI 서비스",
    "개발자 도구",
    "업무 자동화",
    "생산성 앱",
    "소프트웨어 비교",
    "AI 에이전트",
    "노코드 자동화",
)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _blog_name_from_url(url: str, fallback: str) -> str:
    match = re.match(r"https?://([A-Za-z0-9_-]+)\.tistory\.com", url or "")
    if match:
        return match.group(1)
    return fallback


def _profile(
    *,
    key: str,
    display_name: str,
    fallback_blog_name: str,
    fallback_blog_url: str,
    framework: str,
    framework_name: str,
    editorial_direction: str,
    topic_queries: tuple[str, ...],
    categories: tuple[str, ...],
    default_category: str,
) -> BlogProfile:
    prefix = key.upper()
    blog_url = _env(f"{prefix}_BLOG_URL", fallback_blog_url)
    blog_name = _env(
        f"{prefix}_BLOG_NAME",
        _blog_name_from_url(blog_url, fallback_blog_name),
    )
    storage_state = _env(
        f"{prefix}_STORAGE_STATE_PATH",
        f".state/{key}_storage_state.json",
    )
    return BlogProfile(
        key=key,
        display_name=display_name,
        blog_name=blog_name,
        blog_url=blog_url,
        framework=framework,
        framework_name=framework_name,
        editorial_direction=editorial_direction,
        topic_queries=topic_queries,
        categories=categories,
        default_category=default_category,
        storage_state_path=storage_state,
        kakao_id=_env(f"{prefix}_KAKAO_ID", _env("TISTORY_KAKAO_ID")),
        kakao_password=_env(f"{prefix}_KAKAO_PASSWORD", _env("TISTORY_KAKAO_PASSWORD")),
        tistory_category=_env(f"{prefix}_TISTORY_CATEGORY", ""),
        visibility=_env(f"{prefix}_VISIBILITY", _env("TISTORY_VISIBILITY", "public")),
        max_articles_per_day=int(_env(f"{prefix}_MAX_ARTICLES_PER_DAY", "1") or 1),
        min_quality_score=float(_env(f"{prefix}_MIN_QUALITY_SCORE", "85") or 85),
        min_sources=int(_env(f"{prefix}_MIN_SOURCES", "3") or 3),
    )


def get_profile(key: str) -> BlogProfile:
    """Build a fresh profile so environment overrides work in tests/CI."""

    normalized = (key or "").strip().lower()
    if normalized == "crystal":
        return _profile(
            key="crystal",
            display_name="Crystal (Itmeans)",
            fallback_blog_name="rumbell",
            fallback_blog_url="https://rumbell.tistory.com",
            framework="CPPI",
            framework_name="Crystal Practical Profitability Index (CPPI)",
            editorial_direction=(
                "Online income and side hustles, website and blog monetization, "
                "affiliate marketing, digital products, website operations, and "
                "practical online business solutions."
            ),
            topic_queries=_CRYSTAL_QUERIES,
            categories=(
                "온라인 수익",
                "부업",
                "블로그 수익화",
                "제휴 마케팅",
                "디지털 상품",
                "사이트 운영",
            ),
            default_category="온라인 수익",
        )
    if normalized == "quartz":
        return _profile(
            key="quartz",
            display_name="Quartz",
            fallback_blog_name="quar1z",
            fallback_blog_url="https://quar1z.tistory.com",
            framework="QDVI",
            framework_name="Quartz Digital Value Index (QDVI)",
            editorial_direction=(
                "Artificial intelligence, AI tools and services, software analysis "
                "and comparisons, digital product analysis, developer tools, "
                "automation and productivity, and practical technology guides."
            ),
            topic_queries=_QUARTZ_QUERIES,
            categories=(
                "AI",
                "AI 도구",
                "소프트웨어 분석",
                "디지털 상품",
                "개발자 도구",
                "자동화·생산성",
            ),
            default_category="AI 도구",
        )
    raise ValueError(f"unknown editorial blog: {key!r} (expected 'crystal' or 'quartz')")


def list_profiles() -> list[BlogProfile]:
    return [get_profile("crystal"), get_profile("quartz")]


# A small compatibility alias used by tests and tooling.
PROFILE_KEYS = ("crystal", "quartz")
