"""
Expert Knowledge: Order Flow Analysis and Market Microstructure

Sources: James Dalton (Mind Over Markets), Jigsaw Trading Research,
Wyckoff Method, Auction Market Theory, NSE F&O microstructure research.
"""
from . import KnowledgeChunk

DOMAIN = "order_flow"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="Market Microstructure Theory",
        title="Bid-Ask Spread, Market Impact, and Order Types",
        content="""
MARKET MICROSTRUCTURE: The study of how orders are converted into prices.

BID-ASK SPREAD:
  - Bid = highest price buyers will pay. Ask = lowest price sellers will accept.
  - Spread = Ask - Bid. Represents transaction cost and liquidity.
  - Tight spread (NSE Nifty ATM: 1-2 points) = highly liquid, low cost.
  - Wide spread (OTM options, small caps) = low liquidity, high cost.
  - Spread widens: pre-market, post-market, around events, low-volume periods.

ORDER TYPES and their microstructure impact:
  - Market Order: Aggressor. Crosses the spread, guaranteed fill, worse price.
    Creates immediate price movement in the direction of aggression.
  - Limit Order: Passive. Adds liquidity to the order book. Better price, uncertain fill.
  - Stop Order: Converts to market when price triggers. Creates cascading moves.
    Stop clusters below support create sharp breakdowns (stop hunts).
  - Iceberg Order: Large order hidden in small visible pieces.
    Detectable: same size appearing repeatedly at same price.

MARKET MAKERS vs TAKERS:
  - Market makers provide liquidity (post limits on both sides), earn spread.
  - Market takers consume liquidity (hit bids, lift offers), pay spread.
  - Large institutional flow → market makers widen spread + reprice quotes.
  - Algo dominated markets (80%+ NSE F&O): HFT market makers update quotes
    in microseconds, creating extremely tight ATM spreads.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Jigsaw Trading - Order Flow Mastery",
        title="Footprint Charts and Delta Analysis",
        content="""
FOOTPRINT CHARTS (also called Order Flow charts) show at EACH PRICE LEVEL
within a candle: buy volume vs sell volume.

KEY CONCEPTS:
  Delta (within footprint) = Buy Volume - Sell Volume per price level.
  - Positive delta per bar: more aggressive buying than selling.
  - Negative delta per bar: more aggressive selling than buying.
  - Delta divergence: price moves but delta contradicts → high-probability reversal signal.

READING FOOTPRINT IMBALANCES:
  Imbalance = when bid volume or ask volume at one price is 3x+ the opposing level.
  - Ask imbalance (ask >> bid): aggressive buyers stepping in → price likely to go UP.
  - Bid imbalance (bid >> ask): aggressive sellers stepping in → price likely to go DOWN.
  - "Stack of imbalances" = multiple consecutive price levels with same-direction imbalance →
    institutional participation, high conviction directional move.

DELTA DIVERGENCE (most reliable signal):
  Setup 1 — Bearish divergence: Price makes new high but candle delta is NEGATIVE.
  Interpretation: Buyers pushed price up but sellers overwhelmed them → exhaustion → short.

  Setup 2 — Bullish divergence: Price makes new low but candle delta is POSITIVE.
  Interpretation: Sellers pushed price down but buyers overwhelmed them → exhaustion → long.

  Confirm with: price staying below/above the divergence candle, increased volume.

CUMULATIVE DELTA (CD):
  Running sum of per-bar delta over a session.
  - CD rising with price: healthy trend, confirmed buying.
  - CD falling with rising price: distribution (selling into strength) → bearish.
  - CD rising with falling price: accumulation (buying into weakness) → bullish.
  - Divergence between CD trend and price trend = high-conviction reversal setup.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Wyckoff Method + Modern Order Flow Research",
        title="Absorption Theory: Effort vs Result and the Wyckoff Tests",
        content="""
ABSORPTION is when large orders (institutional) absorb the smaller opposing orders,
preventing price movement despite high volume. The "effort" doesn't produce the "result."

BULLISH ABSORPTION (at support):
  - High volume on down bars that don't break support → sellers being absorbed by buyers.
  - Classic Wyckoff "Spring" — price briefly dips below support, absorbs all sellers,
    immediately reverses. This is the best long entry.
  - Signs: Large volume, small range bars at support → strong buyer sitting there.

BEARISH ABSORPTION (at resistance):
  - High volume on up bars that don't break resistance → buyers being absorbed by sellers.
  - Classic Wyckoff "Upthrust" — price briefly spikes above resistance, absorbs all buyers,
    immediately reverses. Best short entry.
  - Signs: Large volume, small range bars at resistance → strong seller sitting there.

WYCKOFF'S "EFFORT VS RESULT" LAW:
  - Large effort (volume) should produce large result (price movement).
  - If large volume + small price move → absorption by opposing force.
  - If small volume + large price move → low resistance, trend continuation.

STOPPING VOLUME:
  - One exceptional-volume bar that halts a trend = stopping volume.
  - After stopping volume, price consolidates or reverses.
  - Identify: largest volume bar in a series of bars in the same direction.
  - NSE example: Nifty drops 200 points on 5 large candles, final candle has 3x avg volume
    but closes midrange → stopping volume → potential reversal at this level.

VOLUME CLIMAX (Selling Climax / Buying Climax):
  - Selling Climax: panic selling → maximum pessimism → smart money absorbs → reversal.
  - Buying Climax: euphoric buying → maximum optimism → smart money distributes → reversal.
  - Always preceded by a prolonged trend followed by an EXTREME volume spike.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Institutional Trading Research",
        title="Large Lot Detection and Institutional Order Flow in NSE F&O",
        content="""
DETECTING INSTITUTIONAL ORDERS IN NSE F&O:

LARGE LOT THRESHOLDS (NSE F&O):
  - Nifty Futures: > 100 lots (= 2,500 units) in single trade = institutional.
  - Nifty Options: > 50 lots (= 1,250 units) in single trade.
  - BankNifty Options: > 25 lots (= 375 units) in single trade.
  - Stock Options: > 10 lots or > ₹50 lakh notional.

BULK DEALS vs BLOCK DEALS (NSE rules):
  - Bulk Deal: Single transaction ≥ 0.5% of equity share capital.
    Reported on NSE website same day after market close.
  - Block Deal: Minimum ₹10 crore or 5 lakh shares in a single transaction.
    Executed in special 15-min window (8:45-9:00 AM or 2:05-2:20 PM).
  - Both signal institutional activity; direction indicates accumulation vs distribution.

TIME-AND-SALES TAPE READING (Nifty Options):
  - Rapid succession of trades at ASK price = aggressive buying (bullish signal).
  - Rapid succession of trades at BID price = aggressive selling (bearish signal).
  - Alternating bid-ask trades = two-way flow, balanced, NEUTRAL.
  - Large single trade at ask above rolling average size = institutional aggression.

HIDDEN INSTITUTIONAL ACTIVITY (algo detection):
  - TWAP (Time-Weighted Average Price) orders: Equal-sized lots placed every N minutes.
    Detectable: exact same size appearing at regular intervals at multiple prices.
  - VWAP orders: Volume-proportional throughout the day. Volume peaks at VWAP = institutional.
  - "Dark pool" equivalent on NSE: Exchange has institutional deals negotiated off-book
    and reported to exchange. RDX (Retail Direct) and institutional platform flows differ.

DERIVATIVE PROXY FOR CASH MARKET INTENT:
  - FII buying index futures = directional bet on broad market.
  - FII selling index futures + buying single-stock options = hedge on index but bullish individual.
  - Large OTM put purchases: Could be hedging or anticipating sharp fall.
  - Large OTM call purchases: Could be speculative or covering short positions.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Advanced Trading Research",
        title="Order Flow in Indian F&O: Algo Dominance and Retail Flow Patterns",
        content="""
NSE F&O MARKET STRUCTURE (2024-2025):
  - Algorithmic trading: ~80% of Nifty/BankNifty F&O volume by value.
  - Retail participation: ~20% by value, ~60-70% by number of accounts.
  - Consequence: Price discovery is FASTER than pre-algo era.
  - Large retail option buying creates predictable contrarian opportunities.
  - NSE reports: 90% of retail F&O traders lost money (2021-2023 SEBI study).

RETAIL vs INSTITUTIONAL FLOW PATTERNS:
  Retail:
    - Buys OTM options (lottery mentality).
    - Buys calls on green days, puts on red days (momentum chasing).
    - Average holding period < 1 day for options.
    - Concentrates activity in 9:15-9:45 AM and 2:30-3:30 PM.

  Institutional:
    - Sells options to retail (theta harvest strategy).
    - Uses spreads and hedged positions.
    - Builds positions gradually (TWAP/VWAP execution).
    - Concentrates activity 9:30-11:00 AM and 2:00-3:00 PM.

CONTRA-RETAIL SIGNAL:
  - When retail OI in OTM calls spikes dramatically (bullish enthusiasm) → SELL.
  - When retail OI in OTM puts spikes dramatically (panic) → BUY.
  - PCR < 0.6: Retail is irrationally bullish, institutional likely selling strength.
  - PCR > 1.8: Retail is panic-buying protection, institutional likely selling puts.

ORDER FLOW DURING KEY INTRADAY WINDOWS:
  9:15-9:45 AM (Opening): Maximum uncertainty. Widest spreads. Institutional limit orders.
    Often false breakouts as algos test both sides.
  10:00-11:30 AM (Discovery): True trend establishes. Best for directional trades.
  11:30 AM-1:30 PM (Lunch consolidation): Low volume. Often range-bound. Theta works.
  2:00-3:00 PM (Institutional close): Institutional position adjustment. Real moves.
  3:00-3:30 PM (Power hour): Final price discovery. High volume, definitive moves.
        """,
    ),
]
