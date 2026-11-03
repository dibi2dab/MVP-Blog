from __future__ import annotations

import random
from datetime import datetime, timedelta

from src.collectors.base import BaseCollector, RawRecord
from src.config.settings import Settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MockDisclosureCollector(BaseCollector):
    """Mock 공시 수집기. DART API 키 없이 공시 파이프라인 테스트."""

    source_id = "mock.disclosure"
    source_name = "Mock DART"
    source_type = "disclosure"

    def __init__(self, settings: Settings, seed: int = 11) -> None:
        super().__init__()
        self.settings = settings
        self.rng = random.Random(seed)

    def collect(self) -> list[RawRecord]:
        records: list[RawRecord] = []
        templates = [
            ("유상증자 결정", "유상증자"),
            ("영업(잠정)실적 발표", "실적"),
            ("타법인 주식 및 출자증권 취득 결정", "취득"),
            ("제3자배정 유상증자", "유상증자"),
            ("전환사채 발행 결정", "전환사채"),
            ("자사주 취득 결정", "자사주"),
        ]
        for item in self.settings.stocks_universe[:5]:
            title, category = self.rng.choice(templates)
            date = (datetime.now() - timedelta(days=self.rng.randint(0, 3))).strftime("%Y-%m-%d")
            record = self.make_record(
                data_type="disclosure",
                data={
                    "title": f"{item.name} {title}",
                    "published_at": date,
                    "url": "https://dart.fss.or.kr/mock",
                    "rcept_no": f"MOCK-{item.code}-{self.rng.randint(1000, 9999)}",
                    "corp_code": f"mock_{item.code}",
                    "corp_name": item.name,
                    "report_name": f"{item.name} {title}",
                    "category": category,
                },
                original_url="https://dart.fss.or.kr/mock",
                metadata={"corp_code": f"mock_{item.code}", "category": category},
            )
            records.append(record)
        self.logger.info("mock collected %d disclosures", len(records))
        return records