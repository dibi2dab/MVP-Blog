from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.utils.logging import get_logger


class RawRecord(BaseModel):
    """Collector 가 생성하는 표준 원본 레코드."""

    source_id: str
    source_name: str
    source_type: str
    collected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    original_url: str = ""
    data_type: str
    data: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class BaseCollector(ABC):
    """모든 Collector 의 공통 인터페이스. 추가 소스는 이 클래스를 상속."""

    source_id: str = "base"
    source_name: str = "base"
    source_type: str = "other"

    def __init__(self) -> None:
        self.logger = get_logger(f"collector.{self.source_id}")

    @abstractmethod
    def collect(self) -> list[RawRecord]:
        """데이터를 수집해 RawRecord 목록을 반환."""

    def normalize(self, records: list[RawRecord]) -> list[BaseModel]:
        """원본 레코드를 정규화된 모델로 변환. 기본은 그대로 재노출."""
        return list(records)  # type: ignore[return-value]

    def validate(self, records: list[RawRecord]) -> list[RawRecord]:
        """필수 필드 존재 검사. 비정상 레코드는 제거."""
        out: list[RawRecord] = []
        for r in records:
            if not r.source_id or not r.data_type:
                self.logger.warning("invalid raw record dropped: %s", r.source_id)
                continue
            out.append(r)
        return out

    def collect_pipeline(self) -> tuple[list[RawRecord], list[BaseModel]]:
        raw = self.collect()
        raw = self.validate(raw)
        normalized = self.normalize(raw)
        return raw, normalized

    def make_record(
        self,
        data_type: str,
        data: dict[str, Any],
        original_url: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> RawRecord:
        return RawRecord(
            source_id=self.source_id,
            source_name=self.source_name,
            source_type=self.source_type,
            data_type=data_type,
            original_url=original_url,
            data=data,
            metadata=metadata or {},
        )