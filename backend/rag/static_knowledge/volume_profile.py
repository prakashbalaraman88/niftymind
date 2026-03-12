"""
Expert Knowledge: Volume Profile and Market Profile Analysis

Sources: J. Peter Steidlmayer (Market Profile, CBOT 1985), James Dalton
(Mind Over Markets, Markets in Profile), CME Group education, VWAP research.
"""
from . import KnowledgeChunk

DOMAIN = "volume_profile"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="J. Peter Steidlmayer - CBOT Market Profile",
        title="Market Profile Theory: Auction Market Fundamentals",
        content="""
MARKET PROFILE was developed by J. Peter Steidlmayer at CBOT in 1985.
Core insight: Markets are AUCTION processes — price moves UP to find sellers,
price moves DOWN to find buyers. Fair value is where time is maximized.

FUNDAMENTAL PRINCIPLE (Auction Market Theory):
  The market's primary function is to FACILITATE TRADE — bring together buyers and sellers.
  When the market prices too low: buyers overwhelm sellers → price rises (seeking sellers).
  When the market prices too high: sellers overwhelm buyers → price falls (seeking buyers).
  FAIR VALUE: price where both buyers and sellers are satisfied → time maximized → VALUE AREA.

TPO (TIME PRICE OPPORTUNITY):
  Each 30-minute period is assigned a letter (A, B, C...).
  At each price level, a letter is placed for each period price traded there.
  More letters at a price = more TIME spent there = higher value = stronger support/resistance.

NORMAL DISTRIBUTION:
  In a BALANCED market day:
    - Profile has bell-curve shape centered at POC.
    - 70% of time in Value Area (VA).
    - Extremes (Initial Balance High/Low) = price rejected after auction.
  In a TREND day:
    - Profile is skewed or elongated.
    - Multiple POCs forming a staircase up or down.
    - Value area migrates strongly in one direction.

PROFILE SHAPES AND DAY TYPE IDENTIFICATION:
  - "D" shape: Normal distribution. Balanced. Fade extremes.
  - "b" shape: Selling tail at top, distribution at bottom. Bearish.
  - "p" shape: Buying tail at bottom, distribution at top. Bullish.
  - "B" shape: Double distribution. Two-timeframe activity. Trend day likely next day.
  - Thin/elongated: Trend day. Do NOT fade — follow the trend.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="James Dalton - Mind Over Markets",
        title="Point of Control, Value Area, and Key Profile Levels",
        content="""
POINT OF CONTROL (POC):
  The single price level with the MOST trading activity (time or volume).
  POC acts as a MAGNET — price returns to POC repeatedly.
  - VWAP ≈ Volume-based POC for the session.
  - POC from previous session = key reference for next day.
  - Price above POC: bullish. Price below POC: bearish.
  - Price rapidly passing through POC without accepting = trend strength.

VALUE AREA (VA):
  The range of prices containing approximately 70% of total volume (or TPOs).
  - Value Area High (VAH): Top of value area.
  - Value Area Low (VAL): Bottom of value area.
  - Trading WITHIN value area = balanced, range-bound behavior expected.
  - Trading OUTSIDE value area = potential trend day, follow breakout direction.

VALUE AREA RULE (most reliable Market Profile rule):
  If price opens ABOVE yesterday's VAH and stays above VAH for first 30-60 min:
    → Market accepted higher value → BULLISH → trade long toward higher targets.
  If price opens BELOW yesterday's VAL and stays below for first 30-60 min:
    → Market accepted lower value → BEARISH → trade short toward lower targets.
  If price opens OUTSIDE value area but RETURNS within 30-60 min:
    → Attempted breakout FAILED → expect rotation back to opposite end of value area.

HIGH VOLUME NODES (HVN):
  Price levels with significantly more volume than surrounding levels.
  HVN = PRICE ACCEPTANCE zones.
  - Price SLOWS DOWN at HVN (buyers and sellers agree on value here).
  - HVN acts as SUPPORT when approached from above.
  - HVN acts as RESISTANCE when approached from below.
  - Breaking through HVN with high volume = significant.

LOW VOLUME NODES (LVN):
  Price levels with significantly LESS volume than surrounding levels.
  LVN = PRICE REJECTION zones.
  - Price ACCELERATES through LVN (no agreement at these prices).
  - LVN between two HVNs = price travels quickly from one HVN to another.
  - LVN breakouts are fast and violent — set stops BELOW the LVN, not inside it.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="VWAP Trading Research",
        title="VWAP: Institutional Benchmark, Bands, and Trading Signals",
        content="""
VWAP (Volume Weighted Average Price):
  Formula: VWAP = Σ(Price × Volume) / Σ(Volume)
  Resets at market open (9:15 AM IST for NSE) each day.

WHY VWAP MATTERS INSTITUTIONALLY:
  - Large institutions judge trader performance against VWAP.
  - Buy below VWAP = good fill. Sell above VWAP = good fill.
  - SEBI regulated portfolios often required to execute near VWAP.
  - VWAP is the institutional "fair price" for the day.

VWAP AS SUPPORT/RESISTANCE:
  - Price above VWAP: Intraday trend is BULLISH. Institutions are "trapped" below VWAP.
  - Price below VWAP: Intraday trend is BEARISH. Institutions are "trapped" above VWAP.
  - First test of VWAP from above after a morning rally: often a BUY (institutional demand).
  - First test of VWAP from below after a morning decline: often a SELL (institutional supply).
  - Multiple failed tests of VWAP from one side → price likely to break to the other side.

VWAP STANDARD DEVIATION BANDS (MVWAP):
  - 1 SD Band: Contains ~68% of normal intraday price action.
  - 2 SD Band: Contains ~95%. Mean-reversion trades fade extremes at 2 SD.
  - Price reaching 2 SD above VWAP: Extremely overbought intraday → fade short.
  - Price reaching 2 SD below VWAP: Extremely oversold intraday → fade long.
  - TREND DAYS: Price stays at 1-2 SD above/below VWAP all day (do NOT fade).

ANCHORED VWAP (AVWAP):
  Calculate VWAP from a SPECIFIC anchor point (major high, major low, breakout bar).
  - AVWAP from previous significant low = dynamic support.
  - AVWAP from previous significant high = dynamic resistance.
  - Monthly AVWAP from start of month = institutional monthly target.
  - NSE use case: AVWAP from Budget Day or RBI decision = key institutional reference.

VWAP in OPTIONS TRADING (indirect):
  - Nifty option price targets often correspond to VWAP +/- round numbers.
  - At expiry, pin risk concentrates around VWAP of expiry day.
  - OTM options nearest to day's VWAP on expiry day are most at risk of oscillation.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="CME Group Market Profile Manual",
        title="Market Profile Day Types and Trading Strategies",
        content="""
MARKET PROFILE DAY TYPES (7 types, each with specific trading approach):

1. NORMAL DAY:
   Symmetric bell curve. Opening range = 60-100% of day's range.
   Strategy: Fade extremes. Buy IB Low, sell IB High.
   NSE equivalent: < 50-point initial balance on Nifty → range-bound day likely.

2. NORMAL VARIATION DAY:
   Opening range set first 2 hours, then one-time extension in one direction.
   Strategy: Follow extension direction, target opposite end of prior value area.

3. TREND DAY:
   Price opens and moves continuously in ONE direction. Never returns to open.
   Elongated profile with NO clear bell curve.
   Strategy: BUY early and HOLD. Adding on every pullback. Do NOT fade.
   NSE signal: First 15 minutes make a clean directional move with high volume → trend day.

4. DOUBLE DISTRIBUTION TREND DAY:
   Two separate bell curves connected by thin LVN (low volume node).
   Price creates a new value area distinct from morning.
   Strategy: Trade in direction of the second distribution.

5. NEUTRAL DAY:
   Extensions in BOTH directions from initial balance. Price finishes near midpoint.
   Both buyers and sellers happy.
   Strategy: Fade both extremes. Tight stops.

6. NON-TREND DAY:
   Very small initial balance. Very quiet, narrow range.
   Often precedes a trend day next session.
   Strategy: Be patient. Avoid during the day. Prepare for next day breakout.

7. SPIKE AND CHANNEL DAY:
   Sharp opening move (spike) followed by gradual channel in same direction.
   Strategy: Buy pullbacks to top of spike.

INITIAL BALANCE (IB) — First 60 minutes of trading:
  - IB range < 50% of previous day's range → expect extension.
  - IB range > 100% of previous day's range → likely reversal day.
  - IB set in first 30 min with high volume → high confidence in day's range.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Volume Profile Practical Application",
        title="Applying Volume Profile to Nifty and BankNifty Intraday Trading",
        content="""
NSE NIFTY/BANKNIFTY VOLUME PROFILE SPECIFICS:

BUILDING THE PROFILE:
  - Use 30-min TPO charts OR volume profile from 9:15 AM to 3:30 PM.
  - Reference profiles: Current day, Previous day, Current week, Monthly.
  - Weekly profile: 5-day composite. Most important for identifying major HVN/LVN.

KEY REFERENCE LEVELS (priority order):
  1. Previous week's POC: High-conviction support/resistance.
  2. Previous day's POC: Likely magnet for early session.
  3. Previous day's VAH/VAL: Key levels for day's bias.
  4. Current session's developing VWAP: Institutional benchmark.
  5. Current session's developing POC: Real-time magnet.

PRACTICAL SETUP — NIFTY OPENING GAP:
  If Nifty opens ABOVE previous VAH (value area high):
    → Gap has "accepted" value above → LONG BIAS for the day.
    → First trade: Buy pullback to previous day's VAH.
    → Target: Previous week's POC or 1.5× previous day's range above open.

  If Nifty opens BELOW previous VAL (value area low):
    → Gap has "accepted" value below → SHORT BIAS for the day.
    → First trade: Sell bounce to previous day's VAL.
    → Target: Previous week's POC or 1.5× previous day's range below open.

  If Nifty opens WITHIN previous day's value area:
    → No strong bias. Wait for direction.
    → Break above VAH → long. Break below VAL → short.

BANKNIFTY NUANCE:
  BankNifty is 2.5-3× more volatile than Nifty. Same profile rules apply
  but with 2.5-3× larger expected ranges.
  BankNifty POC levels in round numbers (e.g. 50000, 50500) act as strong magnets.
        """,
    ),
]
