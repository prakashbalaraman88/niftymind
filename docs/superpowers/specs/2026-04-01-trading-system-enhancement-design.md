# NiftyMind Trading System Enhancement — Design Spec

**Date:** 2026-04-01
**Status:** Approved
**Capital:** ₹1L (testing) → ₹25L (production)
**Strategies:** Scalp + Intraday + BTST
**Broker:** Zerodha Kite Connect
**Data:** TrueData (tick-by-tick + options chain)

---

## 1. Agent Knowledge Enhancement

### 1.1 Options Chain Agent (agent_1)
Upgrade system prompt with:
- IV surface modeling: ATM IV vs strike-wise IV curve, skew direction (call skew vs put skew)
- Gamma exposure (GEX) mapping: Net gamma across strikes, dealer hedging zones
- OI change rate: Rising OI + rising price = long buildup, rising OI + falling price = short buildup
- PCR by expiry: Weekly PCR vs monthly PCR divergence signals
- Pin risk detection: High OI strikes within 0.5% of spot on expiry day
- Synthetic positioning: Identify institutional straddle/strangle writes via OI distribution
- Max pain drift tracking: Track max pain movement over last 3 sessions

### 1.2 Order Flow Agent (agent_2)
Upgrade heuristic logic with:
- Iceberg order detection: Repeated same-size orders at same level = hidden large order
- Sweep detection: Rapid execution across multiple price levels = aggressive buyer/seller
- Block deal identification: Single orders > 5x average order size
- Cumulative delta divergence: Price rising but cumulative delta falling = exhaustion
- Absorption scoring: Large resting orders that don't move despite opposing flow
- Bid-ask imbalance ratio: Weighted by size, not just count
- Tick-by-tick momentum: Consecutive upticks/downticks count

### 1.3 Volume Profile Agent (agent_3)
Upgrade with:
- Market Profile TPO (Time Price Opportunity): Time spent at each price level
- Initial Balance Range (IBR): First 30-min high-low as reference framework
- IB breakout detection: Price breaking IBR with volume confirmation
- Excess and poor highs/lows: Excess = strong rejection (single print tails), poor = likely revisit
- Single prints: Low-volume gaps in profile = magnet for price return
- Naked POC: Previous day's POC not yet revisited = support/resistance
- Value area migration: Compare today's developing VA vs yesterday's settled VA
- Volume-weighted momentum: Price move quality measured by volume participation

### 1.4 Technical Agent (agent_4)
Upgrade with:
- Market structure: Higher Highs/Higher Lows (uptrend), Lower Highs/Lower Lows (downtrend), Break of Structure (BOS), Change of Character (CHoCH)
- Supply-demand zones: Last bearish candle before rally = demand zone, last bullish candle before drop = supply zone
- Order blocks: Institutional candles with significant OI change
- Fair value gaps (FVG): 3-candle gaps where middle candle doesn't overlap with outer candles
- Multi-timeframe confluence: Signal strength multiplier when 1m + 5m + 15m align
- VWAP bands: +/- 1, 2, 3 standard deviations as dynamic S/R
- Bollinger squeeze: Band width < 20-period low = imminent breakout
- RSI divergence: Price makes new high but RSI doesn't = bearish divergence (and vice versa)
- EMA ribbon: 9/13/21/34/55 EMAs for trend strength visualization

### 1.5 Sentiment Agent (agent_5)
Upgrade system prompt with:
- FII index futures positioning: Net long/short contracts and change from previous day
- FII index options positioning: Net call writing vs put writing, long-short ratio
- DII sector allocation shifts: Defensive → cyclical rotation = risk-on
- India VIX term structure: Near-month vs next-month VIX, contango vs backwardation
- Put-call OI ratio by expiry: Weekly skew vs monthly skew
- Retail vs institutional flow: Option buyer (retail) vs writer (institutional) positioning
- Market breadth internals: % stocks above 20/50/200 DMA, new highs vs new lows
- Advance-decline line: Cumulative A/D vs Nifty divergence = breadth thrust or deterioration

### 1.6 News Agent (agent_6)
Upgrade system prompt with:
- Earnings playbooks for top 30 Nifty stocks: Historical beat/miss/inline reaction patterns
- RBI policy reaction model: Rate cut → banks rally, hold → muted, hike → sell-off timeline
- Event volatility crush: IV drops 20-40% post-event, avoid buying options 1 hour before major events
- Pre-event positioning: Straddle sellers dominate pre-event = range-bound until event
- Post-event momentum: First 15-min direction after event has 70% continuation probability
- Budget day playbook: Pre-budget rally typical, post-budget sell-the-news frequent
- Global event cascade: US CPI → Dollar move → FII flow → next-day Nifty impact chain
- Earnings season calendar: Auto-flag weeks with >5 Nifty50 companies reporting

### 1.7 Macro Agent (agent_7)
Upgrade system prompt with:
- USD/INR-Nifty correlation model: INR weakening >0.5% in a day = 80% chance Nifty negative
- Crude oil-OMC chain: Crude >$85 = BPCL/HPCL/IOC drag on Nifty, crude <$70 = tailwind
- US yield curve analysis: 2Y-10Y spread, inversion signals, impact on EM flows
- DXY-FII flow model: DXY >105 = FII selling pressure increases 60%
- Asian market open correlation: SGX Nifty + Nikkei + Hang Seng first 30 min = Nifty direction predictor
- Overnight gap prediction model: Based on US close, Asia open, crude, DXY — predict gap size with confidence bands
- Global risk-on/risk-off scoring: Composite score from VIX, DXY, gold, yields, crypto sentiment
- Fed meeting impact timeline: Decision → presser → next-day Asian reaction → 2-day delayed India impact

---

## 2. Strike Selection Engine (NEW)

**New file:** `backend/agents/strike_selector.py`

### 2.1 Strike Selection by Strategy

**Scalp:**
- ATM strike (delta 0.45-0.55) or 1 strike OTM
- Highest gamma = fastest premium movement
- Prefer weekly expiry (cheaper premium, more gamma)
- Min OI: 50,000 contracts
- Max bid-ask spread: ₹3

**Intraday:**
- High conviction (confidence > 0.8): ATM strike (delta 0.45-0.55)
- Moderate conviction (0.65-0.8): 1-2 strikes OTM (delta 0.30-0.45)
- Avoid strikes where IV > 1.5x ATM IV (overpriced)
- Min OI: 1,00,000 contracts
- Max bid-ask spread: ₹5
- Prefer weekly expiry unless >3 days to expiry, then consider monthly

**BTST:**
- Monthly expiry only (less theta overnight)
- ITM or ATM (delta 0.50-0.65) — survives theta + gap
- Never weekly if <2 trading days to expiry
- Min OI: 50,000 contracts
- Max bid-ask spread: ₹5

### 2.2 Strike Validation Checks
- Liquidity: OI > threshold for strategy
- Spread: Bid-ask < max spread for strategy
- IV rank: Warn if IV percentile > 80 (buying expensive premium)
- Premium floor: Option price > ₹10 (avoid illiquid penny options)
- Premium ceiling: Option price < 5% of capital per lot (₹5,000 at ₹1L)

---

## 3. Stop Loss & Take Profit Engine (UPGRADED)

### 3.1 Stop Loss

**ATR-based calculation:**
- Compute ATR(14) on option's 5-min chart
- SL distance = max(1.5x ATR, distance to nearest structure level)
- Hard cap: Never risk > 2% of capital per trade (₹2,000 at ₹1L)
- If ATR-based SL > 2% capital, reduce position size or skip trade

**Trailing stop:**
- After 1:1 R:R achieved: Move SL to breakeven
- After 1.5:1 R:R: Trail at 1x ATR below current price
- After 2:1 R:R: Tighten trail to 0.75x ATR

**Time-based stops:**
- Intraday: Close all positions by 15:15 IST
- Scalp: If not in profit within 10 minutes, exit at market
- BTST: Place hard SL order overnight (GTC) for gap protection

### 3.2 Take Profit (Multi-Target)

- **T1 (60% of position):** 1.5:1 R:R — secure majority profit
- **T2 (30% of position):** 2.5:1 R:R — let momentum run
- **T3 (10% runner):** Trail with 2x ATR — catch trend days
- If T1 hit: Move SL to breakeven on remaining position

### 3.3 Options-Specific Exit Rules
- Premium < ₹10: Exit immediately (becoming illiquid)
- Time to expiry < 2 hours: Exit (theta acceleration)
- VIX drops > 5% intraday: Tighten all targets by 30% (vol crush)
- Underlying moves 1.5% against position: Exit regardless of SL (momentum against)

---

## 4. Position Sizing

### 4.1 Core Formula
```
max_risk_amount = capital * max_risk_pct
position_lots = floor(max_risk_amount / (sl_points * lot_size * point_value))
final_lots = min(position_lots, max_lots_for_capital_tier)
```

### 4.2 Capital Tiers
| Capital | Max Risk/Trade | Max Positions | Daily Loss Limit | Weekly Loss Limit |
|---------|---------------|---------------|-----------------|-------------------|
| ₹1L | 2% (₹2K) | 2 | 5% (₹5K) | 10% (₹10K) |
| ₹5L | 2% (₹10K) | 3 | 4% (₹20K) | 8% (₹40K) |
| ₹10L | 1.5% (₹15K) | 4 | 3% (₹30K) | 6% (₹60K) |
| ₹25L | 1% (₹25K) | 5 | 2.5% (₹62.5K) | 5% (₹1.25L) |

### 4.3 Dynamic Adjustments
- After 3 consecutive losses: Reduce size by 50% for next 2 trades
- After 5 consecutive wins: Reduce size by 25% (mean reversion protection)
- Weekly loss limit hit: Reduce all sizes 50% for remainder of week
- Equity below 20-day MA: Reduce all sizes 50% until recovery

---

## 5. Execution Engine Upgrades

### 5.1 Smart Order Routing
- Place limit order at mid-price
- Wait 3 seconds; if unfilled, widen by ₹1
- Repeat up to 3 times (9 seconds total)
- After 3 attempts: Market order (emergency fill)
- Log slippage for every trade

### 5.2 Order Validation
- Pre-trade: Check margin availability via Kite API
- Post-trade: Verify order status, handle partial fills
- Partial fill: Wait 10 seconds, cancel remainder, adjust position

### 5.3 Re-entry Logic
- If SL hit but all agents still aligned (same direction, confidence > 0.7):
- Allow ONE re-entry at better price (must be > 0.5% better than original entry)
- Max 1 re-entry per signal cycle
- Re-entry uses 50% of original position size

---

## 6. Risk Manager Upgrades

### 6.1 New Risk Checks
- Correlation guard: Never hold same-direction Nifty + BankNifty simultaneously
- Event day guard: Auto-reduce size 50% on RBI/Budget/Fed days
- Equity curve filter: If account equity < 20-day moving average, 50% size reduction
- Drawdown circuit breaker: If drawdown > 15% from peak, pause trading for 1 day

### 6.2 VIX-Based Adjustments (Enhanced)
- VIX < 12: Full size, expect breakout (buy slightly OTM)
- VIX 12-18: Full size, normal operations
- VIX 18-22: Reduce to 75% size, prefer ATM strikes
- VIX 22-28: Reduce to 50% size, scalps only
- VIX > 28: Trading paused (except hedging existing positions)

---

## 7. Performance Tracking

### 7.1 Trade Journal
Every trade logged with: entry/exit time/price, agent votes, SL/TP levels, actual slippage, R:R achieved, reasoning

### 7.2 Dashboard Metrics
- Win rate (target: >55%)
- Average R:R (target: >1.5:1)
- Profit factor (target: >1.5)
- Max drawdown (limit: <15%)
- Sharpe ratio (target: >1.5 annualized)
- Expectancy per trade in ₹

### 7.3 Proof-of-Profitability Gate
System must complete 100+ paper trades with profit factor > 1.5 before recommending live trading at scale.

---

## 8. Files to Create/Modify

### New Files:
- `backend/agents/strike_selector.py` — Strike selection engine
- `backend/execution/smart_order.py` — Smart order routing
- `backend/execution/trailing_stop.py` — Multi-target TP + trailing SL
- `backend/risk/equity_curve.py` — Equity curve monitoring
- `backend/risk/drawdown_manager.py` — Drawdown recovery logic
- `backend/performance/trade_journal.py` — Trade logging
- `backend/performance/metrics.py` — Performance calculation

### Modified Files:
- `backend/agents/options_chain_agent.py` — Enhanced system prompt
- `backend/agents/order_flow_agent.py` — Enhanced heuristics
- `backend/agents/volume_profile_agent.py` — Market profile additions
- `backend/agents/technical_agent.py` — Market structure + advanced patterns
- `backend/agents/sentiment_agent.py` — Enhanced system prompt
- `backend/agents/news_agent.py` — Earnings playbooks + event models
- `backend/agents/macro_agent.py` — Enhanced correlation models
- `backend/agents/scalping_agent.py` — Strike selection integration
- `backend/agents/intraday_agent.py` — Strike selection + multi-target TP
- `backend/agents/btst_agent.py` — Strike selection + overnight SL
- `backend/agents/risk_manager.py` — All new risk checks
- `backend/agents/consensus_orchestrator.py` — Regime-adaptive weights
- `backend/execution/kite_executor.py` — Smart order routing
- `backend/execution/paper_executor.py` — Realistic simulation
- `backend/config.py` — New capital tier configs
