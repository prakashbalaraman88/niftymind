"""Paper trading gate: enforces mandatory warmup period before live trading.

Rules:
1. First N days (default 5) MUST be paper trading — no override
2. After warmup, check proof threshold (100+ trades, PF > 1.5, WR > 55%)
3. Only when proof threshold is met can live trading be enabled
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from learning.lesson_store import LessonStore

logger = logging.getLogger("niftymind.learning.paper_trading_gate")

IST = timezone(timedelta(hours=5, minutes=30))


class PaperTradingGate:
    """Enforces paper trading warmup before allowing live mode."""

    def __init__(self, warmup_days: int = 5):
        self.warmup_days = warmup_days
        self.lesson_store = LessonStore()

    def should_force_paper(self) -> bool:
        """Returns True if the system must remain in paper mode.

        Reasons to force paper:
        1. Less than warmup_days since first trade
        2. Fewer than 50 total lessons (insufficient learning)
        """
        # Check warmup period
        earliest = self.lesson_store.get_earliest_trade_date()
        if earliest is None:
            logger.info("GATE: No trades yet. Paper mode enforced.")
            return True

        # Make timezone-aware comparison
        now = datetime.now(IST)
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)

        days_trading = (now - earliest).days
        if days_trading < self.warmup_days:
            logger.info(
                f"GATE: Only {days_trading}/{self.warmup_days} warmup days complete. "
                f"Paper mode enforced."
            )
            return True

        # Check lesson count
        lesson_count = self.lesson_store.get_lesson_count()
        if lesson_count < 50:
            logger.info(
                f"GATE: Only {lesson_count}/50 lessons accumulated. "
                f"Paper mode enforced."
            )
            return True

        logger.info(
            f"GATE: Warmup complete ({days_trading} days, {lesson_count} lessons). "
            f"Live trading eligible."
        )
        return False

    def get_status(self) -> dict:
        """Get gate status for dashboard display."""
        earliest = self.lesson_store.get_earliest_trade_date()
        lesson_count = self.lesson_store.get_lesson_count()

        now = datetime.now(IST)
        days_trading = 0
        if earliest:
            if earliest.tzinfo is None:
                earliest = earliest.replace(tzinfo=timezone.utc)
            days_trading = (now - earliest).days

        forced_paper = self.should_force_paper()

        return {
            "warmup_days_required": self.warmup_days,
            "days_trading": days_trading,
            "lessons_accumulated": lesson_count,
            "lessons_required": 50,
            "warmup_complete": days_trading >= self.warmup_days,
            "lessons_sufficient": lesson_count >= 50,
            "live_eligible": not forced_paper,
            "forced_paper": forced_paper,
            "first_trade_date": earliest.isoformat() if earliest else None,
        }
