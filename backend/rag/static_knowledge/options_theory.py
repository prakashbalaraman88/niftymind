"""
Expert Knowledge: Options Theory & Options Chain Analysis

Sources: Sheldon Natenberg (Option Volatility & Pricing), Lawrence McMillan
(Options as a Strategic Investment), NSE Academy, Zerodha Varsity Module 5 & 6,
CBOE Education, and original research on Indian F&O markets.
"""
from . import KnowledgeChunk

DOMAIN = "options_chain"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="Natenberg - Option Volatility & Pricing",
        title="Black-Scholes Model and Assumptions",
        content="""
The Black-Scholes model (1973) prices European options using five inputs: underlying price (S),
strike price (K), time to expiry (T in years), risk-free rate (r), and implied volatility (σ).

Formula: C = S·N(d1) - K·e^(-rT)·N(d2)
Where: d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T), d2 = d1 - σ√T

Critical assumptions that Indian traders must account for:
1. European-style exercise ONLY (NSE options are European — no early exercise).
2. Log-normal distribution of returns — fat tails exist in real markets (especially around RBI, Budget).
3. Constant volatility — IV changes dramatically (volatility smile, skew).
4. Continuous trading — NSE has pre-open, regular, and post-close sessions.
5. No dividends — adjust for dividend ex-dates when pricing Nifty options.

Practical implication: B-S underprices tail risk. Always add an 'event premium' of 20-40% to
model price when an RBI policy or Budget is within the option's life. Market makers know this
and widen spreads accordingly. The actual traded IV will always exceed theoretical IV near events.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="CBOE Options Institute",
        title="The Greeks: Delta, Gamma, Theta, Vega — Deep Dive",
        content="""
DELTA (Δ) — measures option price sensitivity to ₹1 move in underlying.
  - ATM calls: delta ≈ 0.50 (50% probability of expiring ITM).
  - Deep ITM calls: delta → 1.0 (behaves like holding the underlying).
  - Far OTM calls: delta → 0 (lottery ticket, tiny directional exposure).
  - Put delta ranges from -1 to 0 (PE delta = CE delta - 1 for same strike).
  - Delta as hedge ratio: 100 CE delta of 0.45 → sell 45 units of underlying to hedge.
  - Delta changes with spot movement (curvature = gamma).

GAMMA (Γ) — rate of change of delta per ₹1 move in underlying.
  - Gamma is highest for ATM options, especially near expiry.
  - On Nifty expiry (Thursday): ATM gamma can be 5-10x normal day's gamma.
  - "Gamma scalping": market makers constantly re-hedge delta exposure.
  - Long gamma = benefits from large moves in either direction.
  - Gamma squeeze: when stock moves sharply, market makers must buy/sell heavily to stay delta-neutral.
  - India specific: NSE weekly expiry creates extreme gamma events every Thursday.

THETA (Θ) — daily time decay of option premium.
  - Theta is NEGATIVE for long options (you LOSE premium daily).
  - Theta accelerates non-linearly as expiry approaches (√T decay).
  - ATM options decay fastest in absolute ₹ terms.
  - OTM options decay fastest as % of premium near expiry.
  - Typical Nifty ATM weekly option: theta ≈ 15-25 points/day (accelerates Thursday morning).
  - Rule: Don't hold long options through weekends — you pay 3 days of theta.
  - Post-2 PM on expiry day: theta becomes catastrophic, buy only if strong signal.

VEGA (V) — sensitivity to 1% change in implied volatility.
  - Vega highest for ATM long-dated options.
  - Long options benefit from rising IV (long vega).
  - Short options (iron condor, short straddle) suffer from rising IV.
  - IV crush after RBI policy: buy before announcement, sell immediately after.
  - Rule: Vega exposure doubles when buying ATM options near high-IV events.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="NSE Academy - F&O Markets",
        title="Implied Volatility: Rank, Percentile, and Skew",
        content="""
IMPLIED VOLATILITY (IV) is the market's forward-looking expectation of volatility.
It's derived by solving Black-Scholes backwards — plugging in market price, finding σ.

IV RANK (IVR):
  Formula: IVR = (Current IV - 52wk Low IV) / (52wk High IV - 52wk Low IV) × 100
  Interpretation:
  - IVR 0-20: IV is at historical lows → long options (buy calls/puts or straddles) are CHEAP.
  - IVR 20-50: Normal range, no edge from IV level alone.
  - IVR 50-80: IV is elevated → selling premium (iron condor, short strangle) has edge.
  - IVR 80-100: IV is extremely high → strong selling edge, but use caution (event risk).

IV PERCENTILE (IVP):
  Formula: % of trading days in past year where IV was BELOW current level.
  - More robust than IVR for instruments with one-time spikes.
  - IVP > 80: Good conditions for premium selling strategies.

VOLATILITY SKEW (critical for NSE):
  - Normal skew: OTM puts (PE) have HIGHER IV than OTM calls (CE). Protective put demand.
  - Steeper skew than normal → market expects downside risk (sell CE, buy PE).
  - Flat/inverted skew → bullish optimism, OTM calls are expensive relative to puts.
  - On expiry Thursday: IV collapses dramatically after 11 AM if no major move.
  - Skew trade: When CE IV > PE IV significantly, institutional short sellers are likely active.

INDIA VIX:
  - NSE's fear gauge, measures expected 30-day volatility of Nifty 50.
  - Computed using bid-ask midpoints of near and next-month Nifty options (CBOE methodology adapted).
  - India VIX < 12: Complacency, often precedes correction.
  - India VIX 12-18: Normal market range for Nifty.
  - India VIX 18-25: Elevated concern, reduce option buying.
  - India VIX > 25: High fear — risk-off, potential capitulation.
  - India VIX > 30: Extreme (seen in March 2020 COVID crash, 2008 GFC).
  - Nifty and VIX: strong negative correlation (-0.75 to -0.85).
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Options Research Institute",
        title="Put-Call Ratio (PCR): Construction, Interpretation and Contrarian Signals",
        content="""
PCR (Put-Call Ratio) = Total Put Open Interest / Total Call Open Interest
      OR
PCR (Volume) = Total Put Volume / Total Call Volume

PCR INTERPRETATION — Contrarian indicator:
  - PCR > 1.5: Extreme bearishness. Contrarian signal — possible short-covering rally.
  - PCR 1.2-1.5: Bearish sentiment dominates. Bullish bias for contrarians.
  - PCR 0.8-1.2: Neutral / balanced market.
  - PCR 0.6-0.8: Bearish bias — excessive bullishness may lead to correction.
  - PCR < 0.5: Extreme bullishness. Contrarian signal — potential reversal down.

WHY PCR IS CONTRARIAN:
  Option BUYERS are typically retail (mostly wrong at extremes).
  Large PCR = retail panic-buying puts → market makers on the other side SHORT puts →
  they delta-hedge by buying the underlying → creates buying pressure → market bounces.

PCR TRENDS more important than levels:
  - Rising PCR (from 0.8 to 1.2) while price falls = smart money hedging, bearish.
  - Rising PCR (from 1.5 to 2.0) = extreme fear, WATCH FOR REVERSAL.
  - Falling PCR (from 1.2 to 0.8) while price rises = put writers confident, bullish.
  - Sudden PCR spike on green day = danger, smart money hedging into strength.

NSE-SPECIFIC PCR NUANCES:
  - Nifty PCR includes NEXT WEEK and MONTHLY contracts — all-expiry PCR is more reliable.
  - Near-expiry CE OI gets destroyed (worthless) every Thursday, artificially inflating PCR.
  - Check PCR for current week only when near Thursday expiry.
  - BankNifty PCR often leads Nifty PCR by 15-20 minutes (faster price discovery).
  - Highest OI strikes = key support/resistance, NOT necessarily where price will close.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="CME Group - Options Education",
        title="Max Pain Theory: Mechanics and Market Implications",
        content="""
MAX PAIN (also called Options Pain or Strike Price Magnetism) is the price at which the
total dollar loss of ALL option holders (both CE and PE) is maximized at expiry.

CALCULATION:
  For each possible underlying price (X):
    CE pain(X) = Σ [max(0, strike - X) × OI] for all ITM calls at price X
    PE pain(X) = Σ [max(0, X - strike) × OI] for all ITM puts at price X
    Total pain(X) = CE pain(X) + PE pain(X)
  Max Pain = price X where total pain is maximum (= most option buyers lose most money).

WHY PRICE GRAVITATES TO MAX PAIN:
  Option writers (mostly institutional) hold the other side of retail trades.
  Near expiry, institutions with large option books DELTA-HEDGE by buying/selling underlying.
  This hedging activity naturally creates price pressure toward max pain.
  Not manipulation — it's a mechanical consequence of delta-hedging large books.

PRACTICAL RULES FOR NSE EXPIRY (THURSDAY):
  1. Last 2 hours of Thursday: price has strong pull toward max pain.
  2. Max pain effect strongest when overall OI is high (large open books).
  3. Max pain within 50 Nifty points = very strong gravity zone.
  4. Max pain 200+ points away = price can expire anywhere.
  5. If spot is ABOVE max pain: MMs are short calls, they sell futures to hedge → bearish pressure.
  6. If spot is BELOW max pain: MMs are short puts, they buy futures to hedge → bullish pressure.
  7. Max pain should be checked at 9:30 AM, 12:00 PM, and 2:00 PM on expiry day.
  8. Max pain shifts intraday as OI changes via new trades and position closures.

LIMITATIONS:
  - Max pain theory assumes all OI remains open until expiry (not always true).
  - Large directional moves override max pain (news, global events).
  - Works BEST in low-VIX, low-event environments.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Natenberg + NSE F&O Data Research",
        title="Open Interest Analysis: Buildup, Unwinding, and Institutional Positioning",
        content="""
OPEN INTEREST (OI) = Total number of outstanding contracts not yet settled.
Unlike volume (which resets daily), OI accumulates over time and reflects committed positions.

FOUR KEY OI SCENARIOS (Price-OI matrix):

1. Price UP + OI UP = LONG BUILDUP (Fresh bulls entering) → BULLISH confirmation.
2. Price UP + OI DOWN = SHORT COVERING (Bears exiting) → Caution: rally may be unsustainable.
3. Price DOWN + OI UP = SHORT BUILDUP (Fresh bears entering) → BEARISH confirmation.
4. Price DOWN + OI DOWN = LONG UNWINDING (Bulls exiting) → Caution: decline may exhaust.

OI CONCENTRATION AT STRIKES:
  - Highest CE OI strike = key resistance (Call writers defend this level).
  - Highest PE OI strike = key support (Put writers defend this level).
  - When price breaks through highest OI strike with acceleration = shorts getting squeezed.
  - When price retreats from highest OI strike = resistance holding.

OI CHANGE PATTERNS (Expiry Week):
  Monday-Tuesday: Positions build for current week's expiry.
  Wednesday: Sharp increase in ATM OI as directional bets finalize.
  Thursday AM: OI declines rapidly as positions are closed before 3:30 PM.
  Thursday PM: Sudden OI collapse = shorts and longs both squaring off.

INSTITUTIONAL POSITIONING VIA OI:
  - Large CE OI build at OTM strikes = institutional selling calls (bullish floor below).
  - Large PE OI build at OTM strikes = institutional selling puts (bearish ceiling above).
  - Simultaneous big CE + PE OI = institutional short straddle → expect range-bound day.
  - One-sided OI explosion (CE only or PE only) = directional institutional bet.

GAMMA-WEIGHTED OI (advanced):
  Weight each strike's OI by its gamma to find the true "pressure zone."
  Near expiry, ATM options have highest gamma → small OI but HIGH price impact.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Zerodha Varsity - Options Module",
        title="India NSE Options: Weekly Expiry Dynamics and Expiry Day Trading",
        content="""
NSE EXPIRY CALENDAR:
  - Nifty 50: Weekly options expire every Thursday. Monthly options expire last Thursday of month.
  - BankNifty: Weekly options expire every Wednesday (changed from Thursday in Oct 2023).
  - FinNifty: Weekly options expire every Tuesday.
  - MidcapNifty: Weekly options expire every Monday.
  - Stock options: Monthly expiry on last Thursday of month.

LOT SIZES (as of 2024-2025):
  - Nifty 50: 25 units per lot (changed from 50 in Nov 2024).
  - BankNifty: 15 units per lot.
  - FinNifty: 40 units per lot.

EXPIRY THURSDAY SPECIFIC DYNAMICS:
  1. PRE-OPEN (9:00-9:15 AM): Delta hedging by MMs creates opening gap toward max pain.
  2. FIRST 30 MIN (9:15-9:45 AM): Extreme volatility. ATM gamma 10x normal.
     Nifty can move 50-100 points in minutes. Avoid new positions unless on 5-min breakout.
  3. MID-DAY (11 AM-1 PM): Price "pins" near max pain or key OI strikes. Theta kills OTM options.
  4. AFTERNOON DRIFT (1-2:30 PM): IV collapses dramatically. OTM options → near zero.
  5. POWER HOUR (2:30-3:30 PM): Final hedging, position closure. Gamma explosion for ATM.
     ATM Nifty option can double or go to near-zero in final 30 minutes.

THETA STRATEGY ON EXPIRY DAY:
  - SELL: Sell strangles/straddles in morning and buy back in afternoon.
  - BUY: Only buy ATM options for directional bets AFTER strong breakout confirmation.
  - AVOID: Buying OTM options after 2 PM (near-certain total loss even if correct direction).

SETTLEMENT:
  - Physical settlement was introduced for stock options in 2019 (NSE).
  - Index options (Nifty, BankNifty) remain cash-settled.
  - Settlement price = closing price of Nifty/BankNifty on expiry day.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Market Maker Research + Trading Experience",
        title="Smart Money Positioning and Options Chain Reading for Institutional Intent",
        content="""
HOW TO READ INSTITUTIONAL INTENT FROM OPTIONS CHAIN:

1. CALL WRITING PATTERN (Bearish for near-term):
   - Large CE OI at current ATM or slightly OTM = institutional selling calls.
   - Interpretation: Institutions believe price will NOT exceed this level in current expiry.
   - Action: Watch for resistance at this strike; if breached with volume → short squeeze.

2. PUT WRITING PATTERN (Bullish for near-term):
   - Large PE OI at current ATM or slightly OTM below = institutional selling puts.
   - Interpretation: Institutions believe price will NOT fall below this level.
   - Action: Watch for support at this strike; if breached → put sellers scramble → sharp decline.

3. PUT-CALL PARITY AND SYNTHETIC POSITIONS:
   - Market makers maintain: C - P = S - K·e^(-rT) (put-call parity).
   - When this breaks: synthetic arbitrage is available (very rare in liquid NSE markets).
   - Divergence between CE and PE premium = market maker delta-hedging impact.

4. READING THE OI CHANGE COLUMN:
   - Fresh OI in CE (strike below spot): Long CALL accumulation → bullish.
   - Fresh OI in PE (strike above spot): Short PUT accumulation → bullish.
   - Fresh OI in CE (strike far above spot): Covered call writing → range-bound.
   - Unwinding in PE (OI decrease) while price falls: Long puts being closed → bearish exhaustion.

5. DELTA-ADJUSTED POSITIONING:
   - True directional exposure = Strike OI × Delta at that strike.
   - ATM OI matters more than OTM OI for near-term price pressure.
   - Delta of 0.30 on 10,000 OI contracts = 3,000 effective shares of exposure.

6. VANNA AND CHARM FLOWS (advanced):
   - Vanna: dVega/dSpot or equivalently dDelta/dIV — affects hedging when IV moves.
   - Charm: Rate of delta decay over time — creates natural selling/buying as expiry approaches.
   - These second-order Greeks create mechanical buying/selling that explains intraday drift.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Professional Options Trading Research",
        title="IV Crush, Event Premium, and Volatility Trading Around Events",
        content="""
IV CRUSH is the rapid decline in implied volatility after a binary event (earnings, RBI, Fed).

HOW IV CRUSH WORKS:
  1. Before event: Market buys options (straddles) → IV inflates to price in event uncertainty.
  2. The event occurs → uncertainty resolves → option buyers liquidate → IV collapses.
  3. Options SELLERS win even if they predicted direction correctly (IV collapse destroys premium).

HISTORICAL IV CRUSH ON NSE (approximate):
  - RBI Policy Day: IV drops 20-35% immediately after announcement.
  - Union Budget: IV drops 25-50% immediately after speech concludes.
  - US Fed FOMC: IV drops 15-25% on Nifty/BankNifty in next session.
  - Nifty quarterly index review: IV drops 10-15%.
  - Heavyweights earnings (TCS, Infosys, HDFC Bank): Stock IV drops 30-60%.

TRADING IV CRUSH (EVENT VOLATILITY STRATEGIES):
  Strategy 1 — Short Straddle/Strangle BEFORE event (risky):
    Sell ATM straddle 2 days before event. Close immediately after event.
    Risk: Event causes large move exceeding premium collected.
    Edge: IV is overstated vs realized move ~60% of the time historically.

  Strategy 2 — Buy before, Sell after:
    Buy options (long gamma) before event, sell into IV expansion.
    Close before event announcement if possible.
    Avoid: Being long through the event itself.

  Strategy 3 — Calendar Spread:
    Short near-term option (high IV), long far-term option (lower IV).
    Profit from near-term IV collapsing faster than far-term.

QUANTIFYING EVENT PREMIUM:
  Expected Move = ATM Straddle Price ≈ IV × Spot × √(T/365)
  For RBI policy day (IV = 15%, Nifty at 24000, T = 1/365):
  Expected Move ≈ 0.15 × 24000 × √(1/365) ≈ 188 points (±0.78%)
  If actual realized move < 188 pts → option sellers win.
        """,
    ),
]
