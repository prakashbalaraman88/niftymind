"""
Expert Knowledge: Indian Market Sentiment Analysis

Sources: SEBI FII/DII data research, India VIX methodology (NSE),
NSE Academy, Zerodha Varsity, RBI publications, institutional trading research.
"""
from . import KnowledgeChunk

DOMAIN = "sentiment_analysis"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="SEBI and NSE Institutional Flow Research",
        title="FII and DII Flow Analysis: Structure, Patterns, and Market Impact",
        content="""
FII (Foreign Institutional Investors) / FPI (Foreign Portfolio Investors):
  - Classification: Registered foreign entities investing in Indian securities.
  - Include: Sovereign wealth funds, hedge funds, mutual funds, pension funds, insurance.
  - FII assets in India: ~20-25% of total NSE market cap (2024).
  - Their buy/sell activity has OUTSIZED impact on Nifty/BankNifty.

DII (Domestic Institutional Investors):
  - Include: Indian mutual funds (AMFI), insurance companies (LIC, others), banks, provident funds.
  - DII assets: ~18-22% of NSE market cap.
  - Domestic mutual funds: ~₹60 lakh crore AUM (2024), growing rapidly.
  - DII SIP (Systematic Investment Plan) flows: ~₹18,000-22,000 Cr/month — creates steady buying.

FII vs DII COUNTERBALANCING:
  - LIC and domestic MFs regularly COUNTER FII selling (bought when FII sold heavily in 2022).
  - DII net buying ≥ FII net selling → market stays supported even during FII exits.
  - DII accumulate during dips, providing a floor.

INTERPRETING FII CASH vs DERIVATIVE FLOWS:
  CASH MARKET:
    FII net buying in cash > ₹2,000 Cr/day: Strong buying signal. Rally likely next day.
    FII net selling > ₹2,000 Cr/day: Selling pressure. Weakness likely.
    FII net buying + DII net selling: FII rotation from DII. Bullish if FII net positive.

  DERIVATIVE (F&O) MARKET:
    FII long INDEX FUTURES (large net long): Directional bullish bet on indices.
    FII short INDEX FUTURES: Either hedging cash portfolio OR directional bear bet.
    FII buying index PUTS: Hedging OR anticipating major fall.
    FII net short in F&O + net long in cash = hedged portfolio (neutral-to-bullish).
    FII net short in BOTH cash AND F&O = genuine bearish positioning.

TIMING OF FII DATA:
  NSE publishes FII/DII data after market close (~4:30-5:00 PM IST).
  Provisional data available during market hours (less reliable).
  Derivatives data available separately (daily F&O participant data).
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="India VIX Methodology - NSE India",
        title="India VIX: Calculation, Interpretation, and Trading Signals",
        content="""
INDIA VIX = India's Volatility Index. Measures market's expectation of Nifty 50 volatility
for the next 30 calendar days. Published by NSE using CBOE's adapted methodology.

CALCULATION BASIS:
  Uses bid-ask midpoints of near-month and next-month Nifty 50 options.
  Interpolates to get a constant 30-day measure.
  India VIX of 15 means: Market expects Nifty to move ±15% annually → ±15/√12 = ±4.33%/month.

INDIA VIX INTERPRETATION:
  < 12:   Complacency. Market is very calm. Options are cheap. Often PRECEDES a correction.
            Historical pattern: India VIX under 12 often followed by 3-7% correction within 4-8 weeks.
  12-15:  Normal, healthy market. Low volatility with mild directional moves.
  15-18:  Slightly elevated. Uncertainty increasing. Good time to sell expensive options.
  18-22:  Elevated concern. Reduce leveraged positions. Option premiums rising.
  22-25:  High fear. Sharp moves likely. Institutional hedging. BTST risky.
  25-30:  Very high fear. Potential capitulation setting up. Watch for EXTREME REVERSAL.
  > 30:   Extreme (2008, 2020 COVID). Maximum fear. Buy when blood on streets.

VIX TRADING SIGNALS:
  VIX SPIKE + PRICE HOLD: Price doesn't fall despite VIX spike → institutional buying absorbing.
    BULLISH signal — smart money is buying fear.
  VIX DECLINING + PRICE RISING: Classic bull market. Confirm trend continuation.
  VIX DECLINING + PRICE FALLING: Complacency before potential sharp drop. Very DANGEROUS.
  VIX SPIKE + PRICE BREAK: Panic selling. Avoid new positions. Wait for VIX to peak.

VIX HALTING RULE:
  When India VIX > 25: DO NOT initiate new long options positions (both calls and puts are expensive).
  When India VIX > 30: STOP all new positions. Risk of gap opens exceeds option premium collected.
  When India VIX < 12: BUY options (straddles/strangles) — cheap relative to likely moves.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Breadth Analysis Research",
        title="Market Breadth Indicators: Advance-Decline, TRIN, and Trend Health",
        content="""
MARKET BREADTH measures the participation of stocks in a move.
A rally with broad participation (many stocks rising) is healthier than a narrow rally.

ADVANCE-DECLINE (A/D) RATIO:
  Formula: A/D = Advances / Declines
  Daily data from NSE includes: Advances, Declines, Unchanged.
  NSE typically has ~1,800-2,000 listed stocks.

  A/D > 3:1 (e.g., 1,500 advances, 500 declines): Extremely broad rally. Very bullish.
  A/D > 2:1: Broad participation. Sustainable rally.
  A/D 1.5:1 to 2:1: Moderately healthy rally.
  A/D 1:1 to 1.5:1: Narrow rally. Index up but breadth weak. Caution.
  A/D < 1:1 (advances < declines) + Index rising: Index heavyweight-driven rally. DANGEROUS. Short-term.
  A/D < 0.5:1: Broad decline. Panic selling across the board.

ADVANCE-DECLINE LINE (cumulative):
  Cumulative sum of (Advances - Declines) each day.
  A/D Line making new highs with price → confirmed uptrend, healthy.
  A/D Line diverging (not confirming price new highs) → distribution, bearish.

ARMS INDEX (TRIN):
  Formula: TRIN = (Advances/Declines) / (Advancing Volume/Declining Volume)
  > 1.0: Volume concentrated in declining stocks → bearish.
  < 1.0: Volume concentrated in advancing stocks → bullish.
  > 2.0: Panic selling (extreme oversold) → contrarian BUY signal.
  < 0.5: Extreme buying enthusiasm → contrarian SELL signal.

% STOCKS ABOVE KEY MOVING AVERAGES:
  % above 50 DMA > 70%: Healthy bull market breadth.
  % above 50 DMA 40-70%: Mixed market.
  % above 50 DMA < 30%: Widespread selling. Oversold. Watch for reversal.
  % above 200 DMA > 60%: Long-term bull market intact.
  % above 200 DMA < 40%: Bear market regime.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="SGX Nifty and Pre-market Analysis",
        title="Pre-Market Indicators: SGX Nifty, Gift Nifty, and US Futures Gap Prediction",
        content="""
PRE-MARKET INDICATORS FOR NSE GAP PREDICTION:

GIFT NIFTY (formerly SGX Nifty):
  - Gift City (Gujarat) exchange trades Nifty futures 24 hours.
  - Gap between Gift Nifty (at 9:00 AM IST) and previous Nifty close = expected gap open.
  - Gift Nifty +0.5% vs close → expect Nifty to open +0.3-0.5%.
  - Gift Nifty -1%: → expect Nifty to open -0.7-0.9%.
  - Note: Gift Nifty slightly overstates gap (approximately 70-80% of Gift Nifty move realized in NSE gap).

US MARKET CORRELATION WITH INDIA:
  S&P 500 up 1% overnight → Nifty typically opens 0.3-0.5% higher.
  S&P 500 down 1% overnight → Nifty typically opens 0.3-0.5% lower.
  S&P 500 moves > 2% (either direction): High probability of following gap in India.
  Correlation breaks when: India-specific events (Budget, RBI, elections, local crisis).

GLOBAL SEQUENCE FOR PRE-MARKET ANALYSIS (IST times):
  3:30 PM IST: US markets open (9 AM EST). Monitors US initial move.
  8:30 PM - 9:30 PM IST: US major data releases (CPI, NFP, GDP, FOMC).
  1:30-3:00 AM IST: US markets close. Final S&P 500 level = primary indicator.
  3:00-6:00 AM IST: Asian markets: Nikkei, Hang Seng, ASX start trading.
  6:00 AM IST: Gift Nifty signal most reliable at this time.
  9:00 AM IST: Pre-open NSE session. Order matching at 9:15 AM.

SECTOR ROTATION READING FROM PRE-MARKET:
  IT stocks + Nasdaq strong → Nifty IT likely outperforms.
  Crude oil down → ONGC/IOC up, but overall market positive (India import cost down).
  Gold up + DXY down → EMs (including India) likely to outperform.
  Bank stocks (US banking sector ETF) up → Likely BankNifty outperforms Nifty.
  Defensive (utilities, healthcare) outperforming → risk-off signal for India equities.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Seasonal and Structural Sentiment Research",
        title="India Market Seasonal Patterns and Event-Driven Sentiment",
        content="""
SEASONAL PATTERNS IN INDIAN MARKETS:

CALENDAR EFFECTS:
  January Effect: Small-cap outperformance (similar to US, less pronounced in India).
  Pre-Budget Rally (Nov-Jan): Markets often rally ahead of Union Budget (Feb 1).
  Post-Budget Correction: 50-60% probability of correction if budget disappoints.
  Diwali Rally (Oct-Nov): "Muhurat Trading" — bullish sentiment, often marks year low.
  March Tax Selling: Mutual fund portfolio rebalancing pressure before March 31 (year-end).
  December Cheer: FPI (foreign) year-end positioning often bullish.

QUARTERLY RESULTS SEASON (Jan, Apr, Jul, Oct):
  TCS, Infosys, Wipro (results in first 2-3 weeks) → set tone for IT sector.
  HDFC Bank, ICICI Bank → set tone for BankNifty.
  Reliance Industries → largest index heavyweight, moves Nifty 0.2-0.4%.
  Watch for earnings surprise direction: >3% beat → significant positive reaction.

EXPIRY WEEK EFFECTS:
  Monday: Low volatility. Positions establishing.
  Tuesday: India VIX often rises 0.5-1 pt as hedging begins.
  Wednesday: Increasing activity. BankNifty expiry (as of 2023).
  Thursday: Nifty expiry. Extreme gamma. Highest volume of the week.
  Pattern: Market often moves in OPPOSITE direction from Tuesday's trend on Thursday.

FII OWNERSHIP AND MARKET IMPACT:
  When FII ownership % drops below 18%: Historically creates strong buying opportunity.
  When FII ownership % rises above 25%: Market getting expensive, reversal risk.
  FII SEBI registration data: Monthly patterns in allocation shifts.
        """,
    ),
]
