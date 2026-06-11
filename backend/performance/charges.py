"""
Indian equity derivatives charges calculator.
Deducted from P&L to give realistic net profitability.

Rates verified June 2026 (zerodha.com/charges, NSE circulars):
- STT hiked effective 1 Apr 2026: options 0.15% on sell premium, futures 0.05% sell side.
- NSE transaction charges: options 0.03553% on premium, futures 0.00183%.
- GST 18% applies to brokerage + transaction charges + SEBI fee.
"""

# STT (Securities Transaction Tax) — charged on sell side only
STT_OPTIONS_SELL = 0.0015   # 0.15% on sell-side premium (effective 1 Apr 2026)
STT_FUTURES_SELL = 0.0005   # 0.05% on sell-side value (effective 1 Apr 2026)

# Exchange transaction charges (NSE, on premium for options)
EXCHANGE_NFO_OPTIONS = 0.0003553  # 0.03553% on premium turnover
EXCHANGE_NFO_FUTURES = 0.0000183  # 0.00183% on turnover

# SEBI turnover fee — ₹10 per crore, both sides
SEBI_FEE = 0.000001

# Stamp duty (on buy side only)
STAMP_DUTY_OPTIONS = 0.00003  # 0.003% on buy-side premium
STAMP_DUTY_FUTURES = 0.00002  # 0.002% on buy-side value

# GST on (brokerage + exchange transaction charges + SEBI fee)
GST_RATE = 0.18

# Zerodha flat brokerage
BROKERAGE_PER_ORDER = 20.0  # ₹20 per executed order (options); futures min(0.03%, ₹20)


def calculate_charges(
    entry_price: float,
    exit_price: float,
    quantity: int,
    is_options: bool = True,
) -> dict:
    """
    Calculate all-in charges for a round-trip options/futures trade.
    Buy at entry, sell at exit (long-premium system). Returns dict with breakdown and total.
    """
    if entry_price <= 0 or quantity <= 0:
        return {"total": 0.0, "breakdown": {}}

    entry_value = entry_price * quantity
    exit_value = exit_price * quantity if exit_price > 0 else entry_value

    if is_options:
        stt = exit_value * STT_OPTIONS_SELL
        exchange = (entry_value + exit_value) * EXCHANGE_NFO_OPTIONS
        stamp = entry_value * STAMP_DUTY_OPTIONS
        brokerage_entry = BROKERAGE_PER_ORDER
        brokerage_exit = BROKERAGE_PER_ORDER
    else:
        stt = exit_value * STT_FUTURES_SELL
        exchange = (entry_value + exit_value) * EXCHANGE_NFO_FUTURES
        stamp = entry_value * STAMP_DUTY_FUTURES
        brokerage_entry = min(BROKERAGE_PER_ORDER, entry_value * 0.0003)
        brokerage_exit = min(BROKERAGE_PER_ORDER, exit_value * 0.0003)

    sebi = (entry_value + exit_value) * SEBI_FEE
    brokerage = brokerage_entry + brokerage_exit
    gst = (brokerage + exchange + sebi) * GST_RATE

    total = round(stt + exchange + stamp + sebi + brokerage + gst, 2)

    return {
        "total": total,
        "breakdown": {
            "stt": round(stt, 2),
            "exchange": round(exchange, 2),
            "stamp_duty": round(stamp, 2),
            "sebi_fee": round(sebi, 4),
            "brokerage": round(brokerage, 2),
            "gst": round(gst, 2),
        },
    }


def net_pnl(gross_pnl: float, entry_price: float, exit_price: float,
            quantity: int, is_options: bool = True) -> tuple[float, dict]:
    """Return (net_pnl, charges_dict) after deducting all charges."""
    charges = calculate_charges(entry_price, exit_price, quantity, is_options)
    return round(gross_pnl - charges["total"], 2), charges
