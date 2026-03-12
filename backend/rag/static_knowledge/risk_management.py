"""
Expert Knowledge: Risk Management for Options and F&O Trading

Sources: Van Tharp (Trade Your Way to Financial Freedom), Kelly Criterion research,
Edward Thorp (Beat the Dealer, Fortune's Formula), SEBI margin regulations,
professional risk management frameworks.
"""
from . import KnowledgeChunk

DOMAIN = "risk_management"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="Kelly Criterion and Position Sizing Theory",
        title="Optimal Position Sizing: Kelly Criterion, Half-Kelly, and Fixed Fractional",
        content="""
KELLY CRITERION (developed by John L. Kelly Jr., 1956):
  Optimal bet fraction = f* = (bp - q) / b
  Where: b = net odds (reward/risk ratio), p = win probability, q = 1 - p = loss probability.

  Example: Trade with 60% win rate and 1.5:1 risk/reward.
  f* = (1.5 × 0.60 - 0.40) / 1.5 = (0.90 - 0.40) / 1.5 = 0.50/1.5 = 33.3% of capital.
  This means risking 33.3% of capital per trade.

PROBLEMS WITH FULL KELLY:
  - Massive drawdowns (Kelly drawdown can be 50-60% of peak capital).
  - Overconfident p and b estimates in trading → Kelly severely overbets.
  - Psychological inability to sustain large drawdowns.

HALF-KELLY (most recommended by practitioners):
  f = f* / 2. In the example above: 33.3% / 2 = 16.7%.
  Half-Kelly provides 75% of the Kelly return with significantly lower drawdown.

FIXED FRACTIONAL SYSTEM (most practical for retail traders):
  Risk FIXED % of current capital per trade.
  Standard: 1-2% of capital per trade (conservative), 3-5% (aggressive).
  ₹5 lakh capital × 2% = ₹10,000 maximum risk per trade.
  This is the recommended approach for NiftyMind trading.

CALCULATING TRADE SIZE FROM RISK:
  Max Risk = Capital × Risk% = ₹5,00,000 × 2% = ₹10,000
  Option SL distance = 30 points (Nifty ATM)
  Nifty lot size = 25 units per lot
  Max lots = ₹10,000 / (30 points × 25 units) = ₹10,000 / ₹750 = 13.3 → 13 lots maximum.
  BankNifty lot size 15: ₹10,000 / (50 × 15) = ₹10,000 / ₹750 = 13 lots maximum.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Van Tharp - Trade Your Way to Financial Freedom",
        title="Expectancy, System Quality, and Circuit Breakers",
        content="""
TRADING SYSTEM EXPECTANCY:
  Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
  A system must have POSITIVE expectancy to be profitable long-term.

  Example — NiftyMind intraday system:
    Win rate = 55%, Avg win = ₹8,000, Avg loss = ₹5,000.
    Expectancy per trade = (0.55 × 8,000) - (0.45 × 5,000) = 4,400 - 2,250 = ₹2,150.
    This means on average, each trade generates ₹2,150 expected profit.

RISK OF RUIN:
  Even positive expectancy systems can go to zero without proper sizing.
  Risk of Ruin = ((1-Edge)/(1+Edge))^(Capital/Bet)
  With 55% win rate and 1:1 R:R: Edge = 0.10. Risk of Ruin with 10% bets = very high.
  With 1% per trade bets: Risk of Ruin approaches near zero.

CIRCUIT BREAKERS (mandatory daily stops):

  DAILY LOSS LIMIT: Stop all trading for the day if total loss reaches X%.
  Recommended: 5-10% of capital per day.
  NiftyMind default: ₹50,000 on ₹5L capital (10% daily stop).
  Psychological rule: After hitting daily stop, DO NOT OVERRIDE IT. Log off, review.

  STREAK RULE: Stop after 3 consecutive losing trades (regardless of total loss).
  "Three and done" rule protects against revenge trading and system malfunction.

  DRAWDOWN CIRCUIT BREAKER:
  10% drawdown from peak: Reduce all position sizes by 50%.
  20% drawdown from peak: Stop ALL trading. Full system review required.
  Rationale: Drawdowns are MULTIPLICATIVE. Need +25% to recover from -20% drawdown.

  WEEKLY LOSS LIMIT: Total week loss > 15% of capital → take off remaining week.
  Forces reflection and prevents accelerating losses.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="SEBI Margin Regulations + NSE Risk Management",
        title="SEBI Margin Rules, Peak Margin, and NSE F&O Risk Frameworks",
        content="""
SEBI MARGIN REGULATIONS (effective 2021):

PEAK MARGIN REQUIREMENTS:
  NSE collects margin from brokers 4 times per day (intraday snapshots).
  Broker must ensure client has margin at PEAK intraday usage, not just EOD.
  This eliminated "T+5 day" leverage (leveraging beyond collateral was banned).
  Impact: Effective leverage in F&O reduced. Must have full SPAN + Exposure margin upfront.

SPAN MARGIN (Standard Portfolio Analysis of Risk):
  Calculated by NSCCL (clearing corporation) using SPAN methodology (CME developed).
  Based on portfolio's worst-case scenario loss over 16 risk scenarios.
  Nifty ATM option: SPAN margin approximately ₹50,000-80,000 per lot (varies with VIX).
  Higher VIX → higher SPAN margin → less leverage available.

EXPOSURE MARGIN:
  Additional margin over SPAN. For index options: 2% or 1.5× SPAN (whichever higher).
  Total margin = SPAN + Exposure margin.

M2M (MARK-TO-MARKET) SETTLEMENT:
  Futures positions: MTM calculated daily. Losses debited from account intraday.
  Options positions: Premium paid upfront (buyer). No daily MTM for buyers.
  Options sellers: SPAN margin required + M2M on unrealized losses.

POSITION LIMITS:
  For proprietary/retail trading in index derivatives:
  Nifty futures: No specific limit (portfolio-level margin controls).
  Index options: No explicit position limit for trading members.
  FII position limits: 20% of total open interest in index derivatives.

IMPORTANT SEBI REGULATIONS (2024):
  - Lot size changes: SEBI increased minimum contract value (caused Nifty lot size change to 25).
  - Weekly expiry consolidation: SEBI limiting to 1 weekly expiry per exchange.
  - Options buyer expense disclosure mandate: Brokers must show transaction costs clearly.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Portfolio Risk Theory",
        title="Correlation Risk, Concentration Risk, and Portfolio-Level Risk Management",
        content="""
CORRELATION RISK IN OPTIONS PORTFOLIOS:

NIFTY vs BANKNIFTY CORRELATION:
  Historical correlation: 0.70-0.85.
  Practical implication: Long Nifty call + Long BankNifty call = NOT diversified.
  It's essentially the same directional bet with amplified risk.
  Maximum rule: No more than 2 positions in the same direction on correlated underlyings.

CONCENTRATION RISK:
  Never have > 50% of option exposure in a single underlying on a single expiry.
  Even if all 12 signals are BULLISH, trade ONE underlying at a time.
  Diversification rule: Split between Nifty and BankNifty if both are valid setups.

VEGA RISK (volatility correlation):
  All NSE options are CORRELATED in IV. When India VIX spikes, ALL option premiums rise.
  A long straddle portfolio benefits; a short straddle portfolio is universally hurt.
  Net vega must be monitored at portfolio level, not just individual trade level.

GAMMA RISK (expiry approach):
  Near expiry (Thursday): Gamma becomes the dominant risk.
  Long gamma options can 10× or go to zero in the same day.
  Rule: On expiry day, long options are lottery tickets. Short options are near-maximum-liability.

DELTA-HEDGING CONCEPT (advanced):
  Portfolio delta = sum of (position × option delta × lot size × price).
  Keeping delta near zero = neutral directional risk.
  For pure directional trades, allow delta exposure up to 25% of portfolio capital.
  For neutral strategies, delta should be within ±10% of portfolio capital.

CORRELATION MATRIX — Key Indian Sectors:
  BankNifty ↔ PrivateBanks (HDFC, ICICI): 0.92 — essentially the same.
  Nifty IT (TCS, Infosys, HCL): ↔ Nasdaq: 0.65 — US tech proxy.
  Nifty Metal ↔ China A-shares: 0.55 — China growth proxy.
  Nifty Energy ↔ Crude Oil: 0.50 — commodity correlation.
  Nifty Pharma ↔ INR: -0.45 — export revenue in USD, INR weakness = earnings boost.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Options Risk Management Specific Research",
        title="VIX-Based Position Sizing and Volatility-Adjusted Stops",
        content="""
VOLATILITY-ADJUSTED POSITION SIZING:
  High VIX environments require SMALLER positions (wider price swings, higher premium).
  Low VIX environments allow LARGER positions (tighter swings, lower premium).

VIX-BASED SCALING:
  India VIX < 12: Scale up to 150% of normal position size (options cheap, edge large).
  India VIX 12-18: Normal position size (100%).
  India VIX 18-22: Scale down to 75% of normal.
  India VIX 22-25: Scale down to 50% of normal.
  India VIX > 25: Scale down to 25% or STOP TRADING.
  India VIX > 30: Emergency stop. No new positions.

VOLATILITY-ADJUSTED STOPS:
  Standard stop: SL in option premium = fixed rupee amount (e.g., ₹20 on Nifty option).
  Better approach: ATR-based stops.
  ATR(14) of Nifty × 0.25 = stop distance in index points.
  Convert to option premium: stop_points × option delta = premium stop.
  Example: ATR = 120 points. Stop = 120 × 0.25 = 30 points. ATM delta = 0.50.
  Premium stop = 30 × 0.50 = ₹15 on option.
  Advantage: Auto-adjusts to current volatility regime.

MAXIMUM ADVERSE EXCURSION (MAE) ANALYSIS:
  Track the maximum drawdown of each trade before it either hits SL or target.
  Trade that moved 15 points against you before recovering = high stress trade.
  If MAE consistently > 50% of SL, stop is too tight.
  If MAE < 20% of SL, stop can be tightened (improving R:R without much impact).

TAIL RISK MANAGEMENT:
  Options can gap through stop levels on news events.
  ALWAYS use options for directional plays (not futures) — max loss is limited to premium paid.
  Avoid selling naked options near major events (unlimited loss potential).
  For selling strategies, use defined-risk spreads (bull put spread, iron condor).
        """,
    ),
]
