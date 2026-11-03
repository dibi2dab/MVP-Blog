from __future__ import annotations

from dataclasses import dataclass, field

from src.config.settings import Settings
from src.models.research_packet import ResearchPacket


@dataclass
class EvidenceResult:
    """Evidence Score 계산 결과. '왜 움직였는가'를 설명할 근거가 얼마나 있는지 요약한다."""

    score: int = 0
    reasons: list[tuple[str, str, int]] = field(default_factory=list)  # (code, label, score)
    has_disclosure: bool = False
    has_news: bool = False
    confirmed_negative: bool = False
    confirmed_positive: bool = False
    cause_known: bool = False
    detail: str = ""

    def score_for(self, code: str) -> int:
        for c, _, s in self.reasons:
            if c == code:
                return s
        return 0


class EvidenceScorer:
    """ResearchPacket이 주가 움직임의 원인·배경을 설명할 근거를 담고 있는지 점수화한다.

    Event Score가 "시장에서 볼 만한 이벤트인가"를 묻는다면,
    Evidence Score는 "그 움직임을 설명할 근거가 있는가"를 묻는다.
    근거 점수 규칙은 settings.yaml 의 `evidence.weights` 에서 관리한다.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.weights = settings.evidence.weights

    def w(self, key: str) -> int:
        return int(self.weights.get(key, 0))

    def evaluate(self, packet: ResearchPacket) -> EvidenceResult:
        result = EvidenceResult()
        result.cause_known = False
        name = (packet.entity.name or "") if packet.entity else ""
        ticker = getattr(packet.entity, "ticker", "") or ""
        event_date = packet.event.event_date

        # 1) 공식 공시: 해당 기업 공시가 있으면 근거로 인정
        disclosures = [d for d in packet.disclosures]
        if disclosures:
            weight = self.w("official_disclosure")
            result.score += weight
            result.reasons.append(("official_disclosure", "공식 기업 공시 확인", weight))
            result.has_disclosure = True

        # 2) 회사 공식 발표: 해당 기업 이름이 등장하고, 발표·확정·공시형 뉴스 + 이벤트일 근접
        if self._has_official_statement_about(packet, name, ticker, event_date):
            weight = self.w("official_company_statement")
            result.score += weight
            result.reasons.append(("official_company_statement", "회사 공식 발표 확인", weight))

        # 3) 복수의 신뢰 뉴스에서 동일 사건 확인:
        #    해당 기업을 언급한 뉴스가 복수이고, 이벤트일과 근접한 뉴스가 존재해야 함.
        entity_news = self._entity_news(packet, name, ticker)
        if len(entity_news) >= 2 and any(self._near(p.published_at, event_date) for p in entity_news):
            weight = self.w("multiple_news_confirmation")
            result.score += weight
            result.reasons.append(("multiple_news_confirmation", "복수의 신뢰 뉴스에서 동일 사건 확인", weight))
            result.has_news = True

        # 4) 관련 산업 이벤트: 산업 데이터에 실질 내용이 있어야 함
        if self._has_industry_content(packet):
            weight = self.w("industry_event")
            result.score += weight
            result.reasons.append(("industry_event", "관련 산업 이벤트 확인", weight))

        # 5) 시장 전체 이벤트와의 명확한 연관: 관련 종목이 함께 움직였다는 근거 필요
        if packet.related_entities:
            weight = self.w("market_linkage")
            result.score += weight
            result.reasons.append(("market_linkage", "시장 전체 이벤트와의 연관성", weight))

        # 6) 뉴스/공시가 주가 움직임 시간과 직접 연결
        if self._is_temporally_linked(packet, name, ticker, event_date):
            weight = self.w("temporal_linkage")
            result.score += weight
            result.reasons.append(("temporal_linkage", "뉴스/공시가 주가 움직임 시간과 직접 연결", weight))

        result.cause_known = result.score >= self.settings.evidence.data_brief_threshold
        direction = packet.market_data.latest_change_pct if packet.market_data else None
        if direction is not None:
            result.confirmed_negative = direction < 0 and result.cause_known
            result.confirmed_positive = direction > 0 and result.cause_known

        result.reasons.sort(key=lambda r: r[2], reverse=True)
        result.detail = ", ".join(f"{label}({s})" for _, label, s in result.reasons) or "근거 부족"
        return result

    def classify(self, score: int) -> str:
        """발행 유형 결정: Type A | Type B | Type C"""
        cfg = self.settings.evidence
        if score >= cfg.deep_analysis_threshold:
            return "A"
        if score >= cfg.data_brief_threshold:
            return "B"
        return "C"

    def _entity_news(self, packet: ResearchPacket, name: str, ticker: str) -> list:
        """해당 기업(이름 또는 종목코드)을 언급한 뉴스 목록."""
        if not name:
            return []
        out = []
        for n in packet.news[:30]:
            title = n.title or ""
            if name in title or (ticker and ticker in title):
                out.append(n)
        return out

    def _has_official_statement_about(self, packet: ResearchPacket, name: str, ticker: str, event_date: str | None) -> bool:
        """회사 공식 발표: 해당 기업 이름을 언급한 발표·확정·공시·승인형 뉴스가 있고 이벤트일 근접."""
        if not name:
            return False
        for n in self._entity_news(packet, name, ticker):
            title = (n.title or "").lower()
            if any(k in title for k in ("공식", "발표", "공시", "보도자료", "확정", "승인", "함께 공개")):
                if event_date and self._near(n.published_at, event_date):
                    return True
        return False

    def _has_industry_content(self, packet: ResearchPacket) -> bool:
        """산업 데이터에 실질 내용(8자 이상 텍스트)이 있는지."""
        for v in (packet.industry_data or {}).values():
            if isinstance(v, str) and len(v.strip()) > 8:
                return True
        return False

    def _is_temporally_linked(self, packet: ResearchPacket, name: str, ticker: str, event_date: str | None) -> bool:
        if not event_date:
            return False
        if any(p.published_at and self._near(p.published_at, event_date) for p in packet.news[:30]):
            return True
        for d in packet.disclosures[:10]:
            rcpt = (d.published_at or "")[:10]
            if rcpt and self._near(rcpt, event_date):
                return True
        return False

    @staticmethod
    def _near(date_a: str | None, date_b: str | None, window: int = 2) -> bool:
        a = (date_a or "")[:10].replace("-", "")
        b = (date_b or "")[:10].replace("-", "")
        if not a or not b:
            return False
        try:
            return abs(int(a[:8]) - int(b[:8])) <= window
        except ValueError:
            return False


def decide_publication_type(
    event_score: int,
    evidence_score: int,
    has_price_data: bool,
    has_volume_data: bool,
    min_event_score: int = 0,
) -> str:
    """발행 유형을 결정한다.

    Type A (Deep Analysis): 이벤트 점수 높음 + 근거 점수 높음
    Type B (Data Brief): 이벤트 점수 높음 + 근거 부족 (단, 데이터 분석 가치 존재)
    Type C (Reject): 이벤트 점수 부족 또는 (근거 부족 + 데이터 분석 가치 낮음)

    시장 움직임 데이터(가격/거래량)가 있으면 분석 가치가 있어 Type B로 살려준다.
    """
    # 이벤트 자체가 저조하면 발행하지 않는다.
    if event_score < min_event_score:
        return "C"

    # 근거 점수 기반 분류
    if evidence_score >= 12:
        return "A"
    if evidence_score >= 5:
        return "B"

    # 근거 부족이지만 가격·거래량 데이터가 있으면 Data Brief로 살린다.
    if has_price_data or has_volume_data:
        return "B"
    return "C"