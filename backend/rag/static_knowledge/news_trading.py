"""
Expert Knowledge: News-Driven and Event-Based Trading

Sources: SEBI Economic Event Research, RBI Publications, NSE Academy,
ForexFactory methodology, economic surprise theory (Citigroup), news NLP research.
"""
from . import KnowledgeChunk

DOMAIN = "news_trading"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="Event-Driven Trading Research",
        title="Tier Classification of Market-Moving Events for Indian Markets",
        content="""
EVENT IMPACT CLASSIFICATION FRAMEWORK (India F&O Markets):

TIER 1 — EXTREME IMPACT (avoid trading 30 min before, 60 min after):
  1. RBI Monetary Policy Committee (MPC) Decision:
     - Announced 6 times/year (Feb, Apr, Jun, Aug, Oct, Dec).
     - Repo rate change of 25 bps = Nifty moves 0.5-1.5%.
     - Rate hike (unexpected) = bearish. Rate cut = bullish. On-hold (expected) = minor reaction.
     - BankNifty moves 2-4× more than Nifty on RBI day.
     - IV typically 50-100% above normal on RBI day.
  2. Union Budget (February 1 each year):
     - Highest impact event of the year. Nifty can move 3-7% on budget day.
     - Market moves on capital gains tax, sector-specific announcements, fiscal deficit.
     - IV inflates 3-5 days before. Sell straddles AFTER speech concludes.
  3. US Federal Reserve FOMC Meeting (8 times/year):
     - Rate hike in US = FII outflows from India = bearish next Indian session.
     - Rate cut in US = EM inflows = bullish.
     - "Hawkish pause" = USD strengthens = bearish for INR and Nifty.
     - Impact reaches India in next morning's opening gap (meeting is 11:30 PM-12 AM IST).
  4. Elections (General and State):
     - General election results: Most impactful event. Nifty ±5-10% on result day.
     - Exit polls on Sunday night → Monday gap open.
     - "Modi premium" / ruling party continuity = bullish.
  5. Critical geopolitical events:
     - India-Pakistan military escalation: Sharp immediate selloff.
     - China-India border tension: Selective selling (defense, autos, IT).
     - Russia-Ukraine, Middle East escalation: Crude spike → India bearish.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Economic Calendar Analysis",
        title="Tier 2 and Tier 3 Events: India and Global Economic Data",
        content="""
TIER 2 — MEDIUM IMPACT (reduce position size, tighten stops):
  India Economic Data:
    - CPI (Consumer Price Index): Released ~12th of each month. >6% = hawkish RBI signal.
    - WPI (Wholesale Price Index): Released ~14th of each month.
    - IIP (Index of Industrial Production): Released ~12th of following month.
    - GDP Quarterly: Last day of month following quarter. India target: >6.5% = bullish.
    - GST Revenue data: Monthly. >₹1.6 lakh Cr = strong domestic demand.
    - Trade Balance: Monthly. Deficit widening + crude high = rupee weakness.

  Corporate Events:
    - Nifty 50 heavyweight earnings (Reliance, HDFC Bank, ICICI, TCS, Infosys, SBI):
      Combined weight ~35% of Nifty 50. Their results matter hugely.
    - MSCI/FTSE India index rebalancing (quarterly): Large-cap additions attract FII buying.
    - FPO/QIP large issues: Dilution pressures specific stocks.

  Global Tier 2:
    - US Non-Farm Payrolls (first Friday of month): >200K = Fed hawkish signal.
    - US CPI: >3% = Fed concern = higher for longer = bad for EM.
    - China PMI (Manufacturing and Services): <50 = contraction = global risk-off.
    - Eurozone interest rate decisions: Impact on DXY and risk-on/off sentiment.

TIER 3 — LOW IMPACT (minimal adjustment needed):
  - Analyst upgrades/downgrades (priced in quickly).
  - Minor corporate news (dividend announcements, small buybacks).
  - Routine export/import data.
  - Auto monthly sales figures (sector-specific, not index-moving).
  - Weekly FII/DII data (market already knows from daily provisional data).
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Economic Surprise Theory - Citigroup Research",
        title="Economic Surprise Index: How Deviations from Consensus Drive Markets",
        content="""
ECONOMIC SURPRISE INDEX (ESI) THEORY (Citigroup, 2003):
  Core insight: Markets price in CONSENSUS forecasts.
  Only DEVIATIONS from consensus move markets, not the absolute numbers.

  Economic Surprise = Actual Result - Consensus Forecast

  Positive surprise → bullish (better than expected = good news despite high absolute level).
  Negative surprise → bearish (worse than expected = bad news despite low absolute level).
  Meets consensus exactly → minimal market impact.

HOW TO APPLY IN NEWS TRADING:
  1. Know the CONSENSUS FORECAST before the announcement (Bloomberg, Reuters, Refinitiv).
  2. Wait for actual number.
  3. Calculate surprise = Actual - Consensus.
  4. Size of surprise × market sensitivity = expected price move.

INDIA CPI EXAMPLE:
  Consensus: 5.0%. Actual: 6.2%. → Surprise = +1.2% → Hawkish RBI signal.
  Market reaction: Nifty down 0.5-1.0%, BankNifty down 1-2%, INR weakens.

  Consensus: 5.5%. Actual: 4.8%. → Surprise = -0.7% → Dovish RBI signal.
  Market reaction: Nifty up 0.3-0.7%, BankNifty up 0.5-1%, INR strengthens.

"PRICED IN" CONCEPT:
  When an event is widely anticipated (no surprise), market has already moved.
  Buy the rumor, sell the news: Price rises INTO the positive announcement, falls AFTER.
  Classic examples: Expected rate cuts already priced in; actual cut causes selling.
  How to identify "priced in": Market has moved significantly toward the expected outcome
  in the 5-10 days BEFORE the announcement.

SECOND-ORDER EFFECTS (read the STATEMENT not just the number):
  RBI raises rates 25 bps (expected) but uses hawkish language → market falls despite "priced in" hike.
  RBI holds rates but signals cuts ahead → market rallies despite "no change".
  Policy statements, forward guidance, and press conference often matter MORE than the number.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="News Sentiment NLP Research",
        title="Headline Sentiment Classification and Market Impact Scoring",
        content="""
NEWS HEADLINE CLASSIFICATION METHODOLOGY:

STEP 1: IDENTIFY THE EVENT TYPE
  Monetary policy → High impact, sector: all
  Budget/Fiscal → High impact, sector: all
  Earnings → Medium-High impact, sector: specific company/sector
  Geopolitical → High impact, sector: defense, energy, IT (disruption)
  Economic data → Medium impact, depends on surprise direction
  Corporate action → Low-Medium impact, sector-specific

STEP 2: ASSESS DIRECTIONAL SENTIMENT
  Positive keywords: "beats", "raises guidance", "stronger than expected", "cuts rates",
    "stimulus", "record profit", "upgraded", "approves", "launches", "wins contract".
  Negative keywords: "misses", "cuts guidance", "weaker than expected", "raises rates",
    "warns", "investigation", "misses target", "defaults", "recession", "slowdown".
  Neutral/Ambiguous: "in-line", "as expected", "plans to", "considering", "may".

STEP 3: CHECK IF PRICED IN
  Price has risen 3%+ in past week AND positive news → likely priced in, reduce bullish confidence.
  Price has fallen 5%+ in past week AND negative news → may be priced in, reduce bearish confidence.

STEP 4: ASSESS AVOID-TRADING WINDOW
  HIGH IMPACT events: Set avoid window 30 minutes before + 60 minutes after.
  MEDIUM IMPACT: Reduce position size, do NOT set full avoid window.
  Exceptions: If direction is extremely clear and consensus is wrong → high confidence trade.

FAKE NEWS AND RUMORS:
  Social media rumors: Low reliability. Require confirmation from mainstream source.
  WhatsApp/Telegram "news": Almost always false or significantly delayed.
  Legitimate sources: RBI website, NSE circular, company BSE/NSE filing, Bloomberg, Reuters.
  Red flag: News not confirmed on BSE/NSE filing system within 30 min of market reaction.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="India Market-Moving Events Calendar Research",
        title="RBI Policy, Budget, and Elections: Detailed Trading Playbooks",
        content="""
RBI MONETARY POLICY PLAYBOOK:
  Day before:
    - IV inflates 20-40% on ATM Nifty options.
    - Sell straddle to capture IV premium → risky approach.
    - Buy strangle if unsure of direction but expecting large move.

  Day of decision (typically 10 AM announcement):
    - 9:15-10:00 AM: High uncertainty, wide spreads. Avoid new positions.
    - 10:00 AM announcement: Immediate sharp move. Widest spreads of the day.
    - 10:00-10:30 AM: IV crush begins. Option premiums collapse rapidly.
    - 10:30 AM onwards: Normal trading resumes. New directional opportunities.

  RATE OUTCOMES AND EXPECTED NIFTY MOVE:
    Unexpected rate CUT: Nifty +1 to +2%, BankNifty +2 to +4%.
    Expected rate CUT: Nifty +0.3 to +0.7% (priced in).
    Rate HOLD (expected): Nifty ±0.2-0.5%.
    Unexpected rate HIKE: Nifty -1.5 to -2.5%, BankNifty -3 to -5%.
    Governor's statement hawkish: BankNifty -1 to -2% even if rate unchanged.

BUDGET DAY (February 1) PLAYBOOK:
  Pre-budget (2-3 weeks before):
    - Capital goods, infrastructure, defense, railways typically rally (budget anticipation).
  Budget speech (11:00 AM - 1:00 PM usually):
    - Nifty often rallies as positive announcements come → then corrects when reality sets in.
    - "Budget speech price" vs "After-reaction price" often diverge.
  Post-speech:
    - Key items: Capital gains tax, STT rate, fiscal deficit number.
    - Capital gains tax hike = immediate option market panic (happened July 2024).
    - Fiscal deficit < 5.1% of GDP = positive.
  3-5 days after: Rerating of sector-specific stocks based on allocations.

ELECTION RESULT DAY PLAYBOOK (General Elections):
  Exit polls (Sunday 6:30 PM IST): SGX Nifty/Gift Nifty spikes 1-3% if ruling party winning.
  Result counting (Monday 8:00 AM): Gradual price discovery.
  Result clear (usually 10:00 AM-2:00 PM): Final major move.
  Key rule: Don't buy on exit poll gap. Wait for actual results to confirm.
        """,
    ),
]
