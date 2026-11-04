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
        """계산 지표 기반 제목 생성.

        규칙:
        - '[YYYY년 M월 D일]' 정확한 날짜로 시작
        - 종목명 + 변동률 + 거래량 배수 + 20일선 이격을 조합
        - '왜 …했을까?' 같은 낚시성 템플릿 금지
        - 기사마다 숫자가 달라 제목이 자연스럽게 구분된다
        """
        name = event.entity.name or "종목"
        date_prefix = f"[{format_korean_date(event.event_date)}]"
        evidence = evidence or {}

        # generate_step 은 percent 단위(예: -5.37)를 quant 에 담아 넘긴다.
        quant = evidence.get("quant_metrics") or {}
        pct = quant.get("change_pct")
        vol = quant.get("volume_ratio")
        ma20 = quant.get("distance_ma20_pct")
        gap = quant.get("gap_pct")

        if pct is None:
            # 이전 호출 호환: fraction 단위(0.05)일 수 있다.
            legacy = evidence.get("latest_change_pct")
            if legacy is not None:
                pct = float(legacy) * 100 if abs(float(legacy)) <= 1 else float(legacy)
        if vol is None:
            vol = evidence.get("volume_ratio")

        if pct is None:
            return self._clean_title(f"{date_prefix} {name} 시장 이벤트 확인")

        direction = "상승" if pct > 0 else "하락" if pct < 0 else "보합"
        parts = [f"{abs(pct):.2f}% {direction}"]
        if vol is not None:
            parts.append(f"거래량 {vol:.2f}배")
        if ma20 is not None:
            parts.append(f"20일선 {ma20:+.2f}%")
        elif gap is not None and abs(gap) >= 1.0:
            parts.append(f"갭 {gap:+.2f}%")
        return self._clean_title(f"{date_prefix} {name} " + "·".join(parts))

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

    def description(self, event: Event, body_preview: str, quant: dict | None = None) -> str:
        quant = quant or {}
        bits: list[str] = []
        if quant.get("change_pct") is not None:
            bits.append(f"전일 대비 {quant['change_pct']:+.2f}%")
        if quant.get("volume_ratio") is not None:
            bits.append(f"20일 평균 거래량의 {quant['volume_ratio']:.2f}배")
        if quant.get("distance_ma20_pct") is not None:
            bits.append(f"20일선 대비 {quant['distance_ma20_pct']:+.2f}%")
        if bits:
            return f"{event.entity.name}의 {', '.join(bits)} 움직임을 자체 계산 지표와 확인된 출처로 분석한 글입니다."[:180]
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