"""Historical backtester: generates training data from past market data.

Fetches 6-12 months of Nifty/BankNifty data, runs simplified agent logic,
simulates trades, and feeds results into the learning system.

This pre-trains the model so it doesn't start cold on Day 1.
Uses Yahoo Finance (free) for OHLCV data. Can upgrade to TrueData for tick data.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger("niftymind.learning.backtester")

IST = timezone(timedelta(hours=5, minutes=30))

# Yahoo Finance symbols
SYMBOLS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

# India VIX
VIX_SYMBOL = "^INDIAVIX"


class HistoricalBacktester:
    """Backtests agent logic on historical data to pre-train the learning model."""

    def __init__(self, llm_config=None):
        self.llm_config = llm_config

    async def run_backtest(
        self,
        months: int = 6,
        trade_types: list[str] | None = None,
        underlyings: list[str] | None = None,
        store_lessons: bool = True,
    ) -> dict:
        """Run full backtest and store lessons.

        Returns summary dict with trade stats.
        """
        if trade_types is None:
            trade_types = ["SCALP", "INTRADAY", "BTST"]
        if underlyings is None:
            underlyings = ["NIFTY", "BANKNIFTY"]

        logger.info(f"Starting historical backtest: {months} months, {underlyings}, {trade_types}")

        # Fetch historical data
        end = datetime.now()
        start = end - timedelta(days=months * 30)

        all_trades = []

        for underlying in underlyings:
            symbol = SYMBOLS.get(underlying)
            if not symbol:
                continue

            logger.info(f"Fetching {underlying} data...")

            # Get daily data for BTST
            daily = yf.download(symbol, start=start, end=end, interval="1d", progress=False)
            if daily.empty:
                logger.warning(f"No daily data for {underlying}")
                continue

            # Flatten multi-level columns if present
            if isinstance(daily.columns, pd.MultiIndex):
                daily.columns = daily.columns.get_level_values(0)

            # Get 5-min data (Yahoo limits to 60 days)
            intraday_start = end - timedelta(days=59)
            intraday = yf.download(symbol, start=intraday_start, end=end, interval="5m", progress=False)
            if isinstance(intraday.columns, pd.MultiIndex):
                intraday.columns = intraday.columns.get_level_values(0)

            # Get VIX data
            vix_data = yf.download(VIX_SYMBOL, start=start, end=end, interval="1d", progress=False)
            if isinstance(vix_data.columns, pd.MultiIndex):
                vix_data.columns = vix_data.columns.get_level_values(0)

            logger.info(f"{underlying}: {len(daily)} daily bars, {len(intraday)} 5min bars")

            # Generate trades for each type
            if "BTST" in trade_types and len(daily) > 30:
                btst_trades = self._backtest_btst(underlying, daily, vix_data)
                all_trades.extend(btst_trades)
                logger.info(f"  BTST: {len(btst_trades)} trades")

            if "INTRADAY" in trade_types and len(intraday) > 100:
                intra_trades = self._backtest_intraday(underlying, intraday, vix_data)
                all_trades.extend(intra_trades)
                logger.info(f"  INTRADAY: {len(intra_trades)} trades")

            if "SCALP" in trade_types and len(intraday) > 100:
                scalp_trades = self._backtest_scalp(underlying, intraday, vix_data)
                all_trades.extend(scalp_trades)
                logger.info(f"  SCALP: {len(scalp_trades)} trades")

        logger.info(f"Total backtested trades: {len(all_trades)}")

        # Store lessons
        if store_lessons and all_trades:
            await self._store_backtest_lessons(all_trades)

        # Summary
        wins = sum(1 for t in all_trades if t["pnl"] > 0)
        losses = sum(1 for t in all_trades if t["pnl"] <= 0)
        total_pnl = sum(t["pnl"] for t in all_trades)

        summary = {
            "total_trades": len(all_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(all_trades) if all_trades else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / len(all_trades), 2) if all_trades else 0,
            "by_type": {},
            "by_underlying": {},
        }

        for tt in trade_types:
            tt_trades = [t for t in all_trades if t["trade_type"] == tt]
            if tt_trades:
                tt_wins = sum(1 for t in tt_trades if t["pnl"] > 0)
                summary["by_type"][tt] = {
                    "trades": len(tt_trades),
                    "win_rate": round(tt_wins / len(tt_trades), 2),
                    "avg_pnl": round(sum(t["pnl"] for t in tt_trades) / len(tt_trades), 2),
                }

        for ul in underlyings:
            ul_trades = [t for t in all_trades if t["underlying"] == ul]
            if ul_trades:
                ul_wins = sum(1 for t in ul_trades if t["pnl"] > 0)
                summary["by_underlying"][ul] = {
                    "trades": len(ul_trades),
                    "win_rate": round(ul_wins / len(ul_trades), 2),
                }

        logger.info(f"Backtest complete: {summary['total_trades']} trades, "
                     f"WR={summary['win_rate']:.0%}, PnL=₹{summary['total_pnl']:,.0f}")

        return summary

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute technical indicators on OHLCV dataframe."""
        df = df.copy()
        c = df["Close"].values.astype(float)
        h = df["High"].values.astype(float)
        l = df["Low"].values.astype(float)

        # EMAs
        df["ema9"] = pd.Series(c).ewm(span=9).mean().values
        df["ema21"] = pd.Series(c).ewm(span=21).mean().values
        df["ema50"] = pd.Series(c).ewm(span=50).mean().values

        # RSI (14)
        delta = pd.Series(c).diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi"] = (100 - 100 / (1 + rs)).values

        # ATR (14)
        tr = np.maximum(h[1:] - l[1:],
                        np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
        tr = np.insert(tr, 0, h[0] - l[0])
        df["atr"] = pd.Series(tr).rolling(14).mean().values

        # VWAP (for intraday)
        if "Volume" in df.columns:
            vol = df["Volume"].values.astype(float)
            cum_vol = np.cumsum(vol)
            cum_vp = np.cumsum(((h + l + c) / 3) * vol)
            df["vwap"] = np.where(cum_vol > 0, cum_vp / cum_vol, c)

        # Bollinger Bands
        sma20 = pd.Series(c).rolling(20).mean()
        std20 = pd.Series(c).rolling(20).std()
        df["bb_upper"] = (sma20 + 2 * std20).values
        df["bb_lower"] = (sma20 - 2 * std20).values
        df["bb_width"] = ((df["bb_upper"] - df["bb_lower"]) / sma20.values * 100)

        return df

    def _simulate_agent_signals(self, row, prev_rows, underlying, vix) -> dict:
        """Simulate what agents WOULD have signaled at this point in time."""
        signals = {}
        close = float(row["Close"])
        rsi = float(row.get("rsi", 50))
        ema9 = float(row.get("ema9", close))
        ema21 = float(row.get("ema21", close))
        ema50 = float(row.get("ema50", close))
        atr = float(row.get("atr", 0))
        bb_width = float(row.get("bb_width", 2))

        # Technical agent: EMA crossover + RSI
        tech_score = 0
        if ema9 > ema21 > ema50:
            tech_score += 0.3
        elif ema9 < ema21 < ema50:
            tech_score -= 0.3

        if rsi < 35:
            tech_score += 0.2  # oversold = bullish
        elif rsi > 65:
            tech_score -= 0.2  # overbought = bearish

        if close > ema21:
            tech_score += 0.15
        else:
            tech_score -= 0.15

        signals["agent_4_technical"] = {
            "direction": "BULLISH" if tech_score > 0 else "BEARISH",
            "confidence": float(min(0.85, abs(tech_score) + 0.35)),
        }

        # Order flow (approximated from volume + price action)
        if len(prev_rows) >= 3:
            recent_closes = [float(r["Close"]) for r in prev_rows[-3:]]
            recent_vols = [float(r.get("Volume", 0)) for r in prev_rows[-3:]]
            price_trend = (recent_closes[-1] - recent_closes[0]) / max(atr, 1)
            vol_trend = recent_vols[-1] / max(np.mean(recent_vols), 1)

            flow_score = price_trend * 0.3 + (vol_trend - 1) * 0.2
            signals["agent_2_order_flow"] = {
                "direction": "BULLISH" if flow_score > 0 else "BEARISH",
                "confidence": float(min(0.80, abs(flow_score) + 0.4)),
            }

        # Volume profile (price vs VWAP)
        vwap = float(row.get("vwap", close))
        vp_score = (close - vwap) / max(atr, 1) * 0.3
        signals["agent_3_volume_profile"] = {
            "direction": "BULLISH" if vp_score > 0 else "BEARISH",
            "confidence": float(min(0.75, abs(vp_score) + 0.4)),
        }

        # Sentiment (VIX-based)
        vix_val = float(vix) if vix else 15
        if vix_val < 14:
            sent_dir, sent_conf = "BULLISH", 0.65
        elif vix_val < 18:
            sent_dir, sent_conf = "BULLISH", 0.55
        elif vix_val < 22:
            sent_dir, sent_conf = "NEUTRAL", 0.45
        else:
            sent_dir, sent_conf = "BEARISH", 0.60
        signals["agent_5_sentiment"] = {"direction": sent_dir, "confidence": sent_conf}

        # Options chain (simplified: BB squeeze = low IV, BB expansion = high IV)
        if bb_width < 2.0:
            oc_dir = "NEUTRAL"
            oc_conf = 0.45
        elif tech_score > 0.1:
            oc_dir = "BULLISH"
            oc_conf = 0.60
        else:
            oc_dir = "BEARISH"
            oc_conf = 0.60
        signals["agent_1_options_chain"] = {"direction": oc_dir, "confidence": oc_conf}

        # News (random/neutral for backtest — no historical news data)
        signals["agent_6_news"] = {"direction": "NEUTRAL", "confidence": 0.45}

        # Macro (approximate from VIX trend)
        signals["agent_7_macro"] = {
            "direction": "BULLISH" if vix_val < 18 else "BEARISH",
            "confidence": 0.55,
        }

        return signals

    def _compute_consensus(self, signals: dict, trade_type: str) -> tuple[float, str]:
        """Simplified consensus from agent signals."""
        weights = {
            "agent_1_options_chain": 0.15,
            "agent_2_order_flow": 0.20,
            "agent_3_volume_profile": 0.15,
            "agent_4_technical": 0.20,
            "agent_5_sentiment": 0.10,
            "agent_6_news": 0.10,
            "agent_7_macro": 0.10,
        }

        score = 0
        total_w = 0
        for aid, sig in signals.items():
            w = weights.get(aid, 0.1)
            dir_mult = 1.0 if sig["direction"] == "BULLISH" else (-1.0 if sig["direction"] == "BEARISH" else 0)
            score += w * float(sig["confidence"]) * dir_mult
            total_w += w

        normalized = score / total_w if total_w > 0 else 0
        direction = "BULLISH" if normalized > 0 else "BEARISH"
        return float(abs(normalized)), direction

    def _get_vix_for_date(self, vix_data: pd.DataFrame, dt) -> float:
        """Get VIX value for a given date."""
        if vix_data.empty:
            return 15.0
        try:
            if hasattr(dt, 'date'):
                dt = dt.date() if not isinstance(dt, pd.Timestamp) else dt
            # Find nearest date
            idx = vix_data.index.get_indexer([dt], method="ffill")[0]
            if idx >= 0:
                return float(vix_data.iloc[idx]["Close"])
        except Exception:
            pass
        return 15.0

    def _get_vix_regime(self, vix: float) -> str:
        if vix < 14:
            return "LOW"
        elif vix < 18:
            return "NORMAL"
        elif vix < 22:
            return "ELEVATED"
        else:
            return "HIGH"

    def _backtest_btst(self, underlying: str, daily: pd.DataFrame, vix_data: pd.DataFrame) -> list[dict]:
        """Backtest BTST strategy on daily data."""
        trades = []
        df = self._compute_indicators(daily)
        df = df.dropna()

        for i in range(30, len(df) - 2):  # Need next 2 days for exit
            row = df.iloc[i]
            prev_rows = [df.iloc[j].to_dict() for j in range(max(0, i-5), i)]
            vix = self._get_vix_for_date(vix_data, df.index[i])
            signals = self._simulate_agent_signals(row, prev_rows, underlying, vix)
            consensus_score, direction = self._compute_consensus(signals, "BTST")

            if consensus_score < 0.55:
                continue  # Skip weak signals

            # Only take BTST every few days to be realistic
            if i % 3 != 0:
                continue

            entry = float(row["Close"])
            atr = float(row.get("atr", entry * 0.01))
            sl = entry - 2.0 * atr if direction == "BULLISH" else entry + 2.0 * atr

            # Exit next day at close
            next_close = float(df.iloc[i + 1]["Close"])
            pnl_per_unit = (next_close - entry) if direction == "BULLISH" else (entry - next_close)

            # Simulate 1 lot
            lot_size = 50 if underlying == "NIFTY" else 15
            # Approximate option premium behavior (delta ~0.5 for ATM)
            option_pnl = pnl_per_unit * 0.55 * lot_size

            # Check if SL hit during the day (using next day's low/high)
            next_low = float(df.iloc[i + 1]["Low"])
            next_high = float(df.iloc[i + 1]["High"])

            if direction == "BULLISH" and next_low < sl:
                option_pnl = (sl - entry) * 0.55 * lot_size  # SL hit
                exit_reason = "STOP_LOSS"
            elif direction == "BEARISH" and next_high > sl:
                option_pnl = (entry - sl) * 0.55 * lot_size
                exit_reason = "STOP_LOSS"
            elif option_pnl > 0:
                exit_reason = "TARGET"
            else:
                exit_reason = "TIME_EXIT"

            trade = {
                "trade_id": f"BT_BTST_{underlying}_{df.index[i].strftime('%Y%m%d')}",
                "underlying": underlying,
                "direction": direction,
                "trade_type": "BTST",
                "entry_price": entry,
                "exit_price": next_close,
                "pnl": round(option_pnl, 2),
                "consensus_score": round(consensus_score, 3),
                "entry_time": df.index[i].isoformat(),
                "exit_time": df.index[i + 1].isoformat(),
                "exit_reason": exit_reason,
                "vix_at_entry": round(vix, 1),
                "market_regime": self._get_vix_regime(vix),
                "signals": signals,
            }
            trades.append(trade)

        return trades

    def _backtest_intraday(self, underlying: str, intraday: pd.DataFrame, vix_data: pd.DataFrame) -> list[dict]:
        """Backtest intraday strategy on 5-min bars."""
        trades = []
        df = self._compute_indicators(intraday)
        df = df.dropna()

        # Group by date
        if hasattr(df.index, 'date'):
            dates = sorted(set(df.index.date))
        else:
            return trades

        for date in dates:
            day_data = df[df.index.date == date]
            if len(day_data) < 20:
                continue

            vix = self._get_vix_for_date(vix_data, pd.Timestamp(date))

            # Look for signal at 10:00-10:30 window (after initial volatility)
            morning = day_data.between_time("04:30", "05:00")  # UTC (10:00-10:30 IST)
            if morning.empty:
                # Try broader window
                morning = day_data.iloc[6:12]  # ~30-60 min after open

            if len(morning) < 2:
                continue

            entry_bar = morning.iloc[-1]
            prev_rows = [day_data.iloc[j].to_dict() for j in range(max(0, day_data.index.get_loc(entry_bar.name) - 5), day_data.index.get_loc(entry_bar.name))]

            signals = self._simulate_agent_signals(entry_bar, prev_rows, underlying, vix)
            consensus_score, direction = self._compute_consensus(signals, "INTRADAY")

            if consensus_score < 0.50:
                continue

            entry = float(entry_bar["Close"])
            atr = float(entry_bar.get("atr", entry * 0.005))

            # Find exit: look at remaining bars
            entry_idx = day_data.index.get_loc(entry_bar.name)
            remaining = day_data.iloc[entry_idx + 1:]

            if remaining.empty:
                continue

            # Simulate: T1 at 1.5 ATR, SL at 1.5 ATR
            sl_dist = 1.5 * atr
            t1_dist = 1.5 * sl_dist

            exit_price = float(remaining.iloc[-1]["Close"])  # Default: EOD exit
            exit_reason = "TIME_EXIT"

            for _, bar in remaining.iterrows():
                high = float(bar["High"])
                low = float(bar["Low"])

                if direction == "BULLISH":
                    if low <= entry - sl_dist:
                        exit_price = entry - sl_dist
                        exit_reason = "STOP_LOSS"
                        break
                    if high >= entry + t1_dist:
                        exit_price = entry + t1_dist
                        exit_reason = "TARGET"
                        break
                else:
                    if high >= entry + sl_dist:
                        exit_price = entry + sl_dist
                        exit_reason = "STOP_LOSS"
                        break
                    if low <= entry - t1_dist:
                        exit_price = entry - t1_dist
                        exit_reason = "TARGET"
                        break

            pnl_per_unit = (exit_price - entry) if direction == "BULLISH" else (entry - exit_price)
            lot_size = 50 if underlying == "NIFTY" else 15
            option_pnl = pnl_per_unit * 0.50 * lot_size

            trade = {
                "trade_id": f"BT_INTRA_{underlying}_{date.strftime('%Y%m%d')}",
                "underlying": underlying,
                "direction": direction,
                "trade_type": "INTRADAY",
                "entry_price": round(entry, 2),
                "exit_price": round(exit_price, 2),
                "pnl": round(option_pnl, 2),
                "consensus_score": round(consensus_score, 3),
                "entry_time": entry_bar.name.isoformat(),
                "exit_time": remaining.iloc[-1].name.isoformat() if exit_reason == "TIME_EXIT" else entry_bar.name.isoformat(),
                "exit_reason": exit_reason,
                "vix_at_entry": round(vix, 1),
                "market_regime": self._get_vix_regime(vix),
                "signals": signals,
            }
            trades.append(trade)

        return trades

    def _backtest_scalp(self, underlying: str, intraday: pd.DataFrame, vix_data: pd.DataFrame) -> list[dict]:
        """Backtest scalp strategy on 5-min bars (quick entries/exits)."""
        trades = []
        df = self._compute_indicators(intraday)
        df = df.dropna()

        if hasattr(df.index, 'date'):
            dates = sorted(set(df.index.date))
        else:
            return trades

        for date in dates:
            day_data = df[df.index.date == date]
            if len(day_data) < 30:
                continue

            vix = self._get_vix_for_date(vix_data, pd.Timestamp(date))

            # Take up to 3 scalps per day at different times
            entry_indices = [10, 20, 35]  # ~50min, ~100min, ~175min after open

            for ei in entry_indices:
                if ei >= len(day_data) - 5:
                    continue

                entry_bar = day_data.iloc[ei]
                prev_rows = [day_data.iloc[j].to_dict() for j in range(max(0, ei - 3), ei)]

                signals = self._simulate_agent_signals(entry_bar, prev_rows, underlying, vix)
                consensus_score, direction = self._compute_consensus(signals, "SCALP")

                if consensus_score < 0.45:
                    continue

                entry = float(entry_bar["Close"])
                atr = float(entry_bar.get("atr", entry * 0.003))

                # Scalp: tight SL (0.75 ATR), quick target (1.0 ATR)
                sl_dist = 0.75 * atr
                target_dist = 1.0 * atr

                # Look at next 5 bars only (25 min max hold)
                window = day_data.iloc[ei + 1: ei + 6]
                exit_price = float(window.iloc[-1]["Close"])
                exit_reason = "TIME_EXIT"

                for _, bar in window.iterrows():
                    high = float(bar["High"])
                    low = float(bar["Low"])

                    if direction == "BULLISH":
                        if low <= entry - sl_dist:
                            exit_price = entry - sl_dist
                            exit_reason = "STOP_LOSS"
                            break
                        if high >= entry + target_dist:
                            exit_price = entry + target_dist
                            exit_reason = "TARGET"
                            break
                    else:
                        if high >= entry + sl_dist:
                            exit_price = entry + sl_dist
                            exit_reason = "STOP_LOSS"
                            break
                        if low <= entry - target_dist:
                            exit_price = entry - target_dist
                            exit_reason = "TARGET"
                            break

                pnl_per_unit = (exit_price - entry) if direction == "BULLISH" else (entry - exit_price)
                lot_size = 50 if underlying == "NIFTY" else 15
                option_pnl = pnl_per_unit * 0.45 * lot_size

                trade = {
                    "trade_id": f"BT_SCALP_{underlying}_{date.strftime('%Y%m%d')}_{ei}",
                    "underlying": underlying,
                    "direction": direction,
                    "trade_type": "SCALP",
                    "entry_price": round(entry, 2),
                    "exit_price": round(exit_price, 2),
                    "pnl": round(option_pnl, 2),
                    "consensus_score": round(consensus_score, 3),
                    "entry_time": entry_bar.name.isoformat(),
                    "exit_time": window.iloc[-1].name.isoformat(),
                    "exit_reason": exit_reason,
                    "vix_at_entry": round(vix, 1),
                    "market_regime": self._get_vix_regime(vix),
                    "signals": signals,
                }
                trades.append(trade)

        return trades

    def _sanitize_numpy(self, val):
        """Convert numpy types to native Python types for DB storage."""
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        if isinstance(val, np.ndarray):
            return val.tolist()
        return val

    async def _store_backtest_lessons(self, trades: list[dict]):
        """Store backtested trades as lessons and update agent accuracy."""
        from learning.lesson_store import LessonStore

        store = LessonStore()
        stored = 0

        for trade in trades:
            pnl = trade["pnl"]
            outcome = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")

            signals = trade.get("signals", {})
            direction = trade["direction"]

            # Determine which agents were correct
            agents_correct = []
            agents_wrong = []
            for aid, sig in signals.items():
                if outcome == "WIN":
                    if sig["direction"] == direction:
                        agents_correct.append(aid)
                    elif sig["direction"] != "NEUTRAL":
                        agents_wrong.append(aid)
                else:
                    # Loss: agents who agreed with direction were wrong
                    if sig["direction"] == direction:
                        agents_wrong.append(aid)
                    elif sig["direction"] != "NEUTRAL":
                        agents_correct.append(aid)

            # Determine key factors based on exit reason
            key_factors = [trade["exit_reason"]]
            if trade["market_regime"] in ("ELEVATED", "HIGH"):
                key_factors.append("high_vix_environment")
            if trade["trade_type"] == "SCALP" and trade["exit_reason"] == "TIME_EXIT":
                key_factors.append("no_momentum")

            lesson = {
                "trade_id": trade["trade_id"],
                "outcome": outcome,
                "pnl": float(pnl),
                "market_regime": trade["market_regime"],
                "underlying": trade["underlying"],
                "trade_type": trade["trade_type"],
                "direction": direction,
                "vix_at_entry": self._sanitize_numpy(trade.get("vix_at_entry")),
                "consensus_score": self._sanitize_numpy(trade.get("consensus_score")),
                "agents_correct": agents_correct,
                "agents_wrong": agents_wrong,
                "agents_neutral": [],
                "why_won_or_lost": f"Backtest {outcome}: {trade['exit_reason']} in {trade['market_regime']} regime",
                "key_factors": key_factors,
                "what_to_repeat": f"Strong consensus in {trade['market_regime']} regime" if outcome == "WIN" else "",
                "what_to_avoid": f"{trade['exit_reason']} pattern in {trade['market_regime']}" if outcome == "LOSS" else "",
                "entry_time": trade.get("entry_time"),
                "exit_time": trade.get("exit_time"),
                "holding_duration_minutes": 0,
                "tags": ["backtest", trade["trade_type"].lower(), trade["market_regime"].lower()],
            }

            if store.store_lesson(lesson):
                stored += 1

                # Update agent accuracy
                for aid, sig in signals.items():
                    if sig["direction"] == "NEUTRAL":
                        continue
                    was_correct = aid in agents_correct
                    store.update_agent_accuracy(
                        agent_id=aid,
                        trade_type=trade["trade_type"],
                        market_regime=trade["market_regime"],
                        was_correct=was_correct,
                        confidence=float(sig["confidence"]),
                    )

        logger.info(f"Stored {stored}/{len(trades)} backtest lessons")


async def run_backtest_cli():
    """CLI entry point for running backtest."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    from dotenv import load_dotenv
    load_dotenv()

    bt = HistoricalBacktester()
    summary = await bt.run_backtest(months=6, store_lessons=True)

    print("\n" + "=" * 60)
    print("  BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Total trades: {summary['total_trades']}")
    print(f"  Wins: {summary['wins']} | Losses: {summary['losses']}")
    print(f"  Win rate: {summary['win_rate']:.0%}")
    print(f"  Total PnL: Rs.{summary['total_pnl']:,.0f}")
    print(f"  Avg PnL/trade: Rs.{summary['avg_pnl']:,.0f}")
    print()
    for tt, stats in summary.get("by_type", {}).items():
        print(f"  {tt}: {stats['trades']} trades, WR={stats['win_rate']:.0%}, Avg=Rs.{stats['avg_pnl']:,.0f}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_backtest_cli())
