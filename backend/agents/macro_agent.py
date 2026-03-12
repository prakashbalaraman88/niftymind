import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are an expert global macro analyst specializing in how international markets impact Indian equities (Nifty 50, BankNifty).

You analyze:
- US market indices (S&P 500, Nasdaq, Dow) — strong correlation with Nifty next-day open
- Crude oil prices — rising crude is bearish for India (import-dependent), especially BankNifty
- USD/INR exchange rate — weakening rupee signals FII outflows, bearish for equities
- US Dollar Index (DXY) — rising DXY is risk-off globally
- US 10Y Treasury yield — yields > 4.5% signal risk-off
- Gold prices — rising gold indicates risk-off sentiment
- Asian markets (Hang Seng, Nikkei) for intraday correlation
- Global risk-on vs risk-off signals

Key correlations:
- US markets up > 1%: Nifty likely to gap up 0.3-0.5%
- Crude above $90: Negative for Indian markets
- DXY rising sharply: FII selling pressure
- US 10Y yield > 4.5%: Risk-off globally

For BTST analysis (near market close):
- Weight overnight risks more heavily
- Consider theta decay on options positions
- Factor in next-day event calendar

Respond with JSON:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "gap_prediction": "description of expected gap",
    "key_global_factors": ["factor1", "factor2"],
    "risk_level": "LOW" | "MEDIUM" | "HIGH"
}"""


class MacroAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_7_macro", "Global Macro Specialist", redis_publisher)
        self.anthropic_config = anthropic_config
        self._last_analysis_time = None
        self._analysis_interval = 600
        self._global_data: dict = {}

    @property
    def subscribed_channels(self) -> list[str]:
        return ["global_macro"]

    def should_run(self) -> bool:
        return self.is_market_hours() or self.is_pre_market()

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        self._global_data = data

        now = datetime.now(IST)
        if (
            self._last_analysis_time
            and (now - self._last_analysis_time).total_seconds() < self._analysis_interval
        ):
            return None

        self._last_analysis_time = now

        is_eod = now.time() >= datetime.strptime("15:00", "%H:%M").time()
        timeframe = "BTST" if is_eod else "INTRADAY"

        return await self._run_analysis(timeframe)

    async def _run_analysis(self, timeframe: str) -> Signal | None:
        now = datetime.now(IST)
        d = self._global_data

        def _fmt(key: str) -> str:
            entry = d.get(key)
            if entry and isinstance(entry, dict):
                return f"{entry.get('price', 'N/A')} ({entry.get('change_pct', 0):+.2f}%)"
            return "N/A"

        user_msg = f"""Analyze global macro environment for Indian markets:

Current Time (IST): {now.strftime('%Y-%m-%d %H:%M')}
Analysis Timeframe: {timeframe}
Is Expiry Day: {self.is_expiry_day()}

Global Market Data:
- S&P 500 Futures: {_fmt('sp500_futures')}
- Nasdaq Futures: {_fmt('nasdaq_futures')}
- Dow Futures: {_fmt('dow_futures')}
- Crude Oil: {_fmt('crude_oil')}
- Gold: {_fmt('gold')}
- US Dollar Index (DXY): {_fmt('dxy')}
- US 10Y Yield: {_fmt('us_10y')}
- USD/INR: {_fmt('usd_inr')}
- Hang Seng: {_fmt('hang_seng')}
- Nikkei 225: {_fmt('nikkei')}

{'This is an EOD analysis for BTST positioning. Focus on overnight risk and next-day gap prediction.' if timeframe == 'BTST' else 'Focus on intraday macro correlation.'}

Provide your macro analysis as JSON."""

        try:
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.anthropic_config)
        except Exception as e:
            self.logger.error(f"Claude API error in macro analysis: {e}")
            return None

        direction = result.get("direction", "NEUTRAL")
        confidence = float(result.get("confidence", 0.3))
        reasoning = result.get("reasoning", "No reasoning provided")

        sp500 = d.get("sp500_futures", {})
        crude = d.get("crude_oil", {})
        usd_inr = d.get("usd_inr", {})
        dxy = d.get("dxy", {})
        us_10y = d.get("us_10y", {})

        return self.create_signal(
            underlying="NIFTY",
            direction=direction,
            confidence=confidence,
            timeframe=timeframe,
            reasoning=reasoning,
            supporting_data={
                "gap_prediction": result.get("gap_prediction", ""),
                "key_global_factors": result.get("key_global_factors", []),
                "risk_level": result.get("risk_level", "MEDIUM"),
                "sp500_change_pct": sp500.get("change_pct") if isinstance(sp500, dict) else None,
                "crude_oil_price": crude.get("price") if isinstance(crude, dict) else None,
                "usd_inr_price": usd_inr.get("price") if isinstance(usd_inr, dict) else None,
                "dxy_price": dxy.get("price") if isinstance(dxy, dict) else None,
                "dxy_change_pct": dxy.get("change_pct") if isinstance(dxy, dict) else None,
                "us_10y_yield": us_10y.get("price") if isinstance(us_10y, dict) else None,
                "is_expiry_day": self.is_expiry_day(),
            },
        )
