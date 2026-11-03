from __future__ import annotations

import hashlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from src.config.settings import Settings
from src.models.chart import ChartSpec, GeneratedChart
from src.models.market_data import MarketSnapshot
from src.models.research_packet import ResearchPacket
from src.utils.logging import get_logger

logger = get_logger(__name__)

try:
    plt.rcParams["font.family"] = "Malgun Gothic"  # Windows 한글 폰트
except Exception:
    pass


class AnalysisChartGenerator:
    """실제 수집된 데이터만으로 분석 차트 생성. AI 가 만든 수치는 절대 사용하지 않는다."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.out_dir = Path(settings.charts.output_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, spec: ChartSpec, packet: ResearchPacket) -> GeneratedChart | None:
        fn = {
            "price_volume": self._price_volume,
            "volume_ratio": self._volume_ratio,
            "financial": self._financial,
        }.get(spec.chart_type)
        if not fn:
            return None
        try:
            chart = fn(spec, packet)
            if chart:
                chart.rel_url = f"{self.settings.publishing.images_base_url}/{Path(chart.path).name}"
            return chart
        except Exception as e:
            logger.error("chart failed %s: %s", spec.chart_type, e)
            return None

    def _session_id(self, spec: ChartSpec) -> str:
        raw = f"{spec.event_type}|{spec.ticker}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:10]

    def _save(self, fig, spec: ChartSpec, kind: str) -> GeneratedChart:
        filename = f"{kind}_{self._session_id(spec)}.png"
        path = self.out_dir / filename
        fig.savefig(path, dpi=self.settings.charts.dpi, bbox_inches="tight")
        plt.close(fig)
        return GeneratedChart(
            chart_key=kind,
            chart_type=spec.chart_type,
            title=spec.title,
            path=str(path),
            rel_url=f"charts/{filename}",
        )

    def _price_volume(self, spec: ChartSpec, packet: ResearchPacket) -> GeneratedChart | None:
        snap = packet.market_data
        if not snap or not snap.price_series.bars:
            return None
        window = spec.params.get("window", 30)
        bars = snap.price_series.bars[-window:]
        dates = [b.date for b in bars]
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(self.settings.charts.width, self.settings.charts.height), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        closes = [b.close for b in bars]
        ax1.plot(range(len(dates)), closes, color="#1f77b4", linewidth=1.6)
        ax1.set_title(f"{snap.name} 주가 추이 (최근 {len(bars)}영업일)")
        ax1.set_ylabel("종가")
        ax1.grid(True, alpha=0.3)
        ax2.bar(range(len(dates)), [b.volume / 1e4 for b in bars], color="#ff7f0e", alpha=0.8)
        ax2.set_ylabel("거래량 (만주)")
        ax2.grid(True, alpha=0.3)
        step = max(1, len(dates) // 8)
        ax2.set_xticks(range(0, len(dates), step))
        ax2.set_xticklabels([dates[i][5:] for i in range(0, len(dates), step)], rotation=45, fontsize=8)
        fig.tight_layout()
        return self._save(fig, spec, "price_volume")

    def _volume_ratio(self, spec: ChartSpec, packet: ResearchPacket) -> GeneratedChart | None:
        snap = packet.market_data
        if not snap or not snap.price_series.bars:
            return None
        series = snap.price_series
        n = len(series.bars)
        ratio_samples: list[tuple[str, float]] = []
        for i in range(max(0, n - 30), n):
            if i < 5:
                continue
            avg = series.avg_volume(i + 1)  # 직전까지 평균
            if avg and avg > 0:
                ratio_samples.append((series.bars[i].date[5:], series.bars[i].volume / avg))
        if not ratio_samples:
            return None
        dates = [d for d, _ in ratio_samples]
        ratios = [r for _, r in ratio_samples]
        fig, ax = plt.subplots(figsize=(self.settings.charts.width, self.settings.charts.height / 2))
        colors = ["#d62728" if r >= 2 else "#1f77b4" for r in ratios]
        ax.bar(range(len(dates)), ratios, color=colors)
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=1)
        ax.set_title(f"{snap.name} 평균 대비 거래량 비율 (오늘 포함 직전 30일)")
        ax.set_ylabel("평균 대비 배수")
        step = max(1, len(dates) // 8)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=45, fontsize=8)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return self._save(fig, spec, "volume_ratio")

    def _financial(self, spec: ChartSpec, packet: ResearchPacket) -> GeneratedChart | None:
        fd = packet.financial_data
        revenues = fd.get("revenues")
        profits = fd.get("operating_profits")
        labels = fd.get("labels")
        if not revenues or not labels:
            return None
        fig, ax = plt.subplots(figsize=(self.settings.charts.width, self.settings.charts.height / 2))
        x = range(len(labels))
        ax.bar([i - 0.2 for i in x], [_n(v) for v in revenues], width=0.4, label="매출", color="#1f77b4")
        ax.bar([i + 0.2 for i in x], [_n(v) for v in (profits or [])], width=0.4, label="영업이익", color="#2ca02c")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=30)
        ax.set_title("매출·영업이익 추이")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return self._save(fig, spec, "financial")


def _n(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0