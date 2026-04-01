import sys
import os
import uuid
from datetime import datetime, time, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.strike_selector import StrikeSelector
from agents.llm_utils import query_claude
from agents import db_logger
from config import NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE

SIGNAL_TTL_SECONDS = 300
MIN_SIGNALS_FOR_DECISION = 7

SYSTEM_PROMPT = """You are an expert intraday options trader specializing in Nifty 50 and BankNifty on the NSE.

You receive signals from 7 analysis agents and must decide whether to propose an intraday options trade.

Agent Roles:
1. Options Chain Agent — Greeks, IV, PCR, OI, max pain analysis
2. Order Flow Agent — Bid-ask absorption, large lots, delta divergence
3. Volume Profile Agent — VWAP, POC, value area, HVN/LVN
4. Technical Analysis Agent — Multi-timeframe EMA, RSI, CPR, Camarilla
5. Sentiment Agent — FII/DII activity, India VIX, market breadth
6. News Agent — Event classification, avoid-trading windows
7. Macro Agent — Global indices, crude, DXY, US yields correlation

Decision Rules:
- Propose a trade ONLY when you see strong directional consensus (5+ agents agree)
- If News Agent flags avoid_trading=true, do NOT propose any trade
- Consider opening range breakout in first 30 minutes
- On expiry days (Thursday), prefer ATM/slightly ITM options for gamma plays
- Outside expiry, prefer slightly OTM options (2-3 strikes away)
- Factor theta decay — avoid buying options after 2 PM unless very strong signal
- Position sizing: 1 lot for moderate conviction, 2 lots for high conviction

Respond with JSON:
{
    "should_trade": true | false,
    "direction": "BULLISH" | "BEARISH",
    "underlying": "NIFTY" | "BANKNIFTY",
    "option_type": "CE" | "PE",
    "strike_offset": 0,
    "lots": 1,
    "sl_points": 20,
    "target_points": 40,
    "confidence": 0.0-1.0,
    "reasoning": "detailed reasoning",
    "risk_notes": "any risk warnings"
}"""


class IntradayDecisionAgent(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None):
        super().__init__("agent_9_intraday", "Intraday Decision Agent", redis_publisher)
        self.llm_config = llm_config
        self._strike_selector = StrikeSelector(capital=100000)
        self._latest_signals: dict[str, dict] = {}
        self._latest_options: dict[str, list] = {}
        self._last_decision_time: datetime | None = None
        self._decision_interval = 180

    @property
    def subscribed_channels(self) -> list[str]:
        return ["signals", "options_chain"]

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        if channel == "options_chain":
            underlying = data.get("underlying", "NIFTY")
            self._latest_options[underlying] = data.get("options", [])
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
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.llm_config)
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

        options_chain_sig = self._latest_signals.get("agent_1_options_chain", {})
        spot_price = float(options_chain_sig.get("supporting_data", {}).get("spot_price", 0))
        options_data = self._latest_options.get(underlying, [])
        selected_strike = self._strike_selector.select_strike(
            strategy="INTRADAY",
            direction=direction,
            spot_price=spot_price,
            options=options_data,
            underlying=underlying,
            confidence=confidence,
        )
        if selected_strike is None:
            self.logger.info(f"No valid strike for INTRADAY {direction} — skipping proposal")
            return None

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
                "selected_strike": selected_strike,
                "option_type": selected_strike["option_type"],
                "strike_price": selected_strike["strike"],
                "premium": selected_strike["ltp"],
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
