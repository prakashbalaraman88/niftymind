import pytest
from risk.drawdown_manager import DrawdownManager

def test_consecutive_losses_reduce_size():
    mgr = DrawdownManager(capital=100000)
    mgr.record_trade(pnl=-500)
    mgr.record_trade(pnl=-300)
    mgr.record_trade(pnl=-200)
    assert mgr.size_multiplier == 0.5  # 3 losses → 50% reduction

def test_recovery_after_losses():
    mgr = DrawdownManager(capital=100000)
    mgr.record_trade(pnl=-500)
    mgr.record_trade(pnl=-300)
    mgr.record_trade(pnl=-200)
    assert mgr.size_multiplier == 0.5
    mgr.record_trade(pnl=400)
    mgr.record_trade(pnl=300)
    assert mgr.size_multiplier == 1.0  # Recovered after 2 trades

def test_consecutive_wins_reduce_size():
    mgr = DrawdownManager(capital=100000)
    for _ in range(5):
        mgr.record_trade(pnl=500)
    assert mgr.size_multiplier == 0.75  # 5 wins → 25% reduction

def test_drawdown_circuit_breaker():
    mgr = DrawdownManager(capital=100000)
    mgr._peak_equity = 100000
    mgr._current_equity = 84000  # 16% drawdown
    assert mgr.should_pause_trading()  # >15% drawdown
