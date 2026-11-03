from __future__ import annotations

from src.analyzers.ai_provider import MockProvider
from src.analyzers.quality_checker import QualityChecker
from src.models.article import Article
from src.models.event import Event
from src.models.source import EntityRef


class TestQualityChecker:
    def _article(self, body: str, sources=None, pub_type: str = "B", title: str | None = None,
                 event_date: str | None = "2026-09-02") -> Article:
        event = Event(
            event_id="e1",
            event_type="stock_surge",
            entity=EntityRef(name="삼성전자", ticker="005930"),
            publication_type=pub_type,
            event_date=event_date,
        )
        return Article(
            article_id="a1",
            event=event,
            title=title or "[2026년 9월 2일] 삼성전자 5.20% 상승…거래량은 평균의 3.1배",
            slug="x",
            body_markdown=body,
            sources=sources or ["출처1"],
        )

    def test_missing_sources_flag(self, settings):
        checker = QualityChecker(MockProvider(), settings)
        body = "# 삼성전자\n\n오늘 주가가 상승했다."
        result = checker.check(self._article(body, sources=[]), body)
        assert not result.passed
        assert any("출처" in i for i in result.issues)

    def test_banned_investment_language(self, settings):
        checker = QualityChecker(MockProvider(), settings)
        body = "# 삼성전자\n\n이 종목은 매수 추천이다. 지금 사야 한다."
        result = checker.check(self._article(body), body)
        assert not result.passed
        assert any("투자 권유" in i for i in result.issues)

    def test_title_missing_date_fails(self, settings):
        # 요구사항 1, 15: 제목에 정확한 날짜가 없으면 발행 차단
        checker = QualityChecker(MockProvider(), settings)
        body = self._good_body()
        article = self._article(body, sources=["출처1"], title="삼성전자 5.20% 상승 분석")
        result = checker.check(article, body)
        assert not result.passed
        assert any("날짜" in i for i in result.issues)

    def test_generic_title_phrase_fails(self, settings):
        # 요구사항 2, 15: 과도하게 일반적인 제목 문구 차단
        checker = QualityChecker(MockProvider(), settings)
        body = self._good_body()
        article = self._article(body, sources=["출처1"], title="[2026년 9월 2일] 삼성전자 데이터로 본 주가·거래량의 실체")
        result = checker.check(article, body)
        assert not result.passed
        assert any("일반적인" in i for i in result.issues)

    def test_good_article_passes(self, settings):
        # 요구사항 15: 날짜·종목명·핵심 숫자 포함, 최소 길이, 차트/공시 관련성 기준을 모두 통과
        checker = QualityChecker(MockProvider(), settings)
        body = self._good_body()
        result = checker.check(self._article(body, sources=["출처1"]), body)
        assert result.passed, result.issues
        assert result.score > 0.5

    def test_title_accuracy_and_generic_sentences(self, settings):
        # 근거 없는 "왜 하락했을까" 제목과 일반 문장은 발행 전 걸러야 한다.
        checker = QualityChecker(MockProvider(), settings)
        body = """# 코미팜

코미팜이 직전 거래일 대비 5.37% 하락했다. 거래량은 평균의 3.11배였다.
향후 추이를 지켜볼 필요가 있다.
향후 상승 가능성이 있다.

## 참고 자료

- 출처1

투자 판단은 본인의 책임이다."""
        article = self._article(body, sources=["출처1"], pub_type="B",
                                title="[2026년 9월 2일] 코미팜 5.37% 하락…거래량은 평균의 3.1배")
        result = checker.check(article, body)
        assert not result.passed
        issues = " ".join(result.issues)
        assert "일반" in issues or "왜" in issues or "반복" in issues

    def _good_body(self) -> str:
        # 최소 길이(700자)와 FACT/CONTEXT/INTERPRETATION/LIMITATION 구조를 충족하는 본문
        paras = []
        paras.append("## 오늘 주가 흐름\n\n")
        paras.append("**FACT** — 삼성전자는 이날 5.20% 상승 거래를 마감했다. 가격은 장중 한때 상승폭을 확대한 뒤 종가를 유지했다. 이는 직전 거래일과 비교해 확연히 다른 흐름이다.\n\n")
        paras.append("**CONTEXT** — 이 상승폭이 갖는 의미는 최근 평균 변동과 비교할 때 드러난다. 보통 저변동 구간에서는 1~2% 내외로 움직이므로, 오늘의 상승은 평소보다 분주한 시장이었다는 뜻이다.\n\n")
        paras.append("**INTERPRETATION** — 가격 상승과 함께 거래량도 평균 대비 3.10배로 늘었다. 이는 소수 물량이 아닌 여러 투자자가 참여했음을 시사한다.\n\n")
        paras.append("**LIMITATION** — 다만 상승폭이나 거래량만으로 특정 뉴스를 원인으로 단정할 수는 없다. 추가 공시가 나올 때까지 해석은 유보하는 것이 안전하다.\n\n")
        paras.append("## 거래량과 시장 참여 변화\n\n")
        paras.append("**FACT** — 거래량은 최근 평균 대비 3.10배 수준으로 집계됐다. 이는 평소보다 많은 물량이 출회된 것이다.\n\n")
        paras.append("**CONTEXT** — 물량이 늘었다는 것은 매수·매도 양방향에서 참여자가 늘었다는 뜻이다. 자금이 유입 혹은 회전했을 가능성이 있다.\n\n")
        paras.append("**INTERPRETATION** — 방향과 거래량이 맞물리면 다수 참여자의 판단이 가격에 실렸음을 뜻한다. 추세를 만들 수 있는 조건이다.\n\n")
        paras.append("**LIMITATION** — 다만 거래량 증가는 단순 회전 때문일 수 있어 원인을 단정하는 근거로는 부족하다.\n\n")
        paras.append("## 종합 분석\n\n")
        paras.append("이번 상승은 가격과 거래량이 함께 움직인 것을 데이터로 확인했다. 원인으로 지목할 단일 사건은 아직 확인되지 않았다.\n\n")
        paras.append("## 참고 자료\n\n- 출처1\n\n투자 판단은 본인의 책임이다.")
        return "".join(paras)