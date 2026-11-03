from __future__ import annotations

from src.config.settings import SourceItemConfig
from src.pipeline.collect_step import CollectStep
from src.pipeline.detect_step import DetectStep
from src.pipeline.generate_step import GenerateStep
from src.pipeline.publish_step import PublishStep
from src.pipeline.research_step import ResearchStep
from src.storage.file_store import JsonStore


def _configure(settings) -> JsonStore:
    settings.stocks_universe = [
        SourceItemConfig(code="000001", name="테스트주"),
        SourceItemConfig(code="000002", name="테스트회사"),
    ]
    settings.sources_raw = {
        "stocks": {"price": {"provider": "mock"}},
        "news": {"provider": "mock"},
        "disclosures": {"provider": "mock"},
    }
    settings.app.mock_mode = "true"
    settings.ai.provider = "mock"
    return JsonStore(settings)


class TestMockPipeline:
    def test_collect_produces_data(self, settings):
        store = _configure(settings)
        result = CollectStep(settings, store).run()
        assert len(result["snapshots"].snapshots) == 2
        assert result["news_items"]
        assert result["disclosures"]

    def test_full_mock_pipeline(self, settings):
        store = _configure(settings)
        result = CollectStep(settings, store).run()

        events = DetectStep(settings, store).run(result["snapshots"], result["news_items"], result["disclosures"])

        research = ResearchStep(settings, store)
        reports = {}
        for event in events:
            report = research.run(
                [event], result["snapshots"], result["news_items"], result["disclosures"]
            ).get(event.event_id)
            if report:
                reports[event.event_id] = report

        generated = []
        for event_id, report in reports.items():
            event = store.load_event(event_id)
            packet = store.load_research_packet(f"packet_{event_id}")
            if not packet:
                continue
            article = GenerateStep(settings, store).run(event, packet, report)
            if article:
                generated.append(article)
        assert generated, "승인된 기사가 1건 이상이어야 함"

        publish = PublishStep(settings, store)
        results = [publish.run(a) for a in generated]
        assert any(r and r.ok for r in results)
        assert publish.run(generated[0]) is None  # 중복 게시 방지