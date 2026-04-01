"""Daily retrainer: runs at 16:00 IST after market close.

1. Fetches all closed trades + agent votes from Supabase
2. Retrains the GradientBoosting model
3. Recalculates agent accuracy (rolling 30-day window)
4. Publishes niftymind:learning_update to refresh caches
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor

from learning.trade_outcome_model import TradeOutcomeModel
from learning.agent_accuracy_tracker import AgentAccuracyTracker

logger = logging.getLogger("niftymind.learning.daily_retrainer")

IST = timezone(timedelta(hours=5, minutes=30))


class DailyRetrainer:
    """End-of-day batch job: retrain model + recalculate agent accuracy."""

    def __init__(self, learning_config, accuracy_tracker: AgentAccuracyTracker,
                 outcome_model: TradeOutcomeModel, redis_publisher=None):
        self.config = learning_config
        self.accuracy_tracker = accuracy_tracker
        self.outcome_model = outcome_model
        self.publisher = redis_publisher
        self.retrain_hour = learning_config.retrain_hour if learning_config else 16

    async def start(self, shutdown_event: asyncio.Event):
        """Run daily at retrain_hour IST."""
        logger.info(f"Daily Retrainer scheduled for {self.retrain_hour}:00 IST")

        while not shutdown_event.is_set():
            now = datetime.now(IST)
            next_run = now.replace(
                hour=self.retrain_hour, minute=0, second=0, microsecond=0
            )
            if now >= next_run:
                next_run += timedelta(days=1)

            wait_seconds = (next_run - now).total_seconds()
            logger.info(f"Next retraining in {wait_seconds/3600:.1f} hours at {next_run.isoformat()}")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=wait_seconds)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Time to retrain

            try:
                await self._run_retraining()
            except Exception as e:
                logger.error(f"Retraining failed: {e}", exc_info=True)

    async def run_now(self):
        """Manual trigger for retraining (e.g., from API endpoint)."""
        await self._run_retraining()

    async def _run_retraining(self):
        """Execute the full retraining pipeline."""
        logger.info("=== Daily Retraining Starting ===")
        start_time = datetime.now()

        # Step 1: Fetch all closed trades with their agent votes
        trades = self._fetch_trades_with_votes()
        logger.info(f"Fetched {len(trades)} closed trades for training")

        if not trades:
            logger.info("No trades to train on. Skipping.")
            return

        # Step 2: Retrain model
        metrics = self.outcome_model.train(trades)
        if metrics:
            logger.info(
                f"Model retrained: accuracy={metrics['accuracy']:.2f}, "
                f"f1={metrics['f1']:.2f}, "
                f"top features: {self._top_features(metrics)}"
            )
        else:
            logger.info("Insufficient data for model training")

        # Step 3: Refresh agent accuracy cache
        self.accuracy_tracker.refresh_cache()
        logger.info("Agent accuracy cache refreshed")

        # Step 4: Publish learning update event
        if self.publisher:
            try:
                await self.publisher.publish("learning_update", {
                    "event": "daily_retrain_complete",
                    "model_version": self.outcome_model._model_version,
                    "training_trades": len(trades),
                    "metrics": metrics,
                    "timestamp": datetime.now(IST).isoformat(),
                })
            except Exception as e:
                logger.warning(f"Failed to publish learning update: {e}")

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"=== Daily Retraining Complete ({elapsed:.1f}s) ===")

    def _fetch_trades_with_votes(self) -> list[dict]:
        """Fetch all closed trades with their agent votes from Supabase."""
        try:
            conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get rolling window trades
            rolling_days = self.config.accuracy_rolling_days if self.config else 30
            since = datetime.now(IST) - timedelta(days=rolling_days)

            cur.execute(
                """SELECT t.trade_id, t.underlying, t.direction, t.entry_price,
                          t.exit_price, t.pnl, t.trade_type, t.consensus_score,
                          t.entry_time, t.exit_time
                   FROM trades t
                   WHERE t.status = 'CLOSED' AND t.created_at >= %s
                   ORDER BY t.created_at""",
                (since,),
            )
            trades = [dict(r) for r in cur.fetchall()]

            # Fetch votes for each trade
            for trade in trades:
                cur.execute(
                    """SELECT agent_id, direction, confidence, weight
                       FROM agent_votes WHERE trade_id = %s""",
                    (trade["trade_id"],),
                )
                trade["votes"] = [dict(r) for r in cur.fetchall()]

            conn.close()
            return trades

        except Exception as e:
            logger.error(f"Failed to fetch trades: {e}")
            return []

    def _top_features(self, metrics: dict, n: int = 3) -> str:
        """Format top N feature importances for logging."""
        importances = metrics.get("feature_importances", {})
        sorted_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)
        return ", ".join(f"{name}={imp:.3f}" for name, imp in sorted_features[:n])
