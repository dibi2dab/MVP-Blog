from __future__ import annotations

"""가격·거래량 데이터에서 기사별로 다른 계산 지표와 패턴을 뽑아낸다.

이 모듈의 목적은 뉴스 제목을 그대로 옮기는 것이 아니라,
같은 종목이라도 날마다 달라지는 거래량 z-score, 이동평균 이격, 갭,
장중 변동성, 5일/20일 수익률 같은 자체 계산 결과를 기사에 제공하는 것이다.
"""

from dataclasses import asdict, dataclass, field
from statistics import mean, pstdev
from typing import Any

from src.models.market_data import DailyPriceBar
from src.models.research_packet import ResearchPacket


def _safe_mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else None


def _safe_pstdev(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return pstdev(vals) if len(vals) >= 2 else None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous * 100.0


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    return f"{value:+.{digits}f}%" if value is not None else "확인 불가"


def _fmt_ratio(value: float | None, digits: int = 2) -> str:
    return f"{value:.{digits}f}배" if value is not None else "확인 불가"


@dataclass
class QuantMetrics:
    """한 기사에만 쓰이는 계산 결과. 모든 값은 원본 일봉에서 직접 계산한다."""

    n_bars: int = 0
    latest_date: str = ""
    close: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int = 0
    amount: float | None = None
    gap_pct: float | None = None
    intraday_range_pct: float | None = None
    close_position: float | None = None
    avg_volume_20: float | None = None
    volume_ratio: float | None = None
    volume_zscore: float | None = None
    avg_amount_20: float | None = None
    amount_ratio: float | None = None
    return_5d: float | None = None
    return_20d: float | None = None
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    distance_ma20_pct: float | None = None
    distance_ma60_pct: float | None = None
    volatility_20d: float | None = None
    return_zscore: float | None = None
    high_60d: float | None = None
    low_60d: float | None = None
    drawdown_from_high_60d_pct: float | None = None
    rally_from_low_60d_pct: float | None = None
    up_days_5: int = 0
    down_days_5: int = 0
    avg_range_20_pct: float | None = None
    range_expansion_ratio: float | None = None
    data_quality: str = "없음"

    def available_metrics(self) -> dict[str, float]:
        """기사에 실제로 등장할 수 있는 계산 지표 목록."""
        keys = (
            "change_pct",
            "gap_pct",
            "intraday_range_pct",
            "close_position",
            "volume_ratio",
            "volume_zscore",
            "amount_ratio",
            "return_5d",
            "return_20d",
            "distance_ma20_pct",
            "distance_ma60_pct",
            "volatility_20d",
            "return_zscore",
            "drawdown_from_high_60d_pct",
            "rally_from_low_60d_pct",
            "range_expansion_ratio",
        )
        out: dict[str, float] = {}
        for key in keys:
            value = getattr(self, key, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = float(value)
        return out

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["available_metrics"] = self.available_metrics()
        return data


def _bar_return(bar: DailyPriceBar, prev: DailyPriceBar | None) -> float | None:
    if bar.change_pct is not None:
        return float(bar.change_pct)
    if prev is None:
        return None
    return _pct_change(bar.close, prev.close)


def compute_quant_metrics(packet: ResearchPacket) -> QuantMetrics:
    """ResearchPacket 의 일봉으로 기사용 계산 지표를 만든다."""
    snapshot = packet.market_data
    if snapshot is None or not snapshot.price_series.bars:
        return QuantMetrics(data_quality="없음")

    bars = sorted(snapshot.price_series.bars, key=lambda b: b.date)
    latest = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else None
    m = QuantMetrics(
        n_bars=len(bars),
        latest_date=latest.date,
        close=latest.close,
        prev_close=prev.close if prev else None,
        change_pct=_bar_return(latest, prev),
        open=latest.open,
        high=latest.high,
        low=latest.low,
        volume=int(latest.volume or 0),
        amount=latest.amount,
    )

    # 갭과 장중 변동
    if prev and latest.open is not None and prev.close:
        m.gap_pct = _pct_change(latest.open, prev.close)
    if prev and prev.close and latest.high is not None and latest.low is not None:
        m.intraday_range_pct = (latest.high - latest.low) / prev.close * 100.0
        if latest.high > latest.low:
            m.close_position = (latest.close - latest.low) / (latest.high - latest.low)

    # 거래량/거래대금 평균과 z-score (오늘을 제외한 직전 20거래일)
    prior = bars[-21:-1] if len(bars) >= 21 else bars[:-1]
    prior_volumes = [float(b.volume) for b in prior if b.volume is not None]
    m.avg_volume_20 = _safe_mean(prior_volumes[-20:])
    if m.avg_volume_20 and m.avg_volume_20 > 0:
        m.volume_ratio = m.volume / m.avg_volume_20
    vol_sd = _safe_pstdev(prior_volumes[-20:])
    if vol_sd and vol_sd > 0 and m.avg_volume_20 is not None:
        m.volume_zscore = (m.volume - m.avg_volume_20) / vol_sd

    prior_amounts = [float(b.amount) for b in prior if b.amount is not None]
    m.avg_amount_20 = _safe_mean(prior_amounts[-20:])
    if m.avg_amount_20 and m.avg_amount_20 > 0 and latest.amount is not None:
        m.amount_ratio = float(latest.amount) / m.avg_amount_20

    # 수익률과 이동평균
    if len(bars) >= 6:
        m.return_5d = _pct_change(latest.close, bars[-6].close)
    if len(bars) >= 21:
        m.return_20d = _pct_change(latest.close, bars[-21].close)
    if len(bars) >= 5:
        m.ma5 = _safe_mean([b.close for b in bars[-5:]])
    if len(bars) >= 20:
        m.ma20 = _safe_mean([b.close for b in bars[-20:]])
    if len(bars) >= 60:
        m.ma60 = _safe_mean([b.close for b in bars[-60:]])
    if m.ma20:
        m.distance_ma20_pct = _pct_change(latest.close, m.ma20)
    if m.ma60:
        m.distance_ma60_pct = _pct_change(latest.close, m.ma60)

    # 변동성과 당일 수익률의 z-score
    returns: list[float] = []
    for idx, bar in enumerate(bars):
        r = _bar_return(bar, bars[idx - 1] if idx > 0 else None)
        if r is not None:
            returns.append(r)
    hist_returns = returns[-21:-1] if len(returns) >= 21 else returns[:-1]
    m.volatility_20d = _safe_pstdev(hist_returns[-20:])
    hist_mean = _safe_mean(hist_returns[-20:])
    hist_sd = m.volatility_20d
    if hist_mean is not None and hist_sd and hist_sd > 0 and m.change_pct is not None:
        m.return_zscore = (m.change_pct - hist_mean) / hist_sd

    # 60일 고점/저점과 현재 위치
    window = bars[-60:]
    highs = [float(b.high if b.high is not None else b.close) for b in window]
    lows = [float(b.low if b.low is not None else b.close) for b in window]
    if highs:
        m.high_60d = max(highs)
        m.drawdown_from_high_60d_pct = _pct_change(latest.close, m.high_60d)
    if lows:
        m.low_60d = min(lows)
        m.rally_from_low_60d_pct = _pct_change(latest.close, m.low_60d)

    # 최근 5일 방향
    recent = bars[-5:]
    for idx, bar in enumerate(recent):
        prev_bar = recent[idx - 1] if idx > 0 else (bars[-6] if len(bars) >= 6 else None)
        r = _bar_return(bar, prev_bar)
        if r is None:
            continue
        if r > 0:
            m.up_days_5 += 1
        elif r < 0:
            m.down_days_5 += 1

    # 장중 변동 폭 확대 배수
    ranges: list[float] = []
    for idx in range(max(1, len(bars) - 21), len(bars) - 1):
        bar = bars[idx]
        prev_bar = bars[idx - 1]
        if bar.high is not None and bar.low is not None and prev_bar.close:
            ranges.append((bar.high - bar.low) / prev_bar.close * 100.0)
    m.avg_range_20_pct = _safe_mean(ranges[-20:])
    if m.avg_range_20_pct and m.avg_range_20_pct > 0 and m.intraday_range_pct is not None:
        m.range_expansion_ratio = m.intraday_range_pct / m.avg_range_20_pct

    if len(bars) >= 60 and latest.open is not None and latest.high is not None and latest.low is not None:
        m.data_quality = "충분"
    elif len(bars) >= 20:
        m.data_quality = "보통"
    else:
        m.data_quality = "제한"
    return m


@dataclass
class MarketPattern:
    code: str
    label: str
    interpretation: str
    limitation: str
    confirmation: str
    priority: int = 0


def detect_patterns(
    metrics: QuantMetrics,
    has_cause_news: bool = False,
    has_cause_disclosure: bool = False,
) -> list[MarketPattern]:
    """계산 지표를 해석 가능한 패턴으로 바꾼다. 기사마다 선택되는 패턴이 달라진다."""
    patterns: list[MarketPattern] = []
    pct = metrics.change_pct
    vr = metrics.volume_ratio

    if vr is not None and vr >= 1.5:
        patterns.append(
            MarketPattern(
                code="volume_spike",
                label="거래량 확대",
                interpretation=(
                    f"20일 평균 거래량의 {_fmt_ratio(vr)}가 거래됐다. "
                    f"거래량 z-score는 {metrics.volume_zscore:+.2f}로, 평소 분포에서 벗어난 수준이다."
                    if metrics.volume_zscore is not None
                    else f"20일 평균 거래량의 {_fmt_ratio(vr)}가 거래됐다."
                ),
                limitation=(
                    "거래량은 방향을 알려주지 않는다. 매수와 매도 중 어느 쪽이 우세했는지는 "
                    "종가 위치와 수급 데이터로 보완해야 한다."
                ),
                confirmation="다음 거래일에도 거래량이 20일 평균을 웃도는지, 종가가 당일 고가·저가 중 어디에 형성됐는지.",
                priority=90,
            )
        )

    if pct is not None and vr is not None:
        if pct < 0 and vr >= 1.5:
            label = "하락 + 거래량 증가"
            interpretation = (
                "가격이 하락하는 가운데 거래량이 늘었다. 매도 물량이 소화됐거나, "
                "반대로 매수세가 약한 상태에서 매도가 우위를 보였을 가능성을 함께 열어둬야 한다."
            )
        elif pct > 0 and vr >= 1.5:
            label = "상승 + 거래량 증가"
            interpretation = (
                "가격 상승과 거래량 증가가 동시에 나타났다. 소수 주문이 아니라 "
                "여러 참여자가 가격 방향에 반응했을 가능성을 시사한다."
            )
        elif pct > 0 and vr < 0.8:
            label = "상승 + 거래량 감소"
            interpretation = (
                "가격은 올랐지만 거래량은 20일 평균을 밑돌았다. 상승의 폭에 비해 "
                "참여가 넓지 않았을 가능성이 있어 추세 신뢰도를 낮춰 잡을 필요가 있다."
            )
        elif pct < 0 and vr < 0.8:
            label = "하락 + 거래량 감소"
            interpretation = (
                "가격은 하락했지만 거래량은 줄었다. 적극적인 매도보다는 "
                "거래가 얇아진 가운데 가격이 밀렸을 가능성을 배제하기 어렵다."
            )
        else:
            label = ""
            interpretation = ""
        if label:
            patterns.append(
                MarketPattern(
                    code="volume_price_relation",
                    label=label,
                    interpretation=interpretation,
                    limitation="가격과 거래량의 동시 움직임은 인과관계가 아니라 상관관계다. 원인은 별도 자료로 확인해야 한다.",
                    confirmation="거래량과 가격 방향이 다음 거래일에도 같은 방향으로 이어지는지.",
                    priority=80,
                )
            )

    if metrics.gap_pct is not None and abs(metrics.gap_pct) >= 1.0:
        direction = "하락" if metrics.gap_pct < 0 else "상승"
        patterns.append(
            MarketPattern(
                code="gap_event",
                label=f"갭 {direction} 출발",
                interpretation=(
                    f"전일 종가 대비 {_fmt_pct(metrics.gap_pct)} 갭으로 출발했다. "
                    f"종가는 장중 고가 대비 {metrics.close_position * 100:.0f}% 위치에 형성됐다."
                    if metrics.close_position is not None
                    else f"전일 종가 대비 {_fmt_pct(metrics.gap_pct)} 갭으로 출발했다."
                ),
                limitation="갭은 개장 전 심리를 반영하지만, 장중에 메워질 수 있어 종가와 함께 봐야 한다.",
                confirmation="종가가 갭 구간을 메웠는지, 갭 방향으로 거래량이 실렸는지.",
                priority=70,
            )
        )

    if metrics.range_expansion_ratio is not None and metrics.range_expansion_ratio >= 1.5:
        patterns.append(
            MarketPattern(
                code="range_expansion",
                label="장중 변동성 확대",
                interpretation=(
                    f"당일 장중 변동 폭이 20일 평균의 {_fmt_ratio(metrics.range_expansion_ratio)}다. "
                    f"고가와 저가의 차이가 {_fmt_pct(metrics.intraday_range_pct)}에 달했다."
                ),
                limitation="변동성 확대는 방향성과 별개다. 위아래 어느 쪽으로든 크게 흔들렸다는 뜻이다.",
                confirmation="변동 폭이 다음 거래일에도 유지되는지, 종가가 변동 범위의 어느 쪽에 붙는지.",
                priority=60,
            )
        )

    if metrics.distance_ma20_pct is not None and metrics.distance_ma20_pct <= -3.0:
        patterns.append(
            MarketPattern(
                code="ma_breakdown",
                label="20일선 하회",
                interpretation=(
                    f"종가가 20일 이동평균보다 {_fmt_pct(metrics.distance_ma20_pct)} 낮다. "
                    "단기 추세가 약해졌다는 신호로 읽을 수 있다."
                ),
                limitation="이동평균은 후행 지표다. 이미 반영된 가격 흐름을 사후적으로 확인하는 성격이 강하다.",
                confirmation="종가가 20일선 위로 다시 올라오는지, 60일선도 이탈하는지.",
                priority=55,
            )
        )
    elif metrics.distance_ma20_pct is not None and metrics.distance_ma20_pct >= 3.0:
        patterns.append(
            MarketPattern(
                code="ma_breakout",
                label="20일선 상회",
                interpretation=(
                    f"종가가 20일 이동평균보다 {_fmt_pct(metrics.distance_ma20_pct)} 높다. "
                    "단기 추세가 평균 위로 올라섰다는 뜻으로 해석할 수 있다."
                ),
                limitation="이동평균 상회만으로 추세 전환을 단정할 수는 없다. 거래량과 후속 가격이 필요하다.",
                confirmation="20일선 위에서 종가가 유지되는지, 거래량이 함께 늘어나는지.",
                priority=55,
            )
        )

    if metrics.drawdown_from_high_60d_pct is not None and metrics.drawdown_from_high_60d_pct >= -2.0:
        patterns.append(
            MarketPattern(
                code="near_high",
                label="60일 고점 부근",
                interpretation=(
                    f"현재 종가는 60일 고점({metrics.high_60d:,.0f}) 대비 "
                    f"{_fmt_pct(metrics.drawdown_from_high_60d_pct)} 수준이다."
                ),
                limitation="고점 부근이라는 사실은 추가 상승 여력이나 저항을 보장하지 않는다.",
                confirmation="고점을 돌파하는지, 돌파 시 거래량이 동반되는지.",
                priority=45,
            )
        )
    if metrics.rally_from_low_60d_pct is not None and metrics.rally_from_low_60d_pct <= 2.0:
        patterns.append(
            MarketPattern(
                code="near_low",
                label="60일 저점 부근",
                interpretation=(
                    f"현재 종가는 60일 저점({metrics.low_60d:,.0f}) 대비 "
                    f"{_fmt_pct(metrics.rally_from_low_60d_pct)} 수준이다."
                ),
                limitation="저점 부근이라는 사실만으로 반등을 기대할 수는 없다. 매도 압력이 계속될 수 있다.",
                confirmation="저점을 지키는지, 거래량이 줄면서 하락이 멈추는지.",
                priority=45,
            )
        )

    if metrics.return_zscore is not None and abs(metrics.return_zscore) >= 2.0:
        patterns.append(
            MarketPattern(
                code="return_outlier",
                label="일간 수익률 이상치",
                interpretation=(
                    f"당일 수익률 {_fmt_pct(pct)}은 최근 20일 일간 수익률 분포에서 "
                    f"z-score {metrics.return_zscore:+.2f}에 해당한다. 통계적으로 드문 움직임이다."
                ),
                limitation="z-score가 크다는 것은 드물다는 뜻이지, 원인이 확인됐다는 뜻은 아니다.",
                confirmation="이례적 움직임이 하루로 끝나는지, 다음 날에도 이어지는지.",
                priority=65,
            )
        )

    if has_cause_disclosure:
        patterns.append(
            MarketPattern(
                code="disclosure_cause",
                label="공시와 시점 일치",
                interpretation="변동일과 가까운 시점에 해당 기업의 직접 공시가 확인된다. 공시 내용과 가격 반응의 방향을 함께 볼 필요가 있다.",
                limitation="공시가 있었다는 사실과 주가 변동의 인과관계는 별개다. 공시가 이미 예상됐을 수도 있다.",
                confirmation="공시의 세부 수치가 시장 예상과 얼마나 달랐는지, 후속 공시가 있는지.",
                priority=85,
            )
        )
    elif has_cause_news:
        patterns.append(
            MarketPattern(
                code="news_cause",
                label="뉴스와 시점 일치",
                interpretation="변동일과 가까운 시점에 해당 기업을 직접 언급한 뉴스가 확인된다. 다만 뉴스의 내용이 가격 방향을 설명하는지는 별도 검증이 필요하다.",
                limitation="뉴스 제목과 실제 내용이 다를 수 있고, 같은 사건을 다룬 복수 보도가 서로 다른 해석을 담을 수 있다.",
                confirmation="복수 매체가 같은 사실을 보도하는지, 회사 공식 발표가 뒤따르는지.",
                priority=85,
            )
        )
    else:
        patterns.append(
            MarketPattern(
                code="no_confirmed_cause",
                label="확인된 단일 원인 없음",
                interpretation="변동일과 가까운 시점에서 해당 기업의 직접 공시나 원인을 설명하는 뉴스를 확인하지 못했다. 가격·거래량만으로 원인을 단정해서는 안 된다.",
                limitation="수집되지 않은 자료가 있을 수 있다. 뉴스 검색 범위와 공시 수집 범위를 벗어난 사건은 반영되지 않았다.",
                confirmation="추가 공시, 회사 발표, 복수 매체의 후속 보도가 나오는지.",
                priority=95,
            )
        )

    patterns.sort(key=lambda p: p.priority, reverse=True)
    return patterns
