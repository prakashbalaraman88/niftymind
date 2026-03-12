import sys
import os
import uuid
from datetime import datetime, time, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST, MARKET_CLOSE
from agents.llm_utils import query_claude
from config import NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE

BTST_WINDOW_START = time(14, 30)
BTST_WINDOW_END = time(15, 25)
SIGNAL_TTL_SECONDS = 600

SYSTEM_PROMPT = """You are an expert BTST (Buy Today Sell Tomorrow) options strategist for Nifty 50 and BankNifty.

BTST trades are held overnight. You must weigh:
- Overnight risk from global markets (US session happens after Indian close)
- Theta decay — choose expiry carefully (weekly vs monthly)
- FII/DII end-of-day positioning
- Global macro indicators for overnight gap prediction
- On Thursday: next-day is Friday (low theta decay over weekend for monthly expiry)
- On Wednesday: next day is Thursday expiry — avoid weekly options for BTST

Key Rules:
1. NEVER propose BTST with weekly expiry options on Wednesday (they expire next day)
2. Prefer monthly expiry for BTST to reduce theta risk
3. Only propose BTST when global macro signals support overnight holding
4. Weight FII/DII end-of-day activity heavily — large FII selling = bearish next day
5. Consider US futures direction as strong next-day indicator
6. Position size conservatively — max 1 lot for BTST due to overnight gap risk
7. Wider stops (50-80 points Nifty, 100-150 BankNifty) to survive gap opens

Respond with JSON:
{
    "should_trade": true | false,
    "direction": "BULLISH" | "BEARISH",
    "underlying": "NIFTY" | "BANKNIFTY",
    "option_type": "CE" | "PE",
    "expiry_preference": "WEEKLY" | "MONTHLY",
    "lots": 1,
    "sl_points": 60,
    "target_points": 100,
    "confidence": 0.0-1.0,
    "reasoning": "detailed reasoning",
    "overnight_risk_assessment": "description of overnight risks",
    "gap_prediction": "expected gap direction and magnitude"
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
        agent_id = data.get("agent_id", "")
        if not agent_id.startswith("agent_"):
            return None

        agent_num = agent_id.split("_")[1] if "_" in agent_id else ""
        if not agent_num.isdigit() or int(agent_num) > 7:
            return None

        data["_received_at"] = datetime.now(IST).isoformat()
        self._latest_signals[agent_id] = data

        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._last_eval_date != today:
            self._btst_evaluated_today = False
            self._last_eval_date = today

        if self._btst_evaluated_today:
            return None

        if len(self._latest_signals) < 4:
            return None

        return await self._evaluate_btst()

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
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.anthropic_config)
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

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        trade_id = f"BTST-{underlying}-{uuid.uuid4().hex[:8]}"

        return self.create_signal(
            underlying=underlying,
            direction=direction,
            confidence=confidence,
            timeframe="BTST",
            reasoning=result.get("reasoning", "BTST trade proposal"),
            supporting_data={
                "trade_id": trade_id,
                "trade_type": "BTST",
                "option_type": option_type,
                "expiry_preference": result.get("expiry_preference", "MONTHLY"),
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
        )
