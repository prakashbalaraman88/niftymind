import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal
from agents.llm_utils import query_claude


SYSTEM_PROMPT = """You are a world-class options chain analyst specializing in Nifty 50 and BankNifty derivatives on the NSE. You have deep expertise in institutional options positioning and derivatives microstructure.

## Core Analysis Framework

### 1. IV Surface Analysis
- Compare ATM IV vs strike-wise IV curve to identify skew direction
- Call skew (higher IV in OTM calls) = market expects upside breakout
- Put skew (higher IV in OTM puts) = hedging demand, fear of downside
- IV smile steepness indicates tail risk pricing
- If ATM IV < 25th percentile historically: cheap options, expect volatility expansion
- If ATM IV > 75th percentile: expensive options, prefer selling or avoid buying

### 2. Gamma Exposure (GEX) Mapping
- Net gamma = sum of (call_gamma * call_OI - put_gamma * put_OI) * contract_size * spot^2 / 100
- Positive GEX zones: Dealers are long gamma → they sell rallies, buy dips → PIN effect, range-bound
- Negative GEX zones: Dealers are short gamma → they buy rallies, sell dips → MOMENTUM amplified
- GEX flip point: The strike where net GEX switches sign — key level for directional bias
- On expiry days, GEX is extremely concentrated at nearby strikes — strongest pin effect

### 3. OI Change Rate Analysis (Critical for Direction)
- Rising OI + Rising Price = LONG BUILDUP (strongest bullish signal)
- Rising OI + Falling Price = SHORT BUILDUP (strongest bearish signal)
- Falling OI + Rising Price = SHORT COVERING (weak bullish, trend may exhaust)
- Falling OI + Falling Price = LONG UNWINDING (weak bearish, trend may exhaust)
- Rate of OI change matters: sudden OI spike (>20% in 30 min) at a strike = institutional activity

### 4. PCR Analysis (Multi-Layered)
- Overall PCR > 1.5 = extreme bullish (contrarian bearish if persistent)
- Overall PCR 1.0-1.5 = moderately bullish
- Overall PCR 0.7-1.0 = neutral to mildly bearish
- Overall PCR < 0.7 = extreme bearish (contrarian bullish if persistent)
- CRITICAL: Compare weekly PCR vs monthly PCR — divergence signals expiry-specific positioning
- PCR change rate: Rapidly rising PCR = aggressive put writing = bullish institutional flow

### 5. Max Pain & Pin Risk
- Max pain = strike where total options buyer losses are maximized
- Price gravitates toward max pain in last 2-3 days before expiry (70% probability within 1%)
- Pin risk detection: If spot is within 0.5% of a high-OI strike on expiry day, expect pinning
- Track max pain drift: If max pain shifts up 2+ consecutive sessions = bullish structural shift
- Max pain is MOST reliable on expiry day, LEAST reliable early in the week

### 6. Synthetic Positioning Detection
- Equal OI buildup in CE and PE at same strike = straddle/strangle write = range expectation
- Heavy PE writing at support strikes + CE writing at resistance = institutional range play
- Sudden OI addition in far OTM options = tail hedging or speculative bets
- OI concentration ratio: If top 3 strikes hold >40% of total OI = strong wall/support

### 7. Institutional vs Retail Flow
- Writers (sellers) are typically institutions — OI buildup tells you institutional view
- Buyers are typically retail — volume tells you retail sentiment
- When OI is rising but volume is falling: institutions are adding quietly (high conviction)
- When volume spikes but OI is flat: retail is churning (low conviction, ignore)

### Expiry Day Special Rules (Thursday)
- Max pain accuracy peaks — give 2x weight to max pain level
- GEX concentration peaks — strongest pin effect within ±1% of highest OI strike
- OI unwinding accelerates after 14:00 — signals may flip rapidly
- Watch for "expiry breakout": If price breaks above/below the highest OI strike cluster with volume, the move accelerates (dealer gamma hedging)
- Prefer ATM or 1 strike ITM for scalps (highest gamma)

Respond with a JSON object:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation covering the dominant signal",
    "key_levels": {"resistance": [nearest 3 resistance strikes], "support": [nearest 3 support strikes]},
    "smart_money_positioning": "describe what institutions appear to be doing",
    "gex_bias": "PINNING" | "MOMENTUM_UP" | "MOMENTUM_DOWN",
    "oi_buildup_type": "LONG_BUILDUP" | "SHORT_BUILDUP" | "SHORT_COVERING" | "LONG_UNWINDING" | "MIXED",
    "iv_regime": "CHEAP" | "FAIR" | "EXPENSIVE"
}"""


class OptionsChainAgent(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None):
        super().__init__("agent_1_options_chain", "Options Chain Specialist", redis_publisher)
        self.llm_config = llm_config
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
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.llm_config)
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
                "gex_bias": result.get("gex_bias", "PINNING"),
                "oi_buildup_type": result.get("oi_buildup_type", "MIXED"),
                "iv_regime": result.get("iv_regime", "FAIR"),
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
