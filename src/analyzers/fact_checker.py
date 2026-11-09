from __future__ import annotations

import re

from src.analyzers.ai_provider import AIProvider
from src.config.settings import Settings
from src.models.analysis import Claim, FactCheckResult
from src.models.research_packet import ResearchPacket
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """당신은 금융 기사 팩트 체커(회의론자)다.
Research Packet 과 Analyst 의 주장 목록을 대조해 다음을 수행한다.

1. 패킷에 없는 숫자/사실을 쓰는 주장 → rejected
2. 추측을 사실처럼 말하는 주장 → hypothesis 로 교체 (type 변경)
3. 근거 없는 확정 진술(은/는다) → 인과 불확실성 표현으로 교체
4. "오를 것이다" 같은 예측은 confidence 를 낮추거나 hypotheses 로 이동
5. 상관관계를 인과관계로 주장하는 문장 수정
6. 주장마다 해당 source_id 가 패킷의 sources 에 존재하는지 확인
7. 확인되지 않은 원인을 단정하는 주장 → rejected
8. 근거 없는 점수·지수·순위·가중치 → rejected
9. 같은 사실을 표현만 바꿔 반복하는 주장 → 중복으로 표시
10. 작성 과정이나 편집 기준을 설명하는 메타 문장 → rejected

응답은 반드시 다음 JSON 구조:
{
  "approved": [...Claim...],
  "rejected": [...Claim...],
  "replaced": [...Claim...],
  "issues": ["...", "..."],
  "verdict": "pass" | "needs_review"
}
"""


class FactChecker:
    """Agent 2 — Analyst 결과 검증. AI 환각 최종 방어."""

    def __init__(self, provider: AIProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings
        self.min_confidence = settings.scoring.minimum_confidence

    def check(self, packet: ResearchPacket, analyst_output) -> FactCheckResult:
        if self.settings.app.mock_mode == "true" or self.provider.name == "mock":
            return self._rule_check(packet, analyst_output)
        user_prompt = self._build_prompt(packet, analyst_output)
        raw = self.provider.chat_json(_SYSTEM_PROMPT, user_prompt, temperature=0.0)
        return self._parse(raw, packet)

    def _build_prompt(self, packet: ResearchPacket, output) -> str:
        import json

        return json.dumps(
            {
                "packet_summary": packet.summary_stats(),
                "sources": [s.model_dump() for s in packet.sources],
                "claims": [c.model_dump() for c in output.facts + output.hypotheses],
                "market_data_bounds": self._data_bounds(packet),
            },
            ensure_ascii=False,
            indent=2,
        )

    def _rule_check(self, packet: ResearchPacket, output) -> FactCheckResult:
        """키 없이도 동작하는 규칙 기반 1차 검증."""
        approved: list[Claim] = []
        rejected: list[Claim] = []
        replaced: list[Claim] = []
        issues: list[str] = []
        known = {s.source_id for s in packet.sources}

        all_text = " ".join(
            [
                *(d.title or "" for d in packet.disclosures),
                *(n.title or "" for n in packet.news),
            ]
        )

        for claim in output.facts + output.hypotheses:
            text = claim.claim
            # 보유 데이터의 숫자를 검증: 패킷 바깥의 구체적인 수치 배제 (5자리 이상 숫자)
            numbers = re.findall(r"\d+[.,]?\d*%?", text)
            if len(numbers) > 8 and not _numbers_in_packet(packet, numbers):
                rejected.append(claim)
                issues.append(f"패킷에 없는 수치 다수 포함: {text[:60]}")
                continue
            if claim.source_ids and not any(sid in known for sid in claim.source_ids):
                claim.source_ids = []
                issues.append(f"출처 검증 실패: {text[:60]}")
            # 추측 어휘 감지
            if _is_forecast(text):
                if claim.type == "fact":
                    claim.type = "hypothesis"
                    claim.confidence = min(claim.confidence, 0.6)
                    issues.append(f"추측을 사실로 표현한 문장을 가설로 변경: {text[:50]}")
            if claim.confidence < self.min_confidence:
                replaced.append(claim)
                issues.append(f"confidence 낮음({claim.confidence:.2f}) -> 배제: {text[:50]}")
                continue
            approved.append(claim)

        verdict = "needs_review" if issues else "pass"
        return FactCheckResult(
            approved_claims=approved,
            rejected_claims=rejected,
            replaced_claims=replaced,
            issue_notes=issues,
            verdict=verdict,
        )

    def _parse(self, raw: dict, packet: ResearchPacket) -> FactCheckResult:
        approved = [Claim.model_validate(c) for c in raw.get("approved", [])]
        rejected = [Claim.model_validate(c) for c in raw.get("rejected", [])]
        replaced = [Claim.model_validate(c) for c in raw.get("replaced", [])]
        known = {s.source_id for s in packet.sources}
        for c in approved + rejected + replaced:
            c.source_ids = [sid for sid in c.source_ids if sid in known]
        result = FactCheckResult(
            approved_claims=approved,
            rejected_claims=rejected,
            replaced_claims=replaced,
            issue_notes=[str(i) for i in raw.get("issues", [])],
            verdict=str(raw.get("verdict", "pass")),
        )
        return result

    def _data_bounds(self, packet: ResearchPacket) -> dict:
        try:
            return {
                "latest_change_pct": packet.market_data.latest_change_pct,
                "volume_ratio": packet.market_data.volume_ratio,
                "n_news": len(packet.news),
                "n_disclosures": len(packet.disclosures),
            }
        except Exception:
            return {}


def _numbers_in_packet(packet: ResearchPacket, numbers: list[str]) -> bool:
    blob = str(packet.model_dump())
    for n in numbers[:5]:
        clean = n.replace("%", "").replace(",", "")
        if clean and clean not in blob:
            return False
    return True


_FORECAST_WORDS = ["전망", "예상", "것이다", "오를", "상승할", "하락할", "반등할", "유지될", "게 분명", "반드시"]


def _is_forecast(text: str) -> bool:
    return any(w in text for w in _FORECAST_WORDS)