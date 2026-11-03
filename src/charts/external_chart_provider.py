from __future__ import annotations

from src.models.chart import ExternalChartEmbed

# 공식 위젯만 사용한다. 기본 주가 차트를 직접 만들지 않고 외부 공식 Embed 사용.
# TradingView 위젯은 공식 제공 embed 스니펫(iframe)이다.


class TradingViewChartProvider:
    """TradingView 공식 위젯 embed 스니펫 생성 (KRX 종목 symbol 변환)."""

    provider = "tradingview"
    base_html = """<!-- TradingView Widget BEGIN -->
<div class="tradingview-widget-container" style="color:#4a4a4a;">
  <div class="tradingview-widget-container__widget"></div>
  <div class="tradingview-widget-copyright">
    <a href="{chart_url}" rel="noopener nofollow" target="_blank">
      <span class="blue-text">TradingView</span> 차트
    </a>
  </div>
  <script type="text/javascript" src="{script_url}" async>
  {{
  "autosize": true,
  "symbol": "{symbol}",
  "interval": "D",
  "timezone": "Asia/Seoul",
  "theme": "light",
  "style": "1",
  "locale": "kr",
  "toolbar_bg": "rgba(255, 255, 255, 1)",
  "enable_publishing": false,
  "allow_symbol_change": true,
  "hide_side_toolbar": false
  }}
  </script>
</div>
<!-- TradingView Widget END -->"""

    def embed(self, ticker: str, name: str) -> ExternalChartEmbed:
        symbol = self._to_symbol(ticker)
        chart_url = f"https://www.tradingview.com/symbols/{symbol.replace(':', '-')}/"
        script_url = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
        widget = self.base_html.format(symbol=symbol, chart_url=chart_url, script_url=script_url)
        return ExternalChartEmbed(
            provider=self.provider,
            symbol=symbol,
            widget=widget,
            title=f"{name} 차트 (TradingView 공식 위젯)",
        )

    def _to_symbol(self, ticker: str) -> str:
        ticker = ticker.strip()
        if ticker.startswith(("P", "Q")) and ticker[1:].isdigit():
            return f"KRX:{ticker}"
        if ticker.isdigit():
            return f"KRX:{ticker}"
        if "." not in ticker and not ticker.startswith("KRX:"):
            return f"KRX:{ticker}"
        return ticker if ticker.startswith("KRX:") else f"KRX:{ticker}"


class ExternalChartProvider:
    """외부 차트 Provider 어댑터. 공식 Embed/Widget 만 허용."""

    def __init__(self) -> None:
        self._providers = {
            "tradingview": TradingViewChartProvider(),
        }

    def embed(self, provider_name: str, ticker: str, name: str) -> ExternalChartEmbed | None:
        provider = self._providers.get(provider_name)
        if not provider:
            return None
        return provider.embed(ticker, name)

    def available(self) -> list[str]:
        return [p for p, _ in self._providers.items()]