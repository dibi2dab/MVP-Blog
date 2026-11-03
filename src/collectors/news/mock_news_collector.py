from __future__ import annotations

import random
from datetime import datetime, timedelta

from src.collectors.base import BaseCollector, RawRecord
from src.config.settings import Settings
from src.models.news import NewsItem
from src.utils.logging import get_logger

logger = get_logger(__name__)


class MockNewsCollector(BaseCollector):
    """Mock 뉴스 수집기. API 키 없이 뉴스 파이프라인 테스트."""

    source_id = "mock.news"
    source_name = "Mock News"
    source_type = "news"

    def __init__(self, settings: Settings, seed: int = 7) -> None:
        super().__init__()
        self.settings = settings
        self.rng = random.Random(seed)

    def _template(self, ticker: str, name: str) -> list[NewsItem]:
        now = datetime.now()
        titles = [
            (f"{name}, 기관 매수세 확대…주가 상승 주도", 2),
            (f"{name} 신제품 출시…시장 기대감 상승", 4),
            (f"{name}, 분기 실적 발표 앞두고 관심 집중", 5),
            (f"{name} 최대주주 지분 변동 공시", 6),
            (f"전기차·반도체 관련주 강세…{name}도 상승", 8),
            (f"{name} 목표주가 상향 리포트 잇따라", 10),
        ]
        items = []
        chosen = self.rng.sample(titles, k=2)
        for title, days_ago in chosen:
            dt = (now - timedelta(days=days_ago)).strftime("%a, %d %b %Y %H:%M:%S +0900")
            items.append(
                NewsItem(
                    title=title,
                    published_at=dt,
                    source=self.rng.choice(["연합뉴스", "한국경제", "매일경제", "머니투데이"]),
                    url="https://example.com/mock-news",
                    summary="Mock 뉴스 요약입니다.",
                    entities=[name, ticker],
                    keywords=["mock"],
                    source_id=self.source_id,
                )
            )
        return items

    def collect(self) -> list[RawRecord]:
        records: list[RawRecord] = []
        for item in self.settings.stocks_universe[:10]:
            for news in self._template(item.code, item.name):
                records.append(
                    self.make_record(
                        data_type="news_item",
                        data=news.model_dump(),
                        original_url=news.url,
                        metadata={"ticker": item.code, "name": item.name},
                    )
                )
        self.logger.info("mock collected %d news", len(records))
        return records

    def search(self, query: str, max_items: int | None = 0) -> list[NewsItem]:
        limit = max_items or 10
        out: list[NewsItem] = []
        for item in self.settings.stocks_universe[:limit]:
            for news in self._template(item.code, item.name):
                out.append(news)
        return out[:limit]