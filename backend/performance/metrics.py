"""Calculate trading performance metrics: win rate, profit factor, Sharpe, max drawdown."""

import math
from typing import List


def calculate_metrics(trades: List[dict]) -> dict:
    """Calculate all performance metrics from a list of trades.

    Each trade dict must have: pnl (float), entry_time (str), exit_time (str)
    """
    if not trades:
        return _empty_metrics()

    pnls = [t["pnl"] for t in trades]
    total_trades = len(pnls)
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]

    win_rate = len(winners) / total_trades if total_trades > 0 else 0
    avg_win = sum(winners) / len(winners) if winners else 0
    avg_loss = abs(sum(losers) / len(losers)) if losers else 0
    avg_rr = avg_win / avg_loss if avg_loss > 0 else float("inf")

    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    net_pnl = sum(pnls)

    # Expectancy per trade
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # Max drawdown
    peak = 0
    max_dd = 0
    cumulative = 0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)

    # Sharpe ratio (annualized, assuming 252 trading days)
    if len(pnls) > 1:
        mean_return = sum(pnls) / len(pnls)
        variance = sum((p - mean_return) ** 2 for p in pnls) / (len(pnls) - 1)
        std_return = math.sqrt(variance)
        sharpe = (mean_return / std_return) * math.sqrt(252) if std_return > 0 else 0
    else:
        sharpe = 0

    return {
        "total_trades": total_trades,
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_rr": round(avg_rr, 2),
        "profit_factor": round(profit_factor, 2),
        "net_pnl": round(net_pnl, 2),
        "expectancy": round(expectancy, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
    }


def _empty_metrics() -> dict:
    return {
        "total_trades": 0, "winners": 0, "losers": 0, "win_rate": 0,
        "avg_win": 0, "avg_loss": 0, "avg_rr": 0, "profit_factor": 0,
        "net_pnl": 0, "expectancy": 0, "max_drawdown": 0, "sharpe_ratio": 0,
        "gross_profit": 0, "gross_loss": 0,
    }


def is_proof_threshold_met(metrics: dict) -> dict:
    """Check if system has met the proof-of-profitability gate."""
    return {
        "sufficient_trades": metrics["total_trades"] >= 100,
        "profitable": metrics["profit_factor"] > 1.5,
        "good_win_rate": metrics["win_rate"] > 0.55,
        "acceptable_drawdown": metrics["max_drawdown"] < metrics.get("capital", 100000) * 0.15,
        "recommendation": "READY_FOR_LIVE" if (
            metrics["total_trades"] >= 100
            and metrics["profit_factor"] > 1.5
            and metrics["win_rate"] > 0.55
        ) else "CONTINUE_PAPER_TRADING",
    }
