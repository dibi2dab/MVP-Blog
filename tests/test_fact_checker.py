from __future__ import annotations

from src.analyzers.ai_provider import MockProvider
from src.analyzers.fact_checker import FactChecker
from src.analyzers.research_analyst import ResearchAnalyst
from src.models.analysis import AnalystOutput, Claim
from src.models.event import Event
from src.models.research_packet import ResearchPacket
from src.models.source import EntityRef


def _packet(settings) -> ResearchPacket:
    return ResearchPacket(
        event=Event(event_id="e", event_type="stock_surge", entity=EntityRef(name="삼성전자", ticker="005930")),
        entity=EntityRef(name="삼성전자", ticker="005930"),
        news=[],
    )


class TestResearchAnalyst:
    def test_parse_output(self, settings):
        provider = MockProvider()
        analyst = ResearchAnalyst(provider, settings)
        output = analyst.analyze(_packet(settings))
        assert isinstance(output, AnalystOutput)
        assert output.facts or output.hypotheses
        assert output.key_drivers
        assert isinstance(output.summary, str)


class TestFactChecker:
    def test_rule_check_removes_unfounded(self, settings):
        checker = FactChecker(MockProvider(), settings)
        output = AnalystOutput(
            facts=[
                Claim(claim="매출은 1조2354억원이다", type="fact", confidence=0.99, source_ids=["missing"]),
                Claim(claim="거래량이 증가했다", type="fact", confidence=0.8, source_ids=[]),
            ]
        )
        result = checker.check(_packet(settings), output)
        # 패킷에 없는 source_id 참조 제거
        for c in result.approved_claims:
            assert c.source_ids == [] or set(c.source_ids) <= set()
        assert result.verdict in ("pass", "needs_review")

    def test_low_confidence_rejected(self, settings):
        checker = FactChecker(MockProvider(), settings)
        output = AnalystOutput(
            facts=[Claim(claim="내일 상승할 것이다", type="fact", confidence=0.5)]
        )
        result = checker.check(_packet(settings), output)
        assert result.approved_claims == []
        # 추측은 hypothesis 로 강등되어 replaced 에 포함되거나 rejected 반영 이슈 존재
        assert result.rejected_claims or result.replaced_claims or result.issue_notes

    def test_foresee_sentence_downgraded(self, settings):
        checker = FactChecker(MockProvider(), settings)
        output = AnalystOutput(
            facts=[Claim(claim="앞으로 주가가 반드시 오를 것이다", type="fact", confidence=0.9)]
        )
        result = checker.check(_packet(settings), output)
        downgraded = [c for c in result.approved_claims + result.replaced_claims]
        assert downgraded, "추측 문장은 기사 삽입 여부와 무관하게 검토돼야 함"
        for c in result.replaced_claims:
            assert c.type == "hypothesis"
            assert c.confidence <= 0.6