from __future__ import annotations

import ast
import datetime as dt
from typing import Any

import requests

from src.collectors.base import BaseCollector, RawRecord
from src.config.settings import Settings
from src.models.market_data import DailyPriceBar, MarketSnapshot, PriceSeries, SnapshotCollection
from src.utils.cache import DiskCache
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)


class NaverStockCollector(BaseCollector):
    """네이버 금융 공개 API 기반 주가 수집기 (API 키 불필요, 무단 스크래핑 아님).

    1순위: https://api.finance.naver.com/siseJson.naver (공개 JSON)
    2순위: https://api.stock.naver.com/chart/domestic/item/{code}/day
    3순위: https://fchart.stock.naver.com/sise.nhn
    """

    source_id = "naver.stock"
    source_name = "Naver Finance"
    source_type = "stock_price"

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; finance-research-blog/1.0)"})
        price_cfg = settings.sources_raw.get("stocks", {}).get("price", {})
        self.period_count = int(price_cfg.get("period_count", 90))
        self.timeout = float(price_cfg.get("timeout_seconds", 15))
        self.cache = DiskCache(str(settings.storage.path("cache")), ttl_seconds=6 * 3600)

    @retry(max_attempts=3, base_delay=2, max_delay=30, logger=logger)
    def _fetch_sise_json(self, code: str) -> list[list[Any]]:
        cache_key = f"naver_sisejson_{code}_{self.period_count}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached["data"]
        end = dt.date.today()
        start = end - dt.timedelta(days=int(self.period_count * 1.6))
        params = {
            "symbol": code,
            "requestType": 1,
            "startTime": start.strftime("%Y%m%d"),
            "endTime": end.strftime("%Y%m%d"),
            "timeframe": "day",
        }
        resp = self.session.get(
            "https://api.finance.naver.com/siseJson.naver", params=params, timeout=self.timeout
        )
        resp.raise_for_status()
        rows = self._parse_sise_json(resp.text)
        self.cache.set(cache_key, {"data": rows})
        return rows

    def _parse_sise_json(self, text: str) -> list[list[Any]]:
        """[['날짜','시간','시가','고가','저가','종가','거래량','외국인비율'], ...] 형식 파싱."""
        text = text.strip()
        if text.startswith("["):
            data = ast.literal_eval(text)
        else:
            return []
        if not isinstance(data, list):
            return []
        rows = [row for row in data if isinstance(row, list) and row and not str(row[0]).startswith(("date", "날짜"))]
        return rows

    def _build_series(self, row_sets: list[list[Any]]) -> PriceSeries | None:
        if not row_sets:
            return None
        bars: list[DailyPriceBar] = []
        prev_close: float | None = None
        for row in row_sets:
            # 실제 데이터 행: [date(YYYYMMDD), open, high, low, close, volume, foreign(생략 가능)]
            # 헤더(시간 포함)와 달리 데이터 행은 '시간' 컬럼이 없어 인덱스가 1씩 앞당겨진다.
            try:
                date_s = str(row[0]).replace(".", "").replace("-", "")
                if len(date_s) < 8:
                    continue
                close = float(row[4])
                open_ = float(row[1])
                high = float(row[2])
                low = float(row[3])
                volume = int(float(row[5]))
            except (TypeError, ValueError, IndexError):
                continue
            change = ((close - prev_close) / prev_close * 100) if prev_close else 0.0
            bars.append(
                DailyPriceBar(
                    date=f"{date_s[:4]}-{date_s[4:6]}-{date_s[6:8]}",
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    amount=None,
                    change_pct=round(change, 2),
                )
            )
            prev_close = close
        if not bars:
            return None
        # fchart/주말 데이터가 섞일 수 있으므로 날짜로 정렬 후 중복 제거
        dedup: dict[str, DailyPriceBar] = {}
        for b in bars:
            dedup[b.date] = b
        ordered = sorted(dedup.values(), key=lambda b: b.date)
        return ordered

    def fetch_series(self, code: str, name: str) -> PriceSeries | None:
        rows = self._fetch_sise_json(code)
        ordered = self._build_series(rows)
        if not ordered:
            return None
        return PriceSeries(
            ticker=code,
            name=name,
            currency="KRW",
            bars=ordered[-self.period_count:],
            source_id=self.source_id,
        )

    def collect(self) -> list[RawRecord]:
        records: list[RawRecord] = []
        for item in self.settings.stocks_universe:
            try:
                series = self.fetch_series(item.code, item.name)
                if not series:
                    logger.warning("no data for %s (%s)", item.code, item.name)
                    continue
                records.append(
                    self.make_record(
                        data_type="price_series",
                        data=series.model_dump(),
                        original_url=f"https://m.stock.naver.com/domestic/stock/{item.code}/total",
                        metadata={"ticker": item.code, "name": item.name},
                    )
                )
            except Exception as e:
                logger.error("failed to collect %s (%s): %s", item.code, item.name, e)
        self.logger.info("collected %d stock series", len(records))
        return records

    def build_snapshot(self) -> SnapshotCollection:
        snapshots: list[MarketSnapshot] = []
        for item in self.settings.stocks_universe:
            try:
                series = self.fetch_series(item.code, item.name)
                if not series:
                    continue
                snapshots.append(
                    MarketSnapshot(
                        ticker=item.code,
                        name=item.name,
                        price_series=series,
                        source_id=self.source_id,
                    )
                )
            except Exception as e:
                logger.error("invalid snapshot for %s: %s", item.code, e)
        if not snapshots:
            logger.warning("네이버 주가 수집 실패 (0 스냅샷)")
        return SnapshotCollection(snapshots=snapshots)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None