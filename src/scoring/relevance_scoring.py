from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.models.disclosure import Disclosure
from src.models.event import Event
from src.models.news import NewsItem
from src.models.source import EntityRef

_DATE_FMT = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


@dataclass
class SourceRelevance:
    """자료(뉴스/공시) 한 건이 해당 종목·이벤트와 얼마나 관련된지를 네 축으로 채점한다."""

    direct_company: float = 0.0     # 0~1: 해당 종목 직접 언급
    industry: float = 0.0           # 0~1: 관련 산업·재료
    event: float = 0.0              # 0~1: 이번 이벤트 유형과 일치
    timeline: float = 0.0           # 0~1: 주가 움직임과 시간적 관련
    include: bool = False           # 본문 포함 여부
    reason: str = ""


def _near(a: str | None, b: str | None, window: int = 3) -> bool:
    a = (a or "")[:10].replace("-", "")
    b = (b or "")[:10].replace("-", "")
    if not a.isdigit() or not b.isdigit():
        return False
    return abs(int(a) - int(b)) <= window


def _has_hangul(word: str) -> bool:
    return any("\uac00" <= c <= "\ud7a3" for c in word or "")


def _titleish(text: str) -> str:
    return text or ""


class SourceRelevanceScorer:
    """Source Relevance Filter(요구사항 8).

    규칙:
    - 직접 관련(Direct Company Relevance 높음) → 포함
    - 또는 산업 관련성이 높고(Industry Relevance) 주가 움직임과 시간적으로 관련
      (Timeline Relevance) → 포함
    - 그 외(삼성전자 공시가 삼성전기 기사로 들어가는 경우 등) → 제외
    """

    def __init__(self, event_name: str, ticker: str, event_date: str | None, event_type: str = "") -> None:
        self.entity_name = event_name or ""
        self.ticker = ticker or ""
        self.event_date = event_date
        self.event_type = event_type
        self._tokens: set[str] = self._make_tokens(event_name)

    @classmethod
    def from_event(cls, event: Event) -> "SourceRelevanceScorer":
        return cls(
            event.entity.name or "",
            event.entity.ticker or "",
            event.event_date,
            event.event_type,
        )

    def _make_tokens(self, name: str) -> set[str]:
        tokens = set()
        if name:
            tokens.add(name)
        if self.ticker and self.ticker != "@disclosure":
            tokens.add(self.ticker)
        return tokens

    # ------------------------------------------------------------------ #
    def score_news(self, item: NewsItem) -> SourceRelevance:
        title = _titleish(item.title)
        summary = _titleish(item.summary)
        text = f"{title} {summary}"
        rel = SourceRelevance()

        # 1) Direct Company Relevance: 종목명/코드 언급
        direct = 0.0
        raw = title
        if self.entity_name and (self.entity_name in raw or self.ticker in raw):
            direct = 1.0
        elif self.entity_name and any(t for t in (self.entity_name, self.ticker) if t and t in text):
            direct = 0.6
        rel.direct_company = direct

        # 2) Industry Relevance: 일반 산업 재료(주가/거래량/업종 등) — 뉴스는 기본 소정치
        if any(k in text for k in ("급등", "급락", "전일 대비", "거래량", "공시", "실적")):
            rel.industry = min(1.0, rel.industry + 0.4)
        rel.industry = min(1.0, rel.industry + 0.2)  # 뉴스는 산업 컨텍스트 기본 제공

        # 3) Event Relevance: 이벤트 유형 키워드
        rel.event = self._event_keyword_hit(text)

        # 4) Timeline Relevance: 특정일 뉴스가 이벤트일과 근접
        if self.event_date and _near(item.published_at, self.event_date):
            rel.timeline = 1.0
        elif self.event_date is None:
            rel.timeline = 0.3

        rel.include = self._decide_include(rel.direct_company, rel.industry, rel.timeline)
        rel.reason = self._reason(rel)
        return rel

    def score_disclosure(self, d: Disclosure) -> SourceRelevance:
        title = _titleish(d.title)
        corp = _titleish(d.corp_name)
        rel = SourceRelevance()

        direct = 0.0
        if corp and corp == self.entity_name:
            direct = 1.0
        elif self.entity_name and (self.entity_name in title or self.ticker in title):
            direct = 1.0
        rel.direct_company = direct

        rel.industry = 1.0 if direct else 0.0
        rel.event = self._event_keyword_hit(title)
        if rel.direct_company:
            rel.timeline = 1.0
        elif self.event_date and _near(d.published_at, self.event_date):
            rel.timeline = 1.0

        rel.include = rel.direct_company >= 1.0
        rel.reason = "기업 직접 공시" if rel.include else "해당 종목 공시 아님 — 관련성이 설명되지 않아 제외"
        return rel

    def score_entity(self, ref: EntityRef) -> float:
        """관련 종목 스냅샷 하나가 실제로 '관련'인지. 이름이 같은 지수 그룹/동일 산업일 때 높임."""
        if not ref.name:
            return 0.0
        if ref.name == self.entity_name or ref.ticker == self.ticker:
            return 0.0  # 자기 자신
        # 동일 산업(단순 같은 이름 전처리) — 이 단계에선 다른 종목은 낮게
        return 0.3

    # ------------------------------------------------------------------ #
    def _event_keyword_hit(self, text: str) -> float:
        et = self.event_type
        if et in ("stock_surge", "stock_crash"):
            for k in ("급등", "급락", "상승", "하락", "주가"):  # noqa: B007
                if k in text:
                    return 0.8
            return 0.3
        if et == "earnings":
            return 1.0 if ("실적" in text or "매출" in text) else 0.2
        if et == "disclosure":
            return 1.0 if "공시" in text else 0.2
        if et == "stock_breakout":
            return 0.8 if ("신고가" in text or "급등" in text) else 0.3
        return 0.2

    def _decide_include(self, direct: float, industry: float, timeline: float) -> bool:
        if direct >= 1.0:
            return True
        if industry >= 0.6 and timeline >= 0.7:
            return True
        return False

    def _reason(self, rel: SourceRelevance) -> str:
        if rel.direct_company >= 1.0:
            return "해당 종목 직접 언급"
        if rel.include:
            return "산업 관련성 + 시점 연관"
        return "관련성 부족으로 제외"