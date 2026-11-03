from __future__ import annotations

from src.models.chart import ChartSpec
from src.models.event import Event

_EVENT_CHARTS: dict[str, list[dict]] = {
    "stock_surge": [
        {"chart_type": "price_volume", "params": {"window": 30}},
        {"chart_type": "volume_ratio"},
    ],
    "stock_crash": [
        {"chart_type": "price_volume", "params": {"window": 30}},
        {"chart_type": "volume_ratio"},
    ],
    "stock_breakout": [
        {"chart_type": "price_volume", "params": {"window": 60}},
        {"chart_type": "volume_ratio"},
    ],
    "earnings": [
        {"chart_type": "price_volume", "params": {"window": 30}},
        {"chart_type": "financial", "params": {}},
    ],
    "disclosure": [
        {"chart_type": "price_volume", "params": {"window": 30}},
    ],
    "news_event": [
        {"chart_type": "price_volume", "params": {"window": 30}},
    ],
}

_DEFAULT = [
    {"chart_type": "price_volume", "params": {"window": 30}},
]


class ChartSelector:
    """이벤트 유형에 따라 필요한 차트를 선택한다 (기사 마다 동일하지 않게)."""

    def __init__(self) -> None:
        self._map = _EVENT_CHARTS

    def select(self, event: Event) -> list[ChartSpec]:
        specs = self._map.get(event.event_type, []) or _DEFAULT
        return [
            ChartSpec(
                chart_type=s["chart_type"],
                title=self._title(s["chart_type"]),
                event_type=event.event_type,
                ticker=event.ticker or "",
                name=event.entity.name or "",
                params=s.get("params", {}),
            )
            for s in specs
        ]

    def _title(self, chart_type: str) -> str:
        return {
            "price_volume": "주가 및 거래량 추이",
            "volume_ratio": "평균 대비 거래량 비율",
            "financial": "매출·영업이익 추이",
        }.get(chart_type, "분석 차트")