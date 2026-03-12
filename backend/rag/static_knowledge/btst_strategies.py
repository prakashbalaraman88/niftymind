"""
Expert Knowledge: BTST (Buy Today Sell Tomorrow) Options Strategies

Sources: NSE F&O research, overnight position management literature,
gap trading research, professional BTST trading methodology.
"""
from . import KnowledgeChunk

DOMAIN = "btst_strategies"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="BTST Strategy Research",
        title="BTST Fundamentals: Risk Framework and When to Trade",
        content="""
BTST (Buy Today, Sell Tomorrow) is a strategy where positions are initiated in the last
hour of the Indian trading session and closed the next morning.

BTST ADVANTAGE:
  - Captures gap move from US session (9:30 PM - 4:00 AM IST) and Asian markets.
  - Low competition window: Fewer traders position overnight.
  - FII flows at EOD often signal next-day direction.
  - Options held overnight: If directional thesis is correct, can 3-5× premium.

BTST REQUIREMENTS — ALL MUST BE MET:
  1. Strong directional consensus from multiple agents (>5 of 7 agree).
  2. Global macro support (US futures aligned with trade direction).
  3. FII/DII EOD flow confirms direction (large net buy = long BTST, net sell = short BTST).
  4. No major event overnight or next morning that contradicts position.
  5. India VIX < 22 (high VIX makes overnight gap risk unacceptable).
  6. NOT Wednesday: Weekly options expire Thursday → overnight theta catastrophic.
  7. Time: 2:30 PM - 3:25 PM window (last 1 hour of trade, AFTER technical direction clear).

WHEN NOT TO DO BTST:
  - Wednesday (weekly expiry tomorrow): Overnight theta decay destroys weekly option value.
  - Day before Budget, RBI policy, FOMC, election results: Gap risk is binary and extreme.
  - India VIX > 22: Gap could be 1-2% in either direction, exceeding option premium.
  - Expiry Thursday: Hold through weekend is fine for monthly options.
  - Poor FII/DII data (selling into close): No institutional support for overnight hold.
  - Contradictory global macro: US rallying but India trend is bearish = confusion.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Options Expiry Selection for BTST",
        title="Weekly vs Monthly Expiry for BTST: Theta, Delta, and Selection Rules",
        content="""
EXPIRY SELECTION FOR BTST OPTIONS — CRITICAL DECISION:

WEEKLY OPTIONS for BTST:
  Pros: Higher delta leverage (bigger % move per index point move).
  Cons: Massive theta decay overnight. Monday-Wednesday weekly option loses significant value.

  Overnight theta for NEAR-EXPIRY weekly option:
  - Monday hold: Lose ~20-30% of ATM premium overnight (1 night = 1/3 of week gone).
  - Tuesday hold: Lose ~25-35% of ATM premium overnight.
  - Wednesday hold: NEVER hold. Expiry Thursday = near-100% overnight theta loss.
  - Thursday hold (for next week): OK, similar to Monday.

  RULE: Only hold weekly options BTST on Monday or Thursday (not Tuesday, NEVER Wednesday).

MONTHLY OPTIONS for BTST:
  Pros: Low overnight theta (<5% of premium per overnight). Safer hold.
  Cons: Lower delta, less leverage.

  Monthly ATM option overnight theta:
  - With 20 DTE (days to expiry): Theta ≈ 0.1% of premium per night. Negligible.
  - With 10 DTE: Theta ≈ 0.2% per night. Still acceptable.
  - With 3 DTE: Theta ≈ 1-2% per night. Getting expensive.

  RULE: Monthly options are the DEFAULT for BTST. Use weekly ONLY Monday/Thursday.
  Wednesday HARD RULE: Force to monthly if Claude suggests weekly on Wednesday.

STRIKE SELECTION FOR BTST:
  Optimal: Slightly ITM (1-2 strikes in-the-money).
  ITM delta: 0.60-0.75 → better delta capture on gap move.
  ATM delta: 0.50 → moderate capture.
  OTM: Too low delta for BTST (gap might be 0.3-0.5%, OTM delta of 0.25 captures little).

  Example: Nifty at 24,000. Bullish BTST.
  Buy 23,800 CE (ITM, delta ~0.70) → Monthly. Captures 70% of gap move.
  Don't buy 24,200 CE (OTM, delta ~0.30) → Only captures 30% of gap move.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Overnight Gap Analysis Research",
        title="Overnight Gap Prediction Framework and BTST Positioning",
        content="""
OVERNIGHT GAP PREDICTION MODEL FOR NIFTY/BANKNIFTY:

PRIMARY INDICATOR: Gift Nifty / SGX Nifty at 6:00 AM IST
  Gift Nifty +0.5%: Expect Nifty to open +0.35-0.45%.
  Gift Nifty -0.5%: Expect Nifty to open -0.35-0.45%.
  Conversion factor: Real gap ≈ 0.7 × Gift Nifty change.

COMPONENT ANALYSIS:

US Market (S&P 500 close):
  S&P 500 +1%: Nifty expected +0.4-0.5%.
  S&P 500 -1%: Nifty expected -0.4-0.5%.
  Weight in overnight model: 40%.

Asian Markets at 8:00 AM IST:
  Nikkei strong (+1%): Add +0.1-0.2% to Nifty expectation.
  Hang Seng strong (+1%): Add +0.1-0.15% to Nifty.
  Weight: 20%.

Crude Oil:
  Crude -2% overnight: Add +0.1-0.2% to Nifty (lower import costs).
  Crude +2% overnight: Subtract -0.1-0.2% from Nifty.
  Weight: 10%.

USD/INR:
  INR strengthens 0.5% overnight: Add +0.1% to Nifty.
  INR weakens 0.5% overnight: Subtract -0.1%.
  Weight: 10%.

DXY:
  DXY -0.5%: Risk-on, add +0.1-0.15% to Nifty.
  DXY +0.5%: Risk-off, subtract -0.1-0.15%.
  Weight: 10%.

India-specific overnight news: ±0.5% to ±2.0% depending on severity.
Weight: 10% baseline, can dominate all other signals.

COMPOSITE OVERNIGHT EXPECTED MOVE:
  Sum all weighted components → if > +0.5% → LONG BTST.
  If < -0.5% → SHORT BTST (buy PE).
  If between -0.5% and +0.5% → NO BTST (insufficient edge).
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="BTST Risk Management",
        title="BTST Position Sizing, Stop Losses, and Exit Strategies",
        content="""
BTST POSITION SIZING:
  Maximum: 1 lot per ₹5 lakh capital (halved from normal intraday sizing).
  Rationale: Overnight gap risk is BINARY. Cannot be stopped out intraday.
  Conservative: 0.5 lots per ₹5 lakh (especially when VIX is elevated).
  Never exceed 2 lots BTST regardless of capital (unmanageable gap risk).

STOP LOSSES FOR BTST:
  Cannot use normal intraday stops (position held overnight).
  Use MENTAL STOPS at next-day open:
  Nifty BTST:
    If long CE and Nifty opens > 30 points up: Hold, trend is working.
    If long CE and Nifty opens 0-30 points up: Evaluate. If no further strength, exit.
    If long CE and Nifty opens flat or down: Exit immediately (thesis failed).
    If long CE and Nifty opens > 50 points DOWN: EMERGENCY EXIT at open. Gap against position.

  Premium-based stop: Exit if option premium falls > 25-30% from entry.
  Time stop: Exit by 10:00 AM IST regardless (BTST is for gap capture, not intraday hold).

TARGET EXITS:
  Target 1 (50% of position): +50-60% premium gain.
  Target 2 (remaining 50%): +80-100% premium gain or trail stop.
  Trailing stop after T1: Move stop to break-even.
  Time-based exit: If no move by 10:30 AM, exit remaining position regardless.

EOD BTST SETUP CHECKLIST:
  □ Time: 2:30-3:25 PM? YES/NO
  □ Day: Not Wednesday? YES/NO
  □ VIX < 22? YES/NO
  □ No overnight event risk? YES/NO
  □ FII EOD net in your direction? YES/NO
  □ US futures in your direction? YES/NO
  □ 5+ agents consensus? YES/NO
  □ Strike: ITM or ATM monthly? YES/NO
  All YES → Execute. Any NO → Skip.
        """,
    ),
]
