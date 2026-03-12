import sys
import os
import asyncio
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are an expert financial news analyst specializing in Indian markets (Nifty 50, BankNifty, NSE).

You classify news and events by their potential market impact:

HIGH IMPACT events (flag avoid-trading windows):
- RBI monetary policy decisions
- Union Budget announcements
- US Federal Reserve decisions
- Major geopolitical events (wars, sanctions)
- Unexpected inflation data (CPI/WPI)
- Quarterly results of index heavyweights (Reliance, HDFC Bank, Infosys, TCS)

MEDIUM IMPACT events:
- FII/DII activity reports
- Corporate earnings (non-heavyweights)
- Government policy changes
- Global market events

LOW IMPACT events:
- Routine economic data
- Analyst opinions
- Minor corporate news

Rules:
- News that is "priced in" (widely expected) should be downgraded in impact
- Unexpected news or data deviations from consensus have higher impact
- Around high-impact events, recommend avoiding new positions

Respond with JSON:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "impact_level": "HIGH" | "MEDIUM" | "LOW",
    "avoid_trading": true | false,
    "avoid_window_minutes": 0,
    "classified_events": [{"event": "...", "impact": "...", "direction": "..."}]
}"""


class NewsAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_6_news", "News & Events Specialist", redis_publisher)
        self.anthropic_config = anthropic_config
        self._news_buffer: list[dict] = []
        self._last_analysis_time = None
        self._analysis_interval = 120
        self._avoid_trading_until = None

    @property
    def subscribed_channels(self) -> list[str]:
        return ["ticks"]

    def should_run(self) -> bool:
        return True

    def is_avoid_trading_window(self) -> bool:
        if self._avoid_trading_until is None:
            return False
        return datetime.now(IST) < self._avoid_trading_until

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        now = datetime.now(IST)
        if (
            self._last_analysis_time
            and (now - self._last_analysis_time).total_seconds() < self._analysis_interval
        ):
            return None

        self._last_analysis_time = now
        return await self._analyze_news()

    async def _analyze_news(self) -> Signal | None:
        now = datetime.now(IST)

        user_msg = f"""Analyze the current news environment for Indian markets.

Current time (IST): {now.strftime('%Y-%m-%d %H:%M')}
Day of week: {now.strftime('%A')}
Is Expiry Day: {self.is_expiry_day()}

Consider any known upcoming events for today and the current week.
Check for: RBI policy, Union Budget timing, US Fed decisions, major earnings, geopolitical events.

If there are no major events today, indicate LOW impact with NEUTRAL direction.

Provide your analysis as JSON."""

        try:
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.anthropic_config)
        except Exception as e:
            self.logger.error(f"Claude API error in news analysis: {e}")
            return None

        direction = result.get("direction", "NEUTRAL")
        confidence = float(result.get("confidence", 0.3))
        reasoning = result.get("reasoning", "No significant news events")
        impact_level = result.get("impact_level", "LOW")
        avoid_trading = result.get("avoid_trading", False)

        if avoid_trading:
            window = int(result.get("avoid_window_minutes", 30))
            self._avoid_trading_until = now + timedelta(minutes=window)
            self.logger.warning(
                f"AVOID TRADING window set for {window} minutes due to: {reasoning}"
            )

        return self.create_signal(
            underlying="NIFTY",
            direction=direction,
            confidence=confidence,
            timeframe="INTRADAY",
            reasoning=reasoning,
            supporting_data={
                "impact_level": impact_level,
                "avoid_trading": avoid_trading,
                "avoid_until": self._avoid_trading_until.isoformat() if self._avoid_trading_until else None,
                "classified_events": result.get("classified_events", []),
                "is_expiry_day": self.is_expiry_day(),
            },
        )
