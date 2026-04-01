"""Drawdown recovery and equity curve management."""

import logging
from datetime import datetime, timezone, timedelta
from collections import deque

logger = logging.getLogger("niftymind.drawdown")

IST = timezone(timedelta(hours=5, minutes=30))

CONSECUTIVE_LOSS_THRESHOLD = 3
CONSECUTIVE_LOSS_REDUCTION = 0.5  # 50% size after 3 losses
LOSS_RECOVERY_TRADES = 2  # Number of wins to recover from loss reduction

CONSECUTIVE_WIN_THRESHOLD = 5
CONSECUTIVE_WIN_REDUCTION = 0.75  # 75% size after 5 wins (mean reversion protection)

MAX_DRAWDOWN_PCT = 0.15  # 15% drawdown → pause
WEEKLY_LOSS_REDUCTION = 0.5  # 50% size if weekly loss limit hit


class DrawdownManager:
    def __init__(self, capital: float = 100_000):
        self._initial_capital = capital
        self._current_equity = capital
        self._peak_equity = capital
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._loss_reduction_remaining = 0  # Trades remaining under reduced size
        self._weekly_pnl = 0.0
        self._weekly_loss_limit = capital * 0.10  # 10% weekly limit at ₹1L
        self._equity_history: deque = deque(maxlen=20)  # For 20-day MA
        self._equity_history.append(capital)
        self._trade_log: list[dict] = []

    @property
    def size_multiplier(self) -> float:
        """Current position size multiplier (0.25 to 1.0)."""
        multiplier = 1.0

        # Consecutive loss reduction
        if self._loss_reduction_remaining > 0:
            multiplier *= CONSECUTIVE_LOSS_REDUCTION

        # Consecutive win reduction
        if self._consecutive_wins >= CONSECUTIVE_WIN_THRESHOLD:
            multiplier *= CONSECUTIVE_WIN_REDUCTION

        # Weekly loss limit hit
        if self._weekly_pnl <= -self._weekly_loss_limit:
            multiplier *= WEEKLY_LOSS_REDUCTION

        # Equity below 20-day MA
        if len(self._equity_history) >= 5:
            ma = sum(self._equity_history) / len(self._equity_history)
            if self._current_equity < ma:
                multiplier *= 0.5

        return max(0.25, min(1.0, multiplier))

    def record_trade(self, pnl: float):
        """Record a completed trade and update all counters."""
        self._current_equity += pnl
        self._weekly_pnl += pnl
        self._peak_equity = max(self._peak_equity, self._current_equity)
        self._equity_history.append(self._current_equity)

        self._trade_log.append({
            "pnl": pnl,
            "equity": self._current_equity,
            "timestamp": datetime.now(IST).isoformat(),
        })

        if pnl < 0:
            self._consecutive_losses += 1
            self._consecutive_wins = 0
            if self._consecutive_losses >= CONSECUTIVE_LOSS_THRESHOLD:
                self._loss_reduction_remaining = LOSS_RECOVERY_TRADES
                logger.warning(
                    f"Drawdown alert: {self._consecutive_losses} consecutive losses. "
                    f"Reducing size by {int((1 - CONSECUTIVE_LOSS_REDUCTION) * 100)}% for {LOSS_RECOVERY_TRADES} trades."
                )
        else:
            self._consecutive_wins += 1
            self._consecutive_losses = 0
            if self._loss_reduction_remaining > 0:
                self._loss_reduction_remaining -= 1
                if self._loss_reduction_remaining == 0:
                    logger.info("Drawdown recovery complete. Returning to normal size.")

    def should_pause_trading(self) -> bool:
        """Check if drawdown circuit breaker should activate."""
        if self._peak_equity <= 0:
            return False
        drawdown_pct = (self._peak_equity - self._current_equity) / self._peak_equity
        return drawdown_pct > MAX_DRAWDOWN_PCT

    def reset_weekly(self):
        """Reset weekly PnL counter (call on Monday market open)."""
        self._weekly_pnl = 0.0

    def get_status(self) -> dict:
        drawdown_pct = (self._peak_equity - self._current_equity) / self._peak_equity if self._peak_equity > 0 else 0
        return {
            "current_equity": self._current_equity,
            "peak_equity": self._peak_equity,
            "drawdown_pct": round(drawdown_pct * 100, 2),
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "size_multiplier": self.size_multiplier,
            "weekly_pnl": self._weekly_pnl,
            "should_pause": self.should_pause_trading(),
        }
