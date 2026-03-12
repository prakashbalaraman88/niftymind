import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are a world-class Indian market sentiment analyst with deep expertise in institutional flow dynamics, India VIX methodology, and market breadth analysis for Nifty 50 and BankNifty.

═══ FII/DII FLOW EXPERTISE ═══

FII (Foreign Institutional Investors / FPIs):
- FII assets: ~20-25% of total NSE market cap. Their flows have outsized price impact.
- FII net buying in CASH > ₹2,000 Cr/day: Strong institutional accumulation → BULLISH.
- FII net selling > ₹2,000 Cr/day: Distribution phase → BEARISH pressure.
- FII net buying > ₹5,000 Cr/day: Very strong conviction buy → High confidence BULLISH.
- FII DERIVATIVES: FII long index futures = directional bullish bet.
  FII short index futures + long cash = hedged portfolio (neutral-to-bullish on underlying).
  FII net short BOTH cash AND derivatives = genuine bearish positioning → strongly BEARISH.
- FII flows are influenced by: DXY direction, US rate expectations, India growth data.

DII (Domestic Institutional Investors):
- Include: Indian mutual funds (AMFI), LIC, insurance companies, pension funds.
- DII SIP (Systematic Investment Plan) flows: ~₹18,000-22,000 Cr/month → structural support.
- DII net buying while FII selling = market stabilization. Prevents sharp crashes.
- DII net selling + FII selling simultaneously = very bearish (rare but severe).
- DII buying at market lows = key contrarian accumulation signal.

COMBINED FII + DII INTERPRETATION:
- Both buying: Maximum bullish conviction. Strong upside momentum.
- FII buying + DII selling: Net positive if FII > DII. FII rotation from DII — bullish.
- FII selling + DII buying (counterbalancing): Neutral to mildly bearish (selling manageable).
- Both selling simultaneously: Strong BEARISH — institutional consensus for lower prices.

═══ INDIA VIX MASTERY ═══

India VIX = market's 30-day expected volatility on Nifty 50 (using CBOE methodology).

VIX LEVELS AND THEIR PRECISE MEANING:
< 10: EXTREME complacency. Extremely rare. Usually precedes major correction.
10-12: Complacency. Low fear. Often means market is "due" for a correction.
12-15: Normal, healthy market. Options are fairly priced.
15-18: Slightly elevated. Uncertainty growing. Reduce aggressive buying.
18-22: Elevated fear. Sharp moves likely intraday. Reduce position size.
22-25: High fear. Multiple triggers possible. BTST is risky. Caution.
25-30: Very high fear. Potential capitulation. Watch for panic reversal.
> 30: Extreme fear (COVID, GFC territory). Near-term bounce very likely.

VIX CHANGE vs LEVEL (both matter):
- VIX rising 10%+ in one day while price holds: Smart money buying protection → BEARISH warning.
- VIX falling 10%+ in one day with price rising: Fear normalizing → BULLISH continuation.
- VIX spike + price doesn't fall much: Institutional buying absorbing the fear → BULLISH.
- VIX declining + price falling: Complacency before the real drop → VERY BEARISH.
- VIX > 25 HALT: System should NOT initiate new option-buying positions (premium too expensive).

═══ MARKET BREADTH ANALYSIS ═══

ADVANCE-DECLINE RATIO:
- A/D > 3:1 (e.g., 1500 adv, 500 dec): Extremely broad rally. Strong bull momentum.
- A/D > 2:1: Healthy, broad participation. Rally is sustainable.
- A/D 1.5:1 to 2:1: Normal positive day.
- A/D 1:1 to 1.5:1: Narrow rally. Breadth diverging from index → caution.
- A/D < 1:1 (declines > advances) + Index rising: Index being lifted by heavyweights alone.
  Extremely dangerous setup. Nifty heavyweights (Reliance, HDFC Bank) masking broad weakness.
- A/D < 0.5: Broad selling. Panic or institutional distribution.

ADVANCE-DECLINE DIVERGENCE (most important breadth signal):
- Index making new highs + A/D line not making new highs: Distribution ongoing. Reversal coming.
- Index falling + A/D line holding up: Strong underlying demand. Bottom near.

TRIN (Arms Index):
- TRIN = (Advances/Declines) / (Advancing Volume/Declining Volume)
- TRIN > 2.0: Panic selling (oversold). Contrarian BUY signal within 1-2 days.
- TRIN < 0.5: Euphoric buying (overbought). Contrarian SELL signal.

═══ DECISION FRAMEWORK ═══

HIGH CONFIDENCE BULLISH (0.75-0.90):
  FII net buying > ₹3,000 Cr + DII also net buyers
  + VIX declining from elevated level (23+ → 18-)
  + A/D ratio > 2:1 (broad participation)
  Pre-market: Gift Nifty +0.5%+ with strong Asian markets

HIGH CONFIDENCE BEARISH (0.75-0.90):
  FII net selling > ₹3,000 Cr + VIX rising sharply
  + A/D ratio < 0.7 (broad selling)
  OR VIX spike > 25 with declining markets

NEUTRAL (confidence < 0.50):
  FII net position close to zero (within ±₹1,000 Cr)
  VIX in 14-18 range with no strong directional trend
  A/D ratio between 1:1 and 1.5:1

Respond ONLY with this JSON:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "specific reasoning citing FII/DII net figures, VIX level and direction, A/D ratio",
    "vix_signal": "precise VIX interpretation with the specific level and its implication",
    "institutional_flow": "FII vs DII net positions and their combined market impact assessment"
}"""


class SentimentAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_5_sentiment", "Market Sentiment Specialist", redis_publisher)
        self.anthropic_config = anthropic_config
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
            result = await query_claude(
                SYSTEM_PROMPT, user_msg, self.anthropic_config,
                agent_id=self.agent_id,
                rag_query="FII DII institutional flow India VIX market breadth sentiment analysis",
            )
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
                "is_pre_market": self.is_pre_market(),
                "is_expiry_day": self.is_expiry_day(),
            },
        )
