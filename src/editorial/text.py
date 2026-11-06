from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_LATIN = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[가-힣A-Za-z0-9]+")
_SENTENCE = re.compile(r"[^.!?。！？\n]+[.!?。！？]?")


def korean_ratio(text: str) -> float:
    hangul = len(_HANGUL.findall(text or ""))
    latin = len(_LATIN.findall(text or ""))
    return hangul / max(1, hangul + latin)


def hangul_count(text: str) -> int:
    return len(_HANGUL.findall(text or ""))


def count_headings(markdown: str) -> int:
    return len(re.findall(r"(?m)^#{2,3}\s+\S", markdown or ""))


def has_table(markdown: str) -> bool:
    lines = (markdown or "").splitlines()
    for index, line in enumerate(lines):
        if "|" in line and index + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[index + 1]):
            return True
    return False


def paragraphs(markdown: str) -> list[str]:
    chunks = re.split(r"\n\s*\n", markdown or "")
    return [chunk.strip() for chunk in chunks if chunk.strip() and not chunk.strip().startswith("#")]


def sentences(markdown: str) -> list[str]:
    text = re.sub(r"(?m)^#+\s+.*$", "", markdown or "")
    text = re.sub(r"\|.*\|", "", text)
    found = [match.group(0).strip() for match in _SENTENCE.finditer(text)]
    return [item for item in found if len(item) >= 5]


def average_sentence_length(markdown: str) -> float:
    items = sentences(markdown)
    if not items:
        return 0.0
    return sum(len(item) for item in items) / len(items)


def body_fingerprint(text: str, *, shingle_size: int = 5, max_hashes: int = 300) -> list[str]:
    words = _WORD.findall((text or "").lower())
    if len(words) < shingle_size:
        return []
    hashes: set[str] = set()
    for index in range(len(words) - shingle_size + 1):
        shingle = " ".join(words[index : index + shingle_size])
        hashes.add(hashlib.sha1(shingle.encode("utf-8")).hexdigest()[:12])
        if len(hashes) >= max_hashes:
            break
    return sorted(hashes)


def fingerprint_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def title_similarity(left: str, right: str) -> float:
    def norm(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").lower()).strip()

    return SequenceMatcher(None, norm(left), norm(right)).ratio()


def safe_slug(value: str, *, fallback: str = "post") -> str:
    slug = (value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        return fallback
    return slug[:80]
