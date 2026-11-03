from src.collectors.base import BaseCollector, RawRecord
from src.collectors.disclosures import DartDisclosureCollector, MockDisclosureCollector
from src.collectors.news import GoogleNewsRssCollector, MockNewsCollector
from src.collectors.stocks import MockStockCollector, NaverStockCollector
from src.config.settings import Settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class Collectors:
    """설정 기반 Collector 팩토리."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def stock(self) -> NaverStockCollector | MockStockCollector:
        provider = (self.settings.sources_raw.get("stocks", {}).get("price", {}) or {}).get("provider", "naver")
        mock = self.settings.app.mock_mode == "true"
        if provider == "mock" or mock:
            return MockStockCollector(self.settings)
        return NaverStockCollector(self.settings)

    def news(self) -> GoogleNewsRssCollector | MockNewsCollector:
        provider = (self.settings.sources_raw.get("news", {}) or {}).get("provider", "google_rss")
        mock = self.settings.app.mock_mode == "true"
        if provider == "mock" or mock:
            return MockNewsCollector(self.settings)
        return GoogleNewsRssCollector(self.settings)

    def disclosures(self) -> list[BaseCollector]:
        """DART 키가 있으면 실제, 없으면 건너뛰거나 mock 으로 대체."""
        default_key = _env("DART_API_KEY")
        mock = self.settings.app.mock_mode == "true"
        if mock:
            return [MockDisclosureCollector(self.settings)]
        real = DartDisclosureCollector(self.settings, api_key=default_key)
        if not real.connected:
            logger.warning("DART_API_KEY 없음 -> 공시 수집을 건너뜁니다 (real=off, mock=off)")
            return []
        return [real]

    def all(self) -> list[BaseCollector]:
        collectors: list[BaseCollector] = [self.stock(), self.news()]
        collectors.extend(self.disclosures())
        return collectors


def _env(name: str) -> str:
    import os

    return os.environ.get(name, "")