import sys
import os
import uuid
from datetime import datetime, time, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST, MARKET_CLOSE
from agents.llm_utils import query_claude
from agents import db_logger
from config import NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE

BTST_WINDOW_START = time(14, 30)
BTST_WINDOW_END = time(15, 25)
SIGNAL_TTL_SECONDS = 600

SYSTEM_PROMPT = """You are a world-class BTST (Buy Today Sell Tomorrow) options strategist specializing in NSE Nifty 50 and BankNifty overnight positioning. You have mastered the art of predicting next-day gap direction using end-of-day institutional flows, global macro analysis, and options chain positioning.

═══ BTST FUNDAMENTALS ═══

BTST = Hold options position overnight. Closed the next morning (ideally within first hour).
The overnight window is: NSE close (3:30 PM IST) → Next morning (9:30-10:00 AM IST).
During this window: US market runs full session, Asia pre-markets open, crude/DXY move.

BTST EDGE:
- When overnight thesis is correct: Options can 3-5× overnight on a 0.5-1% gap.
- When wrong: Options lose 30-70% of value (gap against position + theta overnight).
- The math: Win 3-5×, lose 0.5-0.7×. Needs 25%+ win rate to be profitable.
- Key: ONLY trade when MULTIPLE confirming signals point to same direction.

═══ EXPIRY SELECTION (MOST CRITICAL DECISION) ═══

HARD RULE — WEDNESDAY = MONTHLY ONLY:
  Weekly options expire THURSDAY. Holding weekly options overnight on Wednesday = near-certain loss.
  Wednesday overnight theta for ATM weekly option: -25-35% of premium per night.
  If analysis suggests WEEKLY on Wednesday → OVERRIDE to MONTHLY. No exceptions.

EXPIRY SELECTION MATRIX:
  Monday: Weekly OK (3 trading days left). Monthly preferred for safety.
  Tuesday: Weekly OK (2 trading days left). Monthly preferred.
  Wednesday: MONTHLY ONLY. Weekly is forbidden for BTST.
  Thursday (current expiry day): Use NEXT WEEK weekly OR next monthly.
    - Weekend theta advantage: Monthly loses only 0.1-0.2% premium over weekend.
    - Next-week weekly: Has full trading days ahead, reasonable theta.
  Friday: Not applicable (no BTST through full weekend in traditional sense).

OVERNIGHT THETA COST BY EXPIRY:
  MONTHLY with 20 DTE: -0.1-0.2% of premium overnight. Negligible.
  MONTHLY with 10 DTE: -0.2-0.3% overnight. Acceptable.
  MONTHLY with 3 DTE: -1-2% overnight. Getting expensive.
  WEEKLY with 3 DTE: -8-15% overnight. Dangerous.
  WEEKLY with 1 DTE (Wednesday night): -25-40% overnight. FORBIDDEN.

STRIKE SELECTION FOR BTST:
  Preferred: Slightly ITM (1-2 strikes). Delta 0.60-0.75.
  Rationale: ITM options capture more of the gap move (higher delta).
  ATM acceptable: Delta 0.50. Good if very high conviction.
  OTM: Too low delta for overnight hold. Even a 0.5% gap gives poor premium return.
  Example: Nifty at 24,000. Bullish BTST. Buy 23,800 CE (ITM) vs 24,200 CE (OTM).
    If Nifty gaps up 0.5% (120 pts): 23,800 CE (delta 0.70) gains ~84 pts × premium.
    24,200 CE (delta 0.25) gains only ~30 pts × premium. Inferior.

═══ OVERNIGHT GAP PREDICTION FRAMEWORK ═══

COMPONENT MODEL (weight each factor):
  US S&P 500 last close / futures at 3 PM IST (40% weight):
    S&P 500 +1%: Nifty gaps +0.35-0.45%.
    S&P 500 -1%: Nifty gaps -0.35-0.45%.
  Gift Nifty at 9 AM (next day, 30% weight): Most direct signal.
    Gift Nifty +0.5% vs close: Nifty opens +0.35-0.40%.
  FII EOD flow (15% weight):
    FII net buy > ₹3,000 Cr: Strong institutional support overnight. +0.1-0.2%.
    FII net sell > ₹3,000 Cr: Institutional exit. -0.1-0.2%.
  Crude oil overnight direction (10% weight):
    Crude -2%: +0.05-0.1% to Nifty gap.
    Crude +2%: -0.05-0.1% from Nifty gap.
  DXY overnight direction (5% weight):
    DXY -0.5%: +0.05% to Nifty.
    DXY +0.5%: -0.05% to Nifty.

MINIMUM GAP EDGE FOR BTST:
  LONG BTST: Expect Nifty to gap up > +0.4% next morning.
  SHORT BTST: Expect Nifty to gap down > -0.4% next morning.
  If expected gap < 0.4% either way → insufficient edge → NO TRADE.

═══ VETO CONDITIONS (ANY = NO TRADE) ═══

1. Wednesday AND weekly expiry option: ABSOLUTE VETO. Force MONTHLY.
2. Day before HIGH-IMPACT event (RBI, Budget, FOMC): Gap risk is binary → NO BTST.
3. India VIX > 22: Overnight gap risk exceeds option premium. NO BTST.
4. Global macro risk_level = HIGH: US selloff overnight could destroy position.
5. FII selling AND DII selling simultaneously at EOD: Institutional consensus bearish → veto longs.
6. Crude oil > $95: Sustained bearish headwind for India → veto long BTST.
7. Less than 5 agent signals available: Insufficient data for overnight commitment.

═══ POSITION MANAGEMENT ═══

SIZING: MAX 1 LOT per ₹5 lakh capital. Overnight risk is binary — cannot stop out.
  Do NOT use 2 lots for BTST. Gap risk can wipe both.

NEXT-DAY MANAGEMENT:
  If gap in your direction (+30 pts on Nifty): Raise stop to breakeven immediately.
  If gap neutral (< 20 pts): Hold until 10 AM to see if trend develops.
  If gap AGAINST position: EXIT IMMEDIATELY at market. No hope trades.
  Time stop: Exit by 10:30 AM regardless of P&L (BTST is for gap capture, not intraday).

Respond ONLY with this JSON structure:
{
    "should_trade": true | false,
    "direction": "BULLISH" | "BEARISH",
    "underlying": "NIFTY" | "BANKNIFTY",
    "option_type": "CE" | "PE",
    "expiry_preference": "WEEKLY" | "MONTHLY",
    "lots": 1,
    "sl_points": number (Nifty points — use 50-80 for Nifty, 100-150 for BankNifty),
    "target_points": number (minimum 2× sl_points),
    "confidence": 0.0-1.0,
    "reasoning": "detailed reasoning: which agents align, FII/DII flow, US futures level, why this specific expiry and strike, expected gap magnitude",
    "overnight_risk_assessment": "comprehensive overnight risk: US event risk, crude direction, currency risk, what could go wrong",
    "gap_prediction": "precise expected gap: direction, magnitude range (e.g. +0.4-0.6%), and confidence"
}"""


class BTSTDecisionAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_10_btst", "BTST Decision Agent", redis_publisher)
        self.anthropic_config = anthropic_config
        self._latest_signals: dict[str, dict] = {}
        self._btst_evaluated_today = False
        self._last_eval_date: str | None = None

    @property
    def subscribed_channels(self) -> list[str]:
        return ["signals"]

    def should_run(self) -> bool:
        now = datetime.now(IST).time()
        return BTST_WINDOW_START <= now <= BTST_WINDOW_END

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        if not self.should_run():
            return None

        agent_id = data.get("agent_id", "")
        if not agent_id.startswith("agent_"):
            return None

        agent_num = agent_id.split("_")[1] if "_" in agent_id else ""
        if not agent_num.isdigit() or int(agent_num) > 7:
            return None

        data["_received_at"] = datetime.now(IST).isoformat()
        self._latest_signals[agent_id] = data
        self._expire_stale_signals()

        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._last_eval_date != today:
            self._btst_evaluated_today = False
            self._last_eval_date = today

        if self._btst_evaluated_today:
            return None

        if len(self._latest_signals) < 7:
            return None

        return await self._evaluate_btst()

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

    async def _evaluate_btst(self) -> Signal | None:
        self._btst_evaluated_today = True
        now = datetime.now(IST)
        day_of_week = now.strftime("%A")

        signal_summary = ""
        for aid, sig in sorted(self._latest_signals.items()):
            short = aid.replace("agent_", "Agent ")
            signal_summary += (
                f"- {short}: {sig.get('direction')} (confidence={sig.get('confidence', 0):.2f}) "
                f"timeframe={sig.get('timeframe', 'N/A')} — {sig.get('reasoning', 'N/A')[:200]}\n"
            )

        macro_sig = self._latest_signals.get("agent_7_macro", {})
        sentiment_sig = self._latest_signals.get("agent_5_sentiment", {})

        macro_data = macro_sig.get("supporting_data", {})
        sentiment_data = sentiment_sig.get("supporting_data", {})

        user_msg = f"""End-of-day BTST analysis:

Current Time: {now.strftime('%Y-%m-%d %H:%M')} IST
Day: {day_of_week}
Is Expiry Day: {self.is_expiry_day()}

Analysis Agent Signals:
{signal_summary}

Key EOD Data:
- FII Net: ₹{sentiment_data.get('fii_net', 'N/A')} Cr
- DII Net: ₹{sentiment_data.get('dii_net', 'N/A')} Cr
- India VIX: {sentiment_data.get('vix', 'N/A')}
- Global Macro Risk Level: {macro_data.get('risk_level', 'N/A')}
- S&P 500 Futures Change: {macro_data.get('sp500_change_pct', 'N/A')}%
- Crude Oil: {macro_data.get('crude_oil_price', 'N/A')}
- Gap Prediction: {macro_data.get('gap_prediction', 'N/A')}
- DXY: {macro_data.get('dxy_price', 'N/A')} ({macro_data.get('dxy_change_pct', 'N/A')}%)

{f'WARNING: Tomorrow is expiry day (Thursday). Weekly options expire tomorrow — prefer monthly expiry.' if day_of_week == 'Wednesday' else ''}
{f'NOTE: Today is expiry day. Next-day options have weekend theta advantage for monthly expiry.' if self.is_expiry_day() else ''}

Should we take a BTST position? Respond with JSON."""

        try:
            result = await query_claude(
                SYSTEM_PROMPT, user_msg, self.anthropic_config,
                agent_id=self.agent_id,
                rag_query="BTST overnight options strategy expiry selection weekly monthly gap prediction FII DII",
            )
        except Exception as e:
            self.logger.error(f"Claude API error in BTST decision: {e}")
            return None

        if not result.get("should_trade", False):
            self.logger.info(f"BTST decision: NO TRADE — {result.get('reasoning', 'N/A')[:100]}")
            return None

        direction = result.get("direction", "BULLISH")
        underlying = result.get("underlying", "NIFTY")
        option_type = result.get("option_type", "CE" if direction == "BULLISH" else "PE")
        confidence = float(result.get("confidence", 0.5))
        lots = 1

        expiry_preference = result.get("expiry_preference", "MONTHLY")
        if day_of_week == "Wednesday" and expiry_preference == "WEEKLY":
            expiry_preference = "MONTHLY"
            self.logger.warning("Wednesday hard guard: overriding expiry_preference from WEEKLY to MONTHLY")

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        trade_id = f"BTST-{underlying}-{uuid.uuid4().hex[:8]}"

        proposal = {
            "agent_id": self.agent_id,
            "underlying": underlying,
            "direction": direction,
            "confidence": confidence,
            "timeframe": "BTST",
            "reasoning": result.get("reasoning", "BTST trade proposal"),
            "supporting_data": {
                "trade_id": trade_id,
                "trade_type": "BTST",
                "option_type": option_type,
                "expiry_preference": expiry_preference,
                "lots": lots,
                "lot_size": lot_size,
                "quantity": lots * lot_size,
                "sl_points": float(result.get("sl_points", 60)),
                "target_points": float(result.get("target_points", 100)),
                "overnight_risk": result.get("overnight_risk_assessment", ""),
                "gap_prediction": result.get("gap_prediction", ""),
                "agent_signals": {aid: {"direction": sig.get("direction"), "confidence": sig.get("confidence")} for aid, sig in self._latest_signals.items()},
                "is_expiry_day": self.is_expiry_day(),
                "day_of_week": day_of_week,
            },
        }

        await self.publisher.publish_trade_proposal(proposal)
        self.logger.info(f"BTST proposal published to trade_proposals: {trade_id} {direction} {underlying}")

        db_logger.log_audit(
            event_type="BTST_PROPOSAL",
            source=self.agent_id,
            message=result.get("reasoning", "BTST trade proposal")[:500],
            trade_id=trade_id,
            agent_id=self.agent_id,
            details={
                "trade_id": trade_id,
                "underlying": underlying,
                "direction": direction,
                "confidence": confidence,
                "trade_type": "BTST",
                "day_of_week": day_of_week,
                "expiry_preference": expiry_preference,
                "signals_count": len(self._latest_signals),
                "supporting_data": proposal["supporting_data"],
            },
        )
        return None
