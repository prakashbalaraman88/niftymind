import sys
import os
from collections import deque
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent, Signal, IST
from datetime import time

OHLC_BUFFER_SIZE = 200


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period
    for val in values[period:]:
        result = (val - result) * multiplier + result
    return result


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class TechnicalAgent(BaseAgent):
    def __init__(self, redis_publisher, anthropic_config=None):
        super().__init__("agent_4_technical", "Technical Analysis Specialist", redis_publisher)
        self._ohlc: dict[str, dict[str, deque]] = {}
        self._candle_count: dict[str, int] = {}

    @property
    def subscribed_channels(self) -> list[str]:
        return ["ohlc_1m", "ohlc_5m", "ohlc_15m"]

    def _ensure_buffer(self, underlying: str):
        if underlying not in self._ohlc:
            self._ohlc[underlying] = {
                "1m": deque(maxlen=OHLC_BUFFER_SIZE),
                "5m": deque(maxlen=OHLC_BUFFER_SIZE),
                "15m": deque(maxlen=OHLC_BUFFER_SIZE),
            }
            self._candle_count[underlying] = 0

    async def process_message(self, channel: str, data: dict) -> Signal | None:
        underlying = data.get("underlying", data.get("symbol", ""))
        if not underlying:
            return None
        underlying = "NIFTY" if "NIFTY" in underlying.upper() and "BANK" not in underlying.upper() else "BANKNIFTY"

        self._ensure_buffer(underlying)

        if "1m" in channel:
            tf = "1m"
        elif "5m" in channel:
            tf = "5m"
        elif "15m" in channel:
            tf = "15m"
        else:
            return None

        self._ohlc[underlying][tf].append(data)
        self._candle_count[underlying] += 1

        if tf != "5m":
            return None

        if self._candle_count[underlying] % 3 != 0:
            return None

        return self._analyze(underlying)

    def _analyze(self, underlying: str) -> Signal | None:
        signals_by_tf = {}

        for tf in ["1m", "5m", "15m"]:
            candles = list(self._ohlc[underlying][tf])
            if len(candles) < 20:
                continue
            signals_by_tf[tf] = self._analyze_timeframe(candles, tf)

        if not signals_by_tf:
            return None

        weights = {"1m": 0.2, "5m": 0.4, "15m": 0.4}
        bullish_score = 0
        bearish_score = 0
        total_weight = 0
        all_details = {}

        for tf, result in signals_by_tf.items():
            w = weights.get(tf, 0.33)
            total_weight += w
            if result["direction"] == "BULLISH":
                bullish_score += w * result["confidence"]
            elif result["direction"] == "BEARISH":
                bearish_score += w * result["confidence"]
            all_details[tf] = result

        if total_weight == 0:
            return None

        bullish_score /= total_weight
        bearish_score /= total_weight

        if bullish_score > bearish_score and bullish_score > 0.4:
            direction = "BULLISH"
            confidence = min(0.95, bullish_score)
        elif bearish_score > bullish_score and bearish_score > 0.4:
            direction = "BEARISH"
            confidence = min(0.95, bearish_score)
        else:
            direction = "NEUTRAL"
            confidence = 0.3

        if self.is_expiry_day():
            now_time = datetime.now(IST).time()
            if now_time >= time(14, 0):
                confidence = min(0.95, confidence * 1.2)

        reasoning_parts = []
        for tf, result in signals_by_tf.items():
            reasoning_parts.append(f"{tf}: {result['direction']} ({result['confidence']:.2f}) — {result.get('detail', '')}")
        if self.is_expiry_day():
            reasoning_parts.append("[EXPIRY DAY: Tighter ranges expected pre-expiry; post-14:00 breakouts more decisive]")

        return self.create_signal(
            underlying=underlying,
            direction=direction,
            confidence=confidence,
            timeframe="INTRADAY",
            reasoning="; ".join(reasoning_parts),
            supporting_data={**all_details, "is_expiry_day": self.is_expiry_day()},
        )

    def _analyze_timeframe(self, candles: list[dict], tf: str) -> dict:
        closes = [c.get("close", 0) for c in candles]
        highs = [c.get("high", 0) for c in candles]
        lows = [c.get("low", 0) for c in candles]
        current = closes[-1]

        ema9 = ema(closes, 9)
        ema21 = ema(closes, 21)
        sma50 = sma(closes, 50) if len(closes) >= 50 else None
        rsi_val = rsi(closes)

        day_high = candles[0].get("high", current)
        day_low = candles[0].get("low", current)
        day_close = candles[0].get("close", current)
        pivot = (day_high + day_low + day_close) / 3
        bc = (day_high + day_low) / 2
        tc = 2 * pivot - bc
        cpr_width = abs(tc - bc) / pivot * 100

        h4 = day_close + (day_high - day_low) * 1.1 / 2
        h3 = day_close + (day_high - day_low) * 1.1 / 4
        l3 = day_close - (day_high - day_low) * 1.1 / 4
        l4 = day_close - (day_high - day_low) * 1.1 / 2

        bullish_points = 0
        bearish_points = 0
        detail_parts = []

        if ema9 and ema21:
            if ema9 > ema21 and current > ema9:
                bullish_points += 2
                detail_parts.append("EMA stack bullish")
            elif ema9 < ema21 and current < ema9:
                bearish_points += 2
                detail_parts.append("EMA stack bearish")

        if rsi_val is not None:
            if rsi_val > 60:
                bullish_points += 1
                detail_parts.append(f"RSI={rsi_val:.0f} bullish")
            elif rsi_val < 40:
                bearish_points += 1
                detail_parts.append(f"RSI={rsi_val:.0f} bearish")
            elif rsi_val > 70:
                bearish_points += 0.5
                detail_parts.append(f"RSI={rsi_val:.0f} overbought")
            elif rsi_val < 30:
                bullish_points += 0.5
                detail_parts.append(f"RSI={rsi_val:.0f} oversold")

        if current > pivot and current > tc:
            bullish_points += 1
            detail_parts.append("Above CPR")
        elif current < pivot and current < bc:
            bearish_points += 1
            detail_parts.append("Below CPR")

        if cpr_width < 0.3:
            detail_parts.append(f"Narrow CPR ({cpr_width:.2f}%) — expect breakout")

        if current > h3:
            bullish_points += 1
            detail_parts.append("Above Camarilla H3")
        elif current < l3:
            bearish_points += 1
            detail_parts.append("Below Camarilla L3")

        total = bullish_points + bearish_points
        if total == 0:
            return {"direction": "NEUTRAL", "confidence": 0.3, "detail": "No clear signals"}

        if bullish_points > bearish_points:
            direction = "BULLISH"
            confidence = min(0.9, 0.4 + (bullish_points / (total + 2)) * 0.5)
        elif bearish_points > bullish_points:
            direction = "BEARISH"
            confidence = min(0.9, 0.4 + (bearish_points / (total + 2)) * 0.5)
        else:
            direction = "NEUTRAL"
            confidence = 0.35

        return {
            "direction": direction,
            "confidence": confidence,
            "detail": ", ".join(detail_parts),
            "ema9": ema9,
            "ema21": ema21,
            "sma50": sma50,
            "rsi": rsi_val,
            "pivot": pivot,
            "cpr_width": cpr_width,
        }
