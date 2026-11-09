from __future__ import annotations

from src.models.analysis import AnalysisReport
from src.models.event import Event
from src.models.research_packet import ResearchPacket
from src.models.source import EntityRef
from src.writers.article_writer import ArticleWriter


def _article(sample_snapshot, settings):
    event = Event(
        event_id="e1",
        event_type="stock_surge",
        entity=EntityRef(name=sample_snapshot.name, ticker=sample_snapshot.ticker),
        event_date=sample_snapshot.price_series.bars[-1].date,
    )
    packet = ResearchPacket(event=event, entity=event.entity, market_data=sample_snapshot)
    report = AnalysisReport(packet_id="p1", event_id="e1")
    return ArticleWriter(None, settings).build(event, packet, report)


def test_headings_do_not_expose_writing_meta(sample_snapshot, settings):
    article = _article(sample_snapshot, settings)
    headings = [section.heading for section in article.sections]
    assert "이번 변동은 무엇으로 설명되나" in headings
    assert not any("검색 의도" in heading for heading in headings)


def test_body_has_no_meta_or_english_labels(sample_snapshot, settings):
    article = _article(sample_snapshot, settings)
    body = "\n\n".join(section.body for section in article.sections)
    for phrase in ("이 글의 질문은", "이 글은 그 부분", "이 글은 업종 지수"):
        assert phrase not in body, phrase
    for label in ("**FACT**", "**CONTEXT**", "**INTERPRETATION**", "**LIMITATION**"):
        assert label not in body, label


def test_korean_sentences_are_grammatical(sample_snapshot, settings):
    article = _article(sample_snapshot, settings)
    body = "\n\n".join(section.body for section in article.sections)
    assert "상승다" not in body
    assert "상승 마감했다" in body
    assert "20일선에서" not in body
    assert "종가는 장중 중간에 형성된 종가다" not in body


def test_sections_are_skipped_without_data(sample_snapshot, settings):
    article = _article(sample_snapshot, settings)
    headings = [section.heading for section in article.sections]
    assert "가격·거래량 진단" in headings
    assert "패턴 진단" in headings
    assert all(section.body.strip() for section in article.sections)
