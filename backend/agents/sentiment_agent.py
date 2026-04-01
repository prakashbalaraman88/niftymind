import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are a world-class Indian market sentiment analyst specializing in Nifty 50 and BankNifty with deep expertise in institutional flow analysis.

## Institutional Flow Analysis

### FII (Foreign Institutional Investors)
- **Index Futures Positioning:** Net long/short contracts and daily change. FII net long >20k contracts = strong bullish. Net short >20k = bearish.
- **Index Options Positioning:**
  - Net call writing by FII = bearish (they're selling upside)
  - Net put writing by FII = bullish (they're selling downside)
  - Long-short ratio > 1.5 = bullish positioning, < 0.8 = bearish
- **Cash Segment:** FII net > ₹2000 Cr = strong institutional buying. FII net < -₹2000 Cr = aggressive selling.
- **Derivatives vs Cash divergence:** FII buying in cash but adding shorts in derivatives = hedged/cautious. Both aligned = high conviction.

### DII (Domestic Institutional Investors)
- DII typically provide counter-support when FII sells
- DII buying > ₹3000 Cr on a day when FII is selling = strong floor
- Sector allocation shifts: Money moving from IT/Pharma (defensive) → Banks/Auto (cyclical) = risk-on rotation
- DII selling is rare — when DII sells alongside FII, it signals genuine distribution

### India VIX Analysis (Critical)
- **VIX < 12:** Extreme complacency. Options are cheap. Expect volatility expansion (breakout imminent). Buy slightly OTM options.
- **VIX 12-15:** Normal, low volatility. Standard operations.
- **VIX 15-18:** Slightly elevated. Normal for event weeks (RBI, earnings).
- **VIX 18-22:** High fear. Prefer ATM strikes. Reduce position sizes.
- **VIX 22-28:** Very high fear. Scalps only. Use tight stops.
- **VIX > 28:** Extreme fear. Trading paused (except hedging).
- **VIX Term Structure:**
  - Near-month VIX > Next-month (backwardation) = extreme near-term fear, often near bottoms
  - Near-month VIX < Next-month (contango) = normal, steady market
  - Rapid VIX crush (>10% drop in a day) = post-event relief, options sellers profit

### Market Breadth Internals
- **Advance-Decline Ratio:**
  - A/D > 3:1 = breadth thrust, very bullish, trend day likely
  - A/D > 2:1 = broad bullish breadth
  - A/D 1:1 to 2:1 = mixed, index-driven (few heavyweight movers)
  - A/D < 0.5:1 = broad sell-off, very bearish
- **% Stocks Above Key MAs:**
  - >80% above 20 DMA = overbought breadth, pullback risk
  - <20% above 20 DMA = oversold breadth, bounce candidate
  - >60% above 200 DMA = healthy long-term trend
  - <40% above 200 DMA = structural weakness
- **New Highs vs New Lows:**
  - NH > 50 with NL < 5 = strong bull trend
  - NL > 50 with NH < 5 = strong bear trend
  - Both elevated = churning market, sector rotation
- **Advance-Decline Line vs Nifty:**
  - A/D line making new high with Nifty = healthy trend confirmation
  - A/D line diverging (not confirming Nifty high) = breadth deterioration, top forming

### Retail vs Institutional Flow
- Retail traders are net option BUYERS (long gamma, short theta)
- Institutional traders are net option SELLERS (short gamma, long theta)
- When retail long/short ratio is extreme (>2.0 or <0.5), the opposite move is likely (contrarian signal)
- Client-level OI data from NSE shows: Clients (retail) vs Proprietary vs FII positioning

Respond with a JSON object:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "vix_signal": "description of VIX implication",
    "institutional_flow": "FII/DII flow summary and what it means",
    "breadth_quality": "STRONG" | "MODERATE" | "WEAK" | "DETERIORATING",
    "vix_regime": "LOW" | "NORMAL" | "ELEVATED" | "HIGH" | "EXTREME"
}"""


class SentimentAgent(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None):
        super().__init__("agent_5_sentiment", "Market Sentiment Specialist", redis_publisher)
        self.llm_config = llm_config
        self._last_analysis_time = None
        self._analysis_interval = 300
        self._fii_dii_data: dict | None = None
        self._breadth_data: dict | None = None
        self._vix_data: dict | None = None

    @property
    def subscribed_channels(self) -> list[str]:
        return ["fii_dii", "market_breadth"]

    def should_run(self) -> bool:
        return self.is_market_hours() or self.is_pre_market()

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        if "fii_dii" in channel:
            self._fii_dii_data = data
            return await self._try_analysis()
        elif "market_breadth" in channel:
            if data.get("_merge_key") == "vix_data":
                self._vix_data = {
                    "ltp": data.get("india_vix"),
                    "change_pct": data.get("vix_change"),
                }
            else:
                self._breadth_data = data
            return await self._try_analysis()

        return None

    async def _try_analysis(self) -> Signal | None:
        now = datetime.now(IST)
        if (
            self._last_analysis_time
            and (now - self._last_analysis_time).total_seconds() < self._analysis_interval
        ):
            return None

        if self._fii_dii_data is None and self._breadth_data is None:
            return None

        self._last_analysis_time = now
        return await self._run_analysis()

    async def _run_analysis(self) -> Signal | None:
        fii = self._fii_dii_data or {}
        breadth = self._breadth_data or {}
        vix = self._vix_data or {}

        user_msg = f"""Analyze current Indian market sentiment:

India VIX: {vix.get('ltp', 'N/A')} (Change: {vix.get('change_pct', 'N/A')}%)

FII Activity:
- FII Buy Value: ₹{fii.get('fii_buy', 'N/A')} Cr
- FII Sell Value: ₹{fii.get('fii_sell', 'N/A')} Cr
- FII Net: ₹{fii.get('fii_net', 'N/A')} Cr

DII Activity:
- DII Buy Value: ₹{fii.get('dii_buy', 'N/A')} Cr
- DII Sell Value: ₹{fii.get('dii_sell', 'N/A')} Cr
- DII Net: ₹{fii.get('dii_net', 'N/A')} Cr

Market Breadth:
- Advances: {breadth.get('advances', 'N/A')}
- Declines: {breadth.get('declines', 'N/A')}
- Unchanged: {breadth.get('unchanged', 'N/A')}
- A/D Ratio: {breadth.get('ad_ratio', 'N/A')}

Is Pre-Market: {self.is_pre_market()}
Is Expiry Day: {self.is_expiry_day()}
Current Time (IST): {datetime.now(IST).strftime('%H:%M')}

Provide your sentiment analysis as JSON."""

        try:
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.llm_config)
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
                "vix": vix.get("ltp"),
                "vix_change_pct": vix.get("change_pct"),
                "fii_net": fii.get("fii_net"),
                "dii_net": fii.get("dii_net"),
                "advances": breadth.get("advances"),
                "declines": breadth.get("declines"),
                "ad_ratio": breadth.get("ad_ratio"),
                "vix_signal": result.get("vix_signal", ""),
                "institutional_flow": result.get("institutional_flow", ""),
                "breadth_quality": result.get("breadth_quality", ""),
                "vix_regime": result.get("vix_regime", ""),
                "is_pre_market": self.is_pre_market(),
                "is_expiry_day": self.is_expiry_day(),
            },
        )
