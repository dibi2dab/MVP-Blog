from __future__ import annotations

from pydantic import BaseModel, Field


class ChartSpec(BaseModel):
    """차트 생성 요청 사양."""

    chart_type: str
    title: str
    event_type: str
    ticker: str = ""
    name: str = ""
    params: dict = Field(default_factory=dict)


class GeneratedChart(BaseModel):
    chart_key: str
    chart_type: str
    title: str
    path: str  # 저장된 파일 경로 (static/charts/...)
    rel_url: str  # 블로그에서 참조할 상대 URL
    caption: str = ""


class ExternalChartEmbed(BaseModel):
    provider: str
    symbol: str
    widget: str  # 생성된 embed snippet (공식 위젯만 허용)
    title: str = ""