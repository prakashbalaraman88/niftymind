import sys
import os
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are an expert Indian market sentiment analyst specializing in Nifty 50 and BankNifty.

You analyze:
- FII (Foreign Institutional Investor) and DII (Domestic Institutional Investor) cash and derivatives activity
- India VIX behavior — rising VIX is bearish, falling VIX is bullish; VIX above 20 signals high fear
- Market breadth indicators — advance-decline ratio, % stocks above 50 DMA
- SGX Nifty as a pre-market indicator for gap direction
- Sector rotation patterns — money flowing into defensive vs cyclical sectors

Key thresholds:
- India VIX > 20: High fear, expect sharp moves
- India VIX < 12: Complacency, potential reversal
- FII net buyers > ₹2000 Cr: Strong institutional buying
- Advance-Decline > 2:1: Broad bullish breadth

Respond with JSON:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "vix_signal": "description of VIX interpretation",
    "institutional_flow": "FII/DII summary"
}"""


class SentimentAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_5_sentiment", "Market Sentiment Specialist", redis_publisher)
        self.anthropic_config = anthropic_config
        self._last_analysis_time = None
        self._analysis_interval = 300
        self._market_data = {
            "vix": None,
            "fii_net": None,
            "dii_net": None,
            "advance_decline": None,
            "sgx_nifty": None,
        }

    @property
    def subscribed_channels(self) -> list[str]:
        return ["ticks"]

    def should_run(self) -> bool:
        return self.is_market_hours() or self.is_pre_market()

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        symbol = data.get("symbol", "").upper()

        if "VIX" in symbol:
            self._market_data["vix"] = data.get("ltp")
        elif "SGX" in symbol or "SGXNIFTY" in symbol:
            self._market_data["sgx_nifty"] = data.get("ltp")

        now = datetime.now(IST)
        if (
            self._last_analysis_time
            and (now - self._last_analysis_time).total_seconds() < self._analysis_interval
        ):
            return None

        if self._market_data["vix"] is None:
            return None

        self._last_analysis_time = now
        return await self._run_analysis()

    async def _run_analysis(self) -> Signal | None:
        user_msg = f"""Analyze current Indian market sentiment:

India VIX: {self._market_data.get('vix', 'N/A')}
FII Net Activity: {self._market_data.get('fii_net', 'Data pending')}
DII Net Activity: {self._market_data.get('dii_net', 'Data pending')}
Advance-Decline Ratio: {self._market_data.get('advance_decline', 'Data pending')}
SGX Nifty: {self._market_data.get('sgx_nifty', 'N/A')}
Is Pre-Market: {self.is_pre_market()}
Is Expiry Day: {self.is_expiry_day()}
Current Time (IST): {datetime.now(IST).strftime('%H:%M')}

Provide your sentiment analysis as JSON."""

        try:
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.anthropic_config)
        except Exception as e:
            self.logger.error(f"Claude API error in sentiment analysis: {e}")
            return None

        direction = result.get("direction", "NEUTRAL")
        confidence = float(result.get("confidence", 0.3))
        reasoning = result.get("reasoning", "No reasoning provided")

        return self.create_signal(
            underlying="NIFTY",
            direction=direction,
            confidence=confidence,
            timeframe="INTRADAY",
            reasoning=reasoning,
            supporting_data={
                "vix": self._market_data.get("vix"),
                "fii_net": self._market_data.get("fii_net"),
                "dii_net": self._market_data.get("dii_net"),
                "vix_signal": result.get("vix_signal", ""),
                "institutional_flow": result.get("institutional_flow", ""),
                "is_pre_market": self.is_pre_market(),
                "is_expiry_day": self.is_expiry_day(),
            },
        )
