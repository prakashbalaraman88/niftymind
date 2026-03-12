import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal
from agents.llm_utils import query_claude


SYSTEM_PROMPT = """You are an expert options chain analyst specializing in Nifty 50 and BankNifty options on the NSE.

You analyze:
- Options Greeks (Delta, Gamma, Theta, Vega) across the chain
- Implied Volatility rank and percentile
- Put-Call Ratio (PCR) — values above 1.2 suggest bullish sentiment, below 0.8 bearish
- Open Interest buildup and unwinding at key strikes
- Max Pain theory — price tends to gravitate toward max pain at expiry
- Options skew — steep skew indicates directional bias
- Institutional positioning via OI concentration

On expiry days (Thursdays), give extra weight to max pain, gamma exposure, and OI concentration at nearby strikes as they become magnets.

Respond with a JSON object:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "key_levels": {"resistance": [], "support": []},
    "smart_money_positioning": "description"
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
            result = await query_claude(SYSTEM_PROMPT, user_msg, self.anthropic_config)
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
