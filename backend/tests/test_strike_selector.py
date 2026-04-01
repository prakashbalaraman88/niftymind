import pytest
from agents.strike_selector import StrikeSelector

def test_scalp_prefers_atm():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 24000, "option_type": "CE", "delta": 0.52, "oi": 80000, "bid": 150, "ask": 153, "ltp": 151, "iv": 15.0},
        {"strike": 24050, "option_type": "CE", "delta": 0.42, "oi": 60000, "bid": 120, "ask": 124, "ltp": 122, "iv": 16.0},
        {"strike": 24100, "option_type": "CE", "delta": 0.33, "oi": 40000, "bid": 90, "ask": 95, "ltp": 92, "iv": 17.5},
    ]
    result = selector.select_strike("SCALP", "BULLISH", 24010, options, "NIFTY")
    assert result is not None
    assert result["strike"] == 24000  # ATM preferred for scalp

def test_rejects_low_oi():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 24000, "option_type": "CE", "delta": 0.50, "oi": 10000, "bid": 150, "ask": 155, "ltp": 152, "iv": 15.0},
    ]
    result = selector.select_strike("SCALP", "BULLISH", 24010, options, "NIFTY")
    assert result is None  # OI too low (< 50000 for scalp)

def test_rejects_wide_spread():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 24000, "option_type": "CE", "delta": 0.50, "oi": 100000, "bid": 150, "ask": 160, "ltp": 155, "iv": 15.0},
    ]
    result = selector.select_strike("SCALP", "BULLISH", 24010, options, "NIFTY")
    assert result is None  # Spread 10 > max 3 for scalp

def test_btst_prefers_itm_monthly():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 23900, "option_type": "CE", "delta": 0.62, "oi": 70000, "bid": 195, "ask": 199, "ltp": 197, "iv": 14.0, "expiry_type": "MONTHLY"},
        {"strike": 24000, "option_type": "CE", "delta": 0.50, "oi": 90000, "bid": 150, "ask": 153, "ltp": 151, "iv": 15.0, "expiry_type": "WEEKLY"},
    ]
    result = selector.select_strike("BTST", "BULLISH", 24010, options, "NIFTY")
    assert result is not None
    assert result["strike"] == 23900  # Monthly + ITM preferred for BTST

def test_rejects_penny_options():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 24500, "option_type": "CE", "delta": 0.05, "oi": 200000, "bid": 3, "ask": 5, "ltp": 4, "iv": 50.0},
    ]
    result = selector.select_strike("INTRADAY", "BULLISH", 24010, options, "NIFTY")
    assert result is None  # Premium < 10
