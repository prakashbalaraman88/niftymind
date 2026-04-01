"""Agent accuracy tracker: monitors per-agent hit rates and provides dynamic weight multipliers.

Cached in memory, refreshed on niftymind:learning_update events.
"""

import logging
from learning.lesson_store import LessonStore

logger = logging.getLogger("niftymind.learning.agent_accuracy_tracker")


class AgentAccuracyTracker:
    """Tracks per-agent accuracy and provides dynamic consensus weight multipliers."""

    def __init__(self, learning_config=None):
        self.lesson_store = LessonStore()
        self.min_signals = (
            learning_config.min_signals_for_weight_adjust
            if learning_config else 10
        )
        # In-memory cache: {(trade_type, regime): {agent_id: multiplier}}
        self._cache: dict[tuple, dict[str, float]] = {}

    def get_multipliers(self, trade_type: str, market_regime: str) -> dict[str, float]:
        """Get dynamic weight multipliers for all agents.

        Returns dict of {agent_id: multiplier}.
        Multiplier range: [0.5, 1.5] where 1.0 = no adjustment.
        Agents with < min_signals observations return 1.0 (no adjustment).
        """
        cache_key = (trade_type, market_regime)
        if cache_key in self._cache:
            return self._cache[cache_key]

        multipliers = self.lesson_store.get_agent_multipliers(
            trade_type=trade_type,
            market_regime=market_regime,
            min_signals=self.min_signals,
        )

        # Clamp to [0.5, 1.5]
        clamped = {
            aid: max(0.5, min(1.5, m))
            for aid, m in multipliers.items()
        }

        self._cache[cache_key] = clamped
        return clamped

    def refresh_cache(self):
        """Clear cache so next get_multipliers() hits the DB."""
        self._cache.clear()
        logger.info("Agent accuracy cache cleared")

    def get_all_accuracies(self) -> list[dict]:
        """Get all agent accuracy records (for dashboard display)."""
        import os
        import psycopg2
        from psycopg2.extras import RealDictCursor

        try:
            conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT agent_id, trade_type, market_regime,
                          total_signals, correct_signals, accuracy,
                          weight_multiplier, last_updated
                   FROM agent_accuracy
                   ORDER BY agent_id, trade_type, market_regime"""
            )
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Failed to get accuracies: {e}")
            return []
