"""
Expert Knowledge: F&O Scalping Strategies for NSE

Sources: Inner Circle Trader methodology, Market Profile scalping,
professional day trading research, NSE F&O transaction cost analysis.
"""
from . import KnowledgeChunk

DOMAIN = "scalping"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="Professional Scalping Research",
        title="NSE F&O Scalping: Cost Structure, Edge Requirements, and Setup Quality",
        content="""
F&O SCALPING ECONOMICS IN INDIA:

TRANSACTION COSTS (per round trip, Nifty 1 lot = 25 units):
  Brokerage (Zerodha): ₹20 flat per order × 2 = ₹40.
  STT (Securities Transaction Tax): 0.0625% of premium on BUY side.
    At ATM option ₹100: 0.0625% × ₹100 × 25 = ₹1.56 per lot.
  Exchange transaction charges: 0.053% of premium.
    ₹100 premium × 0.053% × 25 = ₹1.33 per lot.
  GST on charges: 18% on (brokerage + transaction charges).
  SEBI charges: ₹10 per crore.
  Stamp duty: 0.003% of premium on BUY side.

  APPROXIMATE TOTAL COST: ₹60-70 per round trip per lot (for ATM options at ₹100 premium).
  For BankNifty (15 lots): Similar but lot size smaller.

MINIMUM EDGE REQUIREMENT FOR SCALPING:
  Option premium must move > ₹3-4 per unit AFTER costs to be profitable.
  Nifty ATM at ₹100: Need > 3% move in premium = > 3 Nifty points (with delta 1.0 at ATM).
  Realistic: Target 5-10 Nifty points on scalp trades (premium gain ₹5-10 per unit).
  With ₹5 premium gain × 25 lots = ₹125 gross profit per lot.
  After ₹70 costs = ₹55 net per lot. Only viable with 3:1+ risk-reward.

SCALPING VIABILITY WINDOW (NSE):
  9:15-9:45 AM: AVOID. Spreads too wide. Algo wars. High false breakouts.
  9:45-10:30 AM: BEST for scalping. Direction established. Volume high. Tight spreads.
  10:30-11:30 AM: Good. Continuation trades only.
  11:30-1:30 PM: AVOID. Lunch consolidation. Low volume. Theta pain for buyers.
  1:30-2:30 PM: Fair. Wait for institutional re-entry signals.
  2:30-3:30 PM: Good. High volume. Direction often accelerates. But reversals are sharp.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Multi-Factor Scalping Setup Research",
        title="Minimum Signal Requirements for High-Probability Scalp Entries",
        content="""
MULTI-FACTOR SCALP ENTRY FRAMEWORK:
  Requires alignment across OPTIONS CHAIN + ORDER FLOW + VOLUME PROFILE + TECHNICAL.
  Minimum 3 of 4 must align for scalp trade execution.

FACTOR 1 — OPTIONS CHAIN SIGNAL:
  BULLISH: PCR rising, large PE OI buildup at support (writers defending), CE OI unwinding.
  BEARISH: PCR falling, large CE OI buildup at resistance, PE OI unwinding.
  Minimum confidence: 0.60+.

FACTOR 2 — ORDER FLOW SIGNAL:
  BULLISH: Positive delta on 1-min footprint, ask imbalances stacking, large lot buying.
  BEARISH: Negative delta, bid imbalances, large lot selling.
  This is the HIGHEST WEIGHT factor for scalping (35% weight).
  Without order flow confirmation, do NOT scalp.

FACTOR 3 — VOLUME PROFILE SIGNAL:
  BULLISH: Price above VWAP, approaching LVN (fast travel zone) above, bouncing from HVN.
  BEARISH: Price below VWAP, approaching LVN below, rejected from HVN.
  Key: LVN scalp = price enters thin LVN → will travel quickly through it → ride the speed.

FACTOR 4 — TECHNICAL SIGNAL:
  BULLISH: 9 EMA > 20 EMA on 1-min, RSI > 50, breaking OR High.
  BEARISH: 9 EMA < 20 EMA on 1-min, RSI < 50, breaking OR Low.
  CPR: Price holding above TC (Top CPR) = bullish scalp bias.
        Price holding below BC (Bottom CPR) = bearish scalp bias.

SCALP SETUP GRADING:
  A+ Scalp: All 4 factors aligned + high volume + LVN entry + Camarilla level broken.
  A Scalp: 3 of 4 factors + volume confirmation.
  B Scalp: 2 of 4 factors → REDUCE SIZE by 50%.
  No trade: < 2 factors, or conflicting high-weight signals.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Scalp Trade Execution Rules",
        title="Scalp Execution: Entry Timing, Stop Loss, Target, and Cooldown Rules",
        content="""
SCALP TRADE EXECUTION RULES:

ENTRY TIMING:
  Best entry: Break of 1-min candle HIGH (long) or LOW (short) with above-average volume.
  Do NOT chase: If price has already moved 5+ Nifty points from setup, SKIP.
  Entry on RETEST: Price breaks level, pulls back to test, holds, re-enters → best entry.
  Never market order: Always limit orders within 1-2 points of bid/ask.

STOP LOSS (non-negotiable):
  Fixed premium stop: -₹15-20 per unit on Nifty options (3-4 Nifty points equivalent for ATM delta 0.50).
  Index-based stop: Below entry candle low (long) or above entry candle high (short).
  Max stop: Never risk more than 0.5% of capital per scalp (₹2,500 on ₹5L account).

  RULE: If stop hit → EXIT IMMEDIATELY. No averaging down on scalps.

TARGET:
  Minimum target: 2× stop (2:1 R:R). With ₹15 stop → minimum ₹30 target.
  First target: Take 50-70% of position at 1.5× stop.
  Trail remainder: Move stop to break-even after T1. Target Camarilla H3/L3 or next HVN.

COOLDOWN RULE:
  Mandatory 30-second pause between scalp trades (prevents emotional over-trading).
  After 2 consecutive losses: Mandatory 15-minute cooldown break.
  After 3 consecutive losses: Stop scalping for the session. Switch to monitoring only.
  Daily scalp limit: Maximum 10 scalp trades per day OR ₹10,000 net loss, whichever first.

EXPIRY DAY SCALPING:
  Higher gamma = more premium movement per Nifty point → good for scalpers.
  But: WIDER BID-ASK spreads in the last 30 minutes.
  Best scalp window on expiry: 9:45-11:00 AM (gamma active, spreads manageable).
  AVOID scalping expiry after 2:30 PM: Gamma explosion, spreads 10-20 points wide.
        """,
    ),
]
