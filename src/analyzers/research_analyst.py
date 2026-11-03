from __future__ import annotations

import json

from src.analyzers.ai_provider import AIProvider
from src.config.settings import Settings
from src.models.analysis import AnalystOutput, Claim
from src.models.research_packet import ResearchPacket
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """당신은 금융 데이터 리서치 애널리스트다.
주어진 Research Packet(수집된 데이터 묶음)만을 기준으로 분석한다.

반드시 지켜야 할 규칙:
1. 패킷에 없는 구체적인 수치를 만들지 않는다.
2. 패킷에 없는 사건을 사실로 서술하지 않는다.
3. 원인이 명확하지 않으면 "확인된 단일 원인은 없다"고 표현한다.
4. 추측은 type=hypothesis 로, 확인된 내용은 type=fact 로 구분한다.
5. 모든 fact 에는 반드시 source_ids 를 지정한다.
6. 존재하지 않는 출처를 만들지 않는다.
응답은 반드시 다음 JSON 구조로 출력한다:
{
  "facts": [{"claim": "...", "type": "fact", "confidence": 0.0~1.0, "source_ids": ["..."], "reasoning": "..."}],
  "hypotheses": [{"claim": "...", "type": "hypothesis", "confidence": 0.0~1.0, "source_ids": [], "reasoning": "..."}],
  "key_drivers": ["..."],
  "unknowns": ["..."],
  "summary": "한 줄 요약"
}
"""


class ResearchAnalyst:
    """Agent 1 — Research Packet 해석."""

    def __init__(self, provider: AIProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings

    def analyze(self, packet: ResearchPacket) -> AnalystOutput:
        user_prompt = self._build_prompt(packet)
        raw = self.provider.chat_json(
            _SYSTEM_PROMPT,
            user_prompt,
            temperature=self.settings.ai.temperature,
        )
        return self._parse(raw, packet)

    def _build_prompt(self, packet: ResearchPacket) -> str:
        ctx = {
            "event": packet.event.model_dump(),
            "entity": packet.entity.model_dump(),
            "market_data": packet.market_data.model_dump() if packet.market_data else None,
            "price_data": packet.price_data,
            "volume_data": packet.volume_data,
            "financial_data": packet.financial_data,
            "disclosures": [d.model_dump() for d in packet.disclosures],
            "news_titles": [{"title": n.title, "published_at": n.published_at, "source": n.source} for n in packet.news[:15]],
            "news_clusters": [
                {"headline": c.headline, "n_items": c.n_items, "sources": sorted(c.unique_sources)}
                for c in packet.news_clusters[:5]
            ],
            "related_entities": [e.model_dump() for e in packet.related_entities],
            "historical_cases": [h.model_dump() for h in packet.historical_cases],
            "sources": [s.model_dump() for s in packet.sources],
        }
        return json.dumps(ctx, ensure_ascii=False, indent=2)

    def _parse(self, raw: dict, packet: ResearchPacket) -> AnalystOutput:
        facts = [Claim.model_validate(c) for c in raw.get("facts", [])]
        hypos = [Claim.model_validate(c) for c in raw.get("hypotheses", [])]
        # 패킷에 없는 source_id 참조 제거 (존재하지 않는 출처 방지)
        known = {s.source_id for s in packet.sources}
        for claim in facts + hypos:
            claim.source_ids = [sid for sid in claim.source_ids if sid in known] if known else []
        return AnalystOutput(
            facts=facts,
            hypotheses=hypos,
            key_drivers=[str(k) for k in raw.get("key_drivers", [])],
            unknowns=[str(u) for u in raw.get("unknowns", [])],
            summary=str(raw.get("summary", "")),
        )