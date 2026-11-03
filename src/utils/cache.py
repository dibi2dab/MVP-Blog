from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.utils.logging import get_logger

logger = get_logger(__name__)


class CacheEntry:
    def __init__(self, key: str, value: dict, expiration: datetime) -> None:
        self.key = key
        self.value = value
        self.expiration = expiration


CACHE_INDEX: dict[str, CacheEntry] = {}


class DiskCache:
    """간단한 디스크 캐시. 동일한 외부 호출 반복 방지용."""

    def __init__(self, cache_dir: str | Path, ttl_seconds: int = 3600) -> None:
        self.root = Path(cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds

    def _path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                entry = json.load(f)
            exp = datetime.fromisoformat(entry["expiration"])
            if datetime.now(exp.tzinfo) > exp:
                path.unlink(missing_ok=True)
                return None
            return entry["value"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def set(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        entry = {
            "source": "disk_cache",
            "key": key,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "expiration": exp.isoformat(),
            "response_hash": hashlib.sha1(json.dumps(value, ensure_ascii=False, default=str).encode()).hexdigest(),
            "value": value,
        }
        with open(self._path(key), "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)

    def get_or_set(self, key: str, producer, ttl_seconds: int | None = None):
        cached = self.get(key)
        if cached is not None:
            return cached
        value = producer()
        self.set(key, {"data": value}, ttl_seconds=ttl_seconds)
        return value

    def existed(self, key: str) -> bool:
        return self._path(key).exists()

    def clear(self) -> None:
        for p in self.root.glob("*.json"):
            p.unlink(missing_ok=True)


_MEMORY_CACHE: dict[str, dict[str, Any]] = {}
_MEMORY_EXP: dict[str, datetime] = {}


def file_hash(path: str | Path) -> str:
    """파일 내용 해시. 동일 파일 중복 처리 및 변경 감지."""
    path = Path(path)
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()