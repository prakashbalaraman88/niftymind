import sys
import os
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents import db_logger

SIGNAL_TTL_SECONDS = 300

SCALP_WEIGHTS = {
    "agent_1_options_chain": 0.25,
    "agent_2_order_flow": 0.35,
    "agent_3_volume_profile": 0.25,
    "agent_4_technical": 0.15,
    "agent_5_sentiment": 0.0,
    "agent_6_news": 0.0,
    "agent_7_macro": 0.0,
}

INTRADAY_WEIGHTS = {
    "agent_1_options_chain": 0.20,
    "agent_2_order_flow": 0.15,
    "agent_3_volume_profile": 0.10,
    "agent_4_technical": 0.20,
    "agent_5_sentiment": 0.15,
    "agent_6_news": 0.10,
    "agent_7_macro": 0.10,
}

BTST_WEIGHTS = {
    "agent_1_options_chain": 0.10,
    "agent_2_order_flow": 0.05,
    "agent_3_volume_profile": 0.05,
    "agent_4_technical": 0.15,
    "agent_5_sentiment": 0.25,
    "agent_6_news": 0.15,
    "agent_7_macro": 0.25,
}

WEIGHT_PROFILES = {
    "SCALP": SCALP_WEIGHTS,
    "INTRADAY": INTRADAY_WEIGHTS,
    "BTST": BTST_WEIGHTS,
}

DIRECTION_SCORES = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}


class ConsensusOrchestrator(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None, consensus_threshold: float = 0.65):
        super().__init__("agent_12_consensus", "Consensus Orchestrator", redis_publisher)
        self._latest_signals: dict[str, dict] = {}
        self._consensus_threshold = consensus_threshold
        self._last_consensus: dict[str, datetime] = {}
        self._consensus_cooldown = {"SCALP": 30, "INTRADAY": 180, "BTST": 600}

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

        best_consensus = None
        best_score = 0.0

        for trade_type in ("SCALP", "INTRADAY", "BTST"):
            result = self._compute_consensus(trade_type)
            if result is None:
                continue

            score, direction, vote_details = result
            if abs(score) > abs(best_score) and abs(score) >= self._consensus_threshold:
                best_score = score
                best_consensus = (trade_type, score, direction, vote_details)

        if best_consensus is None:
            return None

        trade_type, score, direction, vote_details = best_consensus

        now = datetime.now(IST)
        cooldown = self._consensus_cooldown.get(trade_type, 60)
        last = self._last_consensus.get(trade_type)
        if last and (now - last).total_seconds() < cooldown:
            return None

        self._last_consensus[trade_type] = now

        underlying = self._determine_underlying()
        trade_id = f"CONSENSUS-{trade_type}-{uuid.uuid4().hex[:8]}"
        self._log_votes_to_db(trade_id, trade_type, vote_details, underlying, direction, abs(score))

        proposal = {
            "agent_id": self.agent_id,
            "underlying": underlying,
            "direction": direction,
            "confidence": min(1.0, abs(score)),
            "timeframe": trade_type,
            "reasoning": (
                f"Consensus reached for {trade_type}: weighted score={score:.3f} "
                f"(threshold={self._consensus_threshold}). " +
                "; ".join(
                    f"{v['agent_id']}: {v['direction']} w={v['weight']:.2f} ws={v['weighted_score']:.3f}"
                    for v in vote_details
                )
            ),
            "supporting_data": {
                "trade_id": trade_id,
                "trade_type": trade_type,
                "consensus_score": round(score, 4),
                "threshold": self._consensus_threshold,
                "votes": vote_details,
                "agents_reporting": len(self._latest_signals),
                "is_expiry_day": self.is_expiry_day(),
            },
        }

        await self.publisher.publish_trade_proposal(proposal)
        self.logger.info(
            f"Consensus proposal published to trade_proposals: {trade_id} "
            f"{direction} {underlying} ({trade_type}) score={score:.3f}"
        )
        return None

    def _compute_consensus(self, trade_type: str) -> tuple[float, str, list[dict]] | None:
        weights = WEIGHT_PROFILES.get(trade_type, INTRADAY_WEIGHTS)
        active_agents = {aid: w for aid, w in weights.items() if w > 0 and aid in self._latest_signals}

        if not active_agents:
            return None

        min_agents = {"SCALP": 2, "INTRADAY": 4, "BTST": 3}
        if len(active_agents) < min_agents.get(trade_type, 2):
            return None

        total_weight = sum(active_agents.values())
        weighted_score = 0.0
        vote_details = []

        for aid, weight in active_agents.items():
            sig = self._latest_signals[aid]
            direction = sig.get("direction", "NEUTRAL")
            confidence = float(sig.get("confidence", 0))
            dir_score = DIRECTION_SCORES.get(direction, 0.0)

            normalized_weight = weight / total_weight
            ws = dir_score * confidence * normalized_weight
            weighted_score += ws

            vote_details.append({
                "agent_id": aid,
                "direction": direction,
                "confidence": confidence,
                "weight": round(normalized_weight, 4),
                "weighted_score": round(ws, 4),
                "reasoning": sig.get("reasoning", "")[:200],
            })

        consensus_direction = "BULLISH" if weighted_score > 0 else "BEARISH"
        return weighted_score, consensus_direction, vote_details

    def _determine_underlying(self) -> str:
        nifty_count = 0
        banknifty_count = 0
        for sig in self._latest_signals.values():
            u = sig.get("underlying", "NIFTY").upper()
            if "BANK" in u:
                banknifty_count += 1
            else:
                nifty_count += 1
        return "BANKNIFTY" if banknifty_count > nifty_count else "NIFTY"

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

    def _log_votes_to_db(self, trade_id: str, trade_type: str, vote_details: list[dict],
                         underlying: str, direction: str, consensus_score: float):
        try:
            db_logger.insert_trade(
                trade_id=trade_id,
                symbol=f"{underlying} CONSENSUS",
                underlying=underlying,
                direction=direction,
                quantity=0,
                trade_type=trade_type,
                consensus_score=consensus_score,
            )

            for vote in vote_details:
                db_logger.log_agent_vote(
                    trade_id=trade_id,
                    agent_id=vote["agent_id"],
                    direction=vote["direction"],
                    confidence=vote["confidence"],
                    weight=vote["weight"],
                    weighted_score=vote["weighted_score"],
                    reasoning=vote["reasoning"],
                    supporting_data={"trade_type": trade_type},
                )

            db_logger.log_audit(
                event_type="CONSENSUS_REACHED",
                source=self.agent_id,
                message=f"Consensus reached for {trade_type} with {len(vote_details)} votes",
                trade_id=trade_id,
                agent_id=self.agent_id,
                details={
                    "trade_type": trade_type,
                    "vote_count": len(vote_details),
                    "consensus_score": consensus_score,
                    "votes_summary": [{v["agent_id"]: v["weighted_score"]} for v in vote_details],
                },
            )
        except Exception as e:
            self.logger.error(f"Failed to log votes to DB: {e}")
