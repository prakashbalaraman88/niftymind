"""Bootstrap training: pre-train the TradeOutcomeModel on bulk historical data.

Pulls the maximum history Yahoo Finance allows for NIFTY/BANKNIFTY
(daily: years; 1h: ~720 days; 5m: ~60 days), simulates the agent stack with
the HistoricalBacktester, converts the simulated trades into the model's
training format, trains the GradientBoosting win-probability model with a
chronological holdout, and persists the snapshot (local file always,
Supabase model_snapshots when DATABASE_URL is reachable).

Run:  python backend/learning/bootstrap_training.py [--months 120] [--no-lessons]
"""

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv()  # also pick up a repo-root .env if present

from learning.historical_backtester import HistoricalBacktester
from learning.trade_outcome_model import TradeOutcomeModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("niftymind.learning.bootstrap")


def to_model_trades(backtest_trades: list[dict]) -> list[dict]:
    """Convert backtester output into TradeOutcomeModel training format.

    The backtester emits per-trade `signals` ({agent_id: {direction, confidence}});
    the model trains on `votes` ([{agent_id, direction, confidence}]).
    """
    converted = []
    for t in backtest_trades:
        votes = [
            {"agent_id": aid, "direction": s.get("direction", "NEUTRAL"),
             "confidence": float(s.get("confidence", 0))}
            for aid, s in (t.get("signals") or {}).items()
        ]
        converted.append({**t, "votes": votes})
    return converted


def _db_reachable() -> bool:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(url, connect_timeout=8)
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"DATABASE_URL not reachable ({e}) — training file-only")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Bootstrap-train the trade outcome model")
    parser.add_argument("--months", type=int, default=120,
                        help="Months of daily history to request (default 120 = 10 years)")
    parser.add_argument("--no-lessons", action="store_true",
                        help="Skip storing lessons/agent-accuracy in DB")
    args = parser.parse_args()

    db_ok = _db_reachable()
    store_lessons = db_ok and not args.no_lessons

    logger.info(f"=== Bootstrap training: months={args.months}, "
                f"db={'reachable' if db_ok else 'unavailable'}, "
                f"lessons={'on' if store_lessons else 'off'} ===")

    bt = HistoricalBacktester()
    summary = await bt.run_backtest(
        months=args.months,
        trade_types=["SCALP", "INTRADAY", "BTST"],
        underlyings=["NIFTY", "BANKNIFTY"],
        store_lessons=store_lessons,
    )

    print("\n" + "=" * 64)
    print("  BACKTEST DATA GENERATED")
    print("=" * 64)
    print(f"  Total trades: {summary['total_trades']}  "
          f"(W {summary['wins']} / L {summary['losses']}, WR {summary['win_rate']:.0%})")
    for tt, stats in summary.get("by_type", {}).items():
        print(f"  {tt:9s}: {stats['trades']:5d} trades  WR={stats['win_rate']:.0%}  "
              f"avg=Rs.{stats['avg_pnl']:,.0f}")

    trades = to_model_trades(bt.last_trades)
    if not trades:
        print("\n  No trades generated — model not trained.")
        return 1

    model = TradeOutcomeModel()
    metrics = model.train(trades)

    print("\n" + "=" * 64)
    print("  TRADE OUTCOME MODEL — TRAINING RESULTS")
    print("=" * 64)
    if not metrics:
        print("  Training skipped (insufficient samples or class diversity).")
        return 1

    print(f"  Samples:   {metrics['training_trades']} (test {metrics['test_trades']})")
    print(f"  Accuracy:  {metrics['accuracy']:.3f}  (baseline win-rate {metrics['baseline_win_rate']:.3f})")
    print(f"  Precision: {metrics['precision']:.3f}   Recall: {metrics['recall']:.3f}")
    print(f"  F1:        {metrics['f1']:.3f}   AUC: {metrics['auc']:.3f}")
    top = sorted(metrics["feature_importances"].items(), key=lambda x: x[1], reverse=True)[:6]
    print("  Top features:")
    for name, imp in top:
        print(f"    {name:24s} {imp:.3f}")
    print("=" * 64)
    print(f"  Model persisted: backend/learning/models/latest.pkl"
          f"{' + Supabase model_snapshots' if db_ok else ' (DB skipped)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
