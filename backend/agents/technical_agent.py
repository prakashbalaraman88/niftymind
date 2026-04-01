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
    """Detect Bollinger Band squeeze -- low bandwidth = imminent breakout."""
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


class TechnicalAgent(BaseAgent):
    def __init__(self, redis_publisher, llm_config=None):
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

        # Market structure analysis
        mkt_structure = detect_market_structure(highs, lows)
        if mkt_structure["structure"] == "UPTREND":
            bullish_points += 1.5
            detail_parts.append("Market structure UPTREND")
        elif mkt_structure["structure"] == "DOWNTREND":
            bearish_points += 1.5
            detail_parts.append("Market structure DOWNTREND")
        elif mkt_structure["structure"] == "CONTRACTION":
            detail_parts.append("Market structure CONTRACTION (consolidating)")

        if mkt_structure["last_event"] == "BOS_BULLISH":
            bullish_points += 1
            detail_parts.append("BOS bullish")
        elif mkt_structure["last_event"] == "BOS_BEARISH":
            bearish_points += 1
            detail_parts.append("BOS bearish")
        elif mkt_structure["last_event"] == "CHoCH_BULLISH":
            bullish_points += 1.5
            detail_parts.append("CHoCH bullish reversal")
        elif mkt_structure["last_event"] == "CHoCH_BEARISH":
            bearish_points += 1.5
            detail_parts.append("CHoCH bearish reversal")

        # RSI divergence
        if rsi_val is not None and len(closes) >= 20:
            rsi_series = []
            for k in range(14, len(closes)):
                r = rsi(closes[:k+1])
                if r is not None:
                    rsi_series.append(r)
            divergence = detect_rsi_divergence(closes, rsi_series)
            if divergence == "BULLISH_DIVERGENCE":
                bullish_points += 2
                detail_parts.append("RSI bullish divergence")
            elif divergence == "BEARISH_DIVERGENCE":
                bearish_points += 2
                detail_parts.append("RSI bearish divergence")

        # Fair Value Gaps
        fvg_list = detect_fair_value_gaps(candles)
        if fvg_list:
            recent_fvg = fvg_list[-1]
            if recent_fvg["type"] == "BULLISH_FVG" and current <= recent_fvg["top"]:
                bullish_points += 1
                detail_parts.append(f"Near bullish FVG ({recent_fvg['bottom']:.0f}-{recent_fvg['top']:.0f})")
            elif recent_fvg["type"] == "BEARISH_FVG" and current >= recent_fvg["bottom"]:
                bearish_points += 1
                detail_parts.append(f"Near bearish FVG ({recent_fvg['bottom']:.0f}-{recent_fvg['top']:.0f})")

        # Bollinger squeeze
        bb_squeeze = bollinger_squeeze(closes)
        if bb_squeeze["squeeze"]:
            detail_parts.append(f"BB squeeze (bw={bb_squeeze['bandwidth']:.3f}%) — breakout imminent")

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
            "market_structure": mkt_structure,
            "bb_squeeze": bb_squeeze,
            "fvg_count": len(fvg_list),
        }
