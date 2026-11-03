from __future__ import annotations

import re

_HANGUL = re.compile(r"[가-힣]")
_PARTICLES = {
    "은": "는",
    "이": "가",
    "을": "를",
    "과": "와",
}


def has_final_consonant(word: str) -> bool:
    """한글 단어의 마지막 글자에 받침이 있는지 판단."""
    m = _HANGUL.search(word)
    if not m:
        return False  # 한글이 없으면 주격조사 추정 불가 → 기본 조사 사용
    char = ord(next((c for c in reversed(word) if _HANGUL.match(c)), ""))
    if not char:
        return False
    return (char - 0xAC00) % 28 != 0


def jo(word: str, eul: str = "을") -> str:
    """조사 자동 선택. eul: '을'(objective) , 은(eun), 이(i), 과(gwa)."""
    receiving = _PARTICLES.get(eul)
    if receiving is None:
        receiving = eul
    base = _PARTICLES.get(eul, eul)
    if has_final_consonant(word):
        return base
    return receiving


def subject_after(word: str) -> str:
    """주격 조사 은/는 or 이/가."""
    return "이" if has_final_consonant(word) else "가"


def topic_after(word: str) -> str:
    """주제 조사 은/는."""
    return "은" if has_final_consonant(word) else "는"


def object_after(word: str) -> str:
    """목적격 조사 을/를."""
    return "을" if has_final_consonant(word) else "를"


def format_korean_date(date_str: str | None, error: str = "") -> str:
    """'YYYY-MM-DD' -> '[YYYY년 M월 D일]'. 없거나 파싱 불가 시 fallback."""
    if not date_str:
        return error
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(date_str))
    if not m:
        return error
    y, mo, d = m.groups()
    return f"{int(y)}년 {int(mo)}월 {int(d)}일"