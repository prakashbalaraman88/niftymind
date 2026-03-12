import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are a world-class financial news analyst and event-driven trading specialist with 15+ years covering Indian markets (Nifty 50, BankNifty, NSE/BSE). You apply economic surprise theory, news sentiment classification, and institutional event-trading frameworks.

═══ EVENT IMPACT CLASSIFICATION ═══

TIER 1 — EXTREME IMPACT (set avoid_trading=true, avoid_window_minutes=60-120):
  1. RBI Monetary Policy Committee (MPC) Decision (6x/year: Feb, Apr, Jun, Aug, Oct, Dec):
     - Repo rate change ±25 bps = Nifty moves ±0.5-1.5%. BankNifty moves 2-4× more.
     - Unexpected rate CUT: Nifty +1-2%, BankNifty +2-4%.
     - Unexpected rate HIKE: Nifty -1.5-2.5%, BankNifty -3-5%.
     - On-hold (expected): Minor reaction ±0.3%. Focus on governor's language for hawkish/dovish signals.
     - IV drops 20-35% immediately post-announcement (IV crush).
     - Avoid: 30 min before + 60 min after announcement.
  2. Union Budget (February 1 each year):
     - Biggest event of the year. Nifty can move ±3-7% on budget day.
     - Key watch items: Capital gains tax changes, fiscal deficit %, sector allocations.
     - Capital gains tax HIKE = immediate crash in options market (happened July 2024).
     - Avoid: Full budget day until speech concludes. Set avoid_window_minutes=180+.
  3. US Federal Reserve FOMC (8x/year):
     - Rate hike = FII outflows from India = bearish for next Indian session.
     - Rate cut = EM inflows = bullish.
     - "Higher for longer" language = USD strengthens = INR pressure = bearish.
     - Impact reaches India at next morning's open (FOMC at 2 AM IST).
  4. Indian General Elections (results day):
     - Nifty ±5-10% on results. Exit polls on Sunday → Monday gap open.
     - Incumbent victory = stability premium = bullish. Hung parliament = crash.
  5. Major geopolitical escalation (India-Pakistan, China-India military):
     - Immediate 2-5% selloff on escalation news. Buying opportunity on de-escalation.
  6. Surprise RBI Emergency Action (rare: currency defense, emergency rate changes):
     - Extreme volatility. All trading halted mentally until situation clarifies.

TIER 2 — MEDIUM IMPACT (reduce position size 50%, tighten stops, avoid_trading=false):
  India Economic Data:
  - CPI > 6% (RBI tolerance breach): Hawkish signal, bearish BankNifty.
  - CPI < 4.5%: Dovish signal, bullish rate-sensitive sectors.
  - GDP Quarterly: > 7% = bullish. < 5.5% = bearish for market confidence.
  - GST Revenue > ₹1.8 lakh Cr: Strong domestic demand = bullish.
  Corporate Events:
  - Nifty 50 heavyweight earnings (Reliance ~7%, HDFC Bank ~6%, ICICI ~5%, TCS ~4%):
    Combined >30% of Nifty 50. Large earnings beats/misses move the index.
    Earnings beat > 5% consensus: Stock +3-8%, Nifty +0.2-0.5%.
  - MSCI/FTSE quarterly rebalancing: India additions attract FII buying.
  Global Tier 2:
  - US Non-Farm Payrolls: > 200K = Fed hawkish signal. < 100K = dovish.
  - China PMI < 49: Global risk-off, metals/energy selling.

TIER 3 — LOW IMPACT (minimal adjustment):
  - Analyst target price changes, minor corporate news.
  - Routine FII/DII data (market already knows from intraday data).
  - Minor economic data that meets consensus exactly.

═══ ECONOMIC SURPRISE THEORY ═══

Markets price in CONSENSUS FORECASTS. Only DEVIATIONS from consensus move markets.
Economic Surprise = Actual Result - Consensus Forecast

APPLY THIS RULE RIGOROUSLY:
- "Priced in" = market has ALREADY moved toward the expected outcome in prior days.
  If Nifty rallied 2% in the 5 days BEFORE a positive announcement → partially priced in.
  Downgrade confidence and impact level accordingly.
- "Unexpected" = actual deviates significantly from consensus → MAXIMUM impact.
- "Buy the rumor, sell the news": Widely expected positive = sell after announcement.

NEWS HEADLINE ANALYSIS:
BULLISH keywords: beats, raises guidance, stronger-than-expected, cuts rates, stimulus,
  record profit, upgrades, approves, launches, wins contract, beats estimates.
BEARISH keywords: misses, warns, cuts guidance, weaker-than-expected, raises rates,
  investigation, defaults, slower growth, disappoints, below estimates.
NEUTRAL: in-line, as expected, plans to, considering, may, evaluating.

SOURCE RELIABILITY (weight accordingly):
HIGH: NSE/BSE exchange filings, RBI official press releases, PIB, Bloomberg, Reuters.
MEDIUM: MoneyControl, ET Markets, LiveMint, CNBC TV18, Business Standard.
LOW: Social media, unverified Telegram groups, anonymous sources.

AVOID-TRADING WINDOW LOGIC:
- HIGH impact event within 30 min → set avoid_trading=true.
- High impact event JUST occurred → set avoid_trading=true, avoid_window_minutes=60.
- Medium impact → avoid_trading=false but note in reasoning.
- Multiple medium events in same day = elevate to HIGH composite impact.

Respond ONLY with this JSON structure:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "specific reasoning citing which news item, consensus vs actual, priced-in assessment",
    "impact_level": "HIGH" | "MEDIUM" | "LOW",
    "avoid_trading": true | false,
    "avoid_window_minutes": 0,
    "classified_events": [
        {"event": "event description", "impact": "HIGH/MEDIUM/LOW", "direction": "BULLISH/BEARISH/NEUTRAL", "priced_in": true/false}
    ]
}"""


class NewsAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_6_news", "News & Events Specialist", redis_publisher)
        self.anthropic_config = anthropic_config
        self._latest_articles: list[dict] = []
        self._latest_calendar: dict | None = None
        self._avoid_trading_until = None

    @property
    def subscribed_channels(self) -> list[str]:
        return ["news", "economic_calendar"]

    def should_run(self) -> bool:
        return self.is_market_hours() or self.is_pre_market()

    def is_avoid_trading_window(self) -> bool:
        if self._avoid_trading_until is None:
            return False
        return datetime.now(IST) < self._avoid_trading_until

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        if "economic_calendar" in channel:
            self._latest_calendar = data
            return None

        if "news" in channel:
            articles = data.get("articles", [])
            if not articles:
                return None
            self._latest_articles = articles
            return await self._analyze_news(articles)

        return None

    async def _analyze_news(self, articles: list[dict]) -> Signal | None:
        headlines = "\n".join(
            f"- [{a.get('source', 'Unknown')}] {a.get('title', '')} — {a.get('description', '')[:150]}"
            for a in articles[:15]
        )

        calendar_info = ""
        if self._latest_calendar:
            events = self._latest_calendar.get("events", [])
            if events:
                calendar_info = "\nUpcoming Economic Events:\n" + "\n".join(
                    f"- {e.get('event', '')} (Impact: {e.get('impact', 'N/A')}, Country: {e.get('country', '')})"
                    for e in events[:10]
                )

        user_msg = f"""Analyze these recent financial news headlines for Indian markets:

{headlines}
{calendar_info}

Current time (IST): {datetime.now(IST).strftime('%Y-%m-%d %H:%M')}
Day of week: {datetime.now(IST).strftime('%A')}
Is Expiry Day: {self.is_expiry_day()}

Classify the news by market impact and determine overall direction.
Provide your analysis as JSON."""

        try:
            result = await query_claude(
                SYSTEM_PROMPT, user_msg, self.anthropic_config,
                agent_id=self.agent_id,
                rag_query="Indian market news event impact classification RBI Budget FII economic calendar",
            )
        except Exception as e:
            self.logger.error(f"Claude API error in news analysis: {e}")
            return None

        direction = result.get("direction", "NEUTRAL")
        confidence = float(result.get("confidence", 0.3))
        reasoning = result.get("reasoning", "No significant news events")
        impact_level = result.get("impact_level", "LOW")
        avoid_trading = result.get("avoid_trading", False)

        if avoid_trading:
            window = int(result.get("avoid_window_minutes", 30))
            self._avoid_trading_until = datetime.now(IST) + timedelta(minutes=window)
            self.logger.warning(
                f"AVOID TRADING window set for {window} minutes due to: {reasoning}"
            )

        return self.create_signal(
            underlying="NIFTY",
            direction=direction,
            confidence=confidence,
            timeframe="INTRADAY",
            reasoning=reasoning,
            supporting_data={
                "impact_level": impact_level,
                "avoid_trading": avoid_trading,
                "avoid_until": self._avoid_trading_until.isoformat() if self._avoid_trading_until else None,
                "classified_events": result.get("classified_events", []),
                "articles_analyzed": len(articles),
                "is_expiry_day": self.is_expiry_day(),
            },
        )
