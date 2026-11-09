from __future__ import annotations

"""자체 계산 데이터를 중심으로 기사를 구성한다.

뉴스 제목을 요약하는 대신, 일봉에서 직접 계산한 거래량 z-score, 이동평균 이격,
갭, 장중 변동성, 5일/20일 수익률 같은 값으로 '무엇이 달라졌는지'를 설명한다.
확인된 자료와 확인되지 않은 부분을 분리하고, 시나리오·확인 조건·반대 해석을
모두 포함해 단순 요약 기사와 차별화한다.
"""

from src.analyzers.ai_provider import AIProvider
from src.analysis.quant_metrics import MarketPattern, QuantMetrics, compute_quant_metrics, detect_patterns
from src.analysis.source_filter import FilteredSources, filter_sources, parse_date
from src.config.settings import Settings
from src.models.analysis import AnalysisReport, Claim
from src.models.article import Article, ArticleSection
from src.models.event import Event
from src.models.research_packet import ResearchPacket
from src.scoring.evidence_scoring import EvidenceResult
from src.utils.korean import format_korean_date, topic_after
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ArticleWriter:
    """검증된 데이터 + 계산 지표 + 관련 자료로 기사 섹션을 만든다."""

    def __init__(self, provider: AIProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings

    def build(
        self,
        event: Event,
        packet: ResearchPacket,
        report: AnalysisReport,
        publication_type: str = "B",
        evidence: EvidenceResult | None = None,
        metrics: QuantMetrics | None = None,
    ) -> Article:
        metrics = metrics or compute_quant_metrics(packet)
        filtered = filter_sources(event, packet, self.settings)
        ctx = _Context(event, packet, report, evidence or EvidenceResult(), self.settings, metrics, filtered)
        sections = ctx.build_sections(publication_type)
        return Article(
            article_id=f"a_{event.event_id}",
            event=event,
            title="",
            slug="",
            description="",
            category="stocks",
            sections=sections,
            analysis_report=report,
            sources=filtered.source_lines,
            data_metrics=metrics.available_metrics(),
            frontmatter={},
        )


class _Context:
    def __init__(
        self,
        event: Event,
        packet: ResearchPacket,
        report: AnalysisReport,
        evidence: EvidenceResult,
        settings: Settings,
        metrics: QuantMetrics,
        filtered: FilteredSources,
    ) -> None:
        self.event = event
        self.packet = packet
        self.report = report
        self.evidence = evidence
        self.settings = settings
        self.m = metrics
        self.filtered = filtered
        self.name = event.entity.name or "해당 종목"
        self.patterns: list[MarketPattern] = detect_patterns(
            metrics,
            has_cause_news=filtered.has_cause_news,
            has_cause_disclosure=filtered.has_cause_disclosure,
        )

    # ------------------------------------------------------------------ #
    def build_sections(self, publication_type: str) -> list[ArticleSection]:
        sections: list[ArticleSection] = [
            ArticleSection(heading="", body=self.executive_summary()),
            ArticleSection(heading="핵심 데이터", body=self.data_card()),
            ArticleSection(heading="이번 변동은 무엇으로 설명되나", body=self.search_intent_answer()),
        ]
        if self.m.change_pct is not None:
            sections.append(ArticleSection(heading="가격·거래량 진단", body=self.price_volume_diagnosis()))
        if self.patterns:
            sections.append(ArticleSection(heading="패턴 진단", body=self.pattern_diagnosis()))
        sections.extend(
            [
                ArticleSection(heading="시나리오와 확인 조건", body=self.scenarios()),
                ArticleSection(heading="반대 해석과 한계", body=self.counter_analysis()),
                ArticleSection(heading="확인된 자료와 공시", body=self.source_section()),
                ArticleSection(heading="앞으로 확인할 데이터", body=self.future_data()),
            ]
        )
        if publication_type == "A" and self.filtered.background_news:
            sections.insert(-1, ArticleSection(heading="배경 자료", body=self.background_section()))
        return [s for s in sections if s.body and s.body.strip()]

    # ------------------------------------------------------------------ #
    def executive_summary(self) -> str:
        m = self.m
        lines = ["> **핵심 요약**", ">"]
        pct = _fmt_signed_pct(m.change_pct)
        direction = direction_word(m.change_pct)
        if m.close is not None:
            lines.append(f"> {self.name}{topic_after(self.name)} {self.date_ko} **{pct} {direction}** 마감했다. 종가는 {m.close:,.0f}원이다.")
        else:
            lines.append(f"> {self.name}{topic_after(self.name)} {self.date_ko} 가격 변동이 확인됐다. {pct} {direction} 흐름이다.")
        if m.volume_ratio is not None:
            z = f", 거래량 z-score {m.volume_zscore:+.2f}" if m.volume_zscore is not None else ""
            lines.append(f"> 거래량은 20일 평균의 **{m.volume_ratio:.2f}배**{z}다.")
        if m.return_20d is not None or m.distance_ma20_pct is not None:
            bits = []
            if m.return_5d is not None:
                bits.append(f"5일 수익률 {m.return_5d:+.2f}%")
            if m.return_20d is not None:
                bits.append(f"20일 수익률 {m.return_20d:+.2f}%")
            if m.distance_ma20_pct is not None:
                bits.append(f"20일선 대비 {m.distance_ma20_pct:+.2f}%")
            lines.append(f"> {' · '.join(bits)}다.")
        if self.filtered.has_cause:
            lines.append("> 변동일과 가까운 시점의 직접 관련 자료가 확인됐다. 다만 시점 일치가 인과관계를 보장하지는 않는다.")
        else:
            lines.append("> 변동일 ±3일 안에서 단일 원인을 설명하는 직접 공시·뉴스는 확인되지 않았다. 가격·거래량 계산값으로 범위를 좁힌다.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    def data_card(self) -> str:
        m = self.m
        rows = ["| 항목 | 값 |", "|---|---|"]
        rows.append(f"| 기준일 | {m.latest_date or self.event.event_date or '확인 불가'} |")
        if m.close is not None:
            rows.append(f"| 종가 | {m.close:,.0f}원 |")
        if m.change_pct is not None:
            rows.append(f"| 전일 대비 | {m.change_pct:+.2f}% |")
        if m.volume:
            rows.append(f"| 거래량 | {m.volume:,}주 |")
        if m.volume_ratio is not None:
            rows.append(f"| 20일 평균 거래량 대비 | {m.volume_ratio:.2f}배 |")
        if m.volume_zscore is not None:
            rows.append(f"| 거래량 z-score | {m.volume_zscore:+.2f} |")
        if m.amount_ratio is not None:
            rows.append(f"| 20일 평균 거래대금 대비 | {m.amount_ratio:.2f}배 |")
        if m.gap_pct is not None:
            rows.append(f"| 시가 갭 | {m.gap_pct:+.2f}% |")
        if m.intraday_range_pct is not None:
            rows.append(f"| 장중 변동 폭 | {m.intraday_range_pct:.2f}% |")
        if m.close_position is not None:
            rows.append(f"| 종가의 장중 위치 | {m.close_position * 100:.0f}% |")
        if m.return_5d is not None:
            rows.append(f"| 5일 수익률 | {m.return_5d:+.2f}% |")
        if m.return_20d is not None:
            rows.append(f"| 20일 수익률 | {m.return_20d:+.2f}% |")
        if m.distance_ma20_pct is not None:
            rows.append(f"| 20일선 이격 | {m.distance_ma20_pct:+.2f}% |")
        if m.distance_ma60_pct is not None:
            rows.append(f"| 60일선 이격 | {m.distance_ma60_pct:+.2f}% |")
        if m.drawdown_from_high_60d_pct is not None:
            rows.append(f"| 60일 고점 대비 | {m.drawdown_from_high_60d_pct:+.2f}% |")
        if m.rally_from_low_60d_pct is not None:
            rows.append(f"| 60일 저점 대비 | {m.rally_from_low_60d_pct:+.2f}% |")
        if m.volatility_20d is not None:
            rows.append(f"| 20일 일간 변동성 | {m.volatility_20d:.2f}% |")
        if m.return_zscore is not None:
            rows.append(f"| 당일 수익률 z-score | {m.return_zscore:+.2f} |")
        return "\n".join(rows)

    # ------------------------------------------------------------------ #
    def search_intent_answer(self) -> str:
        pct = _fmt_abs_pct(self.m.change_pct)
        direction = direction_word(self.m.change_pct)
        paras: list[str] = [f"{self.name} 주가는 {self.date_ko} {pct} {direction} 마감했다."]
        if self.filtered.has_cause:
            sources = []
            if self.filtered.has_cause_disclosure:
                sources.append("직접 관련 공시")
            if self.filtered.has_cause_news:
                sources.append("변동일과 가까운 뉴스")
            paras.append(
                f"{'와 '.join(sources)}가 변동일과 가까운 시점에 확인된다. 다만 시점이 가깝다는 사실과 "
                "그 자료가 가격 방향을 실제로 만들었다는 판단은 구분해야 한다."
            )
        else:
            paras.append(
                "변동일 ±3일 안에서 이 움직임을 직접 설명하는 공시나 단일 뉴스는 확인되지 않았다. "
                "원인을 단정하지 않고 가격과 거래량에서 관찰된 변화만 짚는다."
            )
        observations: list[str] = []
        if self.m.volume_ratio is not None:
            observations.append(f"거래량이 20일 평균의 {self.m.volume_ratio:.2f}배로 평소와 달랐다")
        if self.m.return_20d is not None:
            observations.append(f"20일 수익률이 {self.m.return_20d:+.2f}%로 중기 흐름을 보여준다")
        if self.m.distance_ma20_pct is not None:
            gap = self.m.distance_ma20_pct
            relation = "높다" if gap >= 0 else "낮다"
            observations.append(f"종가가 20일선보다 {abs(gap):.2f}% {relation}")
        if self.m.gap_pct is not None and abs(self.m.gap_pct) >= 1.0:
            observations.append(f"시가가 전일 종가 대비 {self.m.gap_pct:+.2f}% 갭으로 출발했다")
        if observations:
            paras.append(" ".join(f"{item}." for item in observations))
        paras.append(
            "매수·매도 주체, 장중 호가 흐름, 사건의 실제 파급력은 수집된 일봉만으로 알 수 없다."
        )
        return "\n\n".join(paras)

    # ------------------------------------------------------------------ #
    def price_volume_diagnosis(self) -> str:
        m = self.m
        if m.change_pct is None:
            return f"{self.name}의 가격 데이터가 충분하지 않아 가격·거래량 진단을 생략한다."

        pct = _fmt_signed_pct(m.change_pct)
        direction = direction_word(m.change_pct)
        paras = [f"**확인된 데이터** — 종가는 {m.close:,.0f}원, 전일 대비 {pct} {direction} 마감했다. 거래량은 {m.volume:,}주다."]

        context_bits = []
        if m.volume_ratio is not None:
            context_bits.append(f"20일 평균 거래량의 {m.volume_ratio:.2f}배")
        if m.volatility_20d is not None:
            context_bits.append(f"최근 20일 일간 변동성은 {m.volatility_20d:.2f}%")
        if m.intraday_range_pct is not None:
            context_bits.append(f"당일 장중 변동 폭은 {m.intraday_range_pct:.2f}%")
        if m.return_5d is not None:
            context_bits.append(f"5일 수익률 {m.return_5d:+.2f}%")
        paras.append("**비교 맥락** — " + ", ".join(context_bits) + "로 집계됐다." if context_bits else "**비교 맥락** — 비교 가능한 평균 데이터가 제한적이다.")

        if m.volume_ratio is not None and m.change_pct is not None:
            if m.change_pct < 0 and m.volume_ratio >= 1.5:
                interpretation = (
                    "가격 하락과 거래량 증가가 동시에 나타났다. 매도 물량이 소화되는 과정일 수도 있고, "
                    "매수세가 약한 가운데 매도가 우위를 보인 결과일 수도 있다. 두 해석을 가르려면 종가 위치와 후속 수급이 필요하다."
                )
            elif m.change_pct > 0 and m.volume_ratio >= 1.5:
                interpretation = (
                    "가격 상승과 거래량 증가가 겹쳤다. 소수 주문이 아니라 여러 참여자가 가격 방향에 반응했을 가능성을 시사한다. "
                    "다만 거래량은 방향을 확정하지 않으므로, 상승분을 되돌리는 물량인지도 함께 봐야 한다."
                )
            elif m.change_pct > 0 and m.volume_ratio < 0.8:
                interpretation = (
                    "가격은 올랐지만 거래량은 20일 평균을 밑돌았다. 상승 폭에 비해 참여가 넓지 않았을 수 있어, "
                    "추세의 신뢰도를 낮춰 잡을 필요가 있다."
                )
            elif m.change_pct < 0 and m.volume_ratio < 0.8:
                interpretation = (
                    "가격은 내렸지만 거래량은 줄었다. 적극적인 매도보다 거래가 얇아진 가운데 가격이 밀렸을 가능성을 배제하기 어렵다."
                )
            else:
                interpretation = (
                    "가격 방향과 거래량이 엇갈리거나 평균 수준에 머물렀다. 이 경우 하루의 가격 변화만으로 추세를 판단하기는 이르다."
                )
        else:
            interpretation = "거래량 비교값이 없어 가격 변화의 성격을 거래 규모와 함께 해석하기 어렵다."
        paras.append(f"**해석** — {interpretation}")

        if m.close_position is not None:
            position = (
                "장중 고가 쪽에 가깝게 형성됐다" if m.close_position >= 0.7
                else "장중 저가 쪽에 가깝게 형성됐다" if m.close_position <= 0.3
                else "장중 고가와 저가의 중간대에서 형성됐다"
            )
            paras.append(
                f"**한계** — 종가는 {position}. 일봉의 시가·고가·저가만으로 장중 매매 주체를 구분할 수 없고, "
                "수집되지 않은 공시나 뉴스가 있을 수 있다."
            )
        else:
            paras.append(
                "**한계** — 일봉의 종가와 거래량만으로 매매 주체를 구분할 수 없고, 수집되지 않은 공시나 뉴스가 있을 수 있다."
            )
        return "\n\n".join(paras)

    # ------------------------------------------------------------------ #
    def pattern_diagnosis(self) -> str:
        top = self.patterns[:4]
        if not top:
            return "계산 지표에서 뚜렷한 패턴이 감지되지 않았다. 이는 특이 움직임이 없다는 뜻이 아니라, 기준선 안에 머물렀다는 뜻이다."
        blocks: list[str] = []
        for pattern in top:
            blocks.append(
                f"### {pattern.label}\n"
                f"- **해석** — {pattern.interpretation}\n"
                f"- **한계** — {pattern.limitation}\n"
                f"- **확인 조건** — {pattern.confirmation}"
            )
        return "\n\n".join(blocks)

    # ------------------------------------------------------------------ #
    def scenarios(self) -> str:
        m = self.m
        levels: list[str] = []
        if m.ma20 is not None:
            levels.append(f"20일선 {m.ma20:,.0f}원")
        if m.high_60d is not None:
            levels.append(f"60일 고점 {m.high_60d:,.0f}원")
        if m.low_60d is not None:
            levels.append(f"60일 저점 {m.low_60d:,.0f}원")
        level_text = ", ".join(levels) if levels else "비교 가능한 가격 기준선"
        paras = [f"기준선은 {level_text}이다. 아래 조건은 예측이 아니라, 다음 거래일의 데이터를 어떤 기준으로 해석할지 정한 것이다."]

        if m.ma20 is not None:
            if m.close is not None and m.close >= m.ma20:
                paras.append(
                    f"**이어지는 흐름** — 종가가 20일선 {m.ma20:,.0f}원 위를 유지하고 거래량이 20일 평균의 1.2배 이상이면, "
                    "현재의 가격 위치가 단기 참여로 이어지는지 확인할 수 있다."
                )
            else:
                paras.append(
                    f"**반등 시도** — 종가가 20일선 {m.ma20:,.0f}원 위로 다시 올라서고 거래량이 동반되면, "
                    "약세 흐름이 완화되는지 판단할 수 있다."
                )
        if m.low_60d is not None:
            paras.append(
                f"**하방 확대** — 종가가 60일 저점 {m.low_60d:,.0f}원 아래로 내려가면, 기존 지지선이 무너졌는지 점검해야 한다. "
                "이 경우 거래량이 줄어드는지도 함께 본다."
            )
        if m.high_60d is not None:
            paras.append(
                f"**상방 확장** — 종가가 60일 고점 {m.high_60d:,.0f}원을 넘어서면, 돌파에 거래량이 실렸는지가 핵심이다. "
                "거래량 없는 돌파는 되돌림 가능성을 함께 열어둔다."
            )
        paras.append(
            "**중립 구간** — 위 기준선 사이에서 종가가 머물고 거래량이 평균 수준으로 줄면, "
            "이번 움직임이 하루성 이벤트였는지 다음 날 확인할 수 있다."
        )
        return "\n\n".join(paras)

    # ------------------------------------------------------------------ #
    def counter_analysis(self) -> str:
        paras = [
            "**반대 해석 1 — 업종 전체의 움직임** — 같은 날 동종 업종이나 시장 지수가 크게 움직였다면, "
            "개별 종목의 재료보다 시장 요인이 가격을 밀었을 수 있다. 업종 지수와의 상대 비교가 없으면 이 가능성을 배제하기 어렵다.",
            "**반대 해석 2 — 이미 반영된 재료** — 확인된 뉴스·공시가 변동일 이전에 이미 시장에 알려졌다면, "
            "그 자료를 당일 변동의 원인으로 보기 어렵다. 발표 시점과 가격 반영 시점은 다를 수 있다.",
            "**반대 해석 3 — 수급의 성격** — 거래량 증가는 매수와 매도 어느 쪽에도 발생한다. "
            "외국인·기관 순매수 데이터가 없거나 장중 데이터가 없으면, 누가 주도했는지 구분할 수 없다.",
        ]
        if self.m.amount_ratio is not None and self.m.volume_ratio is not None:
            if abs(self.m.amount_ratio - self.m.volume_ratio) > 0.5:
                paras.append(
                    "**데이터 불일치 가능성** — 거래량 배수와 거래대금 배수가 크게 다르다. "
                    "가격대가 다른 주문이 섞였거나, 거래대금 집계 범위가 거래량과 다를 수 있다."
                )
        paras.append(
            "**한계** — 20일 평균은 최근 20거래일만 반영하므로 그 이전의 구조 변화를 놓칠 수 있다. "
            "또한 수집되지 않은 공시·뉴스·장중 공시는 분석 범위 밖이다."
        )
        return "\n\n".join(paras)

    # ------------------------------------------------------------------ #
    def source_section(self) -> str:
        lines: list[str] = []
        if self.filtered.cause_news:
            lines.append("### 변동일과 가까운 뉴스")
            for item in self.filtered.cause_news[:3]:
                lines.append(self._news_bullet(item))
        if self.filtered.cause_disclosures:
            lines.append("### 직접 관련 공시")
            lines.append(f"{self.name}와 직접 연결되는 공시는 아래와 같다.")
            lines.append("| 공시 | 발표일 | 요약 |")
            lines.append("|---|---|---|")
            for item in self.filtered.cause_disclosures[:5]:
                title = item.title or item.report_name or "공시"
                date = parse_date(item.published_at) or "-"
                summary = (item.summary or "")[:70]
                lines.append(f"| {title} | {date} | {summary} |")
        if not self.filtered.cause_news and not self.filtered.cause_disclosures:
            lines.append(
                "변동일 ±3일 안에서 이 종목을 직접 언급한 뉴스나 공시를 확인하지 못했다. "
                "아래 배경 자료는 시점이 떨어져 있어 원인으로 단정하지 않는다."
            )
        if self.filtered.background_news:
            lines.append("### 배경 자료")
            for item in self.filtered.background_news[:3]:
                lines.append(self._news_bullet(item, include_summary=False))
        return "\n\n".join(lines)

    def background_section(self) -> str:
        lines = ["변동일 이전에 공개된 배경 자료다. 원인 후보가 아니라 맥락으로만 참고해야 한다."]
        for item in self.filtered.background_news[:5]:
            lines.append(self._news_bullet(item, include_summary=False))
        return "\n".join(lines)

    def _news_bullet(self, item, include_summary: bool = True) -> str:
        title = (item.title or "").strip() or "제목 없는 뉴스"
        source = (item.source or "뉴스").strip()
        date = parse_date(item.published_at) or "-"
        days = None
        if self.event.event_date and date != "-":
            try:
                from datetime import datetime

                days = abs(
                    (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(self.event.event_date[:10], "%Y-%m-%d")).days
                )
            except ValueError:
                days = None
        timing = f"변동일 기준 {days}일 차이" if days is not None else "시점 확인 불가"
        body = f"- **{title}** — {source} ({date}), {timing}"
        if include_summary and item.summary:
            body += f"\n  - 확인된 내용: {item.summary[:160]}"
        if item.url:
            body += f"\n  - 출처: [원문 보기]({item.url})"
        return body

    # ------------------------------------------------------------------ #
    def future_data(self) -> str:
        points: list[str] = []
        if self.m.volume_ratio is not None:
            points.append("다음 거래일 거래량이 20일 평균을 웃도는지, 아니면 평균으로 되돌아오는지")
        if self.m.ma20 is not None:
            points.append(f"종가가 20일선 {self.m.ma20:,.0f}원 위를 유지하는지")
        if self.m.high_60d is not None:
            points.append(f"60일 고점 {self.m.high_60d:,.0f}원 돌파 시 거래량이 동반되는지")
        if self.m.low_60d is not None:
            points.append(f"60일 저점 {self.m.low_60d:,.0f}원이 지지되는지")
        if self.packet.market_data and self.packet.market_data.foreign_net_buy is None:
            points.append("외국인·기관 순매수 데이터가 확인되는지")
        if self.filtered.cause_disclosures:
            points.append("같은 사안의 후속 공시나 정정 공시가 나오는지")
        if self.filtered.cause_news:
            points.append("복수 매체가 같은 사실을 보도하는지, 보도 내용이 수정되는지")
        points.append("동종 업종 지수와 비교해 개별 종목만 움직인 것인지")
        return "\n".join(f"- {p}" for p in list(dict.fromkeys(points))[:7])

    @property
    def date_ko(self) -> str:
        return format_korean_date(self.event.event_date, "해당 거래일")


def direction_word(pct: float | None) -> str:
    if pct is None:
        return "변동"
    return "상승" if pct > 0 else "하락" if pct < 0 else "보합"


def _fmt_signed_pct(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "변동률 확인 불가"


def _fmt_abs_pct(value: float | None) -> str:
    return f"{abs(value):.2f}%" if value is not None else "일정 폭"
