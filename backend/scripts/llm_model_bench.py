"""LLM model comparison bench for NiftyMind's signal agents.

Runs a fixed set of representative market scenarios through each candidate
model and reports, per model:
  - latency (avg / p95)
  - JSON-valid rate (did it return a parseable {direction, confidence} object?)
  - the direction/confidence it produced per scenario

WHAT THIS MEASURES: speed, response reliability, and signal *sanity* (does the
model read an obviously-bullish setup as bullish?). It is the right tool for
"which model is fast and reliable enough to pay for."

WHAT THIS DOES NOT MEASURE: trade win-rate / P&L. That requires forward paper
trading or an expensive historical LLM replay — a spec sheet or a 5-scenario
bench cannot tell you which model makes more money. Use this to shortlist, then
let the live paper engine + daily retrainer settle it on real outcomes.

Run:
  python backend/scripts/llm_model_bench.py
  python backend/scripts/llm_model_bench.py --models google/gemma-4-31b-it,google/gemini-2.5-flash-lite,deepseek/deepseek-v3.2 --runs 2
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv()

from agents.llm_utils import query_llm  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")

DEFAULT_MODELS = [
    "google/gemma-4-31b-it",
    "google/gemini-2.5-flash-lite",
    "deepseek/deepseek-v3.2",
]

SYSTEM_PROMPT = (
    "You are a market sentiment analyst for Indian index options (NIFTY/BANKNIFTY). "
    "Read the market context and respond ONLY with JSON: "
    '{"direction": "BULLISH"|"BEARISH"|"NEUTRAL", "confidence": 0.0-1.0, '
    '"reasoning": "<one sentence>"}'
)

# (name, user_prompt, expected_direction_for_sanity)  expected=None means genuinely ambiguous
SCENARIOS = [
    ("strong_bull",
     "India VIX 12.8 (low). FII bought Rs 3200cr cash. Advance/decline 1920/580. "
     "Banks leading, NIFTY above all key EMAs. Signal for NIFTY?", "BULLISH"),
    ("strong_bear",
     "India VIX spiked to 22.4. FII sold Rs 4100cr. Advance/decline 410/2010. "
     "Crude +5%, USDINR at record high, global risk-off. Signal for NIFTY?", "BEARISH"),
    ("mixed",
     "VIX 15.0 flat. FII net roughly zero, DII bought Rs 700cr. Advance/decline 1130/1120. "
     "Index oscillating in a tight range near VWAP. Signal for BANKNIFTY?", None),
    ("expiry_chop",
     "Tuesday expiry day. VIX 16.2. Heavy OI at 24500 strike, max-pain pinning price. "
     "Choppy two-sided action, no clear trend. Signal for NIFTY?", None),
    ("news_shock",
     "Surprise RBI inter-meeting rate cut announced 11:00 IST. Banks surging, "
     "VIX dropping from 18 to 14, breadth flipping strongly positive. Signal for BANKNIFTY?", "BULLISH"),
]


def _model_cfg(model: str):
    """Per-model config with NO fallback chain, so we measure THIS model alone."""
    return SimpleNamespace(
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model=model,
        model_decision="",
        fallback_models=(),
    )


def _is_valid(result: dict) -> bool:
    return (
        isinstance(result, dict)
        and "raw_response" not in result  # llm_utils only sets this on failure
        and result.get("direction") in ("BULLISH", "BEARISH", "NEUTRAL")
    )


def _pctile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[k]


async def bench_model(model: str, runs: int) -> dict:
    cfg = _model_cfg(model)
    latencies: list[float] = []
    valid = 0
    total = 0
    sane = 0
    sane_total = 0
    per_scenario = []

    for name, user, expected in SCENARIOS:
        for _ in range(runs):
            total += 1
            t0 = time.perf_counter()
            try:
                result = await query_llm(SYSTEM_PROMPT, user, cfg, tier="analysis")
            except Exception as e:
                result = {"raw_response": f"exception: {e}", "direction": "ERROR"}
            dt = time.perf_counter() - t0
            latencies.append(dt)

            ok = _is_valid(result)
            valid += ok
            direction = result.get("direction", "?")
            conf = result.get("confidence", "?")
            if ok and expected is not None:
                sane_total += 1
                sane += (direction == expected)
            per_scenario.append((name, direction, conf, round(dt, 2), ok))

    return {
        "model": model,
        "calls": total,
        "json_valid_pct": round(100 * valid / total, 1) if total else 0.0,
        "sane_pct": round(100 * sane / sane_total, 1) if sane_total else None,
        "avg_latency": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "p95_latency": round(_pctile(latencies, 95), 2),
        "per_scenario": per_scenario,
    }


async def main():
    parser = argparse.ArgumentParser(description="Compare LLM models for NiftyMind signal agents")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS),
                        help="Comma-separated OpenRouter model slugs")
    parser.add_argument("--runs", type=int, default=1, help="Runs per scenario (default 1)")
    args = parser.parse_args()

    if not os.getenv("OPENROUTER_API_KEY"):
        print("ERROR: OPENROUTER_API_KEY not set (backend/.env).")
        return 1

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    print(f"\nBenchmarking {len(models)} model(s), {len(SCENARIOS)} scenarios x {args.runs} run(s)\n")

    results = []
    for model in models:
        print(f"  ... {model}")
        results.append(await bench_model(model, args.runs))

    print("\n" + "=" * 78)
    print("  MODEL COMPARISON  (speed + reliability + sanity — NOT trade win-rate)")
    print("=" * 78)
    header = f"  {'model':<34}{'calls':>6}{'json_ok':>9}{'sane':>7}{'avg_s':>8}{'p95_s':>8}"
    print(header)
    print("  " + "-" * 74)
    for r in results:
        sane = f"{r['sane_pct']}%" if r["sane_pct"] is not None else "n/a"
        print(f"  {r['model']:<34}{r['calls']:>6}{str(r['json_valid_pct'])+'%':>9}{sane:>7}"
              f"{r['avg_latency']:>8}{r['p95_latency']:>8}")

    print("\n  Per-scenario directions:")
    for r in results:
        print(f"\n  {r['model']}")
        seen = set()
        for name, direction, conf, dt, ok in r["per_scenario"]:
            if name in seen:
                continue
            seen.add(name)
            flag = "" if ok else "  [INVALID JSON]"
            print(f"    {name:<14} -> {direction:<8} conf={conf}  ({dt}s){flag}")

    print("\n" + "=" * 78)
    print("  'sane' = agreed with the obvious direction on the 3 unambiguous scenarios.")
    print("  Shortlist on json_ok (reliability) + latency (scalp responsiveness) + sane;")
    print("  then let the live paper engine decide on real P&L. Costs hit your OpenRouter")
    print("  credit — check the dashboard for exact spend.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
