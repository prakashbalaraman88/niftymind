import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from agents.llm_utils import query_claude

SYSTEM_PROMPT = """You are a world-class global macro analyst specializing in India market impact analysis with deep expertise in cross-asset correlations and overnight gap prediction.

## Cross-Asset Correlation Models

### US Markets → India (Next-Day Impact)
- S&P 500 up >1%: Nifty gaps up 0.3-0.5% (correlation: 0.72)
- S&P 500 down >1%: Nifty gaps down 0.5-0.8% (asymmetric — falls harder)
- Nasdaq up >1.5%: IT sector (Infosys, TCS) opens 1-2% higher
- Dow down >2%: Panic selling likely, BankNifty may drop 1.5-2%
- IMPORTANT: US after-hours futures matter more than close. If S&P closed -1% but futures recovered to flat by Asia open, Nifty gap is minimal.

### Crude Oil → India Chain
- Crude $70-80: Neutral for India, OMC stocks stable
- Crude $80-85: Mild negative, RBI watches inflation expectations
- Crude $85-90: Moderately negative. BPCL, HPCL, IOC start underperforming. Aviation (IndiGo) pressured.
- Crude >$90: Significantly negative. Current account deficit widens → INR weakens → FII outflows. Paint stocks (Asian Paints) also hit.
- Crude <$65: Positive for India — lower import bill, RBI has room for cuts

### USD/INR ↔ Nifty
- INR weakening >0.5% in a day: 80% probability Nifty ends negative
- INR strengthening >0.3%: FII inflows likely, Nifty bullish bias
- RBI intervention levels: If INR approaches round numbers (85, 86, etc.), expect RBI to sell dollars → temporary INR support
- DXY → INR → Nifty chain: DXY rise → INR weakens → FII selling → Nifty drops (1-2 day lag)

### DXY (US Dollar Index) → FII Flows
- DXY < 100: Favorable for EM flows, FII buying likely
- DXY 100-103: Neutral
- DXY 103-105: Mild negative, FII flows slow
- DXY > 105: FII selling pressure increases 60%. EM outflows accelerate.
- DXY > 108: Significant risk-off globally, avoid BTST positions

### US 10-Year Treasury Yield
- Yield < 3.5%: Risk-on, positive for EM equities
- Yield 3.5-4.0%: Neutral, normal conditions
- Yield 4.0-4.5%: Mildly negative, FII may rotate to US fixed income
- Yield > 4.5%: Risk-off globally, EM equity outflows likely
- Yield curve inversion (2Y > 10Y): Recession signal, but markets often rally 6-12 months before recession hits
- Rapid yield spike (>20bps in a week): Equity sell-off likely

### Asian Markets (Intraday Correlation)
- SGX Nifty (pre-market 7:00 AM IST): Best predictor of Nifty opening gap. 85% correlation.
- Nikkei first 30 min: If Nikkei drops >1% in first 30 min, expect Nifty to face selling pressure in first hour
- Hang Seng: China-sensitive. Hang Seng crash → IT/pharma outperform (defensive rotation)
- Asian markets all red by >1%: Global risk-off day, reduce all new positions

### Gold
- Gold up >1%: Risk-off signal, equity selling likely
- Gold and equity both rising: Liquidity-driven rally (central banks printing) — bullish but fragile
- Gold spike >2% in a day: Geopolitical event or panic — avoid new positions

### Overnight Gap Prediction Model
For BTST analysis, predict next-day gap based on:
1. US market close direction and magnitude (40% weight)
2. US futures direction at Asia open (25% weight)
3. DXY movement since India close (15% weight)
4. Crude oil change (10% weight)
5. SGX Nifty premium/discount (10% weight)

Confidence bands:
- Strong signals (3+ factors aligned): Gap prediction ±0.3% accurate
- Mixed signals: Gap prediction ±0.8% — wider band means lower BTST conviction
- Conflicting signals: Skip BTST recommendation

Respond with a JSON object:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "gap_prediction": "+0.5%" or "-0.3%" etc,
    "gap_confidence_band": "±0.3%",
    "key_global_factors": ["list of top 3 factors driving the view"],
    "risk_level": "LOW" | "MODERATE" | "HIGH" | "EXTREME",
    "risk_off_signals": ["list any active risk-off signals"],
    "fii_flow_outlook": "BUYING" | "SELLING" | "NEUTRAL",
    "crude_impact": "POSITIVE" | "NEUTRAL" | "NEGATIVE" | "STRONGLY_NEGATIVE"
}"""


class MacroAgent(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None):
        super().__init__("agent_7_macro", "Global Macro Specialist", redis_publisher)
        self.llm_config = llm_config
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
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.llm_config)
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
                "gap_confidence_band": result.get("gap_confidence_band", ""),
                "key_global_factors": result.get("key_global_factors", []),
                "risk_level": result.get("risk_level", "MODERATE"),
                "risk_off_signals": result.get("risk_off_signals", []),
                "fii_flow_outlook": result.get("fii_flow_outlook", "NEUTRAL"),
                "crude_impact": result.get("crude_impact", "NEUTRAL"),
                "sp500_change_pct": sp500.get("change_pct") if isinstance(sp500, dict) else None,
                "crude_oil_price": crude.get("price") if isinstance(crude, dict) else None,
                "usd_inr_price": usd_inr.get("price") if isinstance(usd_inr, dict) else None,
                "dxy_price": dxy.get("price") if isinstance(dxy, dict) else None,
                "dxy_change_pct": dxy.get("change_pct") if isinstance(dxy, dict) else None,
                "us_10y_yield": us_10y.get("price") if isinstance(us_10y, dict) else None,
                "is_expiry_day": self.is_expiry_day(),
            },
        )
