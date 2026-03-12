"""
Expert Knowledge: Global Macro Analysis and India Equity Impact

Sources: Ray Dalio (Principles for Navigating Big Debt Crises), Stanley Druckenmiller
interviews, George Soros (Alchemy of Finance), BIS research papers, RBI annual reports,
IMF India country reports, Bloomberg commodity research.
"""
from . import KnowledgeChunk

DOMAIN = "global_macro"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="Ray Dalio - Bridgewater Associates Research",
        title="Global Macro Framework: Risk-On/Risk-Off and the Economic Machine",
        content="""
RAY DALIO'S ECONOMIC MACHINE MODEL:
  The economy is a collection of transactions. Credit creates economic growth beyond income.
  Long-term debt cycle (50-75 years): Expansion → Bubble → Deleveraging.
  Short-term business cycle (5-8 years): Expansion → Recession → Recovery.
  Understanding which phase we're in determines optimal asset allocation.

RISK-ON vs RISK-OFF ENVIRONMENT:

RISK-ON (favorable for Indian equities/Nifty):
  Indicators: S&P 500 rising, VIX falling, DXY falling, EM currencies strengthening,
  high-yield spreads compressing, commodity prices rising, gold falling.
  What happens to India: FII inflows → INR appreciates → Nifty rallies.
  Typical magnitude: Every 1% S&P 500 gain → 0.3-0.5% Nifty gain.

RISK-OFF (unfavorable for Indian equities):
  Indicators: S&P 500 falling, VIX > 20, DXY rising, US Treasury yields falling
  (flight to safety), gold rising, EM currencies weakening, credit spreads widening.
  What happens to India: FII outflows → INR depreciates → Nifty falls.
  Historical trigger events: US rate hikes 2022 (Nifty -15%), COVID March 2020 (-40% in 4 wks).

ALL WEATHER PORTFOLIO SENSITIVITY:
  Dalio's framework for what beats each macro scenario:
  - High growth + rising inflation: Commodities, gold, inflation-linked bonds.
  - High growth + falling inflation: Equities (India, EM).
  - Low growth + falling inflation (deflation): Long bonds, gold.
  - Low growth + rising inflation (stagflation): Gold, commodities. Worst for equities.
  India macro context: India is typically a "high growth + controlled inflation" story.
  Threat: Crude oil spike causes stagflation scenario → very bearish for Nifty.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Goldman Sachs EM Research + RBI Annual Report",
        title="US-India Equity Correlation: Mechanisms and Quantification",
        content="""
US-INDIA EQUITY CORRELATION (Nifty 50 vs S&P 500):
  Historical correlation coefficient: 0.55-0.70 over 1-year rolling periods.
  Correlation highest during global crises (approaches 0.90+ during extreme events).
  Correlation lower during India-specific events (Budget, RBI, elections).

TRANSMISSION MECHANISM:
  1. DIRECT (FII flows): S&P 500 rises → US institutional risk appetite increases →
     FII allocate more to EM including India → FII buy Indian stocks → Nifty rises.
  2. INDIRECT (sentiment): S&P 500 = global barometer. When US falls, all risk assets fall.
  3. DOLLAR CHANNEL: S&P 500 up → DXY often falls (risk-on) → INR strengthens → FII
     returns in USD terms improve → more India allocation → Nifty up.

OVERNIGHT GAP PREDICTION MODEL:
  Next-day Nifty gap ≈ 0.4 × S&P 500 overnight change + 0.1 × Nasdaq change
  + 0.3 × Gift Nifty change (relative to previous Nifty close)
  + 0.1 × (Asian markets at 8 AM IST) - 0.1 × DXY change
  + India-specific event premium (±0.3-2% depending on event).

SPECIFIC QUANTITATIVE RELATIONSHIPS:
  S&P 500 futures +1%: Nifty likely opens +0.3-0.5%.
  S&P 500 futures -1%: Nifty likely opens -0.3-0.5%.
  S&P 500 futures +2%: Nifty likely opens +0.7-1.0%.
  S&P 500 futures -2%: Nifty likely opens -0.7-1.0%.
  S&P 500 futures > +3% or < -3%: Nifty follow rate may differ (India-specific factors dominate).

WHEN CORRELATION BREAKS:
  RBI surprise decision: India overrides global signal.
  Budget Day: Domestic policy dominates.
  India-specific crises (demonetization 2016, NBFC crisis 2018): India decouples and falls more.
  India-specific boom: IPO market frenzy 2021: India outperformed global markets significantly.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="BIS Research + India Petroleum Ministry Data",
        title="Crude Oil and India: Macroeconomic Impact on Currency, Inflation, and Equities",
        content="""
INDIA'S CRUDE OIL DEPENDENCY:
  - India imports 85-87% of its crude oil requirements.
  - Oil import bill: $140-180 billion/year (depends on Brent price and rupee).
  - Every $10/bbl rise in Brent crude → adds ~₹70,000-90,000 Cr to import bill.
  - Every $10/bbl rise → widens Current Account Deficit (CAD) by ~0.4-0.5% of GDP.

CRUDE → INR → EQUITIES TRANSMISSION:
  Crude rises $10/bbl → CAD widens → INR depreciates ~0.5-1%.
  INR depreciates → FII USD returns erode → FII sell Indian assets.
  FII sell → Nifty falls.
  Magnitude: $10/bbl sustained crude rise = 200-400 Nifty points over 2-4 weeks.

SECTOR-SPECIFIC CRUDE OIL IMPACT:

  NEGATIVE (costs rise):
  - Aviation (IndiGo, SpiceJet): Jet fuel = 30-40% of revenue.
  - Paints (Asian Paints, Berger): Crude derivatives as inputs.
  - Tyres (MRF, Apollo): Natural rubber + crude derivatives.
  - Chemicals: Petrochemical feed stocks become expensive.
  - FMCG: Packaging costs rise.

  POSITIVE (revenues rise):
  - ONGC, Oil India: Upstream producers benefit directly.
  - Reliance Industries: Refining margins + petrochemicals (complex relationship).
  - BPCL, HPCL, IOC: Government controls retail prices → squeezed margins.

  THRESHOLD LEVELS:
  Brent < $70: Very positive for India. Rally likely in next 2-4 weeks.
  Brent $70-85: Comfortable range. Normal market conditions.
  Brent $85-95: Caution. Inflation concern. INR pressure.
  Brent > $95: Negative for India. FII outflows. RBI hawkish. CAD concerns.
  Brent > $100: Significant bearish catalyst. Historical example: 2022 Russia-Ukraine.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Deutsche Bank EM Currency Research",
        title="DXY, USD/INR, and EM Capital Flows",
        content="""
US DOLLAR INDEX (DXY):
  Measures USD strength against basket of 6 currencies: EUR (57.6%), JPY (13.6%),
  GBP (11.9%), CAD (9.1%), SEK (4.2%), CHF (3.6%).
  DXY rising = USD strengthening = risk-off globally.

DXY → INDIA TRANSMISSION:
  DXY rises → USD strengthens → EM currencies (including INR) weaken.
  INR weakens → India becomes less attractive to FIIs (dollar returns erode).
  FII outflows → Nifty falls.
  Typical relationship: DXY +1% → INR weakens 0.3-0.7% → Nifty -0.2-0.5%.

DXY CRITICAL LEVELS:
  DXY > 105: Strong USD regime. EM under pressure. India bearish unless domestic drivers.
  DXY 100-105: Elevated, manageable. Watch FII flow data for India impact.
  DXY 95-100: Normal range. Neutral impact on India.
  DXY < 95: Weak USD = risk-on = EM inflows = Nifty bullish.
  DXY falling sharply after US data disappointment: Immediate positive for Nifty.

USD/INR SPECIFIC DYNAMICS:
  RBI defends INR typically in ₹84-86/$1 range (active intervention via forex reserves).
  RBI forex reserves: ~$640-680 billion (2024). Adequate buffer.
  INR appreciation beyond ₹82/$ = RBI intervenes to prevent export competitiveness loss.
  INR depreciation past ₹86/$: RBI sells USD, reduces dollar supply.
  Sudden INR drop > 1% in a day = emergency risk-off signal → immediate bearish for equities.

CARRY TRADE DYNAMICS:
  India rates (repo 6.5%) vs US rates (Fed 5.25-5.5%) = ~125 bps spread.
  Carry trade: Borrow USD, invest in Indian bonds.
  When spread narrows (US hikes while India holds): Carry trade unwind → FII sell bonds → sell INR.
  "Carry unwind" episodes create sharp INR depreciation and Nifty selloffs.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Federal Reserve Research + Global Macro Analysis",
        title="US Treasury Yields, Fed Policy, and Global Liquidity Impact on India",
        content="""
US TREASURY YIELDS AS GLOBAL BENCHMARK:
  US 10Y Treasury is the risk-free rate of the world.
  All risky assets are priced as: Risk-free rate + Risk premium.
  When 10Y yield rises: Risk premium required for EM equities must ALSO rise → EM equities fall.

YIELD LEVELS AND INDIA IMPACT:
  10Y < 3.5%: Very accommodative. FII flowing freely into EM. India bullish.
  10Y 3.5-4.0%: Moderate. FII selective in EM allocation.
  10Y 4.0-4.5%: Elevated. FII cautious on EM. India needs strong domestic growth to outperform.
  10Y > 4.5%: Risk-off for EM. FII prefer US bonds over Indian equities.
  10Y > 5.0%: Emergency level. Last seen 2007. Extreme FII outflows from EM.

FED POLICY CYCLE AND INDIA EQUITIES (historical patterns):
  First Fed rate cut (post-hike cycle): Nifty initially rallies 3-7% over next 3-6 months.
  Fed hiking cycle begins: India typically underperforms for 6-12 months.
  Fed "pause" after hiking: India stabilizes, waits for cut signal.
  "Higher for longer" (2022-2023): USD strength, FII outflows, Nifty underperformed EM peers.

YIELD CURVE ANALYSIS:
  Normal yield curve (10Y > 2Y): Healthy economy expected.
  Inverted yield curve (2Y > 10Y): Recession warning 6-18 months ahead.
  Current status (2024): US yield curve inverted since July 2022 → recession risk.
  India-specific: Inverted US yield curve → eventually bullish for India (Fed will eventually cut).

REAL YIELDS (nominal yield - inflation) MATTER:
  Real yield = US 10Y nominal - US CPI.
  Positive real yields > 2%: Very bearish for gold, bullish for USD, mixed for EM.
  Negative real yields: USD weakness expected, gold rallies, EM inflows.
  Historical: Nifty performs best when US real yields are negative (2020-2021).

QUANTITATIVE TIGHTENING (QT) vs EASING (QE):
  QT: Fed shrinks balance sheet → less global liquidity → EM outflows → Nifty bearish.
  QE: Fed expands balance sheet → excess global liquidity → EM inflows → Nifty bullish.
  Current: Fed in QT phase since mid-2022 → headwind for India.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Asian Markets Correlation Research",
        title="Hang Seng, Nikkei, and Asian Market Intraday Correlations with Nifty",
        content="""
ASIAN MARKET INTRADAY CORRELATIONS WITH NIFTY:

HANG SENG (Hong Kong, HKEx):
  Trading hours (IST): 6:45 AM - 1:00 PM, 2:15 PM - 5:15 PM.
  Overlap with NSE: 9:15 AM - 1:00 PM.
  Correlation with Nifty: Moderate (0.4-0.6) during intraday overlap.
  When China (HSCEI) weak: India often follows with 30-60 min lag.
  EXCEPTION: During China-India geopolitical tension → India may RISE as China falls (safe-haven EM).
  China PMI < 50 + Hang Seng falling: Bearish signal for Nifty commodity stocks (metals, energy).

NIKKEI 225 (Japan, TSE):
  Trading hours (IST): 5:30 AM - 11:30 AM, 12:30 PM - 4:00 PM.
  Overlap with NSE: 9:15 AM - 4:00 PM (with gap 11:30-12:30 PM IST).
  Nikkei correlation with Nifty: 0.5-0.65.
  Nikkei is risk-on proxy — when Nikkei rises sharply, it signals global risk appetite.
  Nikkei carry trade (borrow JPY, invest in equities): If JPY strengthens sharply → Nikkei falls
  → Global risk-off → Nifty bearish.
  Japan BoJ surprise rate hike (2024): Sent Nikkei -12% in one day, Nifty -2% same day.

SGX NIFTY / GIFT NIFTY (Singapore/Gujarat):
  Available 24 hours. Most direct indicator for Nifty gap.
  8:00-9:00 AM IST: Most reliable reading.
  Gift Nifty tracks S&P 500, Asian markets, and India-specific news overnight.

TRADE-WEIGHTED INTRADAY SIGNAL FRAMEWORK:
  Weight each input:
  - Gift Nifty 8:00 AM: 40% weight (most direct).
  - S&P 500 futures: 30% weight.
  - Hang Seng intraday change: 15% weight.
  - Nikkei intraday change: 10% weight.
  - Crude oil change: 5% weight (inverse for India).
  Composite positive → BULLISH intraday bias.
  Composite negative → BEARISH intraday bias.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Commodity Trading Research",
        title="Gold, Silver, and Commodity Markets as Global Macro Signals",
        content="""
GOLD AS GLOBAL MACRO INDICATOR:

Gold rises when:
  - Real interest rates (nominal - inflation) are negative or falling.
  - USD weakens (inverse correlation).
  - Geopolitical uncertainty increases.
  - Central banks buying (EM central banks including RBI are net buyers).
  - Inflation expectations rise.
  - Global equity volatility spikes.

Gold → India translation:
  Gold rising with USD falling: Risk-on for EM. Nifty bullish.
  Gold rising with USD rising: Flight to safety (both). Nifty bearish.
  Gold falling with USD rising: Risk-off, strong USD. Nifty bearish.
  Gold falling with USD falling: Mild risk-on. Nifty moderately bullish.

India gold demand:
  India consumes 700-900 tonnes/year (second largest consumer).
  Festival season (Oct-Nov): Strong domestic gold demand → INR demand.
  Gold ETF inflows in India: Rising gold ETF AUM = domestic risk-off sentiment.

COPPER as economic indicator:
  "Dr. Copper" — most economically sensitive commodity.
  Copper rising: Global manufacturing strong → risk-on → EM including India bullish.
  Copper falling: Recession fears → risk-off → India metals sector bearish.
  Nifty Metal index closely tracks copper price direction.

NATURAL GAS (India import dependency increasing):
  High natural gas prices: Fertilizer cost up → agro chemicals affected.
  India LNG import dependency: ~20-25% of gas demand met by imports.

AGRICULTURAL COMMODITIES (India food inflation):
  High food commodity prices (wheat, soybean, sugar): India CPI rises → RBI hawkish.
  El Niño/drought years: India Kharif crop failure → food inflation → bearish.
  MSP (Minimum Support Price) hikes by government: Inflationary pressure.
        """,
    ),
]
