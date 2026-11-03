from __future__ import annotations

import re
import unicodedata

from src.models.article import Article
from src.models.event import Event
from src.utils.korean import topic_after, format_korean_date


class SeoGenerator:
    """제목/슬러그/설명/Tag/키워드 자동 생성. 낚시성 과장은 하지 않는다."""

    def __init__(self, banned_title_phrases: list[str] | None = None) -> None:
        self.stopwords = {"코스피", "코스닥", "증권시장", "핵심", "관련"}
        self.banned = set(banned_title_phrases or [])

    def title(self, event: Event, publication_type: str = "B", evidence: dict | None = None) -> str:
        """근거 기반 제목 생성 (요구사항 1, 2).

        규칙:
        - 모든 제목은 '[YYYY년 M월 D일]' 정확한 날짜로 시작
        - 종목명 + 문법에 맞는 주격 조사(은/는/이/가)
        - 핵심 변동률, 확정된 원인일 땐 분석 주제
        - 금지 일반 문구(데이터로 본 주가·거래량의 실체 등) 미사용
        - 원인 미확인(Data Brief) → "왜 ...했을까?" 금지
        """
        name = event.entity.name or "종목"
        date_prefix = f"[{format_korean_date(event.event_date)}]"
        pct = evidence.get("latest_change_pct") if evidence else None
        vol = evidence.get("volume_ratio") if evidence else None
        pct_disp = f"{abs(pct) * 100:.2f}%" if pct is not None else None
        is_up = pct is not None and pct > 0
        is_down = pct is not None and pct < 0
        direction = "상승" if is_up else "하락" if is_down else "변동"

        if publication_type == "A":
            # 원인이 확인된 경우에만 분석 주제 제목
            cause = "왜 급등했을까? 확인된 뉴스와 데이터 분석" if is_up else \
                    "왜 하락했을까? 확인된 뉴스와 데이터 분석" if is_down else \
                    "시장 이벤트 심층 분석"
            return self._clean_title(f"{date_prefix} {name}{topic_after(name)} {cause}")

        # Type B (사실 기반) — 가격·거래량 중심 제목
        if pct_disp is None:
            return self._clean_title(f"{date_prefix} {name} 시장 이벤트 확인")
        if vol is not None and vol >= 1.2:
            return self._clean_title(
                f"{date_prefix} {name} {pct_disp} {direction}…거래량은 평균의 {vol:.1f}배"
            )
        return self._clean_title(f"{date_prefix} {name} {pct_disp} {direction}…확인된 데이터 분석")

    def _clean_title(self, title: str) -> str:
        # 일반적/AI 느낌 문구 제거 또는 대체 (요구사항 2)
        for phrase in self.banned:
            title = title.replace(phrase, "")
        title = re.sub(r"\s{2,}", " ", title).strip()
        title = re.sub(r"\s?[—\-]\s*$", "", title).strip()
        return title.strip()

    def slug(self, title: str) -> str:
        s = unicodedata.normalize("NFKC", title.lower())
        s = re.sub(r"[—\-—–(),.·]", " ", s)
        s = re.sub(r"[^\w\s가-힣]", "", s)
        return re.sub(r"\s+", "-", s).strip("-").replace(" ", "-")

    def description(self, event: Event, body_preview: str) -> str:
        line = " ".join(body_preview.split())[:130]
        return line or f"{event.entity.name} 시장 동향을 수집된 데이터와 뉴스·공시 기반으로 정리합니다."

    def tags(self, event: Event) -> list[str]:
        name = event.entity.name or ""
        tags = [name] if name else []
        if event.event_type == "stock_surge":
            tags += ["급등주", "주가", "거래량"]
        elif event.event_type == "stock_crash":
            tags += ["급락주", "주가", "거래량"]
        elif event.event_type == "earnings":
            tags += ["실적", "기업분석"]
        elif event.event_type == "disclosure":
            tags += ["공시", "DART"]
        else:
            tags += ["증시", "시장분석"]
        return list(dict.fromkeys(tags))

    def keywords(self, event: Event) -> list[str]:
        return self.tags(event) + (["주식시장"] if event.event_type.startswith("stock") else [])

    def frontmatter(self, article: Article) -> dict:
        return {
            "title": article.title,
            "description": article.description,
            "date": article.created_at[:10],
            "category": article.category,
            "tags": article.tags,
            "keywords": article.keywords,
            "event_id": article.event.event_id,
            "event_type": article.event.event_type,
            "entity": article.event.entity.name,
            "ticker": article.event.entity.ticker,
            "sources": article.sources,
        }