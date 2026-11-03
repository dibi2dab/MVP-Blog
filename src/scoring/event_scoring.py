from __future__ import annotations

from dataclasses import dataclass

from src.config.settings import Settings
from src.models.event import EventReason
from src.models.market_data import MarketSnapshot

DETECTION_REASONS = {
    "price_up_10": "주가 +10% 이상",
    "price_up_5": "주가 +5% 이상",
    "price_up_3": "주가 +3% 이상",
    "price_down_10": "주가 -10% 이상",
    "price_down_5": "주가 -5% 이상",
    "price_down_3": "주가 -3% 이상",
    "volume_300": "거래량 평균 대비 300% 이상",
    "volume_100": "거래량 평균 대비 100% 이상",
    "volume_50": "거래량 평균 대비 50% 이상",
    "new_high": "최근 60영업일 신고가",
    "new_low": "최근 60영업일 신저가",
    "gap_up": "갭 상승 (시가 급등)",
    "gap_down": "갭 하락 (시가 급락)",
    "foreign_flow": "외국인 수급 변동",
    "important_disclosure": "중요 공시",
    "earnings": "실적/공시 이벤트",
    "news_high": "대형 뉴스",
}


@dataclass
class DetectionResult:
    """종목별 감지 결과."""

    ticker: str
    name: str
    reasons: list[tuple[str, int]]  # (reason_code, score)
    evidence: dict
    event_date: str | None = None


class EventScorer:
    """이벤트 점수 계산. 점수 규칙은 settings.yaml 에서 읽는다."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.weights = settings.scoring.weights

    def w(self, key: str) -> int:
        return int(self.weights.get(key, 0))

    def score_snapshot(self, snapshot: MarketSnapshot) -> DetectionResult:
        """가격/거래량 기반 1차 점수 계산."""
        reasons: list[tuple[str, int]] = []
        evidence: dict = {}

        change = snapshot.latest_change_pct
        evidence["latest_change_pct"] = change
        if change is not None:
            if change >= 0.10:
                reasons.append(("price_up_10", self.w("price_change_10_percent")))
            elif change >= 0.05:
                reasons.append(("price_up_5", self.w("price_change_5_percent")))
            elif change >= 0.03:
                reasons.append(("price_up_3", self.w("price_change_3_percent")))
            if change <= -0.10:
                reasons.append(("price_down_10", self.w("price_change_negative_10_percent")))
            elif change <= -0.05:
                reasons.append(("price_down_5", self.w("price_change_negative_5_percent")))
            elif change <= -0.03:
                reasons.append(("price_down_3", self.w("price_change_negative_3_percent")))

        vol_ratio = snapshot.volume_ratio
        evidence["volume_ratio"] = vol_ratio
        if vol_ratio is not None:
            if vol_ratio >= 3.0:
                reasons.append(("volume_300", self.w("volume_increase_300_percent")))
            elif vol_ratio >= 2.0:
                reasons.append(("volume_100", self.w("volume_increase_100_percent")))
            elif vol_ratio >= 1.5:
                reasons.append(("volume_50", self.w("volume_increase_50_percent")))

        if snapshot.new_high:
            reasons.append(("new_high", self.w("new_high")))
        if snapshot.new_low:
            reasons.append(("new_low", self.w("new_low")))
        if snapshot.gap_up:
            reasons.append(("gap_up", self.w("gap_up")))
        if snapshot.gap_down:
            reasons.append(("gap_down", self.w("gap_down")))

        latest_amount = snapshot.price_series.bars[-1].amount if snapshot.price_series.bars else None
        evidence["latest_amount"] = latest_amount
        event_date = snapshot.price_series.bars[-1].date if snapshot.price_series.bars else None
        return DetectionResult(
            ticker=snapshot.ticker,
            name=snapshot.name,
            reasons=reasons,
            evidence=evidence,
            event_date=event_date,
        )

    def total_score(self, result: DetectionResult) -> int:
        return sum(score for _, score in result.reasons)

    def select_for_research(self, results: list[DetectionResult]) -> list[DetectionResult]:
        threshold = self.settings.scoring.minimum_research_score
        min_vol = self.settings.detection.min_volume_usd
        selected = []
        for r in results:
            score = self.total_score(r)
            amount = (r.evidence.get("latest_amount") or 0)
            if score < threshold:
                continue
            if r.evidence.get("latest_change_pct") is None and not r.evidence.get("volume_ratio"):
                continue
            if amount and amount < min_vol:
                # 거래대금이 지나치게 낮으면 관심 이벤트 제외 (유동성 필터)
                continue
            selected.append(r)
        selected.sort(key=lambda r: self.total_score(r), reverse=True)
        return selected[: self.settings.detection.max_events_per_run]


def reasons_to_events(result: DetectionResult, score: int) -> list[EventReason]:
    return [
        EventReason(code=code, label=DETECTION_REASONS.get(code, code), score_contribution=s)
        for code, s in result.reasons
    ]