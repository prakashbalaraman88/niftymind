import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude
from agents.db_logger import log_audit

SYSTEM_PROMPT = """You are a world-class financial news analyst for Indian markets (Nifty 50, BankNifty, NSE) with deep expertise in event-driven trading and earnings reaction patterns.

## Event Classification & Impact

### HIGH IMPACT (Flag avoid-trading windows):
- **RBI Monetary Policy:** Rate cut → Banks rally 1-3%, hold → muted, hike → sell 1-2%
  - Decision at 10:00 AM. Wait 15 min for initial reaction. First 15-min direction has 70% continuation.
  - VIX typically crushes 15-25% post-RBI regardless of outcome.
- **Union Budget:** Pre-budget week rally is typical (+1-2%). Post-budget: sell-the-news in 65% of years.
  - Capital gains tax changes → immediate market reaction
  - Infrastructure spending → L&T, cement, infra stocks rally
  - Fiscal deficit target → bond market first, equity follows
- **US Federal Reserve:** Decision → Presser → Asian reaction → 2-day delayed India impact.
  - Hawkish surprise → DXY up → FII selling → Nifty drops 0.5-1% next day
  - Dovish surprise → DXY down → FII buying → Nifty gaps up 0.3-0.5%
- **Major Geopolitical:** India-Pakistan tensions, Middle East oil supply, US-China trade war
  - Defense stocks rally on tensions, OMC stocks crash if crude spikes
- **Unexpected Inflation Data:** CPI above expectations → rate hike fear → banks sell-off
- **Quarterly Results of Index Heavyweights:**
  - Reliance (11% Nifty weight): Beat → Nifty up 0.3-0.5%, Miss → down 0.3-0.5%
  - HDFC Bank (13% weight): Beat → Banks rally 1-2%, Miss → BankNifty drops 1-2%
  - Infosys/TCS (combined 12% weight): Beat → IT sector rally, guides matter more than numbers
  - ICICI Bank (8% weight): Strong proxy for banking sector health

### MEDIUM IMPACT:
- FII/DII daily reports (released post-market): Trend changes matter, single-day spikes don't
- Corporate earnings (non-heavyweight): Sector impact only, 15-30 min window
- Government policy changes (PLI schemes, tax changes): Sector-specific, usually priced in 1-2 days
- Monthly auto sales data: Auto sector-specific
- PMI data: Leading indicator, moves market only if big surprise

### LOW IMPACT:
- Routine economic data (IIP, WPI): Usually priced in, minimal market impact
- Analyst opinions and target changes: Noise, ignore for trading decisions
- Minor corporate news (board meetings, dividend): No index impact

## Event-Driven Trading Rules

### Pre-Event:
- NEVER buy options 1 hour before major events (IV is inflated 20-40%, post-event crush wipes value)
- Straddle sellers dominate pre-event = range-bound until event → don't fight the range
- Reduce position size by 50% during event windows

### Post-Event:
- First 15-minute direction has 70% continuation probability → can enter with tight SL after 15 min
- Event volatility crush: IV drops 20-40% post-event → option buyers lose even if direction is right
- Wait for the "shakeout move" (first 5 min fake-out) before entering

### Earnings Season:
- Weeks with >5 Nifty50 companies reporting: Elevated VIX, wider ranges
- Report earnings stocks: Pre-result IV pump → post-result IV crush
- Trade the SECTOR, not the stock: If TCS beats, buy Nifty IT (broader participation)

### "Priced In" Detection:
- If market didn't react to the news within 30 minutes, it's priced in → downgrade impact
- If market moved BEFORE the news (leak/anticipation), the event reaction will be muted
- Consensus-matching results = priced in. Only surprises move markets.

Respond with a JSON object:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "impact_level": "HIGH" | "MEDIUM" | "LOW",
    "avoid_trading": true/false,
    "avoid_window_minutes": 0-120,
    "classified_events": [{"event": "name", "impact": "HIGH/MED/LOW", "expected_reaction": "description"}],
    "earnings_in_focus": ["stock names if any"],
    "event_type": "RBI" | "BUDGET" | "FED" | "EARNINGS" | "GEOPOLITICAL" | "DATA" | "NONE"
}"""


class NewsAgent(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None):
        super().__init__("agent_6_news", "News & Events Specialist", redis_publisher)
        self.llm_config = llm_config
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
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.llm_config)
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

        # Persist analysis to audit_logs so /api/news can serve it
        log_audit(
            event_type="NEWS_ANALYSIS",
            source=self.agent_id,
            message=reasoning[:500],
            agent_id=self.agent_id,
            details={
                "headline": f"AI Analysis: {reasoning[:150]}",
                "source": "NiftyMind AI",
                "impact": impact_level.lower(),
                "direction": direction,
                "confidence": confidence,
                "category": result.get("event_type", "NONE"),
                "sentiment": "positive" if direction == "BULLISH" else ("negative" if direction == "BEARISH" else "mixed"),
                "classified_events": result.get("classified_events", []),
                "earnings_in_focus": result.get("earnings_in_focus", []),
                "avoid_trading": avoid_trading,
                "articles_analyzed": len(articles),
            },
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
                "earnings_in_focus": result.get("earnings_in_focus", []),
                "event_type": result.get("event_type", "NONE"),
                "articles_analyzed": len(articles),
                "is_expiry_day": self.is_expiry_day(),
            },
        )
