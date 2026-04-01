import sys
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST

PRICE_BUCKET_SIZE = 5.0
ANALYSIS_INTERVAL = 100
HVN_THRESHOLD_PCT = 0.7
LVN_THRESHOLD_PCT = 0.2


class VolumeProfileAgent(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None):
        super().__init__("agent_3_volume_profile", "Volume Profile Specialist", redis_publisher)
        self._volume_at_price: dict[str, defaultdict] = {}
        self._cumulative_volume: dict[str, float] = {}
        self._cumulative_vwap_num: dict[str, float] = {}
        self._tick_count: dict[str, int] = {}
        self._anchor_price: dict[str, float] = {}
        self._anchor_vwap_num: dict[str, float] = {}
        self._anchor_volume: dict[str, float] = {}
        self._tpo_counts: dict[str, dict[float, int]] = {}
        self._initial_balance: dict[str, dict] = {}
        self._ib_set_time: dict[str, bool] = {}
        self._prev_day_poc: dict[str, float | None] = {}
        self._prev_day_value_area: dict[str, dict] = {}
        self._tpo_period_counter: dict[str, int] = {}
        # Buy/sell volume at each price bucket for volume delta
        self._buy_volume_at_price: dict[str, defaultdict] = {}
        self._sell_volume_at_price: dict[str, defaultdict] = {}
        # POC history for migration tracking (last 5 values per underlying)
        self._poc_history: dict[str, list[float]] = {}
        # Previous day value area for VA migration
        self._last_tick_ts: dict[str, datetime | None] = {}

    @property
    def subscribed_channels(self) -> list[str]:
        return ["ticks"]

    def _bucket(self, price: float) -> float:
        return round(price / PRICE_BUCKET_SIZE) * PRICE_BUCKET_SIZE

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        symbol = data.get("symbol", "")
        if not symbol:
            return None

        underlying = "NIFTY" if "NIFTY" in symbol.upper() and "BANK" not in symbol.upper() else "BANKNIFTY"
        ltp = data.get("ltp", 0)
        volume = data.get("volume", 0)
        bid = data.get("bid", 0)
        ask = data.get("ask", 0)

        if underlying not in self._volume_at_price:
            self._volume_at_price[underlying] = defaultdict(float)
            self._cumulative_volume[underlying] = 0
            self._cumulative_vwap_num[underlying] = 0
            self._tick_count[underlying] = 0
            self._anchor_price[underlying] = ltp
            self._anchor_vwap_num[underlying] = 0
            self._anchor_volume[underlying] = 0
            self._buy_volume_at_price[underlying] = defaultdict(float)
            self._sell_volume_at_price[underlying] = defaultdict(float)
            self._poc_history[underlying] = []
            self._last_tick_ts[underlying] = None

        # End-of-day rollover: save session data and reset when crossing 15:30 IST
        tick_ts_raw = data.get("timestamp")
        if tick_ts_raw:
            try:
                tick_ts = datetime.fromisoformat(str(tick_ts_raw))
                if tick_ts.tzinfo is None:
                    tick_ts = tick_ts.replace(tzinfo=IST)
                self._end_of_day_rollover(underlying, tick_ts)
                self._last_tick_ts[underlying] = tick_ts
            except (ValueError, TypeError):
                pass

        bucket = self._bucket(ltp)
        self._volume_at_price[underlying][bucket] += volume
        self._cumulative_volume[underlying] += volume
        self._cumulative_vwap_num[underlying] += ltp * volume
        self._anchor_vwap_num[underlying] += ltp * volume
        self._anchor_volume[underlying] += volume
        self._tick_count[underlying] += 1

        # Track buy vs sell volume using bid/ask comparison
        if bid > 0 and ask > 0 and volume > 0:
            if ltp >= ask:
                self._buy_volume_at_price[underlying][bucket] += volume
            elif ltp <= bid:
                self._sell_volume_at_price[underlying][bucket] += volume
            else:
                # Mid-price trade: split evenly
                self._buy_volume_at_price[underlying][bucket] += volume / 2
                self._sell_volume_at_price[underlying][bucket] += volume / 2
        elif volume > 0:
            # No bid/ask data: split evenly
            self._buy_volume_at_price[underlying][bucket] += volume / 2
            self._sell_volume_at_price[underlying][bucket] += volume / 2

        self._update_tpo(underlying, ltp)
        self._update_initial_balance(underlying, ltp, self._tick_count[underlying])

        if self._tick_count[underlying] % ANALYSIS_INTERVAL != 0:
            return None

        return self._analyze_profile(underlying, ltp)

    def _update_tpo(self, underlying: str, price: float):
        """Track Time Price Opportunity -- count 30-min periods at each price level."""
        if underlying not in self._tpo_counts:
            self._tpo_counts[underlying] = {}
            self._tpo_period_counter[underlying] = 0

        bucket = round(price / PRICE_BUCKET_SIZE) * PRICE_BUCKET_SIZE
        self._tpo_counts[underlying][bucket] = self._tpo_counts[underlying].get(bucket, 0) + 1

    def _update_initial_balance(self, underlying: str, price: float, tick_count: int):
        """Track Initial Balance Range (first 30 min of session = ~first 360 ticks at 5s intervals)."""
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
            "distance_pct": round(distance_pct, 2),
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

    # ── New feature methods ──────────────────────────────────────────────

    def _end_of_day_rollover(self, underlying: str, tick_ts: datetime):
        """Save current day's POC/VA and reset session data when tick crosses 15:30 IST."""
        eod_time = tick_ts.replace(hour=15, minute=30, second=0, microsecond=0, tzinfo=IST)
        prev_ts = self._last_tick_ts.get(underlying)
        if prev_ts is None:
            return
        # Check if the previous tick was before 15:30 and the current tick is at/after 15:30
        if prev_ts < eod_time <= tick_ts:
            # Save today's POC and value area for naked POC / VA migration
            vap = self._volume_at_price.get(underlying)
            if vap and sum(vap.values()) > 0:
                self._prev_day_poc[underlying] = max(vap, key=vap.get)
                # Compute value area for saving
                total_vol = sum(vap.values())
                sorted_prices = sorted(vap.keys())
                cumulative = 0
                val = sorted_prices[0]
                vah = sorted_prices[-1]
                for price in sorted_prices:
                    cumulative += vap[price]
                    if cumulative >= total_vol * 0.3 and val == sorted_prices[0]:
                        val = price
                    if cumulative >= total_vol * 0.7:
                        vah = price
                        break
                self._prev_day_value_area[underlying] = {"low": val, "high": vah}
            # Reset session data
            self._volume_at_price[underlying] = defaultdict(float)
            self._cumulative_volume[underlying] = 0
            self._cumulative_vwap_num[underlying] = 0
            self._tick_count[underlying] = 0
            self._anchor_vwap_num[underlying] = 0
            self._anchor_volume[underlying] = 0
            self._tpo_counts[underlying] = {}
            self._tpo_period_counter[underlying] = 0
            self._initial_balance[underlying] = {"high": 0, "low": 0, "set": False}
            self._buy_volume_at_price[underlying] = defaultdict(float)
            self._sell_volume_at_price[underlying] = defaultdict(float)
            self._poc_history[underlying] = []

    def _detect_single_prints(self, underlying: str) -> list[float]:
        """Detect low-volume gaps between HVN zones — price magnets for return."""
        vap = self._volume_at_price.get(underlying, {})
        if not vap:
            return []
        sorted_prices = sorted(vap.keys())
        if len(sorted_prices) < 5:
            return []
        max_vol = max(vap.values())
        if max_vol == 0:
            return []

        # Build list of HVN prices
        hvn_set = set()
        for p in sorted_prices:
            if vap[p] / max_vol >= HVN_THRESHOLD_PCT:
                hvn_set.add(p)

        # Single prints are prices with near-zero volume sandwiched between higher-volume areas
        single_prints = []
        threshold = max_vol * 0.05  # near-zero = less than 5% of max
        for i, p in enumerate(sorted_prices):
            if vap[p] <= threshold:
                # Check if there's meaningful volume on both sides
                has_above = any(vap.get(sp, 0) > threshold for sp in sorted_prices[i + 1:])
                has_below = any(vap.get(sp, 0) > threshold for sp in sorted_prices[:i])
                if has_above and has_below:
                    single_prints.append(p)
        return single_prints

    def _detect_poc_migration(self, underlying: str) -> str:
        """Check if POC has been migrating consistently up or down (trending day signal)."""
        history = self._poc_history.get(underlying, [])
        if len(history) < 3:
            return "STABLE"
        recent = history[-5:] if len(history) >= 5 else history
        ups = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
        downs = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
        moves = len(recent) - 1
        if ups >= moves * 0.7:
            return "MIGRATING_UP"
        elif downs >= moves * 0.7:
            return "MIGRATING_DOWN"
        return "STABLE"

    def _classify_profile_shape(self, underlying: str) -> str:
        """Classify volume profile shape: P (accumulation), b (distribution), D (balanced), B (double-dist)."""
        vap = self._volume_at_price.get(underlying, {})
        if not vap or len(vap) < 4:
            return "D-shape"
        sorted_prices = sorted(vap.keys())
        n = len(sorted_prices)
        third = max(n // 3, 1)

        bottom_vol = sum(vap[p] for p in sorted_prices[:third])
        middle_vol = sum(vap[p] for p in sorted_prices[third:n - third])
        top_vol = sum(vap[p] for p in sorted_prices[n - third:])
        total = bottom_vol + middle_vol + top_vol
        if total == 0:
            return "D-shape"

        bottom_pct = bottom_vol / total
        middle_pct = middle_vol / total
        top_pct = top_vol / total

        # B-shape: two peaks (top and bottom both significant, middle is valley)
        if bottom_pct > 0.3 and top_pct > 0.3 and middle_pct < 0.35:
            return "B-shape"
        # P-shape: high volume at top
        if top_pct > bottom_pct * 1.5 and top_pct > middle_pct:
            return "P-shape"
        # b-shape: high volume at bottom
        if bottom_pct > top_pct * 1.5 and bottom_pct > middle_pct:
            return "b-shape"
        # D-shape: balanced / high volume in middle
        return "D-shape"

    def _calc_volume_delta_at_price(self, underlying: str) -> list[dict]:
        """Return top 5 price levels with highest buy/sell imbalance (volume delta)."""
        buy_vap = self._buy_volume_at_price.get(underlying, {})
        sell_vap = self._sell_volume_at_price.get(underlying, {})
        all_buckets = set(buy_vap.keys()) | set(sell_vap.keys())
        if not all_buckets:
            return []

        deltas = []
        for bucket in all_buckets:
            bv = buy_vap.get(bucket, 0)
            sv = sell_vap.get(bucket, 0)
            delta = bv - sv
            deltas.append({"price": bucket, "buy_vol": round(bv, 1), "sell_vol": round(sv, 1), "delta": round(delta, 1)})

        deltas.sort(key=lambda x: abs(x["delta"]), reverse=True)
        return deltas[:5]

    def _detect_va_migration(self, underlying: str, current_val: float, current_vah: float) -> str:
        """Compare today's developing VA with yesterday's settled VA."""
        prev_va = self._prev_day_value_area.get(underlying)
        if not prev_va:
            return "VA_OVERLAPPING"
        prev_val = prev_va["low"]
        prev_vah = prev_va["high"]
        # Higher: today's VA entirely above yesterday's
        if current_val > prev_vah:
            return "VA_HIGHER"
        # Lower: today's VA entirely below yesterday's
        if current_vah < prev_val:
            return "VA_LOWER"
        return "VA_OVERLAPPING"

    def _analyze_profile(self, underlying: str, current_price: float) -> Signal | None:
        vap = self._volume_at_price[underlying]
        if not vap:
            return None

        total_vol = sum(vap.values())
        if total_vol == 0:
            return None

        poc_price = max(vap, key=vap.get)

        # Track developing POC history (keep last 5)
        history = self._poc_history.setdefault(underlying, [])
        if not history or history[-1] != poc_price:
            history.append(poc_price)
            if len(history) > 5:
                history[:] = history[-5:]

        vwap = (
            self._cumulative_vwap_num[underlying] / self._cumulative_volume[underlying]
            if self._cumulative_volume[underlying] > 0
            else current_price
        )

        anchor_vwap = (
            self._anchor_vwap_num[underlying] / self._anchor_volume[underlying]
            if self._anchor_volume[underlying] > 0
            else current_price
        )

        sorted_prices = sorted(vap.keys())
        hvn = []
        lvn = []
        max_vol = max(vap.values())

        for price in sorted_prices:
            ratio = vap[price] / max_vol
            if ratio >= HVN_THRESHOLD_PCT:
                hvn.append(price)
            elif ratio <= LVN_THRESHOLD_PCT and vap[price] > 0:
                lvn.append(price)

        cumulative = 0
        val = current_price
        vah = current_price
        for price in sorted_prices:
            cumulative += vap[price]
            if cumulative >= total_vol * 0.3 and val == current_price:
                val = price
            if cumulative >= total_vol * 0.7:
                vah = price
                break

        above_poc = current_price > poc_price
        above_vwap = current_price > vwap
        in_value_area = val <= current_price <= vah

        nearest_lvn_above = None
        nearest_lvn_below = None
        for lvn_price in lvn:
            if lvn_price > current_price and (nearest_lvn_above is None or lvn_price < nearest_lvn_above):
                nearest_lvn_above = lvn_price
            if lvn_price < current_price and (nearest_lvn_below is None or lvn_price > nearest_lvn_below):
                nearest_lvn_below = lvn_price

        # Existing analyses: IB breakout, naked POC, TPO excess/poor highs-lows
        ib_status = self._check_ib_breakout(underlying, current_price)
        naked_poc_info = self._check_naked_poc(underlying, current_price)
        excess_info = self._detect_excess_poor_highs_lows(underlying)
        ib = self._initial_balance.get(underlying, {})

        # New analyses
        poc_migration = self._detect_poc_migration(underlying)
        profile_shape = self._classify_profile_shape(underlying)
        single_prints = self._detect_single_prints(underlying)
        volume_delta = self._calc_volume_delta_at_price(underlying)
        va_migration = self._detect_va_migration(underlying, val, vah)

        if above_poc and above_vwap:
            direction = "BULLISH"
            confidence = 0.6
            if not in_value_area and current_price > vah:
                confidence = 0.7
        elif not above_poc and not above_vwap:
            direction = "BEARISH"
            confidence = 0.6
            if not in_value_area and current_price < val:
                confidence = 0.7
        else:
            direction = "NEUTRAL"
            confidence = 0.4

        # IB breakout boosts confidence in the breakout direction
        if ib_status == "IB_BREAKOUT_UP" and direction == "BULLISH":
            confidence = min(0.95, confidence + 0.1)
        elif ib_status == "IB_BREAKOUT_DOWN" and direction == "BEARISH":
            confidence = min(0.95, confidence + 0.1)

        # Naked POC nearby acts as a magnet — reduce confidence if price is moving away from it
        if naked_poc_info.get("is_nearby"):
            confidence = max(0.3, confidence - 0.05)

        # Excess confirms direction, poor highs/lows suggest revisit
        if direction == "BULLISH" and excess_info.get("excess_low"):
            confidence = min(0.95, confidence + 0.05)
        elif direction == "BEARISH" and excess_info.get("excess_high"):
            confidence = min(0.95, confidence + 0.05)

        # POC migration consistent with direction: confidence +0.05
        if (poc_migration == "MIGRATING_UP" and direction == "BULLISH") or \
           (poc_migration == "MIGRATING_DOWN" and direction == "BEARISH"):
            confidence = min(0.95, confidence + 0.05)

        # Profile shape aligned with direction: confidence +0.05
        if (profile_shape == "P-shape" and direction == "BULLISH") or \
           (profile_shape == "b-shape" and direction == "BEARISH"):
            confidence = min(0.95, confidence + 0.05)

        # VA migrating in direction: confidence +0.05
        if (va_migration == "VA_HIGHER" and direction == "BULLISH") or \
           (va_migration == "VA_LOWER" and direction == "BEARISH"):
            confidence = min(0.95, confidence + 0.05)

        expiry_note = ""
        if self.is_expiry_day():
            if not in_value_area:
                confidence = min(0.95, confidence * 1.1)
                expiry_note = " [EXPIRY DAY: Price outside value area — breakout more significant on expiry]"
            else:
                expiry_note = " [EXPIRY DAY: Mean reversion likely within value area due to pin risk]"

        # Build IB note
        ib_note = ""
        if ib.get("set"):
            ib_note = f" IB Range: {ib['low']:.1f}-{ib['high']:.1f}, Status: {ib_status}."
        else:
            ib_note = " IB still forming."

        # Build naked POC note
        naked_poc_note = ""
        if naked_poc_info.get("has_naked_poc"):
            naked_poc_note = (
                f" Naked POC at {naked_poc_info['naked_poc_price']:.1f}"
                f" ({naked_poc_info['distance_pct']:.1f}% away)"
                f"{' — NEARBY, acts as magnet' if naked_poc_info['is_nearby'] else ''}."
            )

        # Build TPO excess note
        excess_note = ""
        excess_parts = []
        if excess_info.get("excess_high"):
            excess_parts.append("excess high (rejection)")
        if excess_info.get("excess_low"):
            excess_parts.append("excess low (rejection)")
        if excess_info.get("poor_high"):
            excess_parts.append("poor high (likely revisit)")
        if excess_info.get("poor_low"):
            excess_parts.append("poor low (likely revisit)")
        if excess_parts:
            excess_note = f" TPO: {', '.join(excess_parts)}."

        # Build POC migration note
        poc_mig_note = ""
        if poc_migration != "STABLE":
            poc_mig_note = f" POC migration: {poc_migration} (trending day signal)."

        # Build profile shape note
        shape_labels = {
            "P-shape": "P-shape (accumulation/bullish)",
            "b-shape": "b-shape (distribution/bearish)",
            "D-shape": "D-shape (balanced/rotational)",
            "B-shape": "B-shape (double distribution, breakout imminent)",
        }
        shape_note = f" Profile: {shape_labels.get(profile_shape, profile_shape)}."

        # Build single prints note
        single_print_note = ""
        if single_prints:
            nearby_sp = [p for p in single_prints if abs(p - current_price) / current_price < 0.005]
            if nearby_sp:
                single_print_note = f" Single prints NEAR price at {', '.join(f'{p:.1f}' for p in nearby_sp[:3])} — magnet for price return."
            else:
                single_print_note = f" Single prints at {', '.join(f'{p:.1f}' for p in single_prints[:3])}."

        # Build VA migration note
        va_mig_note = ""
        if va_migration != "VA_OVERLAPPING":
            va_labels = {"VA_HIGHER": "VA higher than yesterday (bullish)", "VA_LOWER": "VA lower than yesterday (bearish)"}
            va_mig_note = f" {va_labels.get(va_migration, va_migration)}."

        # Build volume delta note
        vol_delta_note = ""
        if volume_delta:
            top = volume_delta[0]
            side = "buy" if top["delta"] > 0 else "sell"
            vol_delta_note = f" Strongest volume delta at {top['price']:.1f} ({side} imbalance: {abs(top['delta']):.0f})."

        reasoning = (
            f"POC: {poc_price:.1f}, VWAP: {vwap:.1f}, Anchored VWAP: {anchor_vwap:.1f}. "
            f"Value Area: {val:.1f}-{vah:.1f}. Price {'above' if above_poc else 'below'} POC, "
            f"{'above' if above_vwap else 'below'} VWAP. "
            f"HVN count: {len(hvn)}, LVN count: {len(lvn)}. "
            f"{'Inside' if in_value_area else 'Outside'} value area."
            f"{ib_note}{naked_poc_note}{excess_note}"
            f"{poc_mig_note}{shape_note}{single_print_note}{va_mig_note}{vol_delta_note}"
            f"{expiry_note}"
        )

        return self.create_signal(
            underlying=underlying,
            direction=direction,
            confidence=confidence,
            timeframe="INTRADAY",
            reasoning=reasoning,
            supporting_data={
                "poc": poc_price,
                "vwap": round(vwap, 2),
                "anchored_vwap": round(anchor_vwap, 2),
                "value_area_low": val,
                "value_area_high": vah,
                "hvn": hvn[:5],
                "lvn": lvn[:5],
                "nearest_lvn_above": nearest_lvn_above,
                "nearest_lvn_below": nearest_lvn_below,
                "above_poc": above_poc,
                "above_vwap": above_vwap,
                "in_value_area": in_value_area,
                "is_expiry_day": self.is_expiry_day(),
                "ib_status": ib_status,
                "ib_high": ib.get("high"),
                "ib_low": ib.get("low"),
                "ib_set": ib.get("set", False),
                "naked_poc": naked_poc_info,
                "tpo_excess": excess_info,
                "poc_migration": poc_migration,
                "poc_history": list(self._poc_history.get(underlying, [])),
                "profile_shape": profile_shape,
                "single_prints": single_prints[:5],
                "volume_delta_top5": volume_delta,
                "va_migration": va_migration,
                "prev_day_value_area": self._prev_day_value_area.get(underlying),
            },
        )
