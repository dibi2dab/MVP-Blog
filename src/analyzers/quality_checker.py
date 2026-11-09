from __future__ import annotations

import re

from src.analyzers.ai_provider import AIProvider
from src.config.settings import Settings
from src.models.analysis import QualityCheckResult
from src.models.article import Article
from src.utils.korean import format_korean_date
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """당신은 금융 블로그 기사 품질 편집자다.
검사 항목:
- AI 같은 반복 표현
- 같은 문장 구조 반복
- 불필요한 문단
- 내용 중복
- 근거 없는 전망
- 과도한 투자 권유 (매수/시세를 부추기는 표현)
- 데이터와 글의 불일치
- 출처 누락 (아래 sources 목록을 글에 반영했는가)
- 투자 면책 문구 미포함
- 제목에 날짜/종목명/핵심 숫자가 있는가
- 관련 없는 공시가 포함되지 않았는가
- 차트에 설명이 있는가
- 작성 과정이나 편집 기준을 설명하는 메타 문장
- 형식적인 평가표, 자체 점수, 의미 없는 지수·순위
- 모든 글에 반복되는 주의사항
- 주제와 무관한 FAQ
- 같은 사실을 여러 번 설명하는 문장

응답 JSON:
{
  "passed": true|false,
  "score": 0.0~1.0,
  "issues": ["..."],
  "suggestions": ["..."]
}
"""

# 요구사항 #14: 금지하는 일반적 AI 문장
_GENERIC_SENTENCES = [
    "향후 추이를 지켜볼 필요가 있다",
    "시장 상황을 확인해야 한다",
    "추가적인 확인이 필요하다",
    "전문가들은 주목하고 있다",
    "향후 상승 가능성이 있다",
    "시장 상황을 지켜봐야 한다",
    "투자자들의 관심이 집중되고 있다",
    "향후 수익률이 기대된다",
]

# 새 작성 기준: 독자에게 노출하면 안 되는 메타 문장
_META_SENTENCES = [
    "이 글에서는",
    "무엇을 알아볼까요",
    "이 평가는 직접 사용 후기인가요",
    "실제 사용 경험을 바탕으로 작성했는가",
    "독자마다 다르게 느낄 수 있습니다",
    "상황에 따라 달라질 수 있으므로 참고하시기 바랍니다",
    "작성 과정",
    "편집 기준",
]

# 새 작성 기준: 의미 없는 점수·지수
_SCORE_MARKERS = ("CPPI", "QDVI", "평가 지수", "종합 점수")
_SCORE_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*/\s*10")

# 요구사항 #8: 금지/과장 표현
_BANNED = ["반드시 오를", "무조건 매수", "매수 추천", "지금 사야", "무조건 오른다"]

# 요구사항 #2: 과도하게 일반적이거나 AI 느낌이 강한 제목 문구
_GENERIC_TITLE = [
    "데이터로 본 주가·거래량의 실체",
    "오늘 무슨 일이 있었나",
    "주가 움직임의 비밀",
    "전망",
]


class QualityChecker:
    """Agent 4 — 최종 품질 검수. 발행 전 Article Quality Score 계산."""

    def __init__(self, provider: AIProvider, settings: Settings, include_disclaimer: bool = True) -> None:
        self.provider = provider
        self.settings = settings
        self.include_disclaimer = include_disclaimer

    def check(self, article: Article, markdown: str) -> QualityCheckResult:
        if self.settings.app.mock_mode == "true" or self.provider.name == "mock":
            return self._rule_check(article, markdown)

        import json

        user_prompt = json.dumps(
            {
                "title": article.title,
                "body": article.body_markdown or markdown,
                "sources": article.sources,
                "tags": article.tags,
            },
            ensure_ascii=False,
            indent=2,
        )
        raw = self.provider.chat_json(_SYSTEM_PROMPT, user_prompt, temperature=0.0)
        return QualityCheckResult(
            passed=bool(raw.get("passed", True)),
            score=float(raw.get("score", 0.8)),
            issues=[str(i) for i in raw.get("issues", [])],
            suggestions=[str(s) for s in raw.get("suggestions", [])],
        )

    def _rule_check(self, article: Article, markdown: str) -> QualityCheckResult:
        """규칙 기반 Article Quality Score (요구사항 15). mock 모드에서도 동일 기준 적용."""
        issues: list[str] = []
        suggestions: list[str] = []
        body = article.body_markdown or markdown
        text_body = _strip_md(body)
        title = article.title or ""
        event = article.event

        # ---- Evidence / Source Coverage ----
        if not article.sources:
            issues.append("출처 목록이 비어 있음 (Evidence Coverage 부족)")
        if "## 참고 자료" not in body and "참고" not in body:
            issues.append("출처(참고 자료) 섹션 누락")

        # ---- 금지/과장 표현 ----
        for word in _BANNED:
            if word in text_body:
                issues.append(f"부적절한 투자 권유 표현 포함: {word}")

        # ---- 면책 문구 ----
        if self.include_disclaimer and "투자" not in text_body:
            suggestions.append("투자 판단은 본인의 책임이라는 면책 문구 권장")

        # ---- 데이터/특이도 (Specificity & Data Coverage) ----
        has_number = re.search(r"[\d,.]+\s*%", text_body) or re.search(r"[\d.]+\s*배", text_body)
        if not has_number:
            issues.append("구체적 수치(Data Coverage) 부족 — 본문에 % 또는 배 단위 데이터 없음")

        # ---- Section Relevance (빈 섹션 제거 여부) ----
        empty_sections = [s.heading for s in article.sections if not s.body or not s.body.strip()]
        if empty_sections:
            issues.append(f"빈 섹션 존재 (Section Relevance): {', '.join(empty_sections[:3])}")

        # ---- (요구사항 15) 제목 검사 ----
        self._check_title(title, event, issues)

        # ---- (요구사항 15) 제목-본문 일치 ----
        self._check_title_body_match(title, text_body, issues)

        # ---- (요구사항 15 / 10) 동일 데이터 반복 ----
        rep = self._repetition(body)
        if rep["duplicate_sentences"]:
            issues.append(f"반복 문장 {rep['duplicate_sentences']}개 발견")
        if rep["ratio"] > 0.35:
            issues.append("문장 반복 비율이 높음 (Repetition 높음)")

        # ---- (요구사항 15) 일반적 AI 문장 과다 ----
        generic = self._generic_hits(text_body)
        if generic:
            issues.append(f"일반적 문장 사용 {len(generic)}건: {', '.join(generic[:3])}")

        # ---- 새 작성 기준: 메타 문장 / 의미 없는 점수 ----
        self._check_meta_and_scores(text_body, issues)

        # ---- (요구사항 15) 차트에 설명이 있는가 ----
        self._check_chart_descriptions(body, text_body, issues)

        # ---- (요구사항 13, 15) 최소 길이 ----
        min_len = self._min_chars_for(article)
        if len(text_body) < min_len:
            issues.append(f"본문이 유형별 최소 길이({min_len}자)에 미달 — 현재 {len(text_body)}자")

        # ---- (요구사항 8) 관련 없는 공시 포함 여부 ----
        self._check_unrelated_disclosures(article, issues)

        # ---- 점수 산정 ----
        score = 1.0
        score -= len(issues) * 0.15
        score -= rep["ratio"] * 0.4
        score = max(0.0, min(1.0, score))

        return QualityCheckResult(
            passed=not issues,
            score=round(score, 2),
            issues=issues,
            suggestions=suggestions,
        )

    # ------------------------------------------------------------------ #
    def _min_chars_for(self, article: Article) -> int:
        cfg = self.settings.content_quality
        if article.event and article.event.publication_type == "A":
            return cfg.min_deep_chars
        return cfg.min_data_brief_chars

    def _check_title(self, title: str, event, issues: list[str]) -> None:
        """요구사항 1, 2, 15: 날짜·종목명·핵심 숫자가 제목에 있는가."""
        if not title:
            issues.append("제목 비어 있음")
            return
        # 날짜
        date_prefix = f"[{format_korean_date(getattr(event, 'event_date', None))}]"
        if date_prefix not in title:
            issues.append(f"제목에 정확한 날짜({date_prefix}) 없음")
        # 종목명
        name = event.entity.name if event and event.entity else ""
        if name and name not in title:
            issues.append("제목에 종목명 없음")
        # 핵심 숫자 (변동률 % 또는 배)
        if not re.search(r"\d+\.\d+%", title):
            if not re.search(r"\d+\.\d+배", title):
                issues.append("제목에 핵심 숫자(변동률/거래량 배수) 없음")
        # 금지 일반 문구
        for phrase in _GENERIC_TITLE:
            if phrase in title:
                issues.append(f"과도하게 일반적인 제목 문구 사용: {phrase}")

    def _check_title_body_match(self, title: str, text_body: str, issues: list[str]) -> None:
        """요구사항 15: 제목이 본문과 일치하는가."""
        if not title:
            return
        # 제목의 핵심 변동률이 본문에 등장하는지
        m = re.search(r"(\d+\.\d+)%", title)
        if m and m.group(1) not in text_body:
            issues.append("제목의 변동률이 본문에 없어 불일치 가능성 (Title/본문 Mismatch)")

    def _check_chart_descriptions(self, body: str, text_body: str, issues: list[str]) -> None:
        """요구사항 12, 15: 차트 앞뒤에 설명이 있는가."""
        if "![" not in body:
            return
        # 차트 섹션이 "차트" 헤딩 아래 이미지만 나열일 때 설명 문구가 있는지
        if "확인" not in text_body and "흐름" not in text_body:
            issues.append("차트가 이미지만 나열되어 해석 문구 없음 (차트 설명 누락)")

    def _check_unrelated_disclosures(self, article: Article, issues: list[str]) -> None:
        """요구사항 8, 15: 다른 회사 공시가 본문에 포함됐는지."""
        name = article.event.entity.name if article.event and article.event.entity else ""
        if not article.sections:
            return
        for sec in article.sections:
            if sec.heading and "공시" in sec.heading:
                # 본문에 종목명 외 다른 회사가 강조된 표·문장이 있는지
                # 단순하면서 안전한 검사: '직접 관련' 표시 없는 공시 나열이면 의심
                if sec.body.count("|") > 6 and name and name not in sec.body:
                    issues.append("다른 회사 공시가 본문에 포함됨 (Source Relevance 위반)")
                break

    # ------------------------------------------------------------------ #
    def _title_ok(self, title: str, publication_type: str) -> bool:
        """"왜 ...했을까" 제목은 원인 확인(Deep Analysis)에서만 허용한다."""
        if not title:
            return True
        if "왜" in title and "했을까" in title:
            return publication_type == "A"
        return True

    def _repetition(self, body: str) -> dict:
        has_hangul = re.compile(r"[가-힣]")
        markdown_chars = re.compile(r"[\[\]()!`#>]")
        sents = [s.strip() for s in re.split(r"[.!?\n]", body)]
        filtered = [
            s
            for s in sents
            if has_hangul.search(s)
            and not markdown_chars.search(s)
            and 2 <= len(s) <= 40
            and not _is_generic(s)
        ]
        freq: dict[str, int] = {}
        for s in filtered:
            freq[s] = freq.get(s, 0) + 1
        duplicates = [s for s, c in freq.items() if c >= 3]
        ratio = (len(duplicates) / len(filtered)) if filtered else 0.0
        return {"duplicate_sentences": len(duplicates), "ratio": ratio}

    def _generic_hits(self, text: str) -> list[str]:
        hits = []
        for phrase in _GENERIC_SENTENCES:
            if phrase in text:
                hits.append(phrase)
        return hits

    def _check_meta_and_scores(self, text: str, issues: list[str]) -> None:
        """새 작성 기준: 작성 과정 메타 문장과 의미 없는 점수를 차단한다."""
        meta = [phrase for phrase in _META_SENTENCES if phrase in text]
        if meta:
            issues.append(f"작성 과정을 설명하는 메타 문장 포함: {', '.join(meta[:3])}")
        markers = [marker for marker in _SCORE_MARKERS if marker in text]
        if markers:
            issues.append(f"의미 없는 자체 점수·지수 표현 포함: {', '.join(markers[:3])}")
        if _SCORE_PATTERN.search(text):
            issues.append("본문에 근거 없는 10점 척도 점수가 포함됨")


def _is_generic(sent: str) -> bool:
    return any(g in sent for g in _GENERIC_SENTENCES)


def _strip_md(md: str) -> str:
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)  # 이미지
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)  # 링크
    md = re.sub(r"[#>*`-]", " ", md)
    return re.sub(r"\s+", " ", md).strip()