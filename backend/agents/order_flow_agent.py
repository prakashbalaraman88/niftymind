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


class OrderFlowAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_2_order_flow", "Order Flow Specialist", redis_publisher)
        self.anthropic_config = anthropic_config
        self._tick_buffer: dict[str, deque] = {}
        self._tick_count: dict[str, int] = {}
        self._large_lots: dict[str, list] = {}

    @property
    def subscribed_channels(self) -> list[str]:
        return ["ticks"]

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        symbol = data.get("symbol", "")
        if not symbol:
            return None

        underlying = "NIFTY" if "NIFTY" in symbol.upper() and "BANK" not in symbol.upper() else "BANKNIFTY"

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

    def _analyze_flow(self, underlying: str) -> Signal | None:
        ticks = list(self._tick_buffer[underlying])
        if len(ticks) < 20:
            return None

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

        large_lots = self._large_lots.get(underlying, [])
        recent_large = large_lots[-10:] if large_lots else []
        large_buy = sum(1 for l in recent_large if l.get("price", 0) >= l.get("ask", 0))
        large_sell = sum(1 for l in recent_large if l.get("price", 0) <= l.get("bid", 0))

        if buy_ratio > 0.6 and delta_sum > 0 and bid_absorption > ask_absorption:
            direction = "BULLISH"
            confidence = min(0.95, 0.5 + (buy_ratio - 0.5) + (bid_absorption / max(1, bid_absorption + ask_absorption)) * 0.2)
        elif sell_ratio > 0.6 and delta_sum < 0 and ask_absorption > bid_absorption:
            direction = "BEARISH"
            confidence = min(0.95, 0.5 + (sell_ratio - 0.5) + (ask_absorption / max(1, bid_absorption + ask_absorption)) * 0.2)
        else:
            direction = "NEUTRAL"
            confidence = 0.3

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

        expiry_note = ""
        if self.is_expiry_day():
            confidence = min(0.95, confidence * 1.15)
            expiry_note = " [EXPIRY DAY: Higher volatility expected, flow signals weighted up 15%]"

        reasoning = (
            f"Buy pressure: {buy_ratio:.0%}, Sell pressure: {sell_ratio:.0%}. "
            f"Delta: {delta_sum:+}. Bid absorptions: {bid_absorption}, Ask absorptions: {ask_absorption}. "
            f"Large lots — Buy: {large_buy}, Sell: {large_sell}.{expiry_note}"
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
                "tick_count": len(ticks),
                "is_expiry_day": self.is_expiry_day(),
            },
        )
