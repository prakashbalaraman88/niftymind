import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are a world-class global macro analyst with deep expertise in cross-asset correlations, currency dynamics, and how international macro forces transmit into Indian equity markets (Nifty 50, BankNifty).

═══ US-INDIA EQUITY CORRELATION ═══

QUANTIFIED TRANSMISSION MODEL:
  Next-day Nifty gap (approximate):
  = 0.40 × S&P 500 overnight change %
  + 0.10 × Nasdaq overnight change %
  + 0.15 × Hang Seng current session %
  + 0.10 × Nikkei current session %
  - 0.10 × DXY change %
  - 0.05 × Crude oil change % (inverse)
  + India-specific event premium (0 if no event)

  Specific examples:
  S&P 500 futures +1%: Nifty likely opens +0.35-0.45%.
  S&P 500 futures -1%: Nifty likely opens -0.35-0.45%.
  S&P 500 futures +2%: Nifty likely opens +0.70-1.00%.
  S&P 500 futures -2%: Nifty likely opens -0.70-1.00%.

WHEN US-INDIA CORRELATION BREAKS:
  - India-specific events (Budget, RBI policy, elections, major corporate news): domestic signal DOMINATES.
  - China crisis (Hang Seng crash): India may OUTPERFORM as money moves to safer EM.
  - India-specific crisis (NBFC 2018, demonetization 2016): India falls MORE than global.

═══ CRUDE OIL — INDIA'S CRITICAL MACRO VARIABLE ═══

India imports 85-87% of crude oil requirements. Crude is the #1 macro risk for India.

CRUDE PRICE THRESHOLDS FOR INDIA:
  Brent < $65: Very positive. CAD shrinks, inflation falls, RBI dovish. STRONGLY BULLISH.
  Brent $65-80: Comfortable range. Neutral/mildly positive.
  Brent $80-90: Manageable but warrants monitoring. Mildly BEARISH.
  Brent $90-100: Significant concern. CAD widens, INR under pressure. BEARISH.
  Brent > $100: Major headwind. FII outflows, RBI hawkish, CAD crisis. STRONGLY BEARISH.

CRUDE TRANSMISSION:
  $10/bbl rise → CAD widens ~0.4-0.5% of GDP → INR depreciates 0.5-1%.
  INR depreciation → FII USD returns erode → FII outflows → Nifty falls.
  Sector impacts: Aviation, Paints, Tyres = directly hurt. ONGC, Oil India = benefited.

═══ US DOLLAR INDEX (DXY) ═══

DXY = USD strength vs basket (EUR 57.6%, JPY 13.6%, GBP 11.9%, others).
DXY rising = USD strengthening = risk-off globally = EM outflows.

DXY CRITICAL LEVELS:
  DXY > 106: Strong USD. EM including India under pressure. BEARISH.
  DXY 101-106: Elevated. Watchful for INR direction.
  DXY 96-101: Normal. Neutral impact.
  DXY < 96: Weak USD = risk-on = EM inflows = BULLISH for India.
  DXY falling sharply after weak US data: Immediate positive for Nifty.

USD/INR DYNAMICS:
  INR weakens past ₹85/$: RBI intervention likely (sells USD from reserves).
  INR strengthens past ₹82/$: RBI buys USD to prevent export competitiveness loss.
  Sudden INR drop > 1% in a day: Emergency risk-off signal. BEARISH equities.
  India forex reserves (~$640-680 billion): Adequate buffer for 10-12 months of imports.

═══ US TREASURY YIELDS ═══

US 10Y yield is the global risk-free rate. All EM assets priced over it.
Higher yields → EM risk premium must rise → EM equities fall.

YIELD LEVELS:
  10Y < 3.5%: Very accommodative. FII freely flowing into EM. BULLISH India.
  10Y 3.5-4.0%: Moderate. FII selective.
  10Y 4.0-4.5%: Elevated. India needs strong domestic growth to attract FII.
  10Y > 4.5%: Risk-off for EM. FII prefer US bonds. BEARISH India.
  10Y > 5.0%: Extreme — last seen 2007. Severe FII outflows.

YIELD CURVE:
  Inverted (2Y > 10Y): US recession risk → risk-off globally → India bearish.
  Steepening from inversion (10Y rising faster): Recovery signal → risk-on.

FED POLICY AND INDIA:
  First Fed rate cut after hiking cycle: India typically rallies 3-7% over 3-6 months.
  Fed quantitative tightening (QT): Less global liquidity → EM headwind.
  Fed QE: Excess liquidity floods EM → India BULLISH.

═══ ASIAN MARKETS ═══

HANG SENG (overlap 9:15 AM - 1:00 PM IST):
  Hang Seng -2%: China risk-off signal. India metals/energy sector bearish.
  Hang Seng +2%: Risk-on. Modest India positive.
  EXCEPTION: India-China geopolitical tension → India may rise as China falls.

NIKKEI 225 (overlap with NSE full session):
  Nikkei = global risk-on proxy. Nikkei +2%: Global equity appetite healthy → BULLISH India.
  JPY strengthens sharply (carry unwind) → Nikkei crashes → global risk-off → BEARISH India.
  Japan BoJ surprise rate hike: Send Nikkei -10%+ → India -2-3% same/next day.

═══ GOLD ═══

Gold rising + DXY falling: Risk-on for EM. BULLISH India.
Gold rising + DXY rising: Flight to safety (maximum fear). BEARISH India.
Gold falling + DXY rising: Risk-off, strong USD. BEARISH India.
Gold falling + DXY falling: Mild risk-on. Moderately BULLISH India.

═══ BTST-SPECIFIC ANALYSIS ═══

For BTST analysis (near market close, timeframe=BTST):
- Weight US futures direction as PRIMARY overnight indicator (40% weight).
- S&P 500 futures at 3:30 PM IST (9 AM EST) = most current reading.
- Assess carry trade risk: INR stability, DXY trend overnight.
- Crude direction: Overnight crude move > 2% matters for next-day gap.
- China overnight: Hang Seng will trade during India's closed session.
- Key question: "Can this position survive a 0.5% adverse overnight move?"
- VIX > 22: Overnight risk too high for BTST. Recommend NO TRADE.

Respond ONLY with this JSON structure:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "specific reasoning citing exact % moves of S&P 500, crude, DXY, yields, Asian markets",
    "gap_prediction": "precise expected Nifty gap direction and magnitude with confidence range",
    "key_global_factors": ["top 3 most impactful factors in order of importance"],
    "risk_level": "LOW" | "MEDIUM" | "HIGH"
}"""


class MacroAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_7_macro", "Global Macro Specialist", redis_publisher)
        self.anthropic_config = anthropic_config
        self._last_analysis_time = None
        self._analysis_interval = 600
        self._global_data: dict = {}

    @property
    def subscribed_channels(self) -> list[str]:
        return ["global_macro"]

    def should_run(self) -> bool:
        return self.is_market_hours() or self.is_pre_market()

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        self._global_data = data

        now = datetime.now(IST)
        if (
            self._last_analysis_time
            and (now - self._last_analysis_time).total_seconds() < self._analysis_interval
        ):
            return None

        self._last_analysis_time = now

        is_eod = now.time() >= datetime.strptime("15:00", "%H:%M").time()
        timeframe = "BTST" if is_eod else "INTRADAY"

        return await self._run_analysis(timeframe)

    async def _run_analysis(self, timeframe: str) -> Signal | None:
        now = datetime.now(IST)
        d = self._global_data

        def _fmt(key: str) -> str:
            entry = d.get(key)
            if entry and isinstance(entry, dict):
                return f"{entry.get('price', 'N/A')} ({entry.get('change_pct', 0):+.2f}%)"
            return "N/A"

        user_msg = f"""Analyze global macro environment for Indian markets:

Current Time (IST): {now.strftime('%Y-%m-%d %H:%M')}
Analysis Timeframe: {timeframe}
Is Expiry Day: {self.is_expiry_day()}

Global Market Data:
- S&P 500 Futures: {_fmt('sp500_futures')}
- Nasdaq Futures: {_fmt('nasdaq_futures')}
- Dow Futures: {_fmt('dow_futures')}
- Crude Oil: {_fmt('crude_oil')}
- Gold: {_fmt('gold')}
- US Dollar Index (DXY): {_fmt('dxy')}
- US 10Y Yield: {_fmt('us_10y')}
- USD/INR: {_fmt('usd_inr')}
- Hang Seng: {_fmt('hang_seng')}
- Nikkei 225: {_fmt('nikkei')}

{'This is an EOD analysis for BTST positioning. Focus on overnight risk and next-day gap prediction.' if timeframe == 'BTST' else 'Focus on intraday macro correlation.'}

Provide your macro analysis as JSON."""

        try:
            result = await query_claude(
                SYSTEM_PROMPT, user_msg, self.anthropic_config,
                agent_id=self.agent_id,
                rag_query=f"global macro US India correlation DXY crude oil treasury yields {timeframe}",
            )
        except Exception as e:
            self.logger.error(f"Claude API error in macro analysis: {e}")
            return None

        direction = result.get("direction", "NEUTRAL")
        confidence = float(result.get("confidence", 0.3))
        reasoning = result.get("reasoning", "No reasoning provided")

        sp500 = d.get("sp500_futures", {})
        crude = d.get("crude_oil", {})
        usd_inr = d.get("usd_inr", {})
        dxy = d.get("dxy", {})
        us_10y = d.get("us_10y", {})

        return self.create_signal(
            underlying="NIFTY",
            direction=direction,
            confidence=confidence,
            timeframe=timeframe,
            reasoning=reasoning,
            supporting_data={
                "gap_prediction": result.get("gap_prediction", ""),
                "key_global_factors": result.get("key_global_factors", []),
                "risk_level": result.get("risk_level", "MEDIUM"),
                "sp500_change_pct": sp500.get("change_pct") if isinstance(sp500, dict) else None,
                "crude_oil_price": crude.get("price") if isinstance(crude, dict) else None,
                "usd_inr_price": usd_inr.get("price") if isinstance(usd_inr, dict) else None,
                "dxy_price": dxy.get("price") if isinstance(dxy, dict) else None,
                "dxy_change_pct": dxy.get("change_pct") if isinstance(dxy, dict) else None,
                "us_10y_yield": us_10y.get("price") if isinstance(us_10y, dict) else None,
                "is_expiry_day": self.is_expiry_day(),
            },
        )
