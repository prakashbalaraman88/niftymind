"""End-to-end P&L correctness tests for the paper executor's options handling.

These lock in the June 2026 fixes:
- BEARISH options trades are LONG puts: index falling => premium rising => PROFIT
- Slippage: options entries buy (pay more), exits sell (receive less), both directions
- Trailing stops compare PREMIUM against premium-scale SL/targets (never the index)
- Fully-scaled-out trades record the ORIGINAL quantity and accumulated partial P&L
"""

import asyncio
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import execution.paper_executor as pe_mod
from execution.paper_executor import PaperExecutor


class FakePublisher:
    """Captures published events; no Redis required."""

    def __init__(self):
        self.executions = []
        self.published = []

    async def publish_trade_execution(self, data):
        self.executions.append(data)

    async def publish(self, channel, data):
        self.published.append((channel, data))


@pytest.fixture
def executor(monkeypatch):
    upserts = []
    events = []
    monkeypatch.setattr(pe_mod, "upsert_trade", lambda **kw: upserts.append(kw))
    monkeypatch.setattr(pe_mod, "log_trade_event", lambda **kw: events.append(kw))
    monkeypatch.setattr(pe_mod, "log_audit", lambda **kw: None)

    ex = PaperExecutor(FakePublisher())
    ex._test_upserts = upserts
    ex._test_events = events
    return ex


def _approved_options_trade(trade_id, direction, premium, qty=65, sl_points=30.0,
                            trade_type="INTRADAY"):
    return {
        "event": "RISK_APPROVED",
        "trade_id": trade_id,
        "underlying": "NIFTY",
        "direction": direction,
        "quantity": qty,
        "trade_type": trade_type,
        "confidence": 0.8,
        "supporting_data": {
            "selected_strike": {
                "strike": 24500,
                "option_type": "CE" if direction == "BULLISH" else "PE",
                "ltp": premium,
                "delta": 0.5,
            },
            "sl_points": sl_points,
            "symbol": "NIFTY26JUN24500" + ("CE" if direction == "BULLISH" else "PE"),
        },
    }


def test_bearish_options_profit_when_index_falls(executor):
    """The headline bug: a long PE must PROFIT when the index falls."""
    asyncio.run(_run_bearish_scenario(executor))


async def _run_bearish_scenario(ex):
    ex._latest_prices["NIFTY"] = 24500.0
    await ex._execute_entry(_approved_options_trade("T-PE", "BEARISH", premium=150.0))

    pos = ex._positions["T-PE"]
    assert pos["is_options"] is True
    # Entry slippage on an options BUY must INCREASE the fill
    assert pos["entry_price"] > 150.0

    # Index falls 200 points => PE premium rises ~100 (delta 0.5)
    ex._latest_prices["NIFTY"] = 24300.0
    await ex._execute_exit({"trade_id": "T-PE", "exit_reason": "TARGET_HIT"})

    closed = [u for u in ex._test_upserts if u.get("status") == "CLOSED"]
    assert closed, "trade should be closed"
    assert closed[-1]["pnl"] > 0, (
        f"long PE with index down 200 must be profitable, got {closed[-1]['pnl']}"
    )
    # exit premium should be near entry+100, far below the index price
    assert closed[-1]["exit_price"] < 1000


def test_bullish_options_loss_when_index_falls(executor):
    asyncio.run(_run_bullish_loss_scenario(executor))


async def _run_bullish_loss_scenario(ex):
    ex._latest_prices["NIFTY"] = 24500.0
    await ex._execute_entry(_approved_options_trade("T-CE", "BULLISH", premium=150.0))

    ex._latest_prices["NIFTY"] = 24400.0  # index down 100 => CE premium ~ -50
    await ex._execute_exit({"trade_id": "T-CE", "exit_reason": "SL_HIT"})

    closed = [u for u in ex._test_upserts if u.get("status") == "CLOSED"]
    assert closed[-1]["pnl"] < 0


def test_trailing_uses_premium_not_index(executor):
    """With the index at ~24500 and premium-scale SL at ~120, the first tick
    must NOT trigger SL/targets (the old bug compared 24500 against 120)."""
    asyncio.run(_run_trailing_scale_scenario(executor))


async def _run_trailing_scale_scenario(ex):
    ex._latest_prices["NIFTY"] = 24500.0
    # BTST: no EOD square-off, so the test is deterministic outside market hours
    await ex._execute_entry(
        _approved_options_trade("T-TRAIL", "BEARISH", premium=150.0, trade_type="BTST")
    )

    # Tick with unchanged index: premium estimate == entry premium => no exits
    await ex._update_price({"symbol": "NIFTY 50", "ltp": 24500.0, "underlying": "NIFTY"})
    assert "T-TRAIL" in ex._positions, "position must survive a flat tick"
    assert ex._trade_positions["T-TRAIL"].remaining_quantity > 0

    # Premium-space TradePosition is always BULLISH (long premium)
    assert ex._trade_positions["T-TRAIL"].direction == "BULLISH"


def test_partial_exits_record_original_quantity(executor):
    asyncio.run(_run_partial_exit_scenario(executor))


async def _run_partial_exit_scenario(ex):
    ex._latest_prices["NIFTY"] = 24500.0
    await ex._execute_entry(
        _approved_options_trade("T-PART", "BULLISH", premium=150.0, qty=65, sl_points=20.0)
    )

    # Index surges: premium estimate rises through T1 (1.5R=+30) and T2 (2.5R=+50)
    ex._latest_prices["NIFTY"] = 24700.0  # +200 idx => premium +100
    await ex._run_trailing_stop_updates()

    partial_events = [e for e in ex._test_events if str(e.get("event", "")).startswith("PARTIAL_EXIT")]
    assert partial_events, "targets should have produced partial exits"
    for e in partial_events:
        assert e["pnl"] > 0, f"partial exit at higher premium must profit, got {e['pnl']}"

    closed = [u for u in ex._test_upserts if u.get("status") == "CLOSED"]
    if closed:  # fully scaled out
        assert closed[-1]["quantity"] == 65, "closed record must keep ORIGINAL quantity"
        assert closed[-1]["pnl"] > 0


def test_charges_use_2026_rates():
    from performance.charges import calculate_charges

    res = calculate_charges(entry_price=150.0, exit_price=200.0, quantity=65, is_options=True)
    b = res["breakdown"]
    # STT: 0.15% of sell-side premium = 200*65*0.0015 = 19.5
    assert b["stt"] == pytest.approx(19.5, abs=0.01)
    # Exchange: 0.03553% of (entry+exit) premium turnover
    assert b["exchange"] == pytest.approx((150 + 200) * 65 * 0.0003553, abs=0.01)
    # Flat Rs.20 x 2 orders
    assert b["brokerage"] == 40.0
    assert res["total"] > 0
