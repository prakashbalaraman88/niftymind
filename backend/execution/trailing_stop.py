"""Multi-target Take Profit + ATR-based Trailing Stop Loss engine."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("niftymind.trailing_stop")

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_TARGETS = [
    {"ratio": 1.5, "exit_pct": 0.60},  # T1: 60% at 1.5R
    {"ratio": 2.5, "exit_pct": 0.30},  # T2: 30% at 2.5R
    {"ratio": 999, "exit_pct": 0.10},   # T3: 10% runner (trailed)
]

STRATEGY_TIME_LIMITS = {
    "SCALP": {"max_hold_minutes": 10, "eod_exit_time": "15:15"},
    "INTRADAY": {"max_hold_minutes": 999, "eod_exit_time": "15:15"},
    "BTST": {"max_hold_minutes": 999, "eod_exit_time": None},  # No intraday exit
}


@dataclass
class TradePosition:
    trade_id: str
    entry_price: float
    sl_price: float
    direction: str  # BULLISH or BEARISH
    quantity: int
    strategy: str
    targets: list[dict] = field(default_factory=lambda: list(DEFAULT_TARGETS))
    remaining_quantity: int = 0
    targets_hit: list[int] = field(default_factory=list)
    entry_time: datetime = field(default_factory=lambda: datetime.now(IST))
    trailing_active: bool = False
    trail_atr: float = 0.0

    def __post_init__(self):
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.quantity

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.sl_price)


class TrailingStopManager:
    def __init__(self, capital: float = 100_000):
        self.capital = capital
        self.max_risk_pct = 0.02  # 2% max risk per trade

    def calculate_sl(self, entry_price: float, atr: float, structure_level: float | None,
                     direction: str, capital: float | None = None) -> dict:
        """Calculate stop loss based on ATR and structure levels."""
        cap = capital or self.capital
        max_risk = cap * self.max_risk_pct

        atr_sl_distance = 1.5 * atr

        if structure_level is not None:
            structure_distance = abs(entry_price - structure_level)
            sl_distance = max(atr_sl_distance, structure_distance)
        else:
            sl_distance = atr_sl_distance

        if direction == "BULLISH":
            sl_price = entry_price - sl_distance
        else:
            sl_price = entry_price + sl_distance

        return {
            "sl_price": round(sl_price, 2),
            "sl_distance": round(sl_distance, 2),
            "max_risk_amount": max_risk,
            "risk_per_unit": round(sl_distance, 2),
        }

    def update(self, pos: TradePosition, current_price: float,
               current_atr: float | None = None) -> list[dict]:
        """Update position: check SL, targets, trailing. Returns list of actions to execute."""
        actions = []

        if pos.remaining_quantity <= 0:
            return actions

        # Check SL hit
        if pos.direction == "BULLISH" and current_price <= pos.sl_price:
            actions.append({
                "action": "FULL_EXIT_SL",
                "trade_id": pos.trade_id,
                "quantity": pos.remaining_quantity,
                "price": current_price,
                "reason": f"SL hit at {current_price} (SL={pos.sl_price})",
            })
            pos.remaining_quantity = 0
            return actions
        elif pos.direction == "BEARISH" and current_price >= pos.sl_price:
            actions.append({
                "action": "FULL_EXIT_SL",
                "trade_id": pos.trade_id,
                "quantity": pos.remaining_quantity,
                "price": current_price,
                "reason": f"SL hit at {current_price} (SL={pos.sl_price})",
            })
            pos.remaining_quantity = 0
            return actions

        # Check options-specific exit rules
        if current_price < 10:
            actions.append({
                "action": "FULL_EXIT_ILLIQUID",
                "trade_id": pos.trade_id,
                "quantity": pos.remaining_quantity,
                "price": current_price,
                "reason": "Premium below ₹10 — exiting illiquid option",
            })
            pos.remaining_quantity = 0
            return actions

        # Check targets
        risk = pos.risk_per_unit
        if risk <= 0:
            return actions

        for i, target in enumerate(pos.targets):
            if i in pos.targets_hit:
                continue

            if pos.direction == "BULLISH":
                target_price = pos.entry_price + target["ratio"] * risk
                target_hit = current_price >= target_price
            else:
                target_price = pos.entry_price - target["ratio"] * risk
                target_hit = current_price <= target_price

            if target_hit and target["ratio"] < 999:
                exit_qty = int(pos.quantity * target["exit_pct"])
                exit_qty = min(exit_qty, pos.remaining_quantity)
                if exit_qty > 0:
                    actions.append({
                        "action": "PARTIAL_EXIT",
                        "trade_id": pos.trade_id,
                        "quantity": exit_qty,
                        "price": current_price,
                        "target_index": i + 1,
                        "reason": f"T{i+1} hit at {current_price:.2f} ({target['ratio']}R)",
                    })
                    pos.remaining_quantity -= exit_qty
                    pos.targets_hit.append(i)

                    # After T1: Move SL to breakeven
                    if i == 0:
                        pos.sl_price = pos.entry_price
                        logger.info(f"{pos.trade_id}: SL moved to breakeven after T1")

        # Trailing stop for runner (after T1 hit)
        if 0 in pos.targets_hit and current_atr and pos.remaining_quantity > 0:
            rr_achieved = abs(current_price - pos.entry_price) / risk if risk > 0 else 0

            if rr_achieved >= 2.0:
                trail_distance = 0.75 * current_atr
            elif rr_achieved >= 1.5:
                trail_distance = 1.0 * current_atr
            else:
                trail_distance = None

            if trail_distance:
                if pos.direction == "BULLISH":
                    new_sl = current_price - trail_distance
                    if new_sl > pos.sl_price:
                        pos.sl_price = round(new_sl, 2)
                        pos.trailing_active = True
                else:
                    new_sl = current_price + trail_distance
                    if new_sl < pos.sl_price:
                        pos.sl_price = round(new_sl, 2)
                        pos.trailing_active = True

        return actions

    def check_time_exit(self, pos: TradePosition) -> dict | None:
        """Check if position should be exited based on time rules."""
        now = datetime.now(IST)
        config = STRATEGY_TIME_LIMITS.get(pos.strategy, {})

        # Scalp: Exit if not in profit within max_hold_minutes
        if pos.strategy == "SCALP":
            max_hold = config.get("max_hold_minutes", 10)
            elapsed = (now - pos.entry_time).total_seconds() / 60
            if elapsed >= max_hold:
                return {
                    "action": "TIME_EXIT",
                    "trade_id": pos.trade_id,
                    "quantity": pos.remaining_quantity,
                    "reason": f"Scalp time limit: {elapsed:.0f} min > {max_hold} min",
                }

        # EOD exit for intraday
        eod_time_str = config.get("eod_exit_time")
        if eod_time_str:
            h, m = map(int, eod_time_str.split(":"))
            eod_time = now.replace(hour=h, minute=m, second=0)
            if now >= eod_time and pos.remaining_quantity > 0:
                return {
                    "action": "EOD_EXIT",
                    "trade_id": pos.trade_id,
                    "quantity": pos.remaining_quantity,
                    "reason": f"EOD exit at {eod_time_str} IST",
                }

        return None
