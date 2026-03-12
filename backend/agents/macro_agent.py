import sys
import os
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are an expert global macro analyst specializing in how international markets impact Indian equities (Nifty 50, BankNifty).

You analyze:
- US market indices (S&P 500, Nasdaq, Dow) — strong correlation with Nifty next-day open
- Crude oil prices — rising crude is bearish for India (import-dependent), especially BankNifty
- USD/INR exchange rate — weakening rupee signals FII outflows, bearish for equities
- Global risk-on vs risk-off signals — bond yields, VIX, gold prices
- Overnight gap prediction for Nifty based on global cues
- European markets and Asian markets (Hang Seng, Nikkei) for intraday correlation

Key correlations:
- US markets up > 1%: Nifty likely to gap up 0.3-0.5%
- Crude above $90: Negative for Indian markets
- DXY (dollar index) rising sharply: FII selling pressure
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
        self._global_data = {
            "sp500_futures": None,
            "nasdaq_futures": None,
            "crude_oil": None,
            "usd_inr": None,
            "gold": None,
            "us_10y": None,
            "dxy": None,
        }

    @property
    def subscribed_channels(self) -> list[str]:
        return ["ticks"]

    def should_run(self) -> bool:
        return True

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        symbol = data.get("symbol", "").upper()

        if "CRUDE" in symbol or "CL" in symbol:
            self._global_data["crude_oil"] = data.get("ltp")
        elif "USDINR" in symbol:
            self._global_data["usd_inr"] = data.get("ltp")
        elif "GOLD" in symbol or "GC" in symbol:
            self._global_data["gold"] = data.get("ltp")

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

        user_msg = f"""Analyze global macro environment for Indian markets:

Current Time (IST): {now.strftime('%Y-%m-%d %H:%M')}
Analysis Timeframe: {timeframe}
Is Expiry Day: {self.is_expiry_day()}

Global Data:
- S&P 500 Futures: {self._global_data.get('sp500_futures', 'N/A')}
- Nasdaq Futures: {self._global_data.get('nasdaq_futures', 'N/A')}
- Crude Oil: {self._global_data.get('crude_oil', 'N/A')}
- USD/INR: {self._global_data.get('usd_inr', 'N/A')}
- Gold: {self._global_data.get('gold', 'N/A')}
- US 10Y Yield: {self._global_data.get('us_10y', 'N/A')}
- DXY (Dollar Index): {self._global_data.get('dxy', 'N/A')}

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
                "crude_oil": self._global_data.get("crude_oil"),
                "usd_inr": self._global_data.get("usd_inr"),
                "is_expiry_day": self.is_expiry_day(),
            },
        )
