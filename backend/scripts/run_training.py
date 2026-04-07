"""Run full backtest + model training pipeline.

Usage:
    cd backend
    python scripts/run_training.py [--months 6] [--retrain-only]

Steps:
1. Downloads 6 months of NIFTY/BANKNIFTY data via Yahoo Finance
2. Simulates all 7 agent signals on every bar
3. Generates SCALP / INTRADAY / BTST trades with realistic P&L
4. Stores lessons to Supabase
5. Trains GradientBoosting model on all stored lessons
6. Saves model snapshot to Supabase
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("niftymind.training")


async def main(months: int = 6, retrain_only: bool = False):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    from config import AppConfig
    config = AppConfig()

    # ── Step 1: Historical Backtest ──────────────────────────────────────────
    if not retrain_only:
        # Use Fyers REST data (real NSE candles) when credentials available,
        # fall back to Yahoo Finance automatically inside FyersBacktester.
        logger.info(f"Starting {months}-month backtest with Fyers/NSE data...")
        from learning.fyers_backtester import FyersBacktester
        bt = FyersBacktester(fyers_config=config.fyers, llm_config=config.llm)
        summary = await bt.run_backtest(
            months=months,
            trade_types=["SCALP", "INTRADAY", "BTST"],
            underlyings=["NIFTY", "BANKNIFTY"],
            store_lessons=True,
        )

        print("\n" + "=" * 62)
        print(f"  BACKTEST RESULTS  [{summary.get('data_source', 'unknown')}]")
        print("=" * 62)
        print(f"  Total trades : {summary['total_trades']}")
        print(f"  Wins         : {summary['wins']}")
        print(f"  Losses       : {summary['losses']}")
        print(f"  Win rate     : {summary['win_rate']:.1%}")
        print(f"  Total P&L    : Rs.{summary['total_pnl']:>10,.0f}")
        print(f"  Avg P&L/trade: Rs.{summary['avg_pnl']:>10,.0f}")
        print()
        for tt, stats in summary.get("by_type", {}).items():
            print(f"  {tt:<10}: {stats['trades']:>4} trades  "
                  f"WR={stats['win_rate']:.0%}  Avg=Rs.{stats['avg_pnl']:,.0f}")
        for ul, stats in summary.get("by_underlying", {}).items():
            print(f"  {ul:<10}: {stats['trades']:>4} trades  WR={stats['win_rate']:.0%}")
        print("=" * 62)
    else:
        logger.info("--retrain-only: skipping backtest, using existing lessons")

    # ── Step 2: Load all stored lessons & train model ────────────────────────
    logger.info("Loading all lessons from Supabase for model training...")
    from learning.lesson_store import LessonStore
    store = LessonStore()
    lessons = store.get_all_lessons_for_training()
    logger.info(f"Found {len(lessons)} stored lessons")

    if len(lessons) < 10:
        logger.warning("Too few lessons to train (<10). Backtest may not have stored data.")
        return

    # ── Step 3: Train GradientBoosting model ─────────────────────────────────
    logger.info("Training trade outcome model...")
    from learning.trade_outcome_model import TradeOutcomeModel
    model = TradeOutcomeModel()
    metrics = model.train(lessons)

    print("\n" + "=" * 62)
    print("  MODEL TRAINING RESULTS")
    print("=" * 62)
    print(f"  Training samples : {metrics.get('training_trades', '?')}")
    print(f"  Test accuracy    : {metrics.get('accuracy', 0):.1%}")
    print(f"  Precision        : {metrics.get('precision', 0):.1%}")
    print(f"  Recall           : {metrics.get('recall', 0):.1%}")
    print(f"  F1 score         : {metrics.get('f1', 0):.3f}")

    if "feature_importances" in metrics:
        print("\n  Top 10 Feature Importances:")
        importances = sorted(
            metrics["feature_importances"].items(), key=lambda x: x[1], reverse=True
        )[:10]
        for feat, imp in importances:
            bar = "#" * int(imp * 40)
            print(f"    {feat:<35} {imp:.3f} {bar}")
    print("=" * 62)

    # Note: model.train() persists the snapshot to Supabase internally.
    logger.info("Model trained and saved. Training complete.")

    # ── Step 5: Print agent accuracy summary ─────────────────────────────────
    logger.info("Loading agent accuracy stats...")
    try:
        from learning.agent_accuracy_tracker import AgentAccuracyTracker
        tracker = AgentAccuracyTracker(config.learning)
        rows = tracker.get_all_accuracies()
        if rows:
            print("\n" + "=" * 70)
            print("  AGENT ACCURACY SUMMARY (all trade types & regimes)")
            print("=" * 70)
            print(f"  {'Agent':<25} {'Type':<10} {'Regime':<10} {'Signals':>7} {'Acc':>6} {'Wt':>6}")
            print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*7} {'-'*6} {'-'*6}")
            for r in rows:
                acc = float(r.get("accuracy", 0))
                bar = "#" * int(acc * 10)
                print(f"  {r['agent_id']:<25} {r['trade_type']:<10} {r['market_regime']:<10} "
                      f"{r['total_signals']:>7} {acc:>5.0%} {float(r['weight_multiplier']):>5.2f}x  {bar}")
            print("=" * 70)
    except Exception as e:
        logger.warning(f"Could not load agent accuracy: {e}")

    print("\nDone. Agents are pre-trained and ready for tomorrow.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NiftyMind training pipeline")
    parser.add_argument("--months", type=int, default=6, help="Months of history to backtest")
    parser.add_argument("--retrain-only", action="store_true", help="Skip backtest, retrain model only")
    args = parser.parse_args()
    asyncio.run(main(months=args.months, retrain_only=args.retrain_only))
