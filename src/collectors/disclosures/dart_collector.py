from __future__ import annotations

import io
import json
import zipfile
from urllib.parse import urlencode

import requests

from src.collectors.base import BaseCollector, RawRecord
from src.config.settings import Settings
from src.utils.cache import DiskCache
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)


class DartDisclosureCollector(BaseCollector):
    """DART(OpenDart, open) 공시 수집기. DART_API_KEY 필요.

    https://opendart.fss.or.kr/api/list.json : 공시 목록 조회
    https://opendart.fss.or.kr/api/corpCode.xml : 고유번호 최신 목록
    """

    source_id = "dart.disclosure"
    source_name = "DART (OpenDart)"
    source_type = "disclosure"

    def __init__(self, settings: Settings, api_key: str | None = None, session: requests.Session | None = None) -> None:
        super().__init__()
        self.settings = settings
        dart_cfg = settings.sources_raw.get("disclosures", {}).get("dart", {})
        self.base_url = dart_cfg.get("base_url", "https://opendart.fss.or.kr/api")
        self.api_key = api_key or _env("DART_API_KEY") or ""
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; finance-research-blog/1.0)"})
        self.cache = DiskCache(str(settings.storage.path("cache")), ttl_seconds=6 * 3600)

    @property
    def connected(self) -> bool:
        return bool(self.api_key)

    @retry(max_attempts=3, base_delay=2, max_delay=20, logger=logger)
    def _fetch_disclosures(self, start: str, end: str) -> list[dict]:
        cache_key = f"dart_list_{start}_{end}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached["data"]
        params = {
            "crtfc_key": self.api_key,
            "bgn_de": start.replace("-", ""),
            "end_de": end.replace("-", ""),
            "page_no": 1,
            "page_count": 30,
        }
        resp = self.session.get(f"{self.base_url}/list.json", params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "000" and "정상" not in payload.get("message", ""):
            raise RuntimeError(f"DART API error: {payload.get('message')}")
        rows = payload.get("list", []) or []
        self.cache.set(cache_key, {"data": rows})
        return rows

    def collect(self) -> list[RawRecord]:
        if not self.connected:
            logger.warning("DART_API_KEY 부재. mock 설정이 아니면 공시 수집을 건너뜁니다.")
            return []
        from datetime import date, timedelta

        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=3)).strftime("%Y%m%d")
        records: list[RawRecord] = []
        try:
            rows = self._fetch_disclosures(start, end)
            for row in rows:
                records.append(
                    self.make_record(
                        data_type="disclosure",
                        data={
                            "title": row.get("report_nm", ""),
                            "published_at": f"{row.get('rcept_dt', '')[:4]}-{row.get('rcept_dt', '')[4:6]}-{row.get('rcept_dt', '')[6:8]}",
                            "url": f"https://dart.fss.or.kr/dsaj001/main.do?rcpNo={row.get('rcept_no', '')}" if row.get("rcept_no") else "",
                            "rcept_no": row.get("rcept_no", ""),
                            "corp_code": row.get("corp_code", ""),
                            "corp_name": row.get("corp_name", ""),
                            "report_name": row.get("report_nm", ""),
                        },
                        original_url=f"https://dart.fss.or.kr/dsaj001/main.do?rcpNo={row.get('rcept_no', '')}",
                        metadata={"corp_code": row.get("corp_code", "")},
                    )
                )
        except Exception as e:
            logger.error("dart collect failed: %s", e)
        self.logger.info("collected %d disclosure records", len(records))
        return records

    def corp_code_map(self) -> dict[str, str]:
        """corp_name -> corp_code 매핑 (캐시 사용)."""
        cache_key = "dart_corp_code_map"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached["data"]
        resp = self.session.get(f"{self.base_url}/corpCode.xml", params={"crtfc_key": self.api_key}, timeout=30)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            blob = zf.read("CORPCODE.xml").decode("utf-8")
        mapping: dict[str, str] = {}
        cur_code = ""
        for line in blob.splitlines():
            line = line.strip()
            if line.startswith("<corp_code>"):
                cur_code = line.replace("<corp_code>", "").replace("</corp_code>", "").strip()
            elif line.startswith("<corp_name>") and cur_code:
                name = line.replace("<corp_name>", "").replace("</corp_name>", "").strip()
                mapping[name] = cur_code
                cur_code = ""
        self.cache.set(cache_key, {"data": mapping}, ttl_seconds=24 * 3600)
        return mapping


def _env(name: str) -> str:
    import os

    return os.environ.get(name, "")