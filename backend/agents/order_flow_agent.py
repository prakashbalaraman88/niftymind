import sys
import os
from collections import deque
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST

LARGE_LOT_THRESHOLD_NIFTY = 50 * 5
LARGE_LOT_THRESHOLD_BANKNIFTY = 15 * 5
TICK_WINDOW = 500
ANALYSIS_INTERVAL = 50
SWEEP_WINDOW_TICKS = 5  # Consecutive ticks to detect sweep
SWEEP_PRICE_LEVELS = 3  # Min distinct price levels for sweep
ICEBERG_SIZE_TOLERANCE = 0.1  # 10% size tolerance for iceberg detection
ICEBERG_MIN_REPEATS = 3  # Min repeated same-size orders
CUMULATIVE_DELTA_DIVERGENCE_WINDOW = 100  # Ticks for divergence check
UPTICK_DOWNTICK_WINDOW = 20  # Window for consecutive tick momentum
BLOCK_DEAL_MULTIPLIER = 5  # Single order > 5x rolling avg = block deal
BLOCK_DEAL_ROLLING_WINDOW = 50  # Rolling average window for block detection
IMBALANCE_THRESHOLD = 0.3  # Bid-ask imbalance threshold for confidence boost
FLOW_ACCEL_CHANGE_THRESHOLD = 20  # % change in delta to flag acceleration
FOOTPRINT_PRICE_BUCKET_ROUNDING = 1  # Decimal places for price bucketing
FOOTPRINT_TOP_N = 5  # Top N price levels by net delta


class OrderFlowAgent(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None):
        super().__init__("agent_2_order_flow", "Order Flow Specialist", redis_publisher)
        self.llm_config = llm_config
        self._tick_buffer: dict[str, deque] = {}
        self._tick_count: dict[str, int] = {}
        self._large_lots: dict[str, list] = {}
        self._cumulative_delta: dict[str, float] = {}
        self._price_at_delta_start: dict[str, float] = {}
        self._recent_order_sizes: dict[str, deque] = {}
        self._sweep_buffer: dict[str, deque] = {}
        self._consecutive_ticks: dict[str, list] = {}
        self._volume_delta_at_price: dict[str, dict[float, dict]] = {}
        self._latest_depth: dict[str, dict] = {}  # underlying → latest depth snapshot

    @property
    def subscribed_channels(self) -> list[str]:
        return ["ticks", "depth"]

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        symbol = data.get("symbol", "")
        if not symbol:
            return None

        underlying = "NIFTY" if "NIFTY" in symbol.upper() and "BANK" not in symbol.upper() else "BANKNIFTY"

        # Route depth snapshots — cache and return (no signal yet)
        if channel == "depth":
            self._latest_depth[underlying] = data
            return None

        if underlying not in self._tick_buffer:
            self._tick_buffer[underlying] = deque(maxlen=TICK_WINDOW)
            self._tick_count[underlying] = 0
            self._large_lots[underlying] = []

        self._tick_buffer[underlying].append(data)
        self._tick_count[underlying] += 1

        volume = data.get("volume", 0)
        threshold = LARGE_LOT_THRESHOLD_NIFTY if underlying == "NIFTY" else LARGE_LOT_THRESHOLD_BANKNIFTY
        if volume >= threshold:
            self._large_lots[underlying].append({
                "price": data.get("ltp"),
                "volume": volume,
                "bid": data.get("bid"),
                "ask": data.get("ask"),
                "timestamp": data.get("timestamp"),
            })
            if len(self._large_lots[underlying]) > 50:
                self._large_lots[underlying] = self._large_lots[underlying][-50:]

        if self._tick_count[underlying] % ANALYSIS_INTERVAL != 0:
            return None

        return self._analyze_flow(underlying)

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

    def _detect_block_deals(self, ticks: list) -> dict:
        """Detect block deals: single orders > 5x the rolling average order size in last 50 ticks."""
        if len(ticks) < BLOCK_DEAL_ROLLING_WINDOW:
            return {"block_buys": 0, "block_sells": 0, "largest_block": 0.0}

        recent = ticks[-BLOCK_DEAL_ROLLING_WINDOW:]
        volumes = [t.get("volume", 0) for t in recent if t.get("volume", 0) > 0]
        if not volumes:
            return {"block_buys": 0, "block_sells": 0, "largest_block": 0.0}

        avg_size = sum(volumes) / len(volumes)
        threshold = avg_size * BLOCK_DEAL_MULTIPLIER

        block_buys = 0
        block_sells = 0
        largest_block = 0.0

        for tick in recent:
            vol = tick.get("volume", 0)
            if vol >= threshold:
                ltp = tick.get("ltp", 0)
                ask = tick.get("ask", 0)
                bid = tick.get("bid", 0)
                largest_block = max(largest_block, float(vol))
                if ask > 0 and ltp >= ask:
                    block_buys += 1
                elif bid > 0 and ltp <= bid:
                    block_sells += 1

        return {"block_buys": block_buys, "block_sells": block_sells, "largest_block": largest_block}

    def _calc_bid_ask_imbalance(self, ticks: list) -> dict:
        """Calculate size-weighted bid-ask imbalance ratio."""
        bid_qty_sum = 0.0
        ask_qty_sum = 0.0

        for tick in ticks:
            bid_qty_sum += tick.get("bid_qty", 0)
            ask_qty_sum += tick.get("ask_qty", 0)

        total = bid_qty_sum + ask_qty_sum
        if total == 0:
            return {"imbalance_ratio": 0.0, "dominant_side": "NEUTRAL"}

        ratio = (bid_qty_sum - ask_qty_sum) / total
        if ratio > 0:
            dominant_side = "BID"  # Buyers absorbing
        elif ratio < 0:
            dominant_side = "ASK"  # Sellers absorbing
        else:
            dominant_side = "NEUTRAL"

        return {"imbalance_ratio": round(ratio, 4), "dominant_side": dominant_side}

    def _update_footprint(self, underlying: str, ticks: list) -> None:
        """Update volume delta at each price bucket for footprint analysis."""
        if underlying not in self._volume_delta_at_price:
            self._volume_delta_at_price[underlying] = {}

        footprint = self._volume_delta_at_price[underlying]

        for tick in ticks:
            ltp = tick.get("ltp", 0)
            ask = tick.get("ask", 0)
            bid = tick.get("bid", 0)
            vol = tick.get("volume", 0)
            if vol <= 0 or ltp <= 0:
                continue

            price_bucket = round(ltp, FOOTPRINT_PRICE_BUCKET_ROUNDING)
            if price_bucket not in footprint:
                footprint[price_bucket] = {"buy_vol": 0, "sell_vol": 0}

            if ask > 0 and ltp >= ask:
                footprint[price_bucket]["buy_vol"] += vol
            elif bid > 0 and ltp <= bid:
                footprint[price_bucket]["sell_vol"] += vol

        # Keep footprint from growing unbounded: retain only the 200 most recent price levels
        if len(footprint) > 200:
            sorted_prices = sorted(footprint.keys())
            for p in sorted_prices[:-200]:
                del footprint[p]

    def _calc_footprint_delta(self, underlying: str) -> list[dict]:
        """Return the top 5 price levels with highest absolute net delta (imbalance)."""
        footprint = self._volume_delta_at_price.get(underlying, {})
        if not footprint:
            return []

        deltas = []
        for price, vols in footprint.items():
            net_delta = vols["buy_vol"] - vols["sell_vol"]
            deltas.append({
                "price": price,
                "buy_vol": vols["buy_vol"],
                "sell_vol": vols["sell_vol"],
                "net_delta": net_delta,
            })

        deltas.sort(key=lambda x: abs(x["net_delta"]), reverse=True)
        return deltas[:FOOTPRINT_TOP_N]

    def _flow_acceleration(self, ticks: list) -> dict:
        """Compare flow in last 50 ticks vs previous 50 ticks to detect acceleration."""
        if len(ticks) < 100:
            return {"acceleration": "STEADY", "delta_change_pct": 0.0}

        prev_segment = ticks[-100:-50]
        curr_segment = ticks[-50:]

        def _segment_delta(segment: list) -> float:
            delta = 0.0
            for tick in segment:
                ltp = tick.get("ltp", 0)
                ask = tick.get("ask", 0)
                bid = tick.get("bid", 0)
                vol = tick.get("volume", 0)
                if ask > 0 and ltp >= ask:
                    delta += vol
                elif bid > 0 and ltp <= bid:
                    delta -= vol
            return delta

        prev_delta = _segment_delta(prev_segment)
        curr_delta = _segment_delta(curr_segment)

        if prev_delta == 0:
            if curr_delta == 0:
                return {"acceleration": "STEADY", "delta_change_pct": 0.0}
            return {
                "acceleration": "ACCELERATING",
                "delta_change_pct": 100.0 if curr_delta != 0 else 0.0,
            }

        change_pct = ((curr_delta - prev_delta) / abs(prev_delta)) * 100

        if abs(change_pct) < FLOW_ACCEL_CHANGE_THRESHOLD:
            accel = "STEADY"
        elif (curr_delta > 0 and change_pct > 0) or (curr_delta < 0 and change_pct < 0):
            # Delta magnitude increasing in the same direction
            accel = "ACCELERATING"
        else:
            accel = "DECELERATING"

        return {"acceleration": accel, "delta_change_pct": round(change_pct, 2)}

    def _analyze_book_depth(self, underlying: str) -> dict:
        """Analyze Dhan's 200-level order book for institutional walls and imbalance."""
        depth = self._latest_depth.get(underlying)
        if not depth:
            return {
                "book_imbalance": 0.0,
                "bid_wall_price": 0.0,
                "bid_wall_qty": 0,
                "ask_wall_price": 0.0,
                "ask_wall_qty": 0,
                "book_thin": False,
                "top10_bid_qty": 0,
                "top10_ask_qty": 0,
            }

        bids = depth.get("bids", [])  # [{"price": float, "quantity": int}, ...]
        asks = depth.get("asks", [])

        total_bid = sum(b.get("quantity", 0) for b in bids)
        total_ask = sum(a.get("quantity", 0) for a in asks)
        total = total_bid + total_ask

        book_imbalance = (total_bid - total_ask) / total if total > 0 else 0.0

        # Largest single order wall
        bid_wall = max(bids, key=lambda b: b.get("quantity", 0), default={})
        ask_wall = max(asks, key=lambda a: a.get("quantity", 0), default={})

        # Top-10 level liquidity (how thin is the near book?)
        top10_bid = sum(b.get("quantity", 0) for b in sorted(bids, key=lambda b: b.get("price", 0), reverse=True)[:10])
        top10_ask = sum(a.get("quantity", 0) for a in sorted(asks, key=lambda a: a.get("price", 0))[:10])

        # Thin book: top-10 levels have less than 5% of total book
        book_thin = (top10_bid + top10_ask) < (total * 0.05) if total > 0 else False

        return {
            "book_imbalance": round(book_imbalance, 4),
            "bid_wall_price": float(bid_wall.get("price", 0)),
            "bid_wall_qty": int(bid_wall.get("quantity", 0)),
            "ask_wall_price": float(ask_wall.get("price", 0)),
            "ask_wall_qty": int(ask_wall.get("quantity", 0)),
            "book_thin": book_thin,
            "top10_bid_qty": top10_bid,
            "top10_ask_qty": top10_ask,
        }

    def _analyze_flow(self, underlying: str) -> Signal | None:
        ticks = list(self._tick_buffer[underlying])
        if len(ticks) < 20:
            return None

        # === Existing pressure analysis (enhanced with aggressive/passive flow) ===
        buy_pressure = 0
        sell_pressure = 0
        bid_absorption = 0
        ask_absorption = 0
        delta_sum = 0
        aggressive_buys = 0   # Filled at ask = market buy
        aggressive_sells = 0  # Filled at bid = market sell
        passive_fills = 0     # Filled between bid and ask

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
                aggressive_buys += volume
            elif bid > 0 and ltp <= bid:
                sell_pressure += volume
                delta_sum -= volume
                aggressive_sells += volume
            elif bid > 0 and ask > 0 and bid < ltp < ask:
                passive_fills += volume

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
        block_deals = self._detect_block_deals(ticks)
        bid_ask_imbalance = self._calc_bid_ask_imbalance(ticks)
        self._update_footprint(underlying, ticks)
        footprint_delta = self._calc_footprint_delta(underlying)
        flow_accel = self._flow_acceleration(ticks)
        depth_analysis = self._analyze_book_depth(underlying)

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

        # === NEW: Block deal boost ===
        if block_deals["block_buys"] > block_deals["block_sells"]:
            if direction == "BULLISH":
                confidence = min(0.95, confidence + 0.1)
            elif direction == "NEUTRAL":
                direction = "BULLISH"
                confidence = 0.5
        elif block_deals["block_sells"] > block_deals["block_buys"]:
            if direction == "BEARISH":
                confidence = min(0.95, confidence + 0.1)
            elif direction == "NEUTRAL":
                direction = "BEARISH"
                confidence = 0.5

        # === NEW: Bid-ask imbalance boost ===
        imb_ratio = bid_ask_imbalance["imbalance_ratio"]
        if imb_ratio > IMBALANCE_THRESHOLD and direction in ("BULLISH", "NEUTRAL"):
            confidence = min(0.95, confidence + 0.05)
        elif imb_ratio < -IMBALANCE_THRESHOLD and direction in ("BEARISH", "NEUTRAL"):
            confidence = min(0.95, confidence + 0.05)

        # === NEW: Order book depth analysis (Dhan 200-level) ===
        book_imb = depth_analysis["book_imbalance"]
        if book_imb > 0.2 and direction in ("BULLISH", "NEUTRAL"):
            confidence = min(0.95, confidence + 0.07)
            if direction == "NEUTRAL":
                direction = "BULLISH"
        elif book_imb < -0.2 and direction in ("BEARISH", "NEUTRAL"):
            confidence = min(0.95, confidence + 0.07)
            if direction == "NEUTRAL":
                direction = "BEARISH"

        # Thin book: price can move fast — reduce confidence in sustained moves
        if depth_analysis["book_thin"]:
            confidence = max(0.25, confidence - 0.05)

        # === NEW: Flow acceleration boost ===
        if flow_accel["acceleration"] == "ACCELERATING":
            if (direction == "BULLISH" and flow_accel["delta_change_pct"] > 0) or \
               (direction == "BEARISH" and flow_accel["delta_change_pct"] < 0):
                confidence = min(0.95, confidence + 0.05)

        # === Existing: Expiry boost ===
        expiry_note = ""
        if self.is_expiry_day():
            confidence = min(0.95, confidence * 1.15)
            expiry_note = " [EXPIRY DAY: Flow signals weighted up 15%]"

        reasoning = (
            f"Buy pressure: {buy_ratio:.0%}, Sell pressure: {sell_ratio:.0%}. "
            f"Delta: {delta_sum:+}. Absorptions — Bid: {bid_absorption}, Ask: {ask_absorption}. "
            f"Aggressive — Buys: {aggressive_buys}, Sells: {aggressive_sells}, Passive: {passive_fills}. "
            f"Sweeps — Buy: {sweeps['buy_sweeps']}, Sell: {sweeps['sell_sweeps']}. "
            f"Large lots — Buy: {large_buy}, Sell: {large_sell}. "
            f"Block deals — Buy: {block_deals['block_buys']}, Sell: {block_deals['block_sells']}, Largest: {block_deals['largest_block']:.0f}. "
            f"Bid-ask imbalance: {imb_ratio:+.4f} ({bid_ask_imbalance['dominant_side']}). "
            f"Flow: {flow_accel['acceleration']} ({flow_accel['delta_change_pct']:+.1f}%). "
            f"Delta divergence: {delta_divergence}. "
            f"Tick momentum — Up: {momentum['upticks']}, Down: {momentum['downticks']}, Streak: {momentum['max_streak']}. "
            f"Book depth — Imbalance: {depth_analysis['book_imbalance']:+.4f}, "
            f"Bid wall: {depth_analysis['bid_wall_qty']}@{depth_analysis['bid_wall_price']:.0f}, "
            f"Ask wall: {depth_analysis['ask_wall_qty']}@{depth_analysis['ask_wall_price']:.0f}, "
            f"Thin: {depth_analysis['book_thin']}.{expiry_note}"
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
                "aggressive_buys": aggressive_buys,
                "aggressive_sells": aggressive_sells,
                "passive_fills": passive_fills,
                "large_lots_buy": large_buy,
                "large_lots_sell": large_sell,
                "block_buys": block_deals["block_buys"],
                "block_sells": block_deals["block_sells"],
                "largest_block": block_deals["largest_block"],
                "bid_ask_imbalance": bid_ask_imbalance["imbalance_ratio"],
                "bid_ask_dominant_side": bid_ask_imbalance["dominant_side"],
                "flow_acceleration": flow_accel["acceleration"],
                "flow_delta_change_pct": flow_accel["delta_change_pct"],
                "footprint_top_levels": footprint_delta,
                "buy_sweeps": sweeps["buy_sweeps"],
                "sell_sweeps": sweeps["sell_sweeps"],
                "iceberg_buy": icebergs["iceberg_buy"],
                "iceberg_sell": icebergs["iceberg_sell"],
                "delta_divergence": delta_divergence,
                "tick_momentum": momentum,
                "tick_count": len(ticks),
                "is_expiry_day": self.is_expiry_day(),
                "book_imbalance": depth_analysis["book_imbalance"],
                "bid_wall_price": depth_analysis["bid_wall_price"],
                "bid_wall_qty": depth_analysis["bid_wall_qty"],
                "ask_wall_price": depth_analysis["ask_wall_price"],
                "ask_wall_qty": depth_analysis["ask_wall_qty"],
                "book_thin": depth_analysis["book_thin"],
                "depth_available": bool(self._latest_depth.get(underlying)),
            },
        )
