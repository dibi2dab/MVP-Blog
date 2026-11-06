from __future__ import annotations

"""Shared fixtures for the Crystal / Quartz editorial tests.

These helpers build fully-formed Korean articles so the deterministic quality
gate can be exercised without any network or AI calls.
"""

from src.editorial.models import (
    EditorialDraft,
    ResearchSource,
    SelfQuality,
    TopicCandidate,
)

KEYWORDS = {
    "crystal": "온라인 부업",
    "quartz": "AI 회계 자동화",
}

FRAMEWORKS = {"crystal": "CPPI", "quartz": "QDVI"}

RESULTS = {"crystal": 7.3, "quartz": 7.65}

_PRIMARY_URLS = {
    "crystal": "https://stripe.com/docs/billing/subscriptions/overview",
    "quartz": "https://openai.com/index/example-accounting",
}


def make_sources(blog: str = "quartz", count: int = 5) -> list[ResearchSource]:
    keyword = KEYWORDS[blog]
    primary_url = _PRIMARY_URLS[blog]
    sources: list[ResearchSource] = []
    for index in range(1, count + 1):
        is_primary = index == 1
        sources.append(
            ResearchSource(
                source_id=f"S{index}",
                title=f"{keyword} 관련 공개 자료 {index}",
                url=primary_url if is_primary else f"https://news.example.com/{blog}/{index}",
                publisher="공식 문서" if is_primary else "테스트뉴스",
                publisher_url="https://stripe.com" if blog == "crystal" and is_primary else (
                    "https://openai.com" if is_primary else "https://news.example.com"
                ),
                published_at="2026-11-05",
                snippet=f"{keyword}의 기능, 비용, 운영 방식에 대한 설명 {index}",
            )
        )
    return sources


def make_body(blog: str = "quartz") -> str:
    keyword = KEYWORDS[blog]
    framework = FRAMEWORKS[blog]
    paragraphs = [
        (
            f"{keyword} 도구는 반복 업무를 줄여 주는 대신 도입 비용과 학습 부담을 함께 요구합니다. [S1] "
            f"특히 작은 팀일수록 기능의 많고 적음보다 실제 업무 흐름에 얼마나 자연스럽게 붙는지를 먼저 확인해야 합니다. [S2] "
            f"{keyword}를 검토할 때는 기능, 사용성, 가격 대비 가치, 확장성, 신뢰성을 같은 기준으로 비교하는 편이 좋습니다. [S3]"
        ),
        (
            f"{keyword}의 핵심 기능은 단순한 자동화가 아니라 결과를 검토하고 바로잡는 과정까지 포함합니다. [S4] "
            f"도구가 제공하는 기능이 많더라도 실제 담당자가 이해하지 못하면 운영 비용은 오히려 늘어날 수 있습니다. "
            f"그래서 기능 목록과 함께 화면 구성, 오류 복구 방식, 문서의 구체성을 함께 살펴야 합니다. [S5]"
        ),
        (
            f"가격은 정액 구독과 사용량 기반 과금으로 나뉘는 경우가 많습니다. "
            f"{keyword} 도구를 고를 때는 표시 가격만 보지 말고 팀 규모가 커질 때의 비용 변화와 해지 조건을 함께 확인해야 합니다. [S1] "
            f"외부 서비스와 연결하는 확장성도 중요하지만, 연동이 많을수록 관리해야 할 권한과 보안 범위도 넓어집니다. [S3]"
        ),
        (
            f"{keyword} 도입의 가장 큰 위험은 기대 수익이나 절감 효과를 근거 없이 가정하는 것입니다. "
            f"공개된 자료에 없는 수치를 추정할 때는 보수적, 중립적, 낙관적 시나리오를 나누어 설명해야 합니다. [S2] "
            f"또한 자동화 결과를 검토하지 않으면 작은 오류가 반복될 수 있으므로 승인 절차를 함께 설계해야 합니다. [S4]"
        ),
        (
            f"결론적으로 {keyword} 도구는 만능 해결책이 아니라 업무 병목을 줄이는 보조 수단으로 봐야 합니다. "
            f"{framework} 점수는 선택지를 같은 기준으로 비교하도록 돕는 편집상 프레임워크이며, 실제 성과를 보장하지 않습니다. "
            f"도입 전에는 담당자, 예산, 검토 절차, 중단 기준을 문서로 합의해 두는 것이 안전합니다. [S5]"
        ),
    ]
    table = (
        "| 비교 항목 | A 도구 | B 도구 |\n"
        "| --- | --- | --- |\n"
        "| 핵심 기능 | 반복 업무 자동화 | 증빙 수집 자동화 |\n"
        "| 사용성 | 익숙한 화면 | 학습 필요 |\n"
        "| 가격 구조 | 정액 구독 | 사용량 기반 |\n"
        "| 확장성 | 외부 연동 지원 | 연동 제한 |\n"
        "| 신뢰성 | 공개 문서 제공 | 문서 부족 |"
    )
    headings = [
        f"## {keyword} 도구를 {framework}로 비교하는 이유",
        f"## {keyword}의 핵심 기능과 사용성",
        f"## {keyword}의 가격 대비 가치와 확장성",
        f"## {keyword} 도입 전 리스크와 결론",
    ]
    return "\n\n".join(
        [
            headings[0],
            paragraphs[0],
            headings[1],
            paragraphs[1],
            table,
            headings[2],
            paragraphs[2],
            headings[3],
            paragraphs[3],
            paragraphs[4],
        ]
    )


def make_analysis(blog: str = "quartz") -> dict:
    framework = FRAMEWORKS[blog]
    if framework == "CPPI":
        dimensions = [
            {"name": "Revenue Potential", "score": 8, "weight": 0.25, "rationale": "공개 자료 기준 수익화 경로가 명확함"},
            {"name": "Cost Efficiency", "score": 7, "weight": 0.20, "rationale": "초기 비용이 낮고 운영 비용을 통제할 수 있음"},
            {"name": "Time Efficiency", "score": 7, "weight": 0.20, "rationale": "주당 투입 시간을 조절할 수 있음"},
            {"name": "Execution Feasibility", "score": 8, "weight": 0.20, "rationale": "필요한 도구와 절차가 단순함"},
            {"name": "Risk Management", "score": 6, "weight": 0.15, "rationale": "수익 변동성과 플랫폼 의존 위험이 있음"},
        ]
        formula = (
            "CPPI = (Revenue Potential x 0.25) + (Cost Efficiency x 0.20) + "
            "(Time Efficiency x 0.20) + (Execution Feasibility x 0.20) + (Risk Management x 0.15)"
        )
    else:
        dimensions = [
            {"name": "Functional Capability", "score": 8, "weight": 0.25, "rationale": "공개 문서에 핵심 기능이 구체적으로 설명됨"},
            {"name": "Ease of Use", "score": 8, "weight": 0.20, "rationale": "기본 화면과 설정 절차가 단순함"},
            {"name": "Price-to-Value", "score": 7, "weight": 0.20, "rationale": "가격 구조가 투명하지만 규모 확대 시 비용이 증가함"},
            {"name": "Integration & Scalability", "score": 7, "weight": 0.15, "rationale": "주요 연동을 지원하나 고급 확장은 제한적임"},
            {"name": "Reliability & Transparency", "score": 8, "weight": 0.20, "rationale": "공식 문서와 변경 이력이 공개되어 있음"},
        ]
        formula = (
            "QDVI = (Functional Capability x 0.25) + (Ease of Use x 0.20) + "
            "(Price-to-Value x 0.20) + (Integration & Scalability x 0.15) + "
            "(Reliability & Transparency x 0.20)"
        )

    return {
        "framework": framework,
        "purpose": "공개 자료를 같은 기준으로 비교해 도입 여부를 판단하기 위한 분석",
        "formula": formula,
        "dimensions": dimensions,
        "inputs": {
            "공개 가격": "각 도구의 공식 가격 페이지에 표시된 요금제",
            "사용 인원": "소규모 팀을 가정한 편집상 가정",
            "검토 기간": "도입 전 검토 기간을 가정한 편집상 가정",
        },
        "data_sources": ["S1", "S2", "S3", "S4", "S5"],
        "steps": [
            "각 차원의 점수를 공개 자료와 공식 문서를 기준으로 0~10 범위에서 매긴다.",
            "차원별 점수에 공개된 가중치를 곱한다.",
            "가중 합계를 가중치 합계로 나누어 최종 점수를 구한다.",
            "점수의 의미와 한계를 해석에 함께 적는다.",
        ],
        "result": RESULTS[blog],
        "interpretation": "점수가 높을수록 공개 자료 기준의 비교 우위가 크지만, 실제 도입 성과는 운영 방식에 따라 달라질 수 있습니다.",
        "limitations": [
            "공개 문서에 없는 내부 성능과 실제 사용자 경험은 평가하지 않았다.",
            "가격과 기능은 변경될 수 있으므로 도입 전 최신 공식을 다시 확인해야 한다.",
            "이 점수는 편집상 의사결정 프레임워크이며 수익이나 성과를 보장하지 않는다.",
        ],
        "scenario_analysis": [
            {
                "scenario": "보수적",
                "assumptions": "기능 활용도가 낮고 검토 시간이 길어지는 경우",
                "result": "도입 효과가 제한적이므로 무료 체험 후 결정한다.",
            },
            {
                "scenario": "중립적",
                "assumptions": "공개 문서 수준의 기능을 절반 이상 활용하는 경우",
                "result": "반복 업무를 줄이는 데 도움이 될 수 있다.",
            },
        ],
    }


def make_self_quality() -> dict:
    return {
        "factual_accuracy": 22,
        "originality": 18,
        "search_intent": 18,
        "source_quality": 13,
        "readability": 9,
        "seo_quality": 9,
        "total": 89,
        "critical_failures": [],
        "notes": ["공개 자료 범위 안에서 작성함"],
    }


def make_topic(blog: str = "quartz") -> dict:
    keyword = KEYWORDS[blog]
    return {
        "topic": f"{keyword} 도구 비교",
        "search_intent": f"{keyword} 도구를 고르는 기준을 알고 싶다",
        "angle": "공개 문서를 바탕으로 같은 기준에서 비교한다",
        "why_now": "관련 도구의 공개 문서가 최근 갱신되었다",
        "source_ids": ["S1", "S2", "S3"],
        "primary_keyword": keyword,
        "category": "AI 도구" if blog == "quartz" else "온라인 수익",
    }


def make_article_payload(blog: str = "quartz") -> dict:
    keyword = KEYWORDS[blog]
    if blog == "quartz":
        title = "AI 회계 자동화 도구 선택 기준과 QDVI 분석"
        meta = (
            "AI 회계 자동화 도구를 고를 때 기능, 사용성, 가격 대비 가치, 확장성, "
            "신뢰성을 QDVI로 비교하고 도입 전에 확인해야 할 리스크와 체크리스트를 정리했습니다."
        )
        tags = ["AI 회계 자동화", "QDVI", "생산성 도구", "업무 자동화"]
    else:
        title = "온라인 부업 수익화 전략과 CPPI 분석"
        meta = (
            "온라인 부업을 시작할 때 수익 잠재력, 비용 효율, 시간 효율, 실행 가능성, "
            "리스크 관리를 CPPI로 비교하고 현실적인 수익화 전략과 주의할 점을 정리했습니다."
        )
        tags = ["온라인 부업", "CPPI", "블로그 수익화", "디지털 상품"]

    return {
        "title": title,
        "slug": f"{blog}-comparison",
        "meta_description": meta,
        "primary_keyword": keyword,
        "secondary_keywords": [f"{keyword} 비교", f"{keyword} 비용"],
        "category": "AI 도구" if blog == "quartz" else "온라인 수익",
        "tags": tags,
        "body_markdown": make_body(blog),
        "analysis": make_analysis(blog),
        "source_notes": [
            {"source_id": f"S{index}", "supports": "공개 기능과 가격 구조 설명"}
            for index in range(1, 6)
        ],
        "self_quality": make_self_quality(),
    }


def make_draft(
    blog: str = "quartz",
    *,
    body: str | None = None,
    sources: list[ResearchSource] | None = None,
) -> EditorialDraft:
    payload = make_article_payload(blog)
    from src.editorial.analysis import normalize_analysis
    from src.editorial.profiles import get_profile

    profile = get_profile(blog)
    analysis = normalize_analysis(payload["analysis"], profile).analysis
    return EditorialDraft(
        blog=blog,
        title=payload["title"],
        slug=payload["slug"],
        meta_description=payload["meta_description"],
        primary_keyword=payload["primary_keyword"],
        secondary_keywords=payload["secondary_keywords"],
        category=payload["category"],
        tags=payload["tags"],
        body_markdown=body if body is not None else payload["body_markdown"],
        analysis=analysis,
        sources=sources if sources is not None else make_sources(blog),
        source_notes=payload["source_notes"],
        self_quality=SelfQuality.model_validate(payload["self_quality"]),
        topic=TopicCandidate.model_validate(make_topic(blog)),
    )
