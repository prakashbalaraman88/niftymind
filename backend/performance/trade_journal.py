"""Structured trade journal with full context logging."""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("niftymind.journal")

IST = timezone(timedelta(hours=5, minutes=30))


class TradeJournal:
    def __init__(self, journal_dir: str = "data/journal"):
        self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self._trades: list[dict] = []

    def record_entry(self, trade_id: str, entry_data: dict):
        """Record trade entry with full context."""
        entry = {
            "trade_id": trade_id,
            "status": "OPEN",
            "entry_time": datetime.now(IST).isoformat(),
            "entry_price": entry_data.get("entry_price"),
            "strike": entry_data.get("strike"),
            "option_type": entry_data.get("option_type"),
            "underlying": entry_data.get("underlying"),
            "direction": entry_data.get("direction"),
            "quantity": entry_data.get("quantity"),
            "strategy": entry_data.get("strategy"),
            "sl_price": entry_data.get("sl_price"),
            "targets": entry_data.get("targets", []),
            "agent_votes": entry_data.get("agent_votes", {}),
            "consensus_score": entry_data.get("consensus_score"),
            "reasoning": entry_data.get("reasoning"),
            "iv_at_entry": entry_data.get("iv"),
            "vix_at_entry": entry_data.get("vix"),
        }
        self._trades.append(entry)
        self._save_trade(entry)
        return entry

    def record_exit(self, trade_id: str, exit_data: dict):
        """Record trade exit with P&L and context."""
        for trade in self._trades:
            if trade["trade_id"] == trade_id:
                trade["status"] = "CLOSED"
                trade["exit_time"] = datetime.now(IST).isoformat()
                trade["exit_price"] = exit_data.get("exit_price")
                trade["exit_reason"] = exit_data.get("reason")
                trade["pnl"] = exit_data.get("pnl", 0)
                trade["slippage"] = exit_data.get("slippage", 0)
                trade["rr_achieved"] = exit_data.get("rr_achieved", 0)
                trade["targets_hit"] = exit_data.get("targets_hit", [])
                self._save_trade(trade)
                return trade
        return None

    def get_closed_trades(self) -> list[dict]:
        return [t for t in self._trades if t["status"] == "CLOSED"]

    def _save_trade(self, trade: dict):
        """Save trade to daily journal file."""
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
        filepath = self.journal_dir / f"journal_{date_str}.jsonl"
        with open(filepath, "a") as f:
            f.write(json.dumps(trade) + "\n")
