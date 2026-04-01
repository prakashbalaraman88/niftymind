# NiftyMind Trading System Enhancement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform NiftyMind from a prototype into a production-grade AI trading system with deep expert knowledge, precise strike selection, ATR-based risk management, and smart execution.

**Architecture:** Enhance 7 analysis agents with expert-level system prompts and advanced heuristics. Add 3 new modules (strike selection, SL/TP engine, performance tracking). Upgrade risk manager with capital tiers and drawdown recovery. Upgrade execution with smart order routing. All changes maintain the existing LangGraph + Redis pub/sub architecture.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph, Redis, PostgreSQL, Anthropic Claude API, Zerodha Kite Connect, TrueData WebSocket

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `backend/agents/strike_selector.py` | Select optimal strike price based on strategy, Greeks, liquidity |
| `backend/execution/smart_order.py` | Limit-order ladder with slippage tracking |
| `backend/execution/trailing_stop.py` | Multi-target TP + ATR trailing SL engine |
| `backend/risk/capital_tiers.py` | Capital-tier-based position sizing and limits |
| `backend/risk/drawdown_manager.py` | Consecutive loss/win tracking, equity curve filter |
| `backend/performance/trade_journal.py` | Structured trade logging with full context |
| `backend/performance/metrics.py` | Win rate, profit factor, Sharpe, max drawdown calculations |
| `backend/tests/test_strike_selector.py` | Tests for strike selection |
| `backend/tests/test_capital_tiers.py` | Tests for position sizing |
| `backend/tests/test_trailing_stop.py` | Tests for SL/TP engine |
| `backend/tests/test_drawdown_manager.py` | Tests for drawdown recovery |
| `backend/tests/test_metrics.py` | Tests for performance metrics |

### Modified Files
| File | Changes |
|------|---------|
| `backend/agents/options_chain_agent.py` | Enhanced SYSTEM_PROMPT with GEX, IV surface, pin risk |
| `backend/agents/order_flow_agent.py` | Add sweep detection, iceberg detection, cumulative delta divergence |
| `backend/agents/volume_profile_agent.py` | Add TPO, initial balance, naked POC, value area migration |
| `backend/agents/technical_agent.py` | Add market structure, supply-demand zones, RSI divergence, FVG |
| `backend/agents/sentiment_agent.py` | Enhanced SYSTEM_PROMPT with FII derivatives, VIX term structure |
| `backend/agents/news_agent.py` | Enhanced SYSTEM_PROMPT with earnings playbooks, event models |
| `backend/agents/macro_agent.py` | Enhanced SYSTEM_PROMPT with correlation models, gap prediction |
| `backend/agents/scalping_agent.py` | Integrate strike selector, multi-target TP |
| `backend/agents/intraday_agent.py` | Integrate strike selector, multi-target TP |
| `backend/agents/btst_agent.py` | Integrate strike selector, overnight SL |
| `backend/agents/risk_manager.py` | Capital tiers, drawdown manager, event day guard |
| `backend/agents/consensus_orchestrator.py` | VIX regime-adaptive weights |
| `backend/execution/kite_executor.py` | Smart order routing integration |
| `backend/execution/paper_executor.py` | Realistic slippage simulation |
| `backend/config.py` | Capital tier configs, new risk params |

---

## Phase 1: Foundation — Config & Test Setup

### Task 1: Update Config with Capital Tiers

**Files:**
- Modify: `backend/config.py:84-101`

- [ ] **Step 1: Add CapitalTier dataclass and updated RiskConfig**

In `backend/config.py`, after the `RedisConfig` class, add:

```python
from dataclasses import dataclass, field
from typing import Literal

CAPITAL_TIERS = [
    {"min": 0, "max": 100_000, "max_risk_pct": 2.0, "max_positions": 2, "daily_loss_pct": 5.0, "weekly_loss_pct": 10.0},
    {"min": 100_001, "max": 500_000, "max_risk_pct": 2.0, "max_positions": 3, "daily_loss_pct": 4.0, "weekly_loss_pct": 8.0},
    {"min": 500_001, "max": 1_000_000, "max_risk_pct": 1.5, "max_positions": 4, "daily_loss_pct": 3.0, "weekly_loss_pct": 6.0},
    {"min": 1_000_001, "max": 2_500_000, "max_risk_pct": 1.0, "max_positions": 5, "daily_loss_pct": 2.5, "weekly_loss_pct": 5.0},
]

def get_tier_for_capital(capital: float) -> dict:
    for tier in CAPITAL_TIERS:
        if tier["min"] <= capital <= tier["max"]:
            return tier
    return CAPITAL_TIERS[-1]
```

Update `RiskConfig` to default capital to 100000.0 (₹1L starting):

```python
@dataclass(frozen=True)
class RiskConfig:
    max_daily_loss: float = field(default_factory=lambda: _env_float("MAX_DAILY_LOSS", 5000.0))
    max_trade_risk_pct: float = field(default_factory=lambda: _env_float("MAX_TRADE_RISK_PCT", 2.0))
    max_open_positions: int = field(default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 2))
    vix_halt_threshold: float = field(default_factory=lambda: _env_float("VIX_HALT_THRESHOLD", 25.0))
    capital: float = field(default_factory=lambda: _env_float("TRADING_CAPITAL", 100000.0))
    weekly_loss_pct: float = field(default_factory=lambda: _env_float("WEEKLY_LOSS_PCT", 10.0))
```

- [ ] **Step 2: Create test infrastructure**

```bash
mkdir -p backend/tests backend/risk backend/performance
touch backend/tests/__init__.py backend/risk/__init__.py backend/performance/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/config.py backend/tests/ backend/risk/ backend/performance/
git commit -m "feat: add capital tiers config and test/module directories"
```

---

## Phase 2: Agent Knowledge Enhancement

### Task 2: Enhance Options Chain Agent (agent_1)

**Files:**
- Modify: `backend/agents/options_chain_agent.py:9-29`

- [ ] **Step 1: Replace SYSTEM_PROMPT with expert-level knowledge**

Replace the existing `SYSTEM_PROMPT` string (lines 9-29) with:

```python
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
```

- [ ] **Step 2: Update supporting_data in process_message to include new fields**

After line 74, add the new response fields to supporting_data:

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add backend/agents/options_chain_agent.py
git commit -m "feat: enhance options chain agent with GEX, IV surface, OI buildup analysis"
```

---

### Task 3: Enhance Order Flow Agent (agent_2)

**Files:**
- Modify: `backend/agents/order_flow_agent.py`

- [ ] **Step 1: Add sweep detection, iceberg detection, and cumulative delta divergence**

Add these constants after line 13:

```python
SWEEP_WINDOW_TICKS = 5  # Consecutive ticks to detect sweep
SWEEP_PRICE_LEVELS = 3  # Min distinct price levels for sweep
ICEBERG_SIZE_TOLERANCE = 0.1  # 10% size tolerance for iceberg detection
ICEBERG_MIN_REPEATS = 3  # Min repeated same-size orders
CUMULATIVE_DELTA_DIVERGENCE_WINDOW = 100  # Ticks for divergence check
UPTICK_DOWNTICK_WINDOW = 20  # Window for consecutive tick momentum
```

Add new tracking to `__init__`:

```python
self._cumulative_delta: dict[str, float] = {}
self._price_at_delta_start: dict[str, float] = {}
self._recent_order_sizes: dict[str, deque] = {}
self._sweep_buffer: dict[str, deque] = {}
self._consecutive_ticks: dict[str, list] = {}
```

- [ ] **Step 2: Add detection methods to the class**

```python
def _detect_sweeps(self, ticks: list) -> dict:
    """Detect aggressive sweeps: rapid execution across 3+ price levels in 5 ticks."""
    if len(ticks) < SWEEP_WINDOW_TICKS:
        return {"buy_sweeps": 0, "sell_sweeps": 0}

    buy_sweeps = 0
    sell_sweeps = 0

    for i in range(len(ticks) - SWEEP_WINDOW_TICKS + 1):
        window = ticks[i:i + SWEEP_WINDOW_TICKS]
        prices = [t.get("ltp", 0) for t in window]
        unique_prices = len(set(prices))

        if unique_prices >= SWEEP_PRICE_LEVELS:
            if prices[-1] > prices[0]:  # Ascending sweep = buy
                buy_sweeps += 1
            elif prices[-1] < prices[0]:  # Descending sweep = sell
                sell_sweeps += 1

    return {"buy_sweeps": buy_sweeps, "sell_sweeps": sell_sweeps}

def _detect_icebergs(self, ticks: list) -> dict:
    """Detect iceberg orders: repeated same-size orders at the same price level."""
    if len(ticks) < ICEBERG_MIN_REPEATS:
        return {"iceberg_buy": False, "iceberg_sell": False}

    size_counts: dict[str, int] = {}
    for tick in ticks[-50:]:
        vol = tick.get("volume", 0)
        ltp = tick.get("ltp", 0)
        if vol > 0:
            key = f"{round(ltp, 1)}_{round(vol, -1)}"
            size_counts[key] = size_counts.get(key, 0) + 1

    iceberg_buy = False
    iceberg_sell = False
    for key, count in size_counts.items():
        if count >= ICEBERG_MIN_REPEATS:
            price = float(key.split("_")[0])
            last_ask = ticks[-1].get("ask", 0)
            last_bid = ticks[-1].get("bid", 0)
            if price >= last_ask:
                iceberg_buy = True
            elif price <= last_bid:
                iceberg_sell = True

    return {"iceberg_buy": iceberg_buy, "iceberg_sell": iceberg_sell}

def _calc_cumulative_delta_divergence(self, underlying: str, ticks: list) -> str:
    """Detect divergence: price rising but cumulative delta falling = exhaustion."""
    if len(ticks) < CUMULATIVE_DELTA_DIVERGENCE_WINDOW:
        return "NONE"

    recent = ticks[-CUMULATIVE_DELTA_DIVERGENCE_WINDOW:]
    first_price = recent[0].get("ltp", 0)
    last_price = recent[-1].get("ltp", 0)

    cum_delta = 0
    for tick in recent:
        ltp = tick.get("ltp", 0)
        ask = tick.get("ask", 0)
        bid = tick.get("bid", 0)
        vol = tick.get("volume", 0)
        if ask > 0 and ltp >= ask:
            cum_delta += vol
        elif bid > 0 and ltp <= bid:
            cum_delta -= vol

    price_change = last_price - first_price
    if price_change > 0 and cum_delta < 0:
        return "BEARISH_DIVERGENCE"  # Price up, delta down = exhaustion
    elif price_change < 0 and cum_delta > 0:
        return "BULLISH_DIVERGENCE"  # Price down, delta up = accumulation
    return "NONE"

def _tick_momentum(self, ticks: list) -> dict:
    """Count consecutive upticks and downticks for momentum scoring."""
    if len(ticks) < 2:
        return {"upticks": 0, "downticks": 0, "max_streak": 0}

    recent = ticks[-UPTICK_DOWNTICK_WINDOW:]
    upticks = 0
    downticks = 0
    streak = 0
    max_streak = 0
    last_dir = 0

    for i in range(1, len(recent)):
        curr = recent[i].get("ltp", 0)
        prev = recent[i-1].get("ltp", 0)
        if curr > prev:
            upticks += 1
            if last_dir == 1:
                streak += 1
            else:
                streak = 1
                last_dir = 1
        elif curr < prev:
            downticks += 1
            if last_dir == -1:
                streak += 1
            else:
                streak = 1
                last_dir = -1
        max_streak = max(max_streak, streak)

    return {"upticks": upticks, "downticks": downticks, "max_streak": max_streak}
```

- [ ] **Step 3: Integrate new detections into _analyze_flow**

Update `_analyze_flow` to use the new methods and factor them into confidence:

```python
def _analyze_flow(self, underlying: str) -> Signal | None:
    ticks = list(self._tick_buffer[underlying])
    if len(ticks) < 20:
        return None

    # === Existing pressure analysis ===
    buy_pressure = 0
    sell_pressure = 0
    bid_absorption = 0
    ask_absorption = 0
    delta_sum = 0

    for i, tick in enumerate(ticks):
        ltp = tick.get("ltp", 0)
        bid = tick.get("bid", 0)
        ask = tick.get("ask", 0)
        volume = tick.get("volume", 0)
        bid_qty = tick.get("bid_qty", 0)
        ask_qty = tick.get("ask_qty", 0)

        if ask > 0 and ltp >= ask:
            buy_pressure += volume
            delta_sum += volume
        elif bid > 0 and ltp <= bid:
            sell_pressure += volume
            delta_sum -= volume

        if i > 0:
            prev = ticks[i - 1]
            if bid_qty > prev.get("bid_qty", 0) * 1.5 and ltp <= bid:
                bid_absorption += 1
            if ask_qty > prev.get("ask_qty", 0) * 1.5 and ltp >= ask:
                ask_absorption += 1

    total_pressure = buy_pressure + sell_pressure
    if total_pressure == 0:
        return None

    buy_ratio = buy_pressure / total_pressure
    sell_ratio = sell_pressure / total_pressure

    # === NEW: Advanced flow detection ===
    sweeps = self._detect_sweeps(ticks)
    icebergs = self._detect_icebergs(ticks)
    delta_divergence = self._calc_cumulative_delta_divergence(underlying, ticks)
    momentum = self._tick_momentum(ticks)

    # === Large lot analysis (existing) ===
    large_lots = self._large_lots.get(underlying, [])
    recent_large = large_lots[-10:] if large_lots else []
    large_buy = sum(1 for l in recent_large if l.get("price", 0) >= l.get("ask", 0))
    large_sell = sum(1 for l in recent_large if l.get("price", 0) <= l.get("bid", 0))

    # === Direction determination (enhanced) ===
    if buy_ratio > 0.6 and delta_sum > 0 and bid_absorption > ask_absorption:
        direction = "BULLISH"
        confidence = min(0.95, 0.5 + (buy_ratio - 0.5) + (bid_absorption / max(1, bid_absorption + ask_absorption)) * 0.2)
    elif sell_ratio > 0.6 and delta_sum < 0 and ask_absorption > bid_absorption:
        direction = "BEARISH"
        confidence = min(0.95, 0.5 + (sell_ratio - 0.5) + (ask_absorption / max(1, bid_absorption + ask_absorption)) * 0.2)
    else:
        direction = "NEUTRAL"
        confidence = 0.3

    # === NEW: Sweep boost (aggressive institutional activity) ===
    if sweeps["buy_sweeps"] > sweeps["sell_sweeps"] + 2:
        if direction == "BULLISH":
            confidence = min(0.95, confidence + 0.1)
        elif direction == "NEUTRAL":
            direction = "BULLISH"
            confidence = 0.55
    elif sweeps["sell_sweeps"] > sweeps["buy_sweeps"] + 2:
        if direction == "BEARISH":
            confidence = min(0.95, confidence + 0.1)
        elif direction == "NEUTRAL":
            direction = "BEARISH"
            confidence = 0.55

    # === NEW: Iceberg detection boost ===
    if icebergs["iceberg_buy"] and direction in ("BULLISH", "NEUTRAL"):
        confidence = min(0.95, confidence + 0.08)
        if direction == "NEUTRAL":
            direction = "BULLISH"
    elif icebergs["iceberg_sell"] and direction in ("BEARISH", "NEUTRAL"):
        confidence = min(0.95, confidence + 0.08)
        if direction == "NEUTRAL":
            direction = "BEARISH"

    # === NEW: Delta divergence (exhaustion signal) ===
    if delta_divergence == "BEARISH_DIVERGENCE" and direction == "BULLISH":
        confidence = max(0.3, confidence - 0.15)  # Reduce bullish confidence
    elif delta_divergence == "BULLISH_DIVERGENCE" and direction == "BEARISH":
        confidence = max(0.3, confidence - 0.15)  # Reduce bearish confidence

    # === Existing: Large lot boost ===
    if large_buy > large_sell + 2:
        if direction == "BULLISH":
            confidence = min(0.95, confidence + 0.1)
        elif direction == "NEUTRAL":
            direction = "BULLISH"
            confidence = 0.5
    elif large_sell > large_buy + 2:
        if direction == "BEARISH":
            confidence = min(0.95, confidence + 0.1)
        elif direction == "NEUTRAL":
            direction = "BEARISH"
            confidence = 0.5

    # === Existing: Expiry boost ===
    expiry_note = ""
    if self.is_expiry_day():
        confidence = min(0.95, confidence * 1.15)
        expiry_note = " [EXPIRY DAY: Flow signals weighted up 15%]"

    reasoning = (
        f"Buy pressure: {buy_ratio:.0%}, Sell pressure: {sell_ratio:.0%}. "
        f"Delta: {delta_sum:+}. Absorptions — Bid: {bid_absorption}, Ask: {ask_absorption}. "
        f"Sweeps — Buy: {sweeps['buy_sweeps']}, Sell: {sweeps['sell_sweeps']}. "
        f"Large lots — Buy: {large_buy}, Sell: {large_sell}. "
        f"Delta divergence: {delta_divergence}. "
        f"Tick momentum — Up: {momentum['upticks']}, Down: {momentum['downticks']}, Streak: {momentum['max_streak']}.{expiry_note}"
    )

    return self.create_signal(
        underlying=underlying,
        direction=direction,
        confidence=confidence,
        timeframe="SCALP",
        reasoning=reasoning,
        supporting_data={
            "buy_pressure": buy_pressure,
            "sell_pressure": sell_pressure,
            "delta": delta_sum,
            "bid_absorptions": bid_absorption,
            "ask_absorptions": ask_absorption,
            "large_lots_buy": large_buy,
            "large_lots_sell": large_sell,
            "buy_sweeps": sweeps["buy_sweeps"],
            "sell_sweeps": sweeps["sell_sweeps"],
            "iceberg_buy": icebergs["iceberg_buy"],
            "iceberg_sell": icebergs["iceberg_sell"],
            "delta_divergence": delta_divergence,
            "tick_momentum": momentum,
            "tick_count": len(ticks),
            "is_expiry_day": self.is_expiry_day(),
        },
    )
```

- [ ] **Step 4: Commit**

```bash
git add backend/agents/order_flow_agent.py
git commit -m "feat: enhance order flow agent with sweep, iceberg, delta divergence detection"
```

---

### Task 4: Enhance Volume Profile Agent (agent_3)

**Files:**
- Modify: `backend/agents/volume_profile_agent.py`

- [ ] **Step 1: Add TPO tracking, initial balance, naked POC, and value area migration**

Add new tracking structures to `__init__`:

```python
self._tpo_counts: dict[str, dict[float, int]] = {}  # price -> time periods at that price
self._initial_balance: dict[str, dict] = {}  # {high, low, set: bool}
self._ib_set_time: dict[str, bool] = {}
self._prev_day_poc: dict[str, float | None] = {}
self._prev_day_value_area: dict[str, dict] = {}
self._tpo_period_counter: dict[str, int] = {}
```

Add these new methods:

```python
def _update_tpo(self, underlying: str, price: float):
    """Track Time Price Opportunity — count 30-min periods at each price level."""
    if underlying not in self._tpo_counts:
        self._tpo_counts[underlying] = {}
        self._tpo_period_counter[underlying] = 0

    bucket = round(price / self._PRICE_BUCKET) * self._PRICE_BUCKET
    self._tpo_counts[underlying][bucket] = self._tpo_counts[underlying].get(bucket, 0) + 1

def _update_initial_balance(self, underlying: str, price: float, tick_count: int):
    """Track Initial Balance Range (first 30 min of session = ~first 100 ticks at 5s intervals)."""
    if underlying not in self._initial_balance:
        self._initial_balance[underlying] = {"high": price, "low": price, "set": False}

    ib = self._initial_balance[underlying]
    if not ib["set"]:
        ib["high"] = max(ib["high"], price)
        ib["low"] = min(ib["low"], price)
        # After ~360 ticks (~30 min at 5s intervals), lock IB
        if tick_count > 360:
            ib["set"] = True

def _check_ib_breakout(self, underlying: str, price: float) -> str:
    """Check if price has broken out of initial balance range."""
    ib = self._initial_balance.get(underlying, {})
    if not ib.get("set"):
        return "WITHIN_IB"
    if price > ib["high"]:
        return "IB_BREAKOUT_UP"
    elif price < ib["low"]:
        return "IB_BREAKOUT_DOWN"
    return "WITHIN_IB"

def _check_naked_poc(self, underlying: str, current_price: float) -> dict:
    """Check if previous day's POC has been revisited."""
    prev_poc = self._prev_day_poc.get(underlying)
    if prev_poc is None:
        return {"has_naked_poc": False}

    distance_pct = abs(current_price - prev_poc) / current_price * 100
    return {
        "has_naked_poc": True,
        "naked_poc_price": prev_poc,
        "distance_pct": distance_pct,
        "is_nearby": distance_pct < 0.5,
    }

def _detect_excess_poor_highs_lows(self, underlying: str) -> dict:
    """Detect excess (single-print tails) and poor highs/lows from TPO profile."""
    tpo = self._tpo_counts.get(underlying, {})
    if not tpo:
        return {"excess_high": False, "excess_low": False, "poor_high": False, "poor_low": False}

    sorted_prices = sorted(tpo.keys())
    if len(sorted_prices) < 5:
        return {"excess_high": False, "excess_low": False, "poor_high": False, "poor_low": False}

    max_tpo = max(tpo.values())

    # Excess high: top 2 price levels have very low TPO (single prints = rejection)
    top_2_avg = (tpo.get(sorted_prices[-1], 0) + tpo.get(sorted_prices[-2], 0)) / 2
    excess_high = top_2_avg <= max(1, max_tpo * 0.15)

    # Excess low: bottom 2 price levels have very low TPO
    bottom_2_avg = (tpo.get(sorted_prices[0], 0) + tpo.get(sorted_prices[1], 0)) / 2
    excess_low = bottom_2_avg <= max(1, max_tpo * 0.15)

    # Poor high: top price levels have high TPO (no rejection, likely to be revisited)
    poor_high = top_2_avg >= max_tpo * 0.6

    # Poor low: bottom price levels have high TPO
    poor_low = bottom_2_avg >= max_tpo * 0.6

    return {"excess_high": excess_high, "excess_low": excess_low, "poor_high": poor_high, "poor_low": poor_low}
```

- [ ] **Step 2: Integrate new analyses into the main analysis method and enhance signal output**

Update the main analysis to include IB breakout, naked POC, and TPO data in reasoning and supporting_data.

- [ ] **Step 3: Commit**

```bash
git add backend/agents/volume_profile_agent.py
git commit -m "feat: enhance volume profile with TPO, initial balance, naked POC, excess detection"
```

---

### Task 5: Enhance Technical Agent (agent_4)

**Files:**
- Modify: `backend/agents/technical_agent.py`

- [ ] **Step 1: Add market structure detection functions**

Add after the existing `rsi` function (line 44):

```python
def detect_market_structure(highs: list[float], lows: list[float]) -> dict:
    """Detect Higher Highs/Lows (uptrend), Lower Highs/Lows (downtrend), BOS, CHoCH."""
    if len(highs) < 5 or len(lows) < 5:
        return {"structure": "UNKNOWN", "last_event": "NONE"}

    # Find swing points (local maxima/minima with 2-bar lookback)
    swing_highs = []
    swing_lows = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append((i, highs[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append((i, lows[i]))

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"structure": "UNKNOWN", "last_event": "NONE"}

    hh = swing_highs[-1][1] > swing_highs[-2][1]  # Higher High
    hl = swing_lows[-1][1] > swing_lows[-2][1]    # Higher Low
    lh = swing_highs[-1][1] < swing_highs[-2][1]  # Lower High
    ll = swing_lows[-1][1] < swing_lows[-2][1]    # Lower Low

    if hh and hl:
        structure = "UPTREND"
    elif lh and ll:
        structure = "DOWNTREND"
    elif hh and ll:
        structure = "EXPANSION"  # Volatile, widening range
    elif lh and hl:
        structure = "CONTRACTION"  # Consolidating
    else:
        structure = "MIXED"

    # Detect Break of Structure (BOS) and Change of Character (CHoCH)
    last_event = "NONE"
    if len(swing_highs) >= 3 and len(swing_lows) >= 3:
        # CHoCH: Was making HH/HL, now made LL (or vice versa)
        prev_structure_bull = swing_highs[-3][1] < swing_highs[-2][1] and swing_lows[-3][1] < swing_lows[-2][1]
        if prev_structure_bull and ll:
            last_event = "CHoCH_BEARISH"
        prev_structure_bear = swing_highs[-3][1] > swing_highs[-2][1] and swing_lows[-3][1] > swing_lows[-2][1]
        if prev_structure_bear and hh:
            last_event = "CHoCH_BULLISH"
        # BOS: Continuation break
        if structure == "UPTREND" and hh:
            last_event = "BOS_BULLISH"
        elif structure == "DOWNTREND" and ll:
            last_event = "BOS_BEARISH"

    return {
        "structure": structure,
        "last_event": last_event,
        "last_swing_high": swing_highs[-1][1] if swing_highs else None,
        "last_swing_low": swing_lows[-1][1] if swing_lows else None,
    }


def detect_rsi_divergence(closes: list[float], rsi_values: list[float]) -> str:
    """Detect bullish/bearish RSI divergence."""
    if len(closes) < 20 or len(rsi_values) < 20:
        return "NONE"

    # Find last two swing lows in price and compare with RSI at those points
    recent_closes = closes[-20:]
    recent_rsi = rsi_values[-20:]

    # Simple approach: compare last quarter vs current
    mid = len(recent_closes) // 2
    first_half_low_idx = min(range(mid), key=lambda i: recent_closes[i])
    second_half_low_idx = mid + min(range(mid, len(recent_closes) - mid), key=lambda i: recent_closes[mid + i], default=0)

    if second_half_low_idx >= len(recent_rsi) or first_half_low_idx >= len(recent_rsi):
        return "NONE"

    # Bullish divergence: price makes lower low, RSI makes higher low
    if recent_closes[second_half_low_idx] < recent_closes[first_half_low_idx]:
        if recent_rsi[second_half_low_idx] > recent_rsi[first_half_low_idx]:
            return "BULLISH_DIVERGENCE"

    # Find swing highs for bearish divergence
    first_half_high_idx = max(range(mid), key=lambda i: recent_closes[i])
    second_half_high_idx = mid + max(range(mid, len(recent_closes) - mid), key=lambda i: recent_closes[mid + i], default=0)

    if second_half_high_idx >= len(recent_rsi) or first_half_high_idx >= len(recent_rsi):
        return "NONE"

    # Bearish divergence: price makes higher high, RSI makes lower high
    if recent_closes[second_half_high_idx] > recent_closes[first_half_high_idx]:
        if recent_rsi[second_half_high_idx] < recent_rsi[first_half_high_idx]:
            return "BEARISH_DIVERGENCE"

    return "NONE"


def detect_fair_value_gaps(candles: list[dict]) -> list[dict]:
    """Detect Fair Value Gaps (FVG): 3-candle patterns where middle candle doesn't overlap."""
    gaps = []
    for i in range(2, len(candles)):
        c1_high = candles[i-2].get("high", 0)
        c1_low = candles[i-2].get("low", 0)
        c3_high = candles[i].get("high", 0)
        c3_low = candles[i].get("low", 0)

        # Bullish FVG: candle 3's low > candle 1's high (gap up)
        if c3_low > c1_high:
            gaps.append({"type": "BULLISH_FVG", "top": c3_low, "bottom": c1_high, "index": i})
        # Bearish FVG: candle 1's low > candle 3's high (gap down)
        elif c1_low > c3_high:
            gaps.append({"type": "BEARISH_FVG", "top": c1_low, "bottom": c3_high, "index": i})

    return gaps[-3:] if gaps else []  # Return last 3 FVGs


def bollinger_squeeze(closes: list[float], period: int = 20) -> dict:
    """Detect Bollinger Band squeeze — low bandwidth = imminent breakout."""
    if len(closes) < period:
        return {"squeeze": False, "bandwidth": 0}

    recent = closes[-period:]
    mean = sum(recent) / period
    std = (sum((x - mean) ** 2 for x in recent) / period) ** 0.5

    if mean == 0:
        return {"squeeze": False, "bandwidth": 0}

    bandwidth = (std * 2) / mean * 100  # Bandwidth as % of mean

    # Check if current bandwidth is lowest in last 20 periods
    all_bandwidths = []
    for j in range(period, len(closes)):
        window = closes[j-period:j]
        w_mean = sum(window) / period
        w_std = (sum((x - w_mean) ** 2 for x in window) / period) ** 0.5
        if w_mean > 0:
            all_bandwidths.append((w_std * 2) / w_mean * 100)

    squeeze = len(all_bandwidths) > 1 and bandwidth <= min(all_bandwidths[-20:]) * 1.05

    return {"squeeze": squeeze, "bandwidth": round(bandwidth, 3)}
```

- [ ] **Step 2: Integrate new functions into _analyze_timeframe**

Update `_analyze_timeframe` to use market structure, RSI divergence, FVG, and Bollinger squeeze. Add their results to the scoring system and detail_parts.

- [ ] **Step 3: Commit**

```bash
git add backend/agents/technical_agent.py
git commit -m "feat: enhance technical agent with market structure, RSI divergence, FVG, Bollinger squeeze"
```

---

### Task 6: Enhance Sentiment Agent (agent_5)

**Files:**
- Modify: `backend/agents/sentiment_agent.py:10-32`

- [ ] **Step 1: Replace SYSTEM_PROMPT with expert-level knowledge**

```python
SYSTEM_PROMPT = """You are a world-class Indian market sentiment analyst specializing in Nifty 50 and BankNifty with deep expertise in institutional flow analysis.

## Institutional Flow Analysis

### FII (Foreign Institutional Investors)
- **Index Futures Positioning:** Net long/short contracts and daily change. FII net long >20k contracts = strong bullish. Net short >20k = bearish.
- **Index Options Positioning:**
  - Net call writing by FII = bearish (they're selling upside)
  - Net put writing by FII = bullish (they're selling downside)
  - Long-short ratio > 1.5 = bullish positioning, < 0.8 = bearish
- **Cash Segment:** FII net > ₹2000 Cr = strong institutional buying. FII net < -₹2000 Cr = aggressive selling.
- **Derivatives vs Cash divergence:** FII buying in cash but adding shorts in derivatives = hedged/cautious. Both aligned = high conviction.

### DII (Domestic Institutional Investors)
- DII typically provide counter-support when FII sells
- DII buying > ₹3000 Cr on a day when FII is selling = strong floor
- Sector allocation shifts: Money moving from IT/Pharma (defensive) → Banks/Auto (cyclical) = risk-on rotation
- DII selling is rare — when DII sells alongside FII, it signals genuine distribution

### India VIX Analysis (Critical)
- **VIX < 12:** Extreme complacency. Options are cheap. Expect volatility expansion (breakout imminent). Buy slightly OTM options.
- **VIX 12-15:** Normal, low volatility. Standard operations.
- **VIX 15-18:** Slightly elevated. Normal for event weeks (RBI, earnings).
- **VIX 18-22:** High fear. Prefer ATM strikes. Reduce position sizes.
- **VIX 22-28:** Very high fear. Scalps only. Use tight stops.
- **VIX > 28:** Extreme fear. Trading paused (except hedging).
- **VIX Term Structure:**
  - Near-month VIX > Next-month (backwardation) = extreme near-term fear, often near bottoms
  - Near-month VIX < Next-month (contango) = normal, steady market
  - Rapid VIX crush (>10% drop in a day) = post-event relief, options sellers profit

### Market Breadth Internals
- **Advance-Decline Ratio:**
  - A/D > 3:1 = breadth thrust, very bullish, trend day likely
  - A/D > 2:1 = broad bullish breadth
  - A/D 1:1 to 2:1 = mixed, index-driven (few heavyweight movers)
  - A/D < 0.5:1 = broad sell-off, very bearish
- **% Stocks Above Key MAs:**
  - >80% above 20 DMA = overbought breadth, pullback risk
  - <20% above 20 DMA = oversold breadth, bounce candidate
  - >60% above 200 DMA = healthy long-term trend
  - <40% above 200 DMA = structural weakness
- **New Highs vs New Lows:**
  - NH > 50 with NL < 5 = strong bull trend
  - NL > 50 with NH < 5 = strong bear trend
  - Both elevated = churning market, sector rotation
- **Advance-Decline Line vs Nifty:**
  - A/D line making new high with Nifty = healthy trend confirmation
  - A/D line diverging (not confirming Nifty high) = breadth deterioration, top forming

### Retail vs Institutional Flow
- Retail traders are net option BUYERS (long gamma, short theta)
- Institutional traders are net option SELLERS (short gamma, long theta)
- When retail long/short ratio is extreme (>2.0 or <0.5), the opposite move is likely (contrarian signal)
- Client-level OI data from NSE shows: Clients (retail) vs Proprietary vs FII positioning

Respond with a JSON object:
{
    "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "vix_signal": "description of VIX implication",
    "institutional_flow": "FII/DII flow summary and what it means",
    "breadth_quality": "STRONG" | "MODERATE" | "WEAK" | "DETERIORATING",
    "vix_regime": "LOW" | "NORMAL" | "ELEVATED" | "HIGH" | "EXTREME"
}"""
```

- [ ] **Step 2: Update supporting_data to include new fields**

- [ ] **Step 3: Commit**

```bash
git add backend/agents/sentiment_agent.py
git commit -m "feat: enhance sentiment agent with FII derivatives, VIX term structure, breadth internals"
```

---

### Task 7: Enhance News Agent (agent_6)

**Files:**
- Modify: `backend/agents/news_agent.py:10-47`

- [ ] **Step 1: Replace SYSTEM_PROMPT with earnings playbooks and event models**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/agents/news_agent.py
git commit -m "feat: enhance news agent with earnings playbooks, RBI/Budget/Fed reaction models"
```

---

### Task 8: Enhance Macro Agent (agent_7)

**Files:**
- Modify: `backend/agents/macro_agent.py:10-41`

- [ ] **Step 1: Replace SYSTEM_PROMPT with deep correlation models**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/agents/macro_agent.py
git commit -m "feat: enhance macro agent with correlation models, gap prediction, FII flow outlook"
```

---

## Phase 3: New Modules

### Task 9: Build Strike Selection Engine

**Files:**
- Create: `backend/agents/strike_selector.py`
- Create: `backend/tests/test_strike_selector.py`

- [ ] **Step 1: Write test for strike selection**

```python
# backend/tests/test_strike_selector.py
import pytest
from agents.strike_selector import StrikeSelector

def test_scalp_prefers_atm():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 24000, "option_type": "CE", "delta": 0.52, "oi": 80000, "bid": 150, "ask": 153, "ltp": 151, "iv": 15.0},
        {"strike": 24050, "option_type": "CE", "delta": 0.42, "oi": 60000, "bid": 120, "ask": 124, "ltp": 122, "iv": 16.0},
        {"strike": 24100, "option_type": "CE", "delta": 0.33, "oi": 40000, "bid": 90, "ask": 95, "ltp": 92, "iv": 17.5},
    ]
    result = selector.select_strike("SCALP", "BULLISH", 24010, options, "NIFTY")
    assert result is not None
    assert result["strike"] == 24000  # ATM preferred for scalp

def test_rejects_low_oi():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 24000, "option_type": "CE", "delta": 0.50, "oi": 10000, "bid": 150, "ask": 155, "ltp": 152, "iv": 15.0},
    ]
    result = selector.select_strike("SCALP", "BULLISH", 24010, options, "NIFTY")
    assert result is None  # OI too low (< 50000 for scalp)

def test_rejects_wide_spread():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 24000, "option_type": "CE", "delta": 0.50, "oi": 100000, "bid": 150, "ask": 160, "ltp": 155, "iv": 15.0},
    ]
    result = selector.select_strike("SCALP", "BULLISH", 24010, options, "NIFTY")
    assert result is None  # Spread 10 > max 3 for scalp

def test_btst_prefers_itm_monthly():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 23900, "option_type": "CE", "delta": 0.62, "oi": 70000, "bid": 200, "ask": 204, "ltp": 202, "iv": 14.0, "expiry_type": "MONTHLY"},
        {"strike": 24000, "option_type": "CE", "delta": 0.50, "oi": 90000, "bid": 150, "ask": 153, "ltp": 151, "iv": 15.0, "expiry_type": "WEEKLY"},
    ]
    result = selector.select_strike("BTST", "BULLISH", 24010, options, "NIFTY")
    assert result is not None
    assert result["strike"] == 23900  # Monthly + ITM preferred for BTST

def test_rejects_penny_options():
    selector = StrikeSelector(capital=100000)
    options = [
        {"strike": 24500, "option_type": "CE", "delta": 0.05, "oi": 200000, "bid": 3, "ask": 5, "ltp": 4, "iv": 50.0},
    ]
    result = selector.select_strike("INTRADAY", "BULLISH", 24010, options, "NIFTY")
    assert result is None  # Premium < 10
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_strike_selector.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Implement StrikeSelector**

```python
# backend/agents/strike_selector.py
"""Strike Selection Engine — selects optimal option strike based on strategy, Greeks, and liquidity."""

import logging

logger = logging.getLogger("niftymind.strike_selector")

# Strategy-specific thresholds
STRATEGY_CONFIG = {
    "SCALP": {
        "delta_range": (0.42, 0.58),  # ATM or 1 strike OTM
        "min_oi": 50_000,
        "max_spread": 3.0,
        "min_premium": 10.0,
        "prefer_expiry": "WEEKLY",  # Cheaper premium, more gamma
        "iv_max_ratio": 2.0,  # Max IV vs ATM IV
    },
    "INTRADAY": {
        "delta_range_high_conviction": (0.42, 0.58),  # confidence > 0.8
        "delta_range_moderate": (0.28, 0.48),  # confidence 0.65-0.8
        "min_oi": 100_000,
        "max_spread": 5.0,
        "min_premium": 10.0,
        "prefer_expiry": "WEEKLY",  # Unless >3 days to expiry
        "iv_max_ratio": 1.5,
    },
    "BTST": {
        "delta_range": (0.48, 0.68),  # ITM or ATM — survives overnight theta
        "min_oi": 50_000,
        "max_spread": 5.0,
        "min_premium": 15.0,  # Higher floor for overnight hold
        "prefer_expiry": "MONTHLY",  # Less theta overnight
        "iv_max_ratio": 1.5,
    },
}


class StrikeSelector:
    def __init__(self, capital: float = 100_000):
        self.capital = capital
        self.max_premium_pct = 0.05  # Max 5% of capital per lot

    def select_strike(
        self,
        strategy: str,
        direction: str,
        spot_price: float,
        options: list[dict],
        underlying: str,
        confidence: float = 0.7,
        atm_iv: float | None = None,
    ) -> dict | None:
        """Select the best strike for the given strategy and direction.

        Returns dict with selected strike details or None if no valid strike found.
        """
        config = STRATEGY_CONFIG.get(strategy)
        if not config:
            logger.warning(f"Unknown strategy: {strategy}")
            return None

        option_type = "CE" if direction == "BULLISH" else "PE"
        candidates = [o for o in options if o.get("option_type") == option_type]

        if not candidates:
            logger.info(f"No {option_type} options available")
            return None

        # Determine delta range based on strategy and confidence
        if strategy == "INTRADAY":
            if confidence > 0.8:
                delta_range = config["delta_range_high_conviction"]
            else:
                delta_range = config["delta_range_moderate"]
        else:
            delta_range = config["delta_range"]

        valid = []
        for opt in candidates:
            delta = abs(opt.get("delta", 0))
            oi = opt.get("oi", 0)
            bid = opt.get("bid", 0)
            ask = opt.get("ask", 0)
            ltp = opt.get("ltp", 0)
            iv = opt.get("iv", 0)
            spread = ask - bid if ask > 0 and bid > 0 else 999
            expiry_type = opt.get("expiry_type", "WEEKLY")

            # Filter 1: Delta range
            if not (delta_range[0] <= delta <= delta_range[1]):
                continue

            # Filter 2: Minimum OI (liquidity)
            if oi < config["min_oi"]:
                continue

            # Filter 3: Max bid-ask spread
            if spread > config["max_spread"]:
                continue

            # Filter 4: Minimum premium (no penny options)
            if ltp < config["min_premium"]:
                continue

            # Filter 5: Premium ceiling (max 5% of capital)
            lot_size = 25 if underlying == "NIFTY" else 15
            lot_cost = ltp * lot_size
            if lot_cost > self.capital * self.max_premium_pct:
                continue

            # Filter 6: IV check (avoid overpriced options)
            if atm_iv and atm_iv > 0 and iv > atm_iv * config["iv_max_ratio"]:
                continue

            # Filter 7: BTST — prefer monthly expiry
            if strategy == "BTST" and expiry_type == "WEEKLY":
                days_to_expiry = opt.get("days_to_expiry", 0)
                if days_to_expiry < 2:
                    continue  # Never BTST with <2 days on weekly

            # Score: prefer closer to ATM (higher delta), higher OI, tighter spread
            delta_score = 1.0 - abs(delta - 0.50) * 2  # Peaks at 0.50
            oi_score = min(1.0, oi / 500_000)
            spread_score = 1.0 - (spread / config["max_spread"])

            # BTST: bonus for monthly expiry
            expiry_bonus = 0.2 if strategy == "BTST" and expiry_type == "MONTHLY" else 0.0

            total_score = delta_score * 0.4 + oi_score * 0.3 + spread_score * 0.2 + expiry_bonus * 0.1

            valid.append({
                "strike": opt.get("strike"),
                "option_type": option_type,
                "delta": delta,
                "oi": oi,
                "spread": spread,
                "ltp": ltp,
                "iv": iv,
                "expiry_type": expiry_type,
                "score": total_score,
                "lot_cost": lot_cost,
            })

        if not valid:
            logger.info(f"No valid strikes for {strategy} {direction} on {underlying}")
            return None

        # Sort by score descending
        valid.sort(key=lambda x: x["score"], reverse=True)
        best = valid[0]

        logger.info(
            f"Selected {best['option_type']} {best['strike']} for {strategy} "
            f"(delta={best['delta']:.2f}, OI={best['oi']:,}, spread=₹{best['spread']:.1f}, "
            f"premium=₹{best['ltp']:.1f}, score={best['score']:.3f})"
        )

        return best
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_strike_selector.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/strike_selector.py backend/tests/test_strike_selector.py
git commit -m "feat: add strike selection engine with strategy-specific filters and scoring"
```

---

### Task 10: Build Trailing Stop & Multi-Target TP Engine

**Files:**
- Create: `backend/execution/trailing_stop.py`
- Create: `backend/tests/test_trailing_stop.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/test_trailing_stop.py
import pytest
from execution.trailing_stop import TrailingStopManager, TradePosition

def test_initial_sl_set():
    mgr = TrailingStopManager(capital=100000)
    pos = TradePosition(
        trade_id="T001", entry_price=150.0, sl_price=130.0,
        direction="BULLISH", quantity=50, strategy="INTRADAY",
        targets=[{"ratio": 1.5, "exit_pct": 0.6}, {"ratio": 2.5, "exit_pct": 0.3}, {"ratio": 999, "exit_pct": 0.1}],
    )
    assert pos.sl_price == 130.0
    assert pos.risk_per_unit == 20.0

def test_t1_hit_moves_sl_to_breakeven():
    mgr = TrailingStopManager(capital=100000)
    pos = TradePosition(
        trade_id="T001", entry_price=150.0, sl_price=130.0,
        direction="BULLISH", quantity=50, strategy="INTRADAY",
        targets=[{"ratio": 1.5, "exit_pct": 0.6}, {"ratio": 2.5, "exit_pct": 0.3}, {"ratio": 999, "exit_pct": 0.1}],
    )
    # T1 = entry + 1.5 * risk = 150 + 1.5 * 20 = 180
    actions = mgr.update(pos, current_price=181.0)
    assert any(a["action"] == "PARTIAL_EXIT" for a in actions)
    assert pos.sl_price == 150.0  # Moved to breakeven

def test_sl_hit():
    mgr = TrailingStopManager(capital=100000)
    pos = TradePosition(
        trade_id="T001", entry_price=150.0, sl_price=130.0,
        direction="BULLISH", quantity=50, strategy="INTRADAY",
    )
    actions = mgr.update(pos, current_price=129.0)
    assert any(a["action"] == "FULL_EXIT_SL" for a in actions)
```

- [ ] **Step 2: Run tests (expect fail)**

```bash
cd backend && python -m pytest tests/test_trailing_stop.py -v
```

- [ ] **Step 3: Implement TrailingStopManager**

```python
# backend/execution/trailing_stop.py
"""Multi-target Take Profit + ATR-based Trailing Stop Loss engine."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("niftymind.trailing_stop")

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_TARGETS = [
    {"ratio": 1.5, "exit_pct": 0.60},  # T1: 60% at 1.5R
    {"ratio": 2.5, "exit_pct": 0.30},  # T2: 30% at 2.5R
    {"ratio": 999, "exit_pct": 0.10},   # T3: 10% runner (trailed)
]

STRATEGY_TIME_LIMITS = {
    "SCALP": {"max_hold_minutes": 10, "eod_exit_time": "15:15"},
    "INTRADAY": {"max_hold_minutes": 999, "eod_exit_time": "15:15"},
    "BTST": {"max_hold_minutes": 999, "eod_exit_time": None},  # No intraday exit
}


@dataclass
class TradePosition:
    trade_id: str
    entry_price: float
    sl_price: float
    direction: str  # BULLISH or BEARISH
    quantity: int
    strategy: str
    targets: list[dict] = field(default_factory=lambda: list(DEFAULT_TARGETS))
    remaining_quantity: int = 0
    targets_hit: list[int] = field(default_factory=list)
    entry_time: datetime = field(default_factory=lambda: datetime.now(IST))
    trailing_active: bool = False
    trail_atr: float = 0.0

    def __post_init__(self):
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.quantity

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.sl_price)


class TrailingStopManager:
    def __init__(self, capital: float = 100_000):
        self.capital = capital
        self.max_risk_pct = 0.02  # 2% max risk per trade

    def calculate_sl(self, entry_price: float, atr: float, structure_level: float | None,
                     direction: str, capital: float | None = None) -> dict:
        """Calculate stop loss based on ATR and structure levels."""
        cap = capital or self.capital
        max_risk = cap * self.max_risk_pct

        atr_sl_distance = 1.5 * atr

        if structure_level is not None:
            structure_distance = abs(entry_price - structure_level)
            sl_distance = max(atr_sl_distance, structure_distance)
        else:
            sl_distance = atr_sl_distance

        if direction == "BULLISH":
            sl_price = entry_price - sl_distance
        else:
            sl_price = entry_price + sl_distance

        return {
            "sl_price": round(sl_price, 2),
            "sl_distance": round(sl_distance, 2),
            "max_risk_amount": max_risk,
            "risk_per_unit": round(sl_distance, 2),
        }

    def update(self, pos: TradePosition, current_price: float,
               current_atr: float | None = None) -> list[dict]:
        """Update position: check SL, targets, trailing. Returns list of actions to execute."""
        actions = []

        if pos.remaining_quantity <= 0:
            return actions

        # Check SL hit
        if pos.direction == "BULLISH" and current_price <= pos.sl_price:
            actions.append({
                "action": "FULL_EXIT_SL",
                "trade_id": pos.trade_id,
                "quantity": pos.remaining_quantity,
                "price": current_price,
                "reason": f"SL hit at {current_price} (SL={pos.sl_price})",
            })
            pos.remaining_quantity = 0
            return actions
        elif pos.direction == "BEARISH" and current_price >= pos.sl_price:
            actions.append({
                "action": "FULL_EXIT_SL",
                "trade_id": pos.trade_id,
                "quantity": pos.remaining_quantity,
                "price": current_price,
                "reason": f"SL hit at {current_price} (SL={pos.sl_price})",
            })
            pos.remaining_quantity = 0
            return actions

        # Check options-specific exit rules
        if current_price < 10:
            actions.append({
                "action": "FULL_EXIT_ILLIQUID",
                "trade_id": pos.trade_id,
                "quantity": pos.remaining_quantity,
                "price": current_price,
                "reason": "Premium below ₹10 — exiting illiquid option",
            })
            pos.remaining_quantity = 0
            return actions

        # Check targets
        risk = pos.risk_per_unit
        if risk <= 0:
            return actions

        for i, target in enumerate(pos.targets):
            if i in pos.targets_hit:
                continue

            if pos.direction == "BULLISH":
                target_price = pos.entry_price + target["ratio"] * risk
                target_hit = current_price >= target_price
            else:
                target_price = pos.entry_price - target["ratio"] * risk
                target_hit = current_price <= target_price

            if target_hit and target["ratio"] < 999:
                exit_qty = int(pos.quantity * target["exit_pct"])
                exit_qty = min(exit_qty, pos.remaining_quantity)
                if exit_qty > 0:
                    actions.append({
                        "action": "PARTIAL_EXIT",
                        "trade_id": pos.trade_id,
                        "quantity": exit_qty,
                        "price": current_price,
                        "target_index": i + 1,
                        "reason": f"T{i+1} hit at {current_price:.2f} ({target['ratio']}R)",
                    })
                    pos.remaining_quantity -= exit_qty
                    pos.targets_hit.append(i)

                    # After T1: Move SL to breakeven
                    if i == 0:
                        pos.sl_price = pos.entry_price
                        logger.info(f"{pos.trade_id}: SL moved to breakeven after T1")

        # Trailing stop for runner (after T1 hit)
        if 0 in pos.targets_hit and current_atr and pos.remaining_quantity > 0:
            rr_achieved = abs(current_price - pos.entry_price) / risk if risk > 0 else 0

            if rr_achieved >= 2.0:
                trail_distance = 0.75 * current_atr
            elif rr_achieved >= 1.5:
                trail_distance = 1.0 * current_atr
            else:
                trail_distance = None

            if trail_distance:
                if pos.direction == "BULLISH":
                    new_sl = current_price - trail_distance
                    if new_sl > pos.sl_price:
                        pos.sl_price = round(new_sl, 2)
                        pos.trailing_active = True
                else:
                    new_sl = current_price + trail_distance
                    if new_sl < pos.sl_price:
                        pos.sl_price = round(new_sl, 2)
                        pos.trailing_active = True

        return actions

    def check_time_exit(self, pos: TradePosition) -> dict | None:
        """Check if position should be exited based on time rules."""
        now = datetime.now(IST)
        config = STRATEGY_TIME_LIMITS.get(pos.strategy, {})

        # Scalp: Exit if not in profit within max_hold_minutes
        if pos.strategy == "SCALP":
            max_hold = config.get("max_hold_minutes", 10)
            elapsed = (now - pos.entry_time).total_seconds() / 60
            if elapsed >= max_hold:
                return {
                    "action": "TIME_EXIT",
                    "trade_id": pos.trade_id,
                    "quantity": pos.remaining_quantity,
                    "reason": f"Scalp time limit: {elapsed:.0f} min > {max_hold} min",
                }

        # EOD exit for intraday
        eod_time_str = config.get("eod_exit_time")
        if eod_time_str:
            h, m = map(int, eod_time_str.split(":"))
            eod_time = now.replace(hour=h, minute=m, second=0)
            if now >= eod_time and pos.remaining_quantity > 0:
                return {
                    "action": "EOD_EXIT",
                    "trade_id": pos.trade_id,
                    "quantity": pos.remaining_quantity,
                    "reason": f"EOD exit at {eod_time_str} IST",
                }

        return None
```

- [ ] **Step 4: Run tests**

```bash
cd backend && python -m pytest tests/test_trailing_stop.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/execution/trailing_stop.py backend/tests/test_trailing_stop.py
git commit -m "feat: add trailing stop + multi-target TP engine with time-based exits"
```

---

### Task 11: Build Drawdown Manager

**Files:**
- Create: `backend/risk/drawdown_manager.py`
- Create: `backend/tests/test_drawdown_manager.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/test_drawdown_manager.py
import pytest
from risk.drawdown_manager import DrawdownManager

def test_consecutive_losses_reduce_size():
    mgr = DrawdownManager(capital=100000)
    mgr.record_trade(pnl=-500)
    mgr.record_trade(pnl=-300)
    mgr.record_trade(pnl=-200)
    assert mgr.size_multiplier == 0.5  # 3 losses → 50% reduction

def test_recovery_after_losses():
    mgr = DrawdownManager(capital=100000)
    mgr.record_trade(pnl=-500)
    mgr.record_trade(pnl=-300)
    mgr.record_trade(pnl=-200)
    assert mgr.size_multiplier == 0.5
    mgr.record_trade(pnl=400)
    mgr.record_trade(pnl=300)
    assert mgr.size_multiplier == 1.0  # Recovered after 2 trades

def test_consecutive_wins_reduce_size():
    mgr = DrawdownManager(capital=100000)
    for _ in range(5):
        mgr.record_trade(pnl=500)
    assert mgr.size_multiplier == 0.75  # 5 wins → 25% reduction

def test_drawdown_circuit_breaker():
    mgr = DrawdownManager(capital=100000)
    mgr._peak_equity = 100000
    mgr._current_equity = 84000  # 16% drawdown
    assert mgr.should_pause_trading()  # >15% drawdown
```

- [ ] **Step 2: Implement DrawdownManager**

```python
# backend/risk/drawdown_manager.py
"""Drawdown recovery and equity curve management."""

import logging
from datetime import datetime, timezone, timedelta
from collections import deque

logger = logging.getLogger("niftymind.drawdown")

IST = timezone(timedelta(hours=5, minutes=30))

CONSECUTIVE_LOSS_THRESHOLD = 3
CONSECUTIVE_LOSS_REDUCTION = 0.5  # 50% size after 3 losses
LOSS_RECOVERY_TRADES = 2  # Number of wins to recover from loss reduction

CONSECUTIVE_WIN_THRESHOLD = 5
CONSECUTIVE_WIN_REDUCTION = 0.75  # 75% size after 5 wins (mean reversion protection)

MAX_DRAWDOWN_PCT = 0.15  # 15% drawdown → pause
WEEKLY_LOSS_REDUCTION = 0.5  # 50% size if weekly loss limit hit


class DrawdownManager:
    def __init__(self, capital: float = 100_000):
        self._initial_capital = capital
        self._current_equity = capital
        self._peak_equity = capital
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._loss_reduction_remaining = 0  # Trades remaining under reduced size
        self._weekly_pnl = 0.0
        self._weekly_loss_limit = capital * 0.10  # 10% weekly limit at ₹1L
        self._equity_history: deque = deque(maxlen=20)  # For 20-day MA
        self._equity_history.append(capital)
        self._trade_log: list[dict] = []

    @property
    def size_multiplier(self) -> float:
        """Current position size multiplier (0.25 to 1.0)."""
        multiplier = 1.0

        # Consecutive loss reduction
        if self._loss_reduction_remaining > 0:
            multiplier *= CONSECUTIVE_LOSS_REDUCTION

        # Consecutive win reduction
        if self._consecutive_wins >= CONSECUTIVE_WIN_THRESHOLD:
            multiplier *= CONSECUTIVE_WIN_REDUCTION

        # Weekly loss limit hit
        if self._weekly_pnl <= -self._weekly_loss_limit:
            multiplier *= WEEKLY_LOSS_REDUCTION

        # Equity below 20-day MA
        if len(self._equity_history) >= 5:
            ma = sum(self._equity_history) / len(self._equity_history)
            if self._current_equity < ma:
                multiplier *= 0.5

        return max(0.25, min(1.0, multiplier))

    def record_trade(self, pnl: float):
        """Record a completed trade and update all counters."""
        self._current_equity += pnl
        self._weekly_pnl += pnl
        self._peak_equity = max(self._peak_equity, self._current_equity)
        self._equity_history.append(self._current_equity)

        self._trade_log.append({
            "pnl": pnl,
            "equity": self._current_equity,
            "timestamp": datetime.now(IST).isoformat(),
        })

        if pnl < 0:
            self._consecutive_losses += 1
            self._consecutive_wins = 0
            if self._consecutive_losses >= CONSECUTIVE_LOSS_THRESHOLD:
                self._loss_reduction_remaining = LOSS_RECOVERY_TRADES
                logger.warning(
                    f"Drawdown alert: {self._consecutive_losses} consecutive losses. "
                    f"Reducing size by {int((1 - CONSECUTIVE_LOSS_REDUCTION) * 100)}% for {LOSS_RECOVERY_TRADES} trades."
                )
        else:
            self._consecutive_wins += 1
            self._consecutive_losses = 0
            if self._loss_reduction_remaining > 0:
                self._loss_reduction_remaining -= 1
                if self._loss_reduction_remaining == 0:
                    logger.info("Drawdown recovery complete. Returning to normal size.")

    def should_pause_trading(self) -> bool:
        """Check if drawdown circuit breaker should activate."""
        if self._peak_equity <= 0:
            return False
        drawdown_pct = (self._peak_equity - self._current_equity) / self._peak_equity
        return drawdown_pct > MAX_DRAWDOWN_PCT

    def reset_weekly(self):
        """Reset weekly PnL counter (call on Monday market open)."""
        self._weekly_pnl = 0.0

    def get_status(self) -> dict:
        drawdown_pct = (self._peak_equity - self._current_equity) / self._peak_equity if self._peak_equity > 0 else 0
        return {
            "current_equity": self._current_equity,
            "peak_equity": self._peak_equity,
            "drawdown_pct": round(drawdown_pct * 100, 2),
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "size_multiplier": self.size_multiplier,
            "weekly_pnl": self._weekly_pnl,
            "should_pause": self.should_pause_trading(),
        }
```

- [ ] **Step 3: Run tests**

```bash
cd backend && python -m pytest tests/test_drawdown_manager.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/risk/drawdown_manager.py backend/tests/test_drawdown_manager.py
git commit -m "feat: add drawdown manager with consecutive loss/win tracking, equity curve filter"
```

---

### Task 12: Build Performance Metrics

**Files:**
- Create: `backend/performance/metrics.py`
- Create: `backend/performance/trade_journal.py`

- [ ] **Step 1: Implement performance metrics calculator**

```python
# backend/performance/metrics.py
"""Calculate trading performance metrics: win rate, profit factor, Sharpe, max drawdown."""

import math
from typing import List


def calculate_metrics(trades: List[dict]) -> dict:
    """Calculate all performance metrics from a list of trades.

    Each trade dict must have: pnl (float), entry_time (str), exit_time (str)
    """
    if not trades:
        return _empty_metrics()

    pnls = [t["pnl"] for t in trades]
    total_trades = len(pnls)
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]

    win_rate = len(winners) / total_trades if total_trades > 0 else 0
    avg_win = sum(winners) / len(winners) if winners else 0
    avg_loss = abs(sum(losers) / len(losers)) if losers else 0
    avg_rr = avg_win / avg_loss if avg_loss > 0 else float("inf")

    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    net_pnl = sum(pnls)

    # Expectancy per trade
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    # Max drawdown
    peak = 0
    max_dd = 0
    cumulative = 0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)

    # Sharpe ratio (annualized, assuming 252 trading days)
    if len(pnls) > 1:
        mean_return = sum(pnls) / len(pnls)
        variance = sum((p - mean_return) ** 2 for p in pnls) / (len(pnls) - 1)
        std_return = math.sqrt(variance)
        sharpe = (mean_return / std_return) * math.sqrt(252) if std_return > 0 else 0
    else:
        sharpe = 0

    return {
        "total_trades": total_trades,
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_rr": round(avg_rr, 2),
        "profit_factor": round(profit_factor, 2),
        "net_pnl": round(net_pnl, 2),
        "expectancy": round(expectancy, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
    }


def _empty_metrics() -> dict:
    return {
        "total_trades": 0, "winners": 0, "losers": 0, "win_rate": 0,
        "avg_win": 0, "avg_loss": 0, "avg_rr": 0, "profit_factor": 0,
        "net_pnl": 0, "expectancy": 0, "max_drawdown": 0, "sharpe_ratio": 0,
        "gross_profit": 0, "gross_loss": 0,
    }


def is_proof_threshold_met(metrics: dict) -> dict:
    """Check if system has met the proof-of-profitability gate."""
    return {
        "sufficient_trades": metrics["total_trades"] >= 100,
        "profitable": metrics["profit_factor"] > 1.5,
        "good_win_rate": metrics["win_rate"] > 0.55,
        "acceptable_drawdown": metrics["max_drawdown"] < metrics.get("capital", 100000) * 0.15,
        "recommendation": "READY_FOR_LIVE" if (
            metrics["total_trades"] >= 100
            and metrics["profit_factor"] > 1.5
            and metrics["win_rate"] > 0.55
        ) else "CONTINUE_PAPER_TRADING",
    }
```

- [ ] **Step 2: Implement trade journal**

```python
# backend/performance/trade_journal.py
"""Structured trade journal with full context logging."""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("niftymind.journal")

IST = timezone(timedelta(hours=5, minutes=30))


class TradeJournal:
    def __init__(self, journal_dir: str = "data/journal"):
        self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self._trades: list[dict] = []

    def record_entry(self, trade_id: str, entry_data: dict):
        """Record trade entry with full context."""
        entry = {
            "trade_id": trade_id,
            "status": "OPEN",
            "entry_time": datetime.now(IST).isoformat(),
            "entry_price": entry_data.get("entry_price"),
            "strike": entry_data.get("strike"),
            "option_type": entry_data.get("option_type"),
            "underlying": entry_data.get("underlying"),
            "direction": entry_data.get("direction"),
            "quantity": entry_data.get("quantity"),
            "strategy": entry_data.get("strategy"),
            "sl_price": entry_data.get("sl_price"),
            "targets": entry_data.get("targets", []),
            "agent_votes": entry_data.get("agent_votes", {}),
            "consensus_score": entry_data.get("consensus_score"),
            "reasoning": entry_data.get("reasoning"),
            "iv_at_entry": entry_data.get("iv"),
            "vix_at_entry": entry_data.get("vix"),
        }
        self._trades.append(entry)
        self._save_trade(entry)
        return entry

    def record_exit(self, trade_id: str, exit_data: dict):
        """Record trade exit with P&L and context."""
        for trade in self._trades:
            if trade["trade_id"] == trade_id:
                trade["status"] = "CLOSED"
                trade["exit_time"] = datetime.now(IST).isoformat()
                trade["exit_price"] = exit_data.get("exit_price")
                trade["exit_reason"] = exit_data.get("reason")
                trade["pnl"] = exit_data.get("pnl", 0)
                trade["slippage"] = exit_data.get("slippage", 0)
                trade["rr_achieved"] = exit_data.get("rr_achieved", 0)
                trade["targets_hit"] = exit_data.get("targets_hit", [])
                self._save_trade(trade)
                return trade
        return None

    def get_closed_trades(self) -> list[dict]:
        return [t for t in self._trades if t["status"] == "CLOSED"]

    def _save_trade(self, trade: dict):
        """Save trade to daily journal file."""
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
        filepath = self.journal_dir / f"journal_{date_str}.jsonl"
        with open(filepath, "a") as f:
            f.write(json.dumps(trade) + "\n")
```

- [ ] **Step 3: Commit**

```bash
git add backend/performance/
git commit -m "feat: add performance metrics calculator and trade journal"
```

---

## Phase 4: Integration

### Task 13: Integrate Strike Selector into Decision Agents

**Files:**
- Modify: `backend/agents/scalping_agent.py`
- Modify: `backend/agents/intraday_agent.py`
- Modify: `backend/agents/btst_agent.py`

- [ ] **Step 1: Add strike selector import and call in each decision agent**

In each decision agent, after generating a trade proposal, call `StrikeSelector.select_strike()` and include the selected strike in the proposal's supporting_data. If no valid strike is found, skip the proposal.

Example pattern for each agent:

```python
from agents.strike_selector import StrikeSelector

# In __init__:
self._strike_selector = StrikeSelector(capital=getattr(risk_config, 'capital', 100000))

# Before publishing trade proposal:
options_data = self._latest_options.get(underlying, [])
selected_strike = self._strike_selector.select_strike(
    strategy=trade_type,
    direction=direction,
    spot_price=spot_price,
    options=options_data,
    underlying=underlying,
    confidence=confidence,
)
if selected_strike is None:
    self.logger.info(f"No valid strike for {trade_type} {direction} — skipping proposal")
    return None

# Add to supporting_data:
supporting_data["selected_strike"] = selected_strike
supporting_data["option_type"] = selected_strike["option_type"]
supporting_data["strike_price"] = selected_strike["strike"]
supporting_data["premium"] = selected_strike["ltp"]
```

- [ ] **Step 2: Subscribe decision agents to options_chain channel to get live options data**

Add `"options_chain"` to `subscribed_channels` in each decision agent and cache the latest options snapshot.

- [ ] **Step 3: Commit**

```bash
git add backend/agents/scalping_agent.py backend/agents/intraday_agent.py backend/agents/btst_agent.py
git commit -m "feat: integrate strike selector into all decision agents"
```

---

### Task 14: Integrate Drawdown Manager into Risk Manager

**Files:**
- Modify: `backend/agents/risk_manager.py`

- [ ] **Step 1: Add drawdown manager to RiskManager**

```python
from risk.drawdown_manager import DrawdownManager

# In __init__, add:
self._drawdown_mgr = DrawdownManager(capital=self._capital)

# In _handle_execution, after updating daily PnL:
if event in ("EXIT", "SL_HIT", "TARGET_HIT", "EOD_CLOSE", "MANUAL"):
    pnl = float(data.get("pnl", 0))
    self._daily_pnl += pnl
    self._drawdown_mgr.record_trade(pnl)

# In _validate_proposal, add new checks:
# Drawdown pause check
if self._drawdown_mgr.should_pause_trading():
    checks.append({"name": "drawdown_circuit_breaker", "passed": False,
                    "detail": f"Drawdown > 15%: {self._drawdown_mgr.get_status()['drawdown_pct']}%"})
    approved = False

# Apply size multiplier from drawdown manager
size_multiplier = self._drawdown_mgr.size_multiplier
approved_quantity = int(sizing_result["quantity"] * size_multiplier)
```

- [ ] **Step 2: Add VIX regime-based restrictions**

```python
def _check_vix_regime(self) -> dict:
    """Enhanced VIX check with regime-based restrictions."""
    if self._current_vix is None:
        return {"name": "vix_regime", "passed": True, "detail": "VIX N/A", "regime": "UNKNOWN"}

    vix = self._current_vix
    if vix > 28:
        return {"name": "vix_regime", "passed": False, "detail": f"VIX {vix:.1f} > 28 — EXTREME, trading paused", "regime": "EXTREME"}
    elif vix > 22:
        return {"name": "vix_regime", "passed": True, "detail": f"VIX {vix:.1f} — HIGH, scalps only", "regime": "HIGH", "scalps_only": True}
    elif vix > 18:
        return {"name": "vix_regime", "passed": True, "detail": f"VIX {vix:.1f} — ELEVATED, reduce 25%", "regime": "ELEVATED"}
    else:
        return {"name": "vix_regime", "passed": True, "detail": f"VIX {vix:.1f} — NORMAL", "regime": "NORMAL"}
```

- [ ] **Step 3: Add correlation guard (no same-direction Nifty + BankNifty)**

Update `_check_correlation` to also block same-direction across underlyings:

```python
def _check_correlation(self, underlying: str, direction: str) -> dict:
    same_dir_same_ul = [p for p in self._open_positions if p.get("underlying") == underlying and p.get("direction") == direction]
    same_dir_cross = [p for p in self._open_positions if p.get("underlying") != underlying and p.get("direction") == direction]

    count_same = len(same_dir_same_ul)
    count_cross = len(same_dir_cross)

    # Block: same-direction Nifty + BankNifty (85% correlated)
    if count_cross > 0:
        return {"name": "correlation_risk", "passed": False,
                "detail": f"Already holding {direction} on other underlying — 85% correlated, blocking"}

    if count_same >= 2:
        return {"name": "correlation_risk", "passed": False,
                "detail": f"{count_same} existing {direction} on {underlying} (max 2)"}

    return {"name": "correlation_risk", "passed": True,
            "detail": f"{count_same} {direction} on {underlying}, {count_cross} cross-underlying"}
```

- [ ] **Step 4: Commit**

```bash
git add backend/agents/risk_manager.py
git commit -m "feat: integrate drawdown manager, VIX regimes, cross-underlying correlation guard"
```

---

### Task 15: Integrate Trailing Stop into Execution

**Files:**
- Modify: `backend/execution/paper_executor.py`
- Modify: `backend/execution/kite_executor.py`

- [ ] **Step 1: Add TrailingStopManager to paper executor**

Import and initialize the trailing stop manager. On each tick, call `mgr.update()` for all open positions. Execute partial exits and SL updates.

- [ ] **Step 2: Add smart order routing to kite executor**

Replace market orders with the limit-order ladder pattern:

```python
async def _place_smart_order(self, symbol: str, transaction_type: str, quantity: int,
                              exchange: str = "NFO") -> dict:
    """Place limit order at mid-price, widen until filled or fallback to market."""
    mid_price = self._get_mid_price(symbol)

    for attempt in range(3):
        price = mid_price + (attempt * 1.0 if transaction_type == "BUY" else -attempt * 1.0)
        order_id = self._kite.place_order(
            variety="regular",
            exchange=exchange,
            tradingsymbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            product="MIS",
            order_type="LIMIT",
            price=price,
        )

        # Wait 3 seconds for fill
        await asyncio.sleep(3)
        order = self._kite.order_history(order_id)[-1]

        if order["status"] == "COMPLETE":
            slippage = abs(order["average_price"] - mid_price)
            logger.info(f"Order filled: {symbol} {quantity} @ {order['average_price']} (slippage: ₹{slippage:.2f})")
            return {"filled": True, "price": order["average_price"], "slippage": slippage, "order_id": order_id}

        # Cancel unfilled order before retrying
        self._kite.cancel_order(variety="regular", order_id=order_id)

    # Fallback: market order
    order_id = self._kite.place_order(
        variety="regular", exchange=exchange, tradingsymbol=symbol,
        transaction_type=transaction_type, quantity=quantity,
        product="MIS", order_type="MARKET",
    )
    await asyncio.sleep(2)
    order = self._kite.order_history(order_id)[-1]
    slippage = abs(order.get("average_price", mid_price) - mid_price)
    return {"filled": True, "price": order.get("average_price"), "slippage": slippage, "order_id": order_id, "fallback_market": True}
```

- [ ] **Step 3: Commit**

```bash
git add backend/execution/paper_executor.py backend/execution/kite_executor.py
git commit -m "feat: integrate trailing stop + smart order routing into executors"
```

---

### Task 16: Update Consensus Orchestrator with VIX Regime Weights

**Files:**
- Modify: `backend/agents/consensus_orchestrator.py`

- [ ] **Step 1: Add VIX regime-adaptive weight profiles**

```python
# After existing WEIGHT_PROFILES, add:
VIX_REGIME_ADJUSTMENTS = {
    "LOW": {  # VIX < 12: Breakout expected, favor technical + momentum
        "agent_1_options_chain": 1.0,
        "agent_2_order_flow": 1.3,  # Boost: momentum matters more
        "agent_3_volume_profile": 1.2,
        "agent_4_technical": 1.3,
        "agent_5_sentiment": 0.8,
        "agent_6_news": 0.8,
        "agent_7_macro": 0.8,
    },
    "NORMAL": {k: 1.0 for k in ["agent_1_options_chain", "agent_2_order_flow", "agent_3_volume_profile", "agent_4_technical", "agent_5_sentiment", "agent_6_news", "agent_7_macro"]},
    "ELEVATED": {  # VIX 18-22: Favor options chain + sentiment
        "agent_1_options_chain": 1.3,
        "agent_2_order_flow": 0.8,
        "agent_3_volume_profile": 0.8,
        "agent_4_technical": 1.0,
        "agent_5_sentiment": 1.3,
        "agent_6_news": 1.2,
        "agent_7_macro": 1.2,
    },
    "HIGH": {  # VIX > 22: Only fast signals matter, scalps only
        "agent_1_options_chain": 1.0,
        "agent_2_order_flow": 1.5,
        "agent_3_volume_profile": 1.0,
        "agent_4_technical": 0.5,
        "agent_5_sentiment": 0.5,
        "agent_6_news": 0.5,
        "agent_7_macro": 0.5,
    },
}
```

Apply regime adjustment by multiplying base weights by regime multipliers before consensus calculation.

- [ ] **Step 2: Commit**

```bash
git add backend/agents/consensus_orchestrator.py
git commit -m "feat: add VIX regime-adaptive weight profiles to consensus orchestrator"
```

---

### Task 17: Add Performance API Endpoints

**Files:**
- Modify: `backend/api/routes.py`

- [ ] **Step 1: Add /api/performance endpoint**

```python
from performance.metrics import calculate_metrics, is_proof_threshold_met

@app.get("/api/performance")
async def get_performance():
    trades = trade_journal.get_closed_trades()
    metrics = calculate_metrics(trades)
    proof = is_proof_threshold_met(metrics)
    return {"metrics": metrics, "proof_gate": proof}
```

- [ ] **Step 2: Add /api/drawdown endpoint**

```python
@app.get("/api/drawdown")
async def get_drawdown():
    return drawdown_manager.get_status()
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/routes.py
git commit -m "feat: add performance metrics and drawdown status API endpoints"
```

---

### Task 18: Run Full Test Suite & Verify

- [ ] **Step 1: Run all tests**

```bash
cd backend && python -m pytest tests/ -v --tb=short
```
Expected: ALL PASS

- [ ] **Step 2: Run type checks**

```bash
cd "D:\Claude Projects\niftymind-main" && pnpm typecheck
```

- [ ] **Step 3: Rebuild and verify mobile web app**

```bash
cd artifacts/mobile && npx expo export --platform web
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete NiftyMind trading system enhancement — all agents, strike selector, SL/TP, risk manager, performance tracking"
```
