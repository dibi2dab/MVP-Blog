from __future__ import annotations

"""기사 간 유사도 계산.

본문 전체를 그대로 비교하면 공통 템플릿 문장 때문에 서로 다른 종목도 높게 나온다.
그래서 (1) 제목, (2) 이벤트/종목, (3) 계산 지표 서명을 조합해
'실질적으로 같은 글'인지 판단한다.
"""

import re
from difflib import SequenceMatcher

from src.models.article import Article


def _norm_title(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _metric_signature(article: Article) -> set[str]:
    signature: set[str] = set()
    for key, value in (article.data_metrics or {}).items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        # 지표마다 반올림 단위를 달리해 '거의 같은 값'을 같은 버킷으로 묶는다.
        if key in ("change_pct", "gap_pct", "return_5d", "return_20d", "distance_ma20_pct", "distance_ma60_pct"):
            bucket = round(number / 0.5) * 0.5
        elif key in ("volume_ratio", "amount_ratio", "range_expansion_ratio"):
            bucket = round(number / 0.2) * 0.2
        elif key in ("volume_zscore", "return_zscore"):
            bucket = round(number / 0.5) * 0.5
        else:
            bucket = round(number, 1)
        signature.add(f"{key}:{bucket:g}")
    return signature


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def article_similarity(a: Article, b: Article) -> float:
    """0~1. 1에 가까울수록 같은 종목·같은 날·같은 지표의 유사 글."""
    title_ratio = SequenceMatcher(None, _norm_title(a.title), _norm_title(b.title)).ratio()
    metric_ratio = _jaccard(_metric_signature(a), _metric_signature(b))

    same_entity = 0.0
    if a.event.entity.name and a.event.entity.name == b.event.entity.name:
        same_entity = 1.0
    elif a.event.entity.ticker and a.event.entity.ticker == b.event.entity.ticker:
        same_entity = 1.0

    same_type = 1.0 if a.event.event_type and a.event.event_type == b.event.event_type else 0.0
    return round(
        title_ratio * 0.50
        + metric_ratio * 0.25
        + same_entity * 0.15
        + same_type * 0.10,
        4,
    )
