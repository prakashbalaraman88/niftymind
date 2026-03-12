import sys
import os
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from config import NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE

SCALP_SIGNAL_TTL_SECONDS = 30
MIN_CONFIDENCE_THRESHOLD = 0.65
SCALP_SL_POINTS_NIFTY = 15
SCALP_TARGET_POINTS_NIFTY = 25
SCALP_SL_POINTS_BANKNIFTY = 30
SCALP_TARGET_POINTS_BANKNIFTY = 50


class ScalpingDecisionAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_8_scalping", "Scalping Decision Agent", redis_publisher)
        self._latest_signals: dict[str, dict] = {}
        self._last_proposal_time: datetime | None = None
        self._cooldown_seconds = 60

    @property
    def subscribed_channels(self) -> list[str]:
        return ["signals"]

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        agent_id = data.get("agent_id", "")
        if agent_id not in ("agent_1_options_chain", "agent_2_order_flow", "agent_3_volume_profile"):
            return None

        data["_received_at"] = datetime.now(IST).isoformat()
        self._latest_signals[agent_id] = data
        self._expire_stale_signals()

        if len(self._latest_signals) < 2:
            return None

        return self._evaluate_scalp()

    def _expire_stale_signals(self):
        now = datetime.now(IST)
        expired = []
        for aid, sig in self._latest_signals.items():
            try:
                ts = datetime.fromisoformat(sig.get("timestamp", ""))
                if (now - ts).total_seconds() > SCALP_SIGNAL_TTL_SECONDS:
                    expired.append(aid)
            except (ValueError, TypeError):
                expired.append(aid)
        for aid in expired:
            del self._latest_signals[aid]

    def _evaluate_scalp(self) -> Signal | None:
        now = datetime.now(IST)
        if self._last_proposal_time and (now - self._last_proposal_time).total_seconds() < self._cooldown_seconds:
            return None

        signals = self._latest_signals
        directions = {}
        confidences = {}
        for aid, sig in signals.items():
            d = sig.get("direction", "NEUTRAL")
            c = float(sig.get("confidence", 0))
            directions[aid] = d
            confidences[aid] = c

        bullish_count = sum(1 for d in directions.values() if d == "BULLISH")
        bearish_count = sum(1 for d in directions.values() if d == "BEARISH")
        total = len(directions)

        if bullish_count == total:
            consensus_dir = "BULLISH"
        elif bearish_count == total:
            consensus_dir = "BEARISH"
        else:
            return None

        avg_confidence = sum(confidences.values()) / total
        if avg_confidence < MIN_CONFIDENCE_THRESHOLD:
            return None

        order_flow = signals.get("agent_2_order_flow", {})
        underlying = order_flow.get("underlying", "NIFTY")

        if underlying == "BANKNIFTY":
            lot_size = BANKNIFTY_LOT_SIZE
            sl_pts = SCALP_SL_POINTS_BANKNIFTY
            tgt_pts = SCALP_TARGET_POINTS_BANKNIFTY
        else:
            lot_size = NIFTY_LOT_SIZE
            sl_pts = SCALP_SL_POINTS_NIFTY
            tgt_pts = SCALP_TARGET_POINTS_NIFTY

        option_type = "CE" if consensus_dir == "BULLISH" else "PE"
        trade_id = f"SCALP-{underlying}-{uuid.uuid4().hex[:8]}"

        expiry_boost = ""
        confidence = avg_confidence
        if self.is_expiry_day():
            confidence = min(0.95, confidence * 1.1)
            expiry_boost = " [EXPIRY: Gamma-amplified scalp]"

        reasoning_parts = []
        for aid, sig in signals.items():
            short_name = aid.replace("agent_", "").replace("_", " ").title()
            reasoning_parts.append(f"{short_name}: {sig.get('direction')} ({sig.get('confidence', 0):.2f})")

        self._last_proposal_time = now

        proposal = self.create_signal(
            underlying=underlying,
            direction=consensus_dir,
            confidence=confidence,
            timeframe="SCALP",
            reasoning=f"Scalp entry: All {total} fast agents aligned {consensus_dir}. " + "; ".join(reasoning_parts) + expiry_boost,
            supporting_data={
                "trade_id": trade_id,
                "trade_type": "SCALP",
                "option_type": option_type,
                "lot_size": lot_size,
                "quantity": lot_size,
                "sl_points": sl_pts,
                "target_points": tgt_pts,
                "agent_signals": {aid: {"direction": sig.get("direction"), "confidence": sig.get("confidence")} for aid, sig in signals.items()},
                "is_expiry_day": self.is_expiry_day(),
            },
        )
        return proposal
