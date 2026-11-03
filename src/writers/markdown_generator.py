from __future__ import annotations

import re

from src.models.article import Article, ArticleSection
from src.models.chart import ExternalChartEmbed, GeneratedChart
from src.utils.logging import get_logger

logger = get_logger(__name__)

_DISCLAIMER = """---

> 본 문서는 공개된 데이터(주가, 뉴스, 공시 등)를 정리한 참고 자료입니다.
> 투자 판단과 그 결과에 대한 책임은 투자자 본인에게 있습니다.
> 특정 종목의 매수·매도를 권유하는 정보가 아닙니다."""


# 요구사항 12: 차트 앞뒤 설명
_CHART_INTRO_HEADLINE = "아래 차트를 통해 '무엇을 확인해야 하는지'와 '실제로 어떤 데이터가 드러났는지'를 설명한다."
_CHART_INTRO = {
    "price_volume": "아래 차트에서는 최근 주가 흐름과 함께 거래량이 어떻게 변했는지를 함께 확인할 수 있다. 가격 방향과 물량의 동반 움직임이 핵심이다.",
    "volume_ratio": "아래 차트는 최근 평균 대비 당일 거래량이 어느 수준인지를 보여준다. 평소보다 얼마나 많은 물량이 출회됐는지가 판단 포인트다.",
    "financial": "아래 차트는 최근 매출·영업이익 추이를 보여준다. 실적 개선·악화 흐름이 방향성과 맞물리는지가 핵심이다.",
}

_CHART_OUTRO = {
    "price_volume": "특히 거래량 증가가 평소 수준보다 크게 나타난 구간은 이번 가격 변동이 평소보다 높은 시장 관심 속에서 발생했음을 보여준다.",
    "volume_ratio": "거래량 비율이 평균을 크게 웃돈다면 이번 변동이 단발성 물량이 아니라 여러 참여자의 움직임에 따른 것임을 시사한다.",
    "financial": "실적 흐름이 개선됐다면 주가의 방향성 근거가 될 수 있지만, 개선의 지속 여부는 별도로 확인해야 한다.",
}


class MarkdownGenerator:
    """Article -> Markdown 변환. 출처 섹션과 차트, 면책 문구를 자동 포함."""

    def __init__(self, include_disclaimer: bool = True) -> None:
        self.include_disclaimer = include_disclaimer

    def to_markdown(
        self,
        article: Article,
        charts: list[GeneratedChart] | None = None,
        external_embeds: list[ExternalChartEmbed] | None = None,
    ) -> str:
        lines: list[str] = []
        lines.append(f"# {article.title}")
        if article.description:
            lines.append("")
            lines.append(f"> {article.description}")
        lines.append("")

        for section in article.sections:
            if section.heading:
                lines.append(f"## {section.heading}")
                lines.append("")
            for para in self._paragraphs(section.body):
                lines.append(para)
                lines.append("")

        if charts:
            lines.append("## 차트로 보는 데이터")
            lines.append("")
            lines.append("### 📉 차트에서 확인되는 흐름")
            lines.append("")
            lines.append(_CHART_INTRO_HEADLINE)
            lines.append("")
            for chart in charts:
                intro = _CHART_INTRO.get(chart.chart_type)
                if intro:
                    lines.append(intro)
                    lines.append("")
                lines.append(f"![{chart.caption or chart.title}]({chart.rel_url})")
                lines.append("")
                outro = _CHART_OUTRO.get(chart.chart_type)
                if outro:
                    lines.append(outro)
                    lines.append("")

        if external_embeds:
            lines.append("## 기본 주가 차트")
            lines.append("")
            for embed in external_embeds:
                lines.append(f'> {embed.title} (공식 위젯)')
                lines.append(embed.widget)
                lines.append("")

        if article.sources:
            lines.append("## 참고 자료")
            lines.append("")
            for src in article.sources:
                lines.append(f"- {src}")
            lines.append("")

        if self.include_disclaimer:
            lines.append(_DISCLAIMER)
        return "\n".join(lines)

    def _paragraphs(self, body: str) -> list[str]:
        parts = [p.strip() for p in re.split(r"\n\s*\n+", body) if p.strip()]
        if not parts:
            return [body.strip()] if body.strip() else []
        return parts


def render_section(md: str, heading: str | None) -> ArticleSection | None:
    if not md or not md.strip():
        return None
    return ArticleSection(heading=heading or "", body=md.strip())