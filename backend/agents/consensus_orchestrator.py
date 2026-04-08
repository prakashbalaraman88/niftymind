import sys
import os
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents import db_logger
from agents.strike_selector import StrikeSelector
from config import NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE

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

VIX_REGIME_ADJUSTMENTS = {
    "LOW": {  # VIX < 12: Breakout expected, favor technical + momentum
        "agent_1_options_chain": 1.0,
        "agent_2_order_flow": 1.3,
        "agent_3_volume_profile": 1.2,
        "agent_4_technical": 1.3,
        "agent_5_sentiment": 0.8,
        "agent_6_news": 0.8,
        "agent_7_macro": 0.8,
    },
    "NORMAL": {
        "agent_1_options_chain": 1.0,
        "agent_2_order_flow": 1.0,
        "agent_3_volume_profile": 1.0,
        "agent_4_technical": 1.0,
        "agent_5_sentiment": 1.0,
        "agent_6_news": 1.0,
        "agent_7_macro": 1.0,
    },
    "ELEVATED": {  # VIX 18-22: Favor options chain + sentiment
        "agent_1_options_chain": 1.3,
        "agent_2_order_flow": 0.8,
        "agent_3_volume_profile": 0.8,
        "agent_4_technical": 1.0,
        "agent_5_sentiment": 1.3,
        "agent_6_news": 1.2,
        "agent_7_macro": 1.2,
    },
    "HIGH": {  # VIX > 22: Only fast signals matter, scalps only
        "agent_1_options_chain": 1.0,
        "agent_2_order_flow": 1.5,
        "agent_3_volume_profile": 1.0,
        "agent_4_technical": 0.5,
        "agent_5_sentiment": 0.5,
        "agent_6_news": 0.5,
        "agent_7_macro": 0.5,
    },
}

DIRECTION_SCORES = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}


class ConsensusOrchestrator(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None, consensus_threshold: float = 0.65,
                 accuracy_tracker=None, pre_trade_recall=None, outcome_model=None):
        super().__init__("agent_12_consensus", "Consensus Orchestrator", redis_publisher)
        self._latest_signals: dict[str, dict] = {}
        self._consensus_threshold = consensus_threshold
        self._last_consensus: dict[str, datetime] = {}
        self._consensus_cooldown = {"SCALP": 30, "INTRADAY": 180, "BTST": 600}
        self._current_vix: float | None = None
        self._accuracy_tracker = accuracy_tracker
        self._pre_trade_recall = pre_trade_recall
        self._outcome_model = outcome_model
        self._strike_selector = StrikeSelector(capital=100000)
        self._latest_options: dict[str, list] = {}  # underlying -> options chain
        self._latest_spot: dict[str, float] = {}  # underlying -> spot price

    @property
    def subscribed_channels(self) -> list[str]:
        return ["signals", "market_breadth", "options_chain"]

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        if "market_breadth" in channel:
            vix = data.get("india_vix")
            if vix is not None:
                self._current_vix = float(vix)
            return None

        if "options_chain" in channel:
            underlying = data.get("underlying", "NIFTY")
            self._latest_options[underlying] = data.get("options", [])
            spot = data.get("spot_price", 0)
            if spot > 0:
                self._latest_spot[underlying] = spot
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

        best_consensus = None
        best_score = 0.0
        all_evaluations: list[tuple[str, float, str, list[dict]]] = []

        for trade_type in ("SCALP", "INTRADAY", "BTST"):
            result = self._compute_consensus(trade_type)
            if result is None:
                continue

            score, direction, vote_details = result
            all_evaluations.append((trade_type, score, direction, vote_details))

            if abs(score) > abs(best_score) and abs(score) >= self._consensus_threshold:
                best_score = score
                best_consensus = (trade_type, score, direction, vote_details)

        if all_evaluations and best_consensus is None:
            sub_threshold = [
                f"{tt}: {dir_} score={sc:.3f}"
                for tt, sc, dir_, _ in all_evaluations
            ]
            db_logger.log_audit(
                event_type="CONSENSUS_SUB_THRESHOLD",
                source=self.agent_id,
                message=f"All scores below threshold {self._consensus_threshold}: " + "; ".join(sub_threshold),
                agent_id=self.agent_id,
                details={
                    "threshold": self._consensus_threshold,
                    "evaluations": [
                        {"trade_type": tt, "score": round(sc, 4), "direction": dir_,
                         "agents_reporting": len(self._latest_signals)}
                        for tt, sc, dir_, _ in all_evaluations
                    ],
                },
            )

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

        # Select options strike
        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        options_data = self._latest_options.get(underlying, [])
        spot_price = self._latest_spot.get(underlying, 0)
        option_type = "CE" if direction == "BULLISH" else "PE"

        selected_strike = None
        if options_data and spot_price > 0:
            selected_strike = self._strike_selector.select_strike(
                strategy=trade_type,
                direction=direction,
                spot_price=spot_price,
                options=options_data,
                underlying=underlying,
                confidence=min(1.0, abs(score)),
            )

        if selected_strike:
            symbol = f"{underlying}{self._format_expiry()}{int(selected_strike['strike'])}{selected_strike['option_type']}"
            entry_premium = selected_strike["ltp"]
            sl_points = round(entry_premium * 0.30, 1)  # 30% SL on premium
            target_points = round(entry_premium * 0.50, 1)  # 50% target on premium
            self.logger.info(
                f"Strike selected for {trade_id}: {symbol} premium=₹{entry_premium:.1f} "
                f"SL=₹{sl_points:.1f} Target=₹{target_points:.1f}"
            )
        else:
            # Fallback: use ATM strike estimate (no options chain available)
            symbol = f"{underlying} {option_type}"
            entry_premium = 0
            sl_points = 20
            target_points = 40
            self.logger.warning(f"No options chain for strike selection — using fallback for {trade_id}")

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
                "vix_at_entry": self._current_vix,
                "symbol": symbol,
                "option_type": option_type,
                "quantity": lot_size,
                "sl_points": sl_points,
                "target_points": target_points,
                "selected_strike": selected_strike,
                "entry_premium": entry_premium,
                "spot_price": spot_price,
            },
        }

        # Learning system: pre-trade recall
        if self._pre_trade_recall:
            try:
                recall = await self._pre_trade_recall.get_context(
                    underlying=underlying,
                    trade_type=trade_type,
                    market_regime=self._get_vix_regime(),
                    direction=direction,
                )
                proposal["supporting_data"]["recall_context"] = recall

                # If recall strongly recommends AVOID, log warning
                if recall.get("recommendation") == "AVOID":
                    self.logger.warning(
                        f"Pre-trade recall AVOID for {underlying}/{trade_type}: "
                        f"{recall.get('note', '')}"
                    )
            except Exception as e:
                self.logger.warning(f"Pre-trade recall failed: {e}")

        # Learning system: model win probability
        if self._outcome_model:
            try:
                win_prob = self._outcome_model.predict(proposal["supporting_data"])
                proposal["supporting_data"]["model_win_probability"] = round(win_prob, 3)
                self.logger.info(f"Model win probability for {trade_id}: {win_prob:.1%}")
            except Exception as e:
                self.logger.warning(f"Model prediction failed: {e}")

        await self.publisher.publish_trade_proposal(proposal)
        self.logger.info(
            f"Consensus proposal published to trade_proposals: {trade_id} "
            f"{direction} {underlying} ({trade_type}) score={score:.3f}"
        )
        return None

    def _get_vix_regime(self) -> str:
        if self._current_vix is None:
            return "NORMAL"
        if self._current_vix < 12:
            return "LOW"
        elif self._current_vix <= 18:
            return "NORMAL"
        elif self._current_vix <= 22:
            return "ELEVATED"
        else:
            return "HIGH"

    def _compute_consensus(self, trade_type: str) -> tuple[float, str, list[dict]] | None:
        base_weights = WEIGHT_PROFILES.get(trade_type, INTRADAY_WEIGHTS)
        regime = self._get_vix_regime()
        regime_adjustments = VIX_REGIME_ADJUSTMENTS.get(regime, VIX_REGIME_ADJUSTMENTS["NORMAL"])

        # Apply dynamic accuracy-based multipliers from learning system
        dynamic = {}
        if self._accuracy_tracker:
            dynamic = self._accuracy_tracker.get_multipliers(trade_type, regime)

        weights = {
            aid: w * regime_adjustments.get(aid, 1.0) * dynamic.get(aid, 1.0)
            for aid, w in base_weights.items()
        }
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

    def _format_expiry(self) -> str:
        """Format current weekly expiry for options symbol e.g. '26APR' or '2640710'."""
        from calendar import monthrange
        now = datetime.now(IST)
        year_short = str(now.year)[-2:]
        month_abbr = now.strftime("%b").upper()
        # Find next Thursday (weekly expiry)
        days_ahead = (3 - now.weekday()) % 7  # Thursday = 3
        if days_ahead == 0 and now.hour >= 15:
            days_ahead = 7
        expiry = now + timedelta(days=days_ahead)
        return f"{year_short}{month_abbr}{expiry.day:02d}"

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
