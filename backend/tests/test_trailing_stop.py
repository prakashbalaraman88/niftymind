import pytest
from execution.trailing_stop import TrailingStopManager, TradePosition

def test_initial_sl_set():
    mgr = TrailingStopManager(capital=100000)
    pos = TradePosition(
        trade_id="T001", entry_price=150.0, sl_price=130.0,
        direction="BULLISH", quantity=50, strategy="INTRADAY",
        targets=[{"ratio": 1.5, "exit_pct": 0.6}, {"ratio": 2.5, "exit_pct": 0.3}, {"ratio": 999, "exit_pct": 0.1}],
    )
    assert pos.sl_price == 130.0
    assert pos.risk_per_unit == 20.0

def test_t1_hit_moves_sl_to_breakeven():
    mgr = TrailingStopManager(capital=100000)
    pos = TradePosition(
        trade_id="T001", entry_price=150.0, sl_price=130.0,
        direction="BULLISH", quantity=50, strategy="INTRADAY",
        targets=[{"ratio": 1.5, "exit_pct": 0.6}, {"ratio": 2.5, "exit_pct": 0.3}, {"ratio": 999, "exit_pct": 0.1}],
    )
    # T1 = entry + 1.5 * risk = 150 + 1.5 * 20 = 180
    actions = mgr.update(pos, current_price=181.0)
    assert any(a["action"] == "PARTIAL_EXIT" for a in actions)
    assert pos.sl_price == 150.0  # Moved to breakeven

def test_sl_hit():
    mgr = TrailingStopManager(capital=100000)
    pos = TradePosition(
        trade_id="T001", entry_price=150.0, sl_price=130.0,
        direction="BULLISH", quantity=50, strategy="INTRADAY",
    )
    actions = mgr.update(pos, current_price=129.0)
    assert any(a["action"] == "FULL_EXIT_SL" for a in actions)
