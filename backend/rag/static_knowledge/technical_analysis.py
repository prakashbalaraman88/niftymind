"""
Expert Knowledge: Technical Analysis for Indian F&O Markets

Sources: John Murphy (Technical Analysis of Financial Markets), Thomas Bulkowski
(Encyclopedia of Chart Patterns), CPR strategy original research, Camarilla pivot
theory (Nick Scott), Zerodha Varsity Technical Analysis module.
"""
from . import KnowledgeChunk

DOMAIN = "technical_analysis"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="CPR Strategy Research",
        title="Central Pivot Range (CPR): Construction, Width Theory, and Trading Rules",
        content="""
CPR (Central Pivot Range) — India's most widely used intraday pivot system.

FORMULAS:
  Pivot Point (PP) = (Previous High + Previous Low + Previous Close) / 3
  Bottom CPR (BC) = (Previous High + Previous Low) / 2
  Top CPR (TC) = (2 × PP) - BC

PROPERTIES:
  - TC is always ≥ BC. When TC > BC → wide CPR. When TC ≈ BC → narrow CPR.
  - If PP > BC → TC > BC (normal). If PP < BC → inverting CPR (unusual).
  - PP is the "middle" — price gravitates toward it.

CPR WIDTH INTERPRETATION:
  NARROW CPR (TC - BC < 30 Nifty points):
    → Strong TRENDING day expected. Price will move decisively in one direction.
    → Trade BREAKOUT from CPR direction. Buy above TC or Short below BC.
    → Do NOT trade range within narrow CPR.
    → Statistically: Narrow CPR + price opens above CPR → 70% chance of trending up day.

  WIDE CPR (TC - BC > 80 Nifty points):
    → SIDEWAYS/RANGE day expected. CPR acts as magnet — price stays in CPR zone.
    → Trade FADE: Buy at BC, Sell at TC. Tight stops.
    → Wide CPR = difficult environment for directional option buyers.
    → Wide CPR on Monday = choppy week likely ahead.

BIAS DETERMINATION:
  Bullish bias if: Current day's CPR is ABOVE previous day's CPR (CPR migrating up).
  Bearish bias if: Current day's CPR is BELOW previous day's CPR (CPR migrating down).
  Stacked CPRs (3+ days above/below each other) = strong multi-day trend.

SUPPORT/RESISTANCE LEVELS (Standard Pivots):
  R3 = PP + 2 × (H - L) [major resistance]
  R2 = PP + (H - L)
  R1 = 2 × PP - L
  S1 = 2 × PP - H
  S2 = PP - (H - L)
  S3 = PP - 2 × (H - L) [major support]
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Nick Scott - Camarilla Equation (1989)",
        title="Camarilla Pivots: Levels, Breakout Rules, and Reversal Strategies",
        content="""
CAMARILLA PIVOTS were developed by Nick Scott in 1989 for bond trading.
They use previous day's Close, High, and Low to project 8 intraday levels (H1-H4, L1-L4).

FORMULAS (using previous day's High, Low, Close):
  Range = High - Low
  H1 = Close + (Range × 1.1 / 12)
  H2 = Close + (Range × 1.1 / 6)
  H3 = Close + (Range × 1.1 / 4)  ← KEY LEVEL: Reversal short zone
  H4 = Close + (Range × 1.1 / 2)  ← KEY LEVEL: Breakout long zone
  L1 = Close - (Range × 1.1 / 12)
  L2 = Close - (Range × 1.1 / 6)
  L3 = Close - (Range × 1.1 / 4)  ← KEY LEVEL: Reversal long zone
  L4 = Close - (Range × 1.1 / 2)  ← KEY LEVEL: Breakout short zone

TRADING RULES (proven by decades of usage):

H3/L3 REVERSAL STRATEGY (80%+ win rate in ranging markets):
  Price reaches H3 from BELOW → Short with stop above H4. Target PP or L1.
  Price reaches L3 from ABOVE → Long with stop below L4. Target PP or H1.
  CONDITION: Only take H3/L3 trades in RANGE-BOUND market (ADX < 20, or within CPR range).

H4/L4 BREAKOUT STRATEGY (trending markets):
  Price CLOSES above H4 → Strong BUY. Stop below H4. Target: H4 + (H4 - H3).
  Price CLOSES below L4 → Strong SELL. Stop above L4. Target: L4 - (H3 - L3).
  CONDITION: Breakout of H4/L4 with high volume and momentum → trend continuation.

H5/L5 (EXTREME BREAKOUT — less common):
  H5 = High + (High - Low) × 1.1 / 2
  L5 = Low - (High - Low) × 1.1 / 2
  H5/L5 represents extreme conditions (major news, global events).
  Reaching H5 or L5 within one day = exceptional, usually reverses same day.

CAMARILLA vs CPR COMBINED:
  Most powerful setup: CPR shows narrow width (trending day expected) +
  price breaks out of H4/L4 in Camarilla → Very high-probability trend trade.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="John Murphy - Technical Analysis of Financial Markets",
        title="EMA Analysis: Multi-Timeframe Confluence and Trend Identification",
        content="""
EXPONENTIAL MOVING AVERAGES (EMA) smooth price while giving more weight to recent data.
EMA(n) = Price × (2/(n+1)) + EMA(n-1) × (1 - 2/(n+1))

KEY EMA PERIODS AND THEIR ROLES:
  5 EMA: Ultra short-term momentum. Used in 1-minute charts for scalping.
  9 EMA: Short-term intraday trend. Ribbon between 9 and 20 shows momentum.
  20 EMA: Most important for intraday swing traders. Acts as dynamic support/resistance.
  50 EMA: Medium-term trend on 15-min and hourly charts. Institutional reference.
  100 EMA: Swing trading reference on daily charts.
  200 EMA: Long-term trend filter. Price above 200 EMA = bull market.
    "The 200-day moving average is the most followed in all of finance." — John Murphy

MULTI-TIMEFRAME EMA ALIGNMENT (grade the trade):
  A+ setup: 5m, 15m, 1h, and daily ALL show EMA aligned in same direction.
  A setup: 3 of 4 timeframes aligned.
  B setup: 2 of 4 timeframes aligned.
  Avoid: Counter-trend trades against daily 200 EMA direction.

EMA CROSSOVER SIGNALS:
  Golden Cross: Short EMA crosses above long EMA → BULLISH.
  Death Cross: Short EMA crosses below long EMA → BEARISH.
  "9/20 EMA crossover" on 5-min chart = reliable scalping signal for Nifty.
  "20/50 EMA crossover" on 15-min chart = intraday swing signal.

EMA BOUNCE (most reliable EMA trade):
  Trending market: price pulls back to 20 EMA and bounces.
  - Uptrend: 20 EMA acts as support. Buy the bounce. Stop below 20 EMA.
  - Downtrend: 20 EMA acts as resistance. Sell the bounce. Stop above 20 EMA.
  Confirmation: Low-volume pullback to EMA, high-volume rejection = high conviction.

PRICE-EMA RELATIONSHIP:
  Price > 20 EMA > 50 EMA > 200 EMA: Perfect bull alignment. Only buy pullbacks.
  Price < 20 EMA < 50 EMA < 200 EMA: Perfect bear alignment. Only sell bounces.
  EMA "spaghetti" (all tangled): Choppy market. Reduce size. Trade ranges instead.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="J. Welles Wilder - New Concepts in Technical Trading Systems",
        title="RSI: Overbought/Oversold, Divergence Types, and Centerline Strategy",
        content="""
RSI (Relative Strength Index) = 100 - [100/(1 + RS)]
Where RS = Average Gain / Average Loss over N periods (typically 14).

RSI INTERPRETATION:
  > 70: Overbought. In strong uptrend, can stay overbought for extended periods.
  < 30: Oversold. In strong downtrend, can stay oversold for extended periods.
  50 Line: Trend filter. RSI above 50 = bullish momentum. Below 50 = bearish.

RSI IN TRENDING MARKETS (Wilder's corrected interpretation):
  Bull Market RSI zone: 40-90. Oversold = 40-50, not 30.
  Bear Market RSI zone: 10-60. Overbought = 50-60, not 70.
  Most traders make the MISTAKE of shorting RSI > 70 in bull market.

RSI DIVERGENCE (highest probability signal):
  REGULAR BEARISH DIVERGENCE:
    Price makes HIGHER HIGH, RSI makes LOWER HIGH.
    Momentum is weakening. High probability of reversal DOWN.
    Confirm: Price must fail to make new high on subsequent bar.

  REGULAR BULLISH DIVERGENCE:
    Price makes LOWER LOW, RSI makes HIGHER LOW.
    Downside momentum is weakening. High probability of reversal UP.
    Confirm: Price must fail to make new low on subsequent bar.

  HIDDEN BEARISH DIVERGENCE:
    Price makes LOWER HIGH, RSI makes HIGHER HIGH.
    Signals trend continuation DOWN. Use in DOWNTRENDS.

  HIDDEN BULLISH DIVERGENCE:
    Price makes HIGHER LOW, RSI makes LOWER LOW.
    Signals trend continuation UP. Use in UPTRENDS.

RSI FAILURE SWINGS (Wilder's original signal):
  Bullish: RSI falls below 30, bounces above 30, pulls back but stays above 30,
  then breaks previous high on RSI → BUY.
  Bearish: RSI rises above 70, falls below 70, bounces but stays below 70,
  then breaks previous low on RSI → SELL.

INDIA NIFTY/BANKNIFTY RSI NOTES:
  - 14-period RSI on 5-min chart for intraday trading.
  - 14-period RSI on daily chart for swing trading.
  - Nifty RSI > 75 on daily: Historically follows with 3-5% correction within 2-4 weeks.
  - Nifty RSI < 30 on daily: Historically follows with 5-10% bounce within 1-3 weeks.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Opening Range Breakout Research",
        title="Opening Range Breakout and First-Hour Strategies for NSE",
        content="""
OPENING RANGE (OR) = High and Low of the first N minutes of trading.
Most common: 15-min OR, 30-min OR, 60-min OR.

WHY OPENING RANGE WORKS:
  - First 15-60 minutes: Institutional DISCOVERY phase. Price explores both sides.
  - After initial balance is set: Breakout of OR signals DIRECTIONAL CONVICTION.
  - OR breakout = institutions have decided direction for the day.
  - Higher volume on OR breakout = higher conviction.

NSE OPENING RANGE RULES:
  - Nifty 15-min OR: High and Low of 9:15 - 9:30 AM candle.
  - Validity: If 15-min OR range < 30 points → "tight OR" → high conviction expected.
  - Validity: If 15-min OR range > 80 points → "wide OR" → OR may expand further.

BREAKOUT TRADING RULES:
  Long entry: 5-min close ABOVE OR High. Stop: Below OR Low. Target: 1.5-2× OR range above entry.
  Short entry: 5-min close BELOW OR Low. Stop: Above OR High. Target: 1.5-2× OR range below entry.

FALSE BREAKOUT FILTER:
  - Low volume breakout: Likely false. Wait for confirmation candle.
  - Breakout immediately reverses within 1-2 bars: Failed breakout → trade REVERSAL.
  - Opening above previous VAH + breaks OR High with volume: Very strong long signal.
  - Opening below previous VAL + breaks OR Low with volume: Very strong short signal.

GAP ANALYSIS AND OPENING STRATEGY:
  Gap up > 0.5%: Look to BUY pullback to OR bottom or VWAP. Don't short initial gap.
  Gap down > 0.5%: Look to SELL bounce to OR top or VWAP. Don't buy initial gap.
  Gap fill trade: If gap fills (price returns to previous close), often continues filling.
    NSE statistics: ~60% of gaps fill within first 2 hours.
  Gap not filling: Strong trend day in gap direction. Don't fight it.

FIRST-HOUR VOLUME:
  First 60-min volume > 150% of average first-hour volume → Trend day.
  First 60-min volume < 70% of average → Range/sideways day.
        """,
    ),
]
