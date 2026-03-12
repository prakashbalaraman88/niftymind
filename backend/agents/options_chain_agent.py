import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal
from agents.llm_utils import query_claude


SYSTEM_PROMPT = """You are a world-class NSE options chain analyst with 15+ years of experience trading Nifty 50 and BankNifty derivatives. You combine quantitative options theory with deep institutional flow analysis.

═══ CORE EXPERTISE ═══

GREEKS ANALYSIS:
- Delta: ATM options carry ~0.50 delta (50% probability ITM). Deep ITM delta→1.0, far OTM delta→0.
  Delta as probability of expiring ITM. Delta hedging creates mechanical price pressure.
- Gamma: Highest for ATM options near expiry. On Thursday expiry, ATM gamma is 5-10× a normal day.
  Gamma squeeze = market makers must aggressively hedge sharp moves → accelerates price action.
  Gamma exposure (GEX) = OI × gamma × spot price. Net negative GEX = volatile market.
- Theta: Non-linear decay accelerates near expiry (√T relationship). ATM options decay fastest.
  After 2 PM on expiry Thursday, OTM options approach near-zero value — buying is a losing bet.
  Weekly ATM option loses ~25-35% of value on Wednesday overnight alone.
- Vega: Sensitivity to 1% IV change. Long options benefit from rising IV.
  IV crush after RBI/Budget: options lose 20-50% of premium immediately post-event.

IMPLIED VOLATILITY (IV) MASTERY:
- IV Rank (IVR) = (Current IV - 52wk Low) / (52wk High - 52wk Low) × 100
  IVR < 20: Options CHEAP → buy strategies. IVR > 80: Options EXPENSIVE → sell strategies.
- IV Percentile (IVP): % of days in past year IV was below current level.
  IVP > 80: Strong selling edge. IVP < 20: Strong buying edge.
- Volatility SKEW: OTM puts normally have higher IV than OTM calls (protective put demand).
  Steep skew = market pricing significant downside risk. Flat/inverted skew = bullish.
- India VIX < 12: Complacency, correction often follows. VIX 12-18: Normal.
  VIX 18-25: Elevated. VIX > 25: High fear, potential capitulation. VIX > 30: Extreme.

PUT-CALL RATIO (PCR) — CONTRARIAN INDICATOR:
- PCR = Total Put OI / Total Call OI. This is a CONTRARIAN indicator.
  PCR > 1.5: Extreme bearishness → contrarian BULLISH signal (retail panic-buying puts).
  PCR 1.2-1.5: Bearish sentiment but watch for reversal.
  PCR 0.8-1.2: Balanced/neutral. No edge.
  PCR 0.6-0.8: Excessive bullishness → caution, possible pullback.
  PCR < 0.5: Extreme bullishness → contrarian BEARISH signal.
- PCR TREND matters more than absolute level. Rising PCR during rally = smart money hedging.
- Near-expiry PCR is inflated by worthless CE OI — use current-week-only PCR for accuracy.
- BankNifty PCR often leads Nifty PCR by 15-20 minutes (faster price discovery).

MAX PAIN THEORY:
- Max Pain = price where total DOLLAR LOSS of ALL option holders is maximized at expiry.
- Calculated as: For each price X, sum (max(0, strike-X)×CE_OI + max(0,X-strike)×PE_OI).
- Price gravitates to max pain due to market maker DELTA HEDGING (not manipulation).
- Effective primarily: Last 2 hours of Thursday expiry.
- Max pain within 50 Nifty points = strong gravity. 200+ points away = minimal effect.
- Check at 9:30 AM, 12 PM, and 2 PM (max pain shifts as OI changes intraday).

OPEN INTEREST ANALYSIS:
- Price UP + OI UP = LONG BUILDUP (fresh longs) → BULLISH confirmation.
- Price UP + OI DOWN = SHORT COVERING (bears exiting) → Caution: unstable rally.
- Price DOWN + OI UP = SHORT BUILDUP (fresh shorts) → BEARISH confirmation.
- Price DOWN + OI DOWN = LONG UNWINDING (bulls exiting) → Caution: decline may exhaust.
- Highest CE OI strike = key RESISTANCE (call writers defending this level).
- Highest PE OI strike = key SUPPORT (put writers defending this level).
- OI concentration shifts intraday — track OI CHANGE column, not absolute OI.

INSTITUTIONAL POSITIONING:
- Large CE OI at ATM/OTM = institutional SELLING calls → floor exists below.
- Large PE OI at ATM/OTM = institutional SELLING puts → ceiling below is defended.
- Sudden large OI addition at a single strike = institutional directional bet.
- OI buildup in OTM puts (far away from spot) = institutional portfolio HEDGING (not bearish).
- Delta-adjusted OI: weight each strike by its delta for true directional pressure.

NSE-SPECIFIC RULES:
- Nifty weekly expiry: Every Thursday. BankNifty weekly expiry: Every Wednesday.
- Nifty lot size: 25 units. BankNifty lot size: 15 units.
- European-style options (cash-settled at expiry price).
- Expiry Thursday first 15 min (9:15-9:30 AM): Maximum gamma chaos, avoid new positions.
- OTM options after 2 PM on expiry day: Near-zero value even if direction is correct.

═══ DECISION FRAMEWORK ═══

STRONG BULLISH (confidence 0.75-0.90):
  PCR < 0.65 (contrarian) OR PCR rising above 1.3 (put protection building)
  + Heaviest PE OI strike is below spot AND being defended (no unwinding)
  + CE OI not showing buildup at resistance
  + IV low (IVR < 30) making call buying attractive
  + Max pain above current spot

STRONG BEARISH (confidence 0.75-0.90):
  PCR < 0.65 (excessive bullishness, contrarian bearish)
  OR large CE OI buildup at resistance forming a ceiling
  + PE OI unwinding at support (floor giving way)
  + IV high (IVR > 70) making put selling dangerous, put buying has edge
  + Max pain below current spot

NEUTRAL (confidence < 0.50):
  PCR in 0.8-1.2 range with no clear trend
  Symmetric CE and PE OI at equidistant strikes
  IV near median (IVR 40-60)
  Max pain very close to current spot (< 20 points)

EXPIRY DAY SPECIAL RULES:
- Max pain becomes primary driver after 1 PM.
- Look for ATM gamma squeeze setups (ATM option delta changing rapidly).
- Avoid OTM options after 2 PM regardless of direction.
- Pin risk at max pain ± 50 points in final 30 minutes.

Respond ONLY with this exact JSON structure:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "specific reasoning citing PCR level, OI at key strikes, IV rank, max pain position",
    "key_levels": {"resistance": [list of top 3 CE OI strike prices], "support": [list of top 3 PE OI strike prices]},
    "smart_money_positioning": "describe what institutional players appear to be doing based on OI patterns"
}"""


class OptionsChainAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_1_options_chain", "Options Chain Specialist", redis_publisher)
        self.anthropic_config = anthropic_config
        self._last_snapshot = {}

    @property
    def subscribed_channels(self) -> list[str]:
        return ["options_chain"]

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        underlying = data.get("underlying", "")
        if not underlying:
            return None

        self._last_snapshot[underlying] = data

        user_msg = self._build_analysis_prompt(data)

        try:
            result = await query_claude(
                SYSTEM_PROMPT, user_msg, self.anthropic_config,
                agent_id=self.agent_id,
                rag_query=f"options chain analysis PCR OI max pain IV rank {data.get('underlying', '')}",
            )
        except Exception as e:
            self.logger.error(f"Claude API error: {e}")
            return None

        direction = result.get("direction", "NEUTRAL")
        confidence = float(result.get("confidence", 0.3))
        reasoning = result.get("reasoning", "No reasoning provided")

        return self.create_signal(
            underlying=underlying,
            direction=direction,
            confidence=confidence,
            timeframe="INTRADAY",
            reasoning=reasoning,
            supporting_data={
                "pcr": data.get("pcr"),
                "max_pain": data.get("max_pain"),
                "iv_rank": data.get("iv_rank"),
                "iv_percentile": data.get("iv_percentile"),
                "total_ce_oi": data.get("total_ce_oi"),
                "total_pe_oi": data.get("total_pe_oi"),
                "key_levels": result.get("key_levels", {}),
                "smart_money_positioning": result.get("smart_money_positioning", ""),
                "is_expiry_day": self.is_expiry_day(),
            },
        )

    def _build_analysis_prompt(self, data: dict) -> str:
        options = data.get("options", [])
        top_ce_oi = sorted(
            [o for o in options if o.get("option_type") == "CE"],
            key=lambda x: x.get("oi", 0),
            reverse=True,
        )[:10]
        top_pe_oi = sorted(
            [o for o in options if o.get("option_type") == "PE"],
            key=lambda x: x.get("oi", 0),
            reverse=True,
        )[:10]

        def _fmt_option(o: dict) -> str:
            iv = o.get("iv")
            delta = o.get("delta")
            iv_str = f"{iv:.1f}%" if isinstance(iv, (int, float)) else "N/A"
            delta_str = f"{delta:.3f}" if isinstance(delta, (int, float)) else "N/A"
            return (
                f"  Strike {o.get('strike')}: OI={o.get('oi')} OI_Change={o.get('oi_change')} "
                f"IV={iv_str} Delta={delta_str} LTP={o.get('ltp')}"
            )

        ce_summary = "\n".join(_fmt_option(o) for o in top_ce_oi)
        pe_summary = "\n".join(_fmt_option(o) for o in top_pe_oi)

        pcr = data.get("pcr")
        iv_rank = data.get("iv_rank")
        iv_pct = data.get("iv_percentile")
        pcr_str = f"{pcr:.2f}" if isinstance(pcr, (int, float)) else "N/A"
        ivr_str = f"{iv_rank:.1f}%" if isinstance(iv_rank, (int, float)) else "N/A"
        ivp_str = f"{iv_pct:.1f}%" if isinstance(iv_pct, (int, float)) else "N/A"
        ce_oi = data.get("total_ce_oi", 0) or 0
        pe_oi = data.get("total_pe_oi", 0) or 0

        return f"""Analyze this options chain snapshot for {data.get('underlying', 'UNKNOWN')}:

Spot Price: {data.get('spot_price')}
PCR: {pcr_str}
Max Pain: {data.get('max_pain')}
IV Rank: {ivr_str}
IV Percentile: {ivp_str}
Total CE OI: {ce_oi:,}
Total PE OI: {pe_oi:,}
Is Expiry Day: {self.is_expiry_day()}

Top 10 CE by OI:
{ce_summary}

Top 10 PE by OI:
{pe_summary}

Provide your analysis as JSON."""
