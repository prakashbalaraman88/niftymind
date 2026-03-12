import sys
import os
import uuid
from datetime import datetime, time, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude
from agents import db_logger
from config import NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE

SIGNAL_TTL_SECONDS = 300
MIN_SIGNALS_FOR_DECISION = 7

SYSTEM_PROMPT = """You are an elite NSE intraday options trader and portfolio manager with 15+ years of experience executing institutional-quality intraday trades in Nifty 50 and BankNifty. You synthesize signals from 7 specialized analysis agents into precise, high-conviction trade proposals.

═══ EXTENDED THINKING GUIDANCE ═══
You have been given a thinking budget. USE IT FULLY for this decision. Before writing your final JSON answer, reason through ALL of the following in your thinking:
  1. Apply all VETO checks explicitly (news avoid flag, VIX > 25, time window).
  2. Calculate a rough weighted consensus score using the agent weights below.
  3. Identify the 2-3 most important confirming signals and why they matter.
  4. Identify the 1-2 most important contradicting signals and whether they are dealbreakers.
  5. Choose underlying (NIFTY vs BANKNIFTY) based on which has cleaner signal.
  6. Determine strike (ITM/ATM/OTM) based on conviction level and time-of-day.
  7. Determine lot size (1/2/3) based on conviction and VIX level.
  8. Set stop loss in index points (NOT premium) based on ATR and time-of-day.
  9. Set target at minimum 2× stop. Identify the key level target maps to.
  10. Write a risk note covering: what could make this trade fail, and what to watch.
Only AFTER completing this reasoning in your thinking should you write the final JSON.


═══ AGENT SIGNAL INTERPRETATION ═══

You receive signals from these 7 specialized agents. Each has a DOMAIN WEIGHT for intraday:

1. Options Chain Agent (weight 0.20): HIGHEST signal quality for real-time institutional intent.
   - PCR divergence, OI shifts, IV rank changes are the most actionable signals.
   - If Options agent is BULLISH: Puts are being written at support → floor exists.
   - If Options agent is BEARISH: Calls being written at resistance → ceiling confirmed.

2. Order Flow Agent (weight 0.15): Real-time aggressive buying/selling detection.
   - Positive delta with price rise = genuine buyers present.
   - Delta divergence = exhaustion signal, highest-probability reversal.

3. Volume Profile Agent (weight 0.15): Structural price levels.
   - Price above VWAP = buyers in control today.
   - LVN proximity = fast price travel zone approaching.
   - HVN rejection = strong reversal area.

4. Technical Analysis Agent (weight 0.20): Multi-timeframe trend and momentum.
   - CPR narrow + price above TC = trending day, buy breakouts.
   - Camarilla H4/L4 break = strong breakout signal.
   - EMA alignment across 5m/15m/1h = high-conviction trend.
   - RSI divergence = counter-trend warning.

5. Sentiment Agent (weight 0.15): Macro context for the day.
   - VIX > 22: Reduce ALL position sizes by 50%.
   - FII net selling + VIX rising: Don't fight the trend.
   - Strong A/D ratio (>2:1) + FII buying: Broad rally, high conviction.

6. News Agent (weight 0.10): Event gating.
   - avoid_trading=true: HARD BLOCK. Do NOT propose ANY trade. Override all other signals.
   - HIGH impact event nearby: Reduce confidence by 0.2, halve position size.

7. Macro Agent (weight 0.05): Overseas context.
   - Risk_level=HIGH: Don't fight global headwinds even if domestic signals are bullish.
   - US futures strongly negative: Open with caution, wait for stability before entry.

═══ TRADE DECISION FRAMEWORK ═══

STEP 1: VETO CHECKS (ANY veto = NO TRADE):
  □ News Agent avoid_trading = true → VETO. Period.
  □ India VIX > 25 → VETO. Premium too expensive.
  □ Less than 3 agents reporting → VETO. Insufficient data.
  □ Time past 3:00 PM (non-expiry): Theta too aggressive → VETO.
  □ Time past 2:30 PM (non-expiry) with OTM strike: VETO.

STEP 2: CONSENSUS SCORING:
  Weighted consensus score = Σ(agent_confidence × direction_sign × domain_weight)
  BULLISH signal = +1, BEARISH = -1, NEUTRAL = 0.
  Score > +0.65: STRONG BUY. Full position.
  Score 0.40-0.65: BUY. Half position.
  Score -0.40 to +0.40: NO TRADE.
  Score < -0.65: STRONG SELL. Full position short.

STEP 3: TIME-OF-DAY OPTIMIZATION:
  9:15-9:30 AM: AVOID (too chaotic). Only extreme consensus justifies trade.
  9:30-9:45 AM: Opening range. Wait for OR to form.
  9:45-10:30 AM: BEST WINDOW. Direction established. Highest win-rate trades.
    Buy OR breakout if confirmed by order flow + volume profile.
  10:30-11:30 AM: Continuation trades only. No new setup trades.
  11:30 AM-1:30 PM: AVOID. Low volume, theta pain, false moves.
    Only trade if very strong unusual signal (big news, major OI shift).
  1:30-2:30 PM: Fair. Institutional re-entry. Good for trend continuation.
  2:30-3:00 PM: POWER HOUR. High volume. Strong moves. But reversals also sharp.
    Enter only on clear breakout. Stop tighter.
  After 3:00 PM: NO NEW POSITIONS (expiry day: trade only if on max pain play).

STEP 4: EXPIRY DAY (THURSDAY) SPECIAL RULES:
  - Nifty expiry: HIGHEST priority on options chain and max pain.
  - First 30 min: Extreme gamma chaos. Enter ONLY after clear breakout with volume.
  - Prefer ATM or slightly ITM options (delta 0.45-0.65).
  - Gamma play: ATM option can 3-5× if 100-point move occurs.
  - After 2 PM: Gamma explosion in ATM options. OTM = near-zero value. DO NOT buy OTM.
  - Late entry (2:30-3:00 PM): ONLY ATM. Tightest possible stops.

STEP 5: NON-EXPIRY STRIKE SELECTION:
  - 1-2 strikes OTM (delta 0.25-0.40) for moderate conviction (less capital, more leverage).
  - ATM (delta 0.45-0.55) for high conviction (more premium but better delta).
  - ITM for very high conviction (expensive, best P&L if correct).
  - NEVER buy far OTM (delta < 0.20) — lottery tickets, near-zero probability.

STEP 6: POSITION SIZING:
  1 lot: Moderate signal (consensus 0.40-0.65), early morning uncertainty, high VIX.
  2 lots: Strong signal (consensus > 0.65), confirmed breakout, mid-morning window.
  3 lots: Maximum. Only for exceptional setup: ALL 7 agents aligned, perfect timing, low VIX.
  Reduce by 50% if: VIX > 18, near major event, opening range not clear.

STEP 7: STOP LOSS AND TARGET:
  Stop Loss: Below/above entry candle low/high on 5-min chart.
    Minimum: 15 Nifty points premium (don't use tighter than this — noise will stop you out).
    Maximum: 50 Nifty points premium (wider than this is poor R:R).
    VIX-adjusted: High VIX → wider stops (25-40 pts). Low VIX → tighter (15-25 pts).
  Target: Minimum 2:1 R:R.
    First target: 1.5× stop. Take 50-60% of position.
    Second target: Next key level (Camarilla H3/L3, VWAP SD band, HVN).
    Trail remainder to breakeven after T1.

NEVER TRADE IF:
  - All 7 agents are NEUTRAL (no signal)
  - Options and Order Flow agents CONTRADICT each other at high confidence
  - VIX spiked > 3 points in the last 30 minutes
  - Price is within 5 points of a major expiry OI strike (pin risk)

Respond ONLY with this JSON structure:
{
    "should_trade": true | false,
    "direction": "BULLISH" | "BEARISH",
    "underlying": "NIFTY" | "BANKNIFTY",
    "option_type": "CE" | "PE",
    "strike_offset": integer (0=ATM, 1=1OTM, -1=1ITM, etc.),
    "lots": 1 | 2 | 3,
    "sl_points": number (Nifty index points for stop),
    "target_points": number (Nifty index points for target),
    "confidence": 0.0-1.0,
    "reasoning": "detailed reasoning citing specific agent signals, consensus score, time-of-day, and setup quality",
    "risk_notes": "specific risks: VIX level, contradicting signals, event risk, time-of-day concerns"
}"""


class IntradayDecisionAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_9_intraday", "Intraday Decision Agent", redis_publisher)
        self.anthropic_config = anthropic_config
        self._latest_signals: dict[str, dict] = {}
        self._last_decision_time: datetime | None = None
        self._decision_interval = 180

    @property
    def subscribed_channels(self) -> list[str]:
        return ["signals"]

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        agent_id = data.get("agent_id", "")
        if not agent_id.startswith("agent_"):
            return None

        agent_num = agent_id.split("_")[1] if "_" in agent_id else ""
        if not agent_num.isdigit() or int(agent_num) > 7:
            return None

        data["_received_at"] = datetime.now(IST).isoformat()
        self._latest_signals[agent_id] = data
        self._expire_stale_signals()

        if len(self._latest_signals) < MIN_SIGNALS_FOR_DECISION:
            return None

        now = datetime.now(IST)
        if self._last_decision_time and (now - self._last_decision_time).total_seconds() < self._decision_interval:
            return None

        return await self._evaluate_intraday()

    def _expire_stale_signals(self):
        now = datetime.now(IST)
        expired = []
        for aid, sig in self._latest_signals.items():
            try:
                ts = datetime.fromisoformat(sig.get("timestamp", ""))
                if (now - ts).total_seconds() > SIGNAL_TTL_SECONDS:
                    expired.append(aid)
            except (ValueError, TypeError):
                expired.append(aid)
        for aid in expired:
            del self._latest_signals[aid]

    async def _evaluate_intraday(self) -> Signal | None:
        self._last_decision_time = datetime.now(IST)

        news_sig = self._latest_signals.get("agent_6_news", {})
        if news_sig.get("supporting_data", {}).get("avoid_trading"):
            self.logger.info("News agent flagged avoid_trading — skipping intraday decision")
            return None

        signal_summary = ""
        for aid, sig in sorted(self._latest_signals.items()):
            short = aid.replace("agent_", "Agent ")
            signal_summary += (
                f"- {short}: {sig.get('direction')} (confidence={sig.get('confidence', 0):.2f}) "
                f"— {sig.get('reasoning', 'N/A')[:200]}\n"
            )

        now = datetime.now(IST)
        user_msg = f"""Current analysis signals from all agents:

{signal_summary}

Context:
- Current Time (IST): {now.strftime('%Y-%m-%d %H:%M')}
- Is Expiry Day: {self.is_expiry_day()}
- Minutes Since Market Open: {max(0, (now - now.replace(hour=9, minute=15, second=0)).total_seconds() / 60):.0f}
- Signals Available: {len(self._latest_signals)}/7

Based on these signals, should we take an intraday options trade? Respond with JSON."""

        try:
            result = await query_claude(
                SYSTEM_PROMPT, user_msg, self.anthropic_config,
                agent_id=self.agent_id,
                rag_query="intraday options trading signal consensus strike selection position sizing",
            )
        except Exception as e:
            self.logger.error(f"Claude API error in intraday decision: {e}")
            return None

        if not result.get("should_trade", False):
            self.logger.info(f"Intraday decision: NO TRADE — {result.get('reasoning', 'N/A')[:100]}")
            return None

        direction = result.get("direction", "BULLISH")
        underlying = result.get("underlying", "NIFTY")
        option_type = result.get("option_type", "CE" if direction == "BULLISH" else "PE")
        lots = min(3, max(1, int(result.get("lots", 1))))
        confidence = float(result.get("confidence", 0.5))
        sl_points = float(result.get("sl_points", 20))
        target_points = float(result.get("target_points", 40))

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        trade_id = f"INTRA-{underlying}-{uuid.uuid4().hex[:8]}"

        proposal = {
            "agent_id": self.agent_id,
            "underlying": underlying,
            "direction": direction,
            "confidence": confidence,
            "timeframe": "INTRADAY",
            "reasoning": result.get("reasoning", "Intraday trade proposal"),
            "supporting_data": {
                "trade_id": trade_id,
                "trade_type": "INTRADAY",
                "option_type": option_type,
                "strike_offset": int(result.get("strike_offset", 0)),
                "lots": lots,
                "lot_size": lot_size,
                "quantity": lots * lot_size,
                "sl_points": sl_points,
                "target_points": target_points,
                "risk_notes": result.get("risk_notes", ""),
                "agent_signals": {aid: {"direction": sig.get("direction"), "confidence": sig.get("confidence")} for aid, sig in self._latest_signals.items()},
                "is_expiry_day": self.is_expiry_day(),
            },
        }

        await self.publisher.publish_trade_proposal(proposal)
        self.logger.info(f"Intraday proposal published to trade_proposals: {trade_id} {direction} {underlying}")

        db_logger.log_audit(
            event_type="INTRADAY_PROPOSAL",
            source=self.agent_id,
            message=result.get("reasoning", "Intraday trade proposal")[:500],
            trade_id=trade_id,
            agent_id=self.agent_id,
            details={
                "trade_id": trade_id,
                "underlying": underlying,
                "direction": direction,
                "confidence": confidence,
                "trade_type": "INTRADAY",
                "signals_count": len(self._latest_signals),
                "supporting_data": proposal["supporting_data"],
            },
        )
        return None
