import sys
import os
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents import db_logger
from config import NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE


class RiskManager(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None, risk_config=None):
        super().__init__("agent_11_risk", "Risk Manager", redis_publisher)
        self._risk_config = risk_config
        self._max_daily_loss = getattr(risk_config, "max_daily_loss", 50000.0) if risk_config else 50000.0
        self._max_trade_risk_pct = getattr(risk_config, "max_trade_risk_pct", 2.0) if risk_config else 2.0
        self._max_open_positions = getattr(risk_config, "max_open_positions", 5) if risk_config else 5
        self._vix_halt_threshold = getattr(risk_config, "vix_halt_threshold", 25.0) if risk_config else 25.0
        self._capital = getattr(risk_config, "capital", 500000.0) if risk_config else 500000.0

        self._daily_pnl: float = 0.0
        self._open_positions: list[dict] = []
        self._current_vix: float | None = None
        self._last_reset_date: str | None = None

    @property
    def subscribed_channels(self) -> list[str]:
        return ["trade_proposals", "trade_executions", "market_breadth"]

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        self._reset_daily_if_needed()

        if "market_breadth" in channel:
            vix = data.get("india_vix")
            if vix is not None:
                self._current_vix = float(vix)
            return None

        if "trade_executions" in channel:
            self._handle_execution(data)
            return None

        if "trade_proposals" in channel:
            return await self._validate_proposal(data)

        return None

    def _reset_daily_if_needed(self):
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._last_reset_date != today:
            self._daily_pnl = 0.0
            self._open_positions = [p for p in self._open_positions if p.get("status") == "OPEN"]
            self._last_reset_date = today
            self.logger.info(f"Daily reset: PnL zeroed, {len(self._open_positions)} carried positions")

    def _handle_execution(self, data: dict):
        event = data.get("event", "")
        trade_id = data.get("trade_id", "")

        if event == "ENTRY":
            self._open_positions.append({
                "trade_id": trade_id,
                "underlying": data.get("underlying", "NIFTY"),
                "direction": data.get("direction", ""),
                "quantity": data.get("quantity", 0),
                "entry_price": data.get("price", 0),
                "status": "OPEN",
            })

        elif event in ("EXIT", "SL_HIT", "TARGET_HIT"):
            pnl = float(data.get("pnl", 0))
            self._daily_pnl += pnl
            self._open_positions = [p for p in self._open_positions if p.get("trade_id") != trade_id]

    async def _validate_proposal(self, data: dict) -> Signal | None:
        trade_id = data.get("supporting_data", {}).get("trade_id", data.get("trade_id", f"UNKNOWN-{uuid.uuid4().hex[:8]}"))
        trade_type = data.get("supporting_data", {}).get("trade_type", data.get("timeframe", "INTRADAY"))
        underlying = data.get("underlying", "NIFTY")
        direction = data.get("direction", "NEUTRAL")
        confidence = float(data.get("confidence", 0))
        quantity = int(data.get("supporting_data", {}).get("quantity", 0))
        sl_points = float(data.get("supporting_data", {}).get("sl_points", 20))

        checks = []
        approved = True

        daily_loss_check = self._check_daily_loss()
        checks.append(daily_loss_check)
        if not daily_loss_check["passed"]:
            approved = False

        position_check = self._check_open_positions()
        checks.append(position_check)
        if not position_check["passed"]:
            approved = False

        vix_check = self._check_vix_halt()
        checks.append(vix_check)
        if not vix_check["passed"]:
            approved = False

        correlation_check = self._check_correlation(underlying, direction)
        checks.append(correlation_check)
        if not correlation_check["passed"]:
            approved = False

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        sizing_result = self._calculate_position_size(underlying, sl_points, confidence, self._current_vix)
        checks.append(sizing_result["check"])

        approved_quantity = sizing_result["quantity"]
        if approved_quantity <= 0:
            approved = False

        max_risk = self._capital * (self._max_trade_risk_pct / 100)
        trade_risk = sl_points * approved_quantity
        capital_risk_check = {
            "name": "capital_risk",
            "passed": trade_risk <= max_risk,
            "detail": f"Trade risk ₹{trade_risk:,.0f} vs max ₹{max_risk:,.0f}",
        }
        checks.append(capital_risk_check)
        if not capital_risk_check["passed"]:
            approved = False

        verdict = "APPROVED" if approved else "VETOED"
        check_summary = "; ".join(f"{c['name']}: {'PASS' if c['passed'] else 'FAIL'} — {c['detail']}" for c in checks)
        reasoning = f"Risk Manager {verdict}: {check_summary}"

        db_logger.log_trade_event(
            trade_id=trade_id,
            event=f"RISK_{verdict}",
            status=verdict,
            quantity=approved_quantity if approved else 0,
            consensus_score=confidence,
            risk_approval=verdict,
            risk_reasoning=reasoning,
            details={
                "checks": checks,
                "daily_pnl": self._daily_pnl,
                "open_positions": len(self._open_positions),
                "current_vix": self._current_vix,
                "approved_quantity": approved_quantity,
            },
        )

        db_logger.log_audit(
            event_type=f"RISK_{verdict}",
            source=self.agent_id,
            message=reasoning[:500],
            trade_id=trade_id,
            agent_id=self.agent_id,
            details={"checks": checks, "original_proposal": {k: v for k, v in data.items() if k != "supporting_data"}},
        )

        if approved:
            approved_data = dict(data)
            if "supporting_data" not in approved_data:
                approved_data["supporting_data"] = {}
            approved_data["supporting_data"]["risk_approved"] = True
            approved_data["supporting_data"]["risk_reasoning"] = reasoning
            approved_data["supporting_data"]["approved_quantity"] = approved_quantity
            approved_data["supporting_data"]["risk_checks"] = checks

            db_logger.insert_trade(
                trade_id=trade_id,
                symbol=f"{underlying} {data.get('supporting_data', {}).get('option_type', 'CE')}",
                underlying=underlying,
                direction=direction,
                quantity=approved_quantity,
                trade_type=trade_type,
                consensus_score=confidence,
                sl_price=None,
                target_price=None,
            )

            await self.publisher.publish_trade_execution({
                "event": "RISK_APPROVED",
                "trade_id": trade_id,
                "trade_type": trade_type,
                "underlying": underlying,
                "direction": direction,
                "quantity": approved_quantity,
                "confidence": confidence,
                "risk_reasoning": reasoning,
                "timestamp": datetime.now(IST).isoformat(),
            })

            self.logger.info(f"APPROVED trade {trade_id}: {direction} {underlying} x{approved_quantity}")
        else:
            self.logger.warning(f"VETOED trade {trade_id}: {reasoning[:200]}")

        return self.create_signal(
            underlying=underlying,
            direction=direction if approved else "NEUTRAL",
            confidence=confidence if approved else 0.0,
            timeframe=trade_type,
            reasoning=reasoning,
            supporting_data={
                "trade_id": trade_id,
                "verdict": verdict,
                "checks": checks,
                "approved_quantity": approved_quantity if approved else 0,
            },
        )

    def _check_daily_loss(self) -> dict:
        remaining = self._max_daily_loss + self._daily_pnl
        passed = self._daily_pnl > -self._max_daily_loss
        return {
            "name": "daily_loss_limit",
            "passed": passed,
            "detail": f"Daily PnL ₹{self._daily_pnl:,.0f}, limit -₹{self._max_daily_loss:,.0f}, remaining ₹{remaining:,.0f}",
        }

    def _check_open_positions(self) -> dict:
        count = len(self._open_positions)
        passed = count < self._max_open_positions
        return {
            "name": "open_positions",
            "passed": passed,
            "detail": f"{count}/{self._max_open_positions} positions open",
        }

    def _check_vix_halt(self) -> dict:
        if self._current_vix is None:
            return {"name": "vix_halt", "passed": True, "detail": "VIX data not available, allowing trade"}

        passed = self._current_vix < self._vix_halt_threshold
        return {
            "name": "vix_halt",
            "passed": passed,
            "detail": f"India VIX {self._current_vix:.1f} vs halt threshold {self._vix_halt_threshold:.1f}",
        }

    def _check_correlation(self, underlying: str, direction: str) -> dict:
        same_direction_same_underlying = [
            p for p in self._open_positions
            if p.get("underlying") == underlying and p.get("direction") == direction
        ]
        count = len(same_direction_same_underlying)
        passed = count < 2
        return {
            "name": "correlation_risk",
            "passed": passed,
            "detail": f"{count} existing {direction} positions on {underlying} (max 2)",
        }

    def _vix_adjustment_factor(self, vix: float | None) -> float:
        """Scale down position size as VIX rises above normal baseline of 13.
        VIX 13 → 1.0x (full size), VIX 20 → 0.65x, VIX 25 → 0.52x, VIX 35+ → 0.37x.
        Formula: factor = 13 / max(13, vix), clamped to [0.25, 1.0].
        """
        if vix is None or vix <= 0:
            return 1.0
        return max(0.25, min(1.0, 13.0 / max(13.0, vix)))

    def _calculate_position_size(self, underlying: str, sl_points: float,
                                  confidence: float, vix: float | None = None) -> dict:
        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        max_risk_per_trade = self._capital * (self._max_trade_risk_pct / 100)
        remaining_daily = self._max_daily_loss + self._daily_pnl

        effective_risk_budget = min(max_risk_per_trade, remaining_daily * 0.5)

        if sl_points <= 0:
            sl_points = 20

        vix_factor = self._vix_adjustment_factor(vix)
        volatility_adjusted_budget = effective_risk_budget * vix_factor

        risk_per_lot = sl_points * lot_size
        max_lots = max(0, int(volatility_adjusted_budget / risk_per_lot)) if risk_per_lot > 0 else 0

        confidence_adjusted_lots = max(1, min(max_lots, int(confidence * 3)))
        final_lots = min(confidence_adjusted_lots, max_lots) if max_lots > 0 else 0
        final_qty = final_lots * lot_size

        vix_note = f", VIX={vix:.1f} factor={vix_factor:.2f}" if vix is not None else ", VIX=N/A factor=1.0"
        check = {
            "name": "position_sizing",
            "passed": final_qty > 0,
            "detail": (
                f"Risk budget ₹{effective_risk_budget:,.0f} → volatility-adjusted ₹{volatility_adjusted_budget:,.0f}"
                f"{vix_note}, risk/lot ₹{risk_per_lot:,.0f}, lots={final_lots}, qty={final_qty}"
            ),
        }

        return {"quantity": final_qty, "lots": final_lots, "check": check, "vix_factor": vix_factor}
