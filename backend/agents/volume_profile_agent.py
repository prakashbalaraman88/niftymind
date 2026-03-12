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
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_3_volume_profile", "Volume Profile Specialist", redis_publisher)
        self._volume_at_price: dict[str, defaultdict] = {}
        self._cumulative_volume: dict[str, float] = {}
        self._cumulative_vwap_num: dict[str, float] = {}
        self._tick_count: dict[str, int] = {}
        self._anchor_price: dict[str, float] = {}
        self._anchor_vwap_num: dict[str, float] = {}
        self._anchor_volume: dict[str, float] = {}

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

        if underlying not in self._volume_at_price:
            self._volume_at_price[underlying] = defaultdict(float)
            self._cumulative_volume[underlying] = 0
            self._cumulative_vwap_num[underlying] = 0
            self._tick_count[underlying] = 0
            self._anchor_price[underlying] = ltp
            self._anchor_vwap_num[underlying] = 0
            self._anchor_volume[underlying] = 0

        bucket = self._bucket(ltp)
        self._volume_at_price[underlying][bucket] += volume
        self._cumulative_volume[underlying] += volume
        self._cumulative_vwap_num[underlying] += ltp * volume
        self._anchor_vwap_num[underlying] += ltp * volume
        self._anchor_volume[underlying] += volume
        self._tick_count[underlying] += 1

        if self._tick_count[underlying] % ANALYSIS_INTERVAL != 0:
            return None

        return self._analyze_profile(underlying, ltp)

    def _analyze_profile(self, underlying: str, current_price: float) -> Signal | None:
        vap = self._volume_at_price[underlying]
        if not vap:
            return None

        total_vol = sum(vap.values())
        if total_vol == 0:
            return None

        poc_price = max(vap, key=vap.get)

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

        expiry_note = ""
        if self.is_expiry_day():
            if not in_value_area:
                confidence = min(0.95, confidence * 1.1)
                expiry_note = " [EXPIRY DAY: Price outside value area — breakout more significant on expiry]"
            else:
                expiry_note = " [EXPIRY DAY: Mean reversion likely within value area due to pin risk]"

        reasoning = (
            f"POC: {poc_price:.1f}, VWAP: {vwap:.1f}, Anchored VWAP: {anchor_vwap:.1f}. "
            f"Value Area: {val:.1f}-{vah:.1f}. Price {'above' if above_poc else 'below'} POC, "
            f"{'above' if above_vwap else 'below'} VWAP. "
            f"HVN count: {len(hvn)}, LVN count: {len(lvn)}. "
            f"{'Inside' if in_value_area else 'Outside'} value area.{expiry_note}"
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
            },
        )
