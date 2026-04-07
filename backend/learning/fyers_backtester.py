"""Fyers-data backtester: fetches real NSE candles via Fyers REST API
and runs the same agent simulation as HistoricalBacktester.

Data sources:
  - Fyers REST API  → NIFTY/BANKNIFTY 5m & daily candles (primary)
  - Yahoo Finance   → India VIX daily (^INDIAVIX), and fallback for older OHLC

Fyers resolution limits (approximate):
  - 1m  : ~100 days
  - 5m  : ~100 days
  - Daily: years

Usage:
    bt = FyersBacktester(fyers_config, llm_config)
    summary = await bt.run_backtest(months=4, store_lessons=True)
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from learning.historical_backtester import HistoricalBacktester

logger = logging.getLogger("niftymind.learning.fyers_backtester")

IST = timezone(timedelta(hours=5, minutes=30))

# Fyers symbol map for index candles
_FYERS_SYMBOL = {
    "NIFTY":     "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
}

# Yahoo Finance tickers (VIX + fallback)
_YF_SYMBOL = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "VIX":       "^INDIAVIX",
}

_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _fyers_to_df(candles: list[list]) -> pd.DataFrame:
    """Convert Fyers candle list [[epoch, o, h, l, c, v], ...] to DataFrame."""
    df = pd.DataFrame(candles, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    df = df.set_index("ts").sort_index()
    return df


def _fetch_fyers_candles(fyers_model, symbol: str, resolution: str,
                          range_from: str, range_to: str) -> pd.DataFrame:
    """Synchronous Fyers REST call — run in executor."""
    try:
        resp = fyers_model.history({
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "1",
        })
        candles = resp.get("candles", []) if isinstance(resp, dict) else []
        if not candles:
            logger.warning("Fyers returned no candles for %s res=%s: %s", symbol, resolution, resp)
            return pd.DataFrame()
        df = _fyers_to_df(candles)
        logger.info("Fyers %s (%s): %d bars", symbol, resolution, len(df))
        return df
    except Exception as exc:
        logger.error("Fyers history error for %s: %s", symbol, exc)
        return pd.DataFrame()


def _fetch_yf_fallback(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
    """yfinance fallback for VIX and when Fyers data is unavailable."""
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as exc:
        logger.warning("yfinance fallback failed for %s: %s", ticker, exc)
        return pd.DataFrame()


class FyersBacktester(HistoricalBacktester):
    """Same simulation logic as HistoricalBacktester, but uses Fyers REST data."""

    def __init__(self, fyers_config, llm_config=None):
        super().__init__(llm_config=llm_config)
        self.fyers_config = fyers_config
        self._fyers = None

    def _init_fyers(self):
        if self._fyers is not None:
            return True
        if not self.fyers_config.app_id or not self.fyers_config.access_token:
            logger.warning("Fyers credentials missing — will use Yahoo Finance fallback")
            return False
        try:
            from fyers_apiv3 import fyersModel
            token = f"{self.fyers_config.app_id}:{self.fyers_config.access_token}"
            self._fyers = fyersModel.FyersModel(
                client_id=self.fyers_config.app_id,
                token=token,
                log_path="",
            )
            logger.info("Fyers REST client initialised (app_id=%s)", self.fyers_config.app_id)
            return True
        except ImportError:
            logger.error("fyers-apiv3 not installed — falling back to Yahoo Finance")
            return False

    async def run_backtest(
        self,
        months: int = 4,
        trade_types: list[str] | None = None,
        underlyings: list[str] | None = None,
        store_lessons: bool = True,
    ) -> dict:
        if trade_types is None:
            trade_types = ["SCALP", "INTRADAY", "BTST"]
        if underlyings is None:
            underlyings = ["NIFTY", "BANKNIFTY"]

        fyers_ok = self._init_fyers()
        loop = asyncio.get_event_loop()

        end_date   = datetime.now()
        start_date = end_date - timedelta(days=months * 31)
        # Fyers intraday limit: ~100 days; yfinance 5m limit: 60 days
        # Use 55 days so yfinance fallback always works
        intraday_start = end_date - timedelta(days=55)

        range_from_daily    = start_date.strftime("%Y-%m-%d")
        range_from_intraday = intraday_start.strftime("%Y-%m-%d")
        range_to            = end_date.strftime("%Y-%m-%d")

        logger.info(
            "FyersBacktester: %d months, %s, data_source=%s",
            months, underlyings, "Fyers" if fyers_ok else "Yahoo Finance",
        )

        # Fetch India VIX via yfinance (Fyers doesn't expose historical VIX)
        logger.info("Fetching India VIX from Yahoo Finance...")
        vix_data = await loop.run_in_executor(
            _EXECUTOR,
            lambda: _fetch_yf_fallback(
                _YF_SYMBOL["VIX"], range_from_daily, range_to, "1d"
            ),
        )

        all_trades = []

        for underlying in underlyings:
            fyers_sym = _FYERS_SYMBOL.get(underlying)
            yf_sym    = _YF_SYMBOL.get(underlying)

            # ── Daily data (for BTST) ──────────────────────────────────────
            if fyers_ok and fyers_sym:
                daily = await loop.run_in_executor(
                    _EXECUTOR,
                    lambda s=fyers_sym: _fetch_fyers_candles(
                        self._fyers, s, "D", range_from_daily, range_to
                    ),
                )
            else:
                daily = pd.DataFrame()

            if daily.empty and yf_sym:
                logger.info("%s: Fyers daily empty, falling back to yfinance", underlying)
                daily = await loop.run_in_executor(
                    _EXECUTOR,
                    lambda t=yf_sym: _fetch_yf_fallback(t, range_from_daily, range_to, "1d"),
                )

            # ── 5-min data (for INTRADAY + SCALP) ─────────────────────────
            if fyers_ok and fyers_sym:
                intraday = await loop.run_in_executor(
                    _EXECUTOR,
                    lambda s=fyers_sym: _fetch_fyers_candles(
                        self._fyers, s, "5", range_from_intraday, range_to
                    ),
                )
            else:
                intraday = pd.DataFrame()

            if intraday.empty and yf_sym:
                logger.info("%s: Fyers 5m empty, falling back to yfinance", underlying)
                intraday = await loop.run_in_executor(
                    _EXECUTOR,
                    lambda t=yf_sym: _fetch_yf_fallback(t, range_from_intraday, range_to, "5m"),
                )

            if not isinstance(daily.index, pd.DatetimeIndex):
                daily = pd.DataFrame()
            if not isinstance(intraday.index, pd.DatetimeIndex):
                intraday = pd.DataFrame()

            # Make columns consistent (Fyers uses Open/High/Low/Close/Volume already)
            for df_ in [daily, intraday]:
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col not in df_.columns and col.lower() in df_.columns:
                        df_.rename(columns={col.lower(): col}, inplace=True)

            logger.info(
                "%s: %d daily bars, %d 5m bars",
                underlying, len(daily), len(intraday),
            )

            if "BTST" in trade_types and len(daily) > 30:
                btst = self._backtest_btst(underlying, daily, vix_data)
                all_trades.extend(btst)
                logger.info("  BTST: %d trades", len(btst))

            if "INTRADAY" in trade_types and len(intraday) > 100:
                intra = self._backtest_intraday(underlying, intraday, vix_data)
                all_trades.extend(intra)
                logger.info("  INTRADAY: %d trades", len(intra))

            if "SCALP" in trade_types and len(intraday) > 100:
                scalp = self._backtest_scalp(underlying, intraday, vix_data)
                all_trades.extend(scalp)
                logger.info("  SCALP: %d trades", len(scalp))

        logger.info("Total Fyers-backtested trades: %d", len(all_trades))

        if store_lessons and all_trades:
            await self._store_backtest_lessons(all_trades)

        wins   = sum(1 for t in all_trades if t["pnl"] > 0)
        losses = sum(1 for t in all_trades if t["pnl"] <= 0)
        total_pnl = sum(t["pnl"] for t in all_trades)

        summary = {
            "total_trades": len(all_trades),
            "wins":         wins,
            "losses":       losses,
            "win_rate":     wins / len(all_trades) if all_trades else 0,
            "total_pnl":    round(total_pnl, 2),
            "avg_pnl":      round(total_pnl / len(all_trades), 2) if all_trades else 0,
            "data_source":  "Fyers REST" if fyers_ok else "Yahoo Finance",
            "by_type":      {},
            "by_underlying": {},
        }

        for tt in trade_types:
            tt_trades = [t for t in all_trades if t["trade_type"] == tt]
            if tt_trades:
                tt_wins = sum(1 for t in tt_trades if t["pnl"] > 0)
                summary["by_type"][tt] = {
                    "trades":   len(tt_trades),
                    "win_rate": round(tt_wins / len(tt_trades), 2),
                    "avg_pnl":  round(sum(t["pnl"] for t in tt_trades) / len(tt_trades), 2),
                }

        for ul in underlyings:
            ul_trades = [t for t in all_trades if t["underlying"] == ul]
            if ul_trades:
                ul_wins = sum(1 for t in ul_trades if t["pnl"] > 0)
                summary["by_underlying"][ul] = {
                    "trades":   len(ul_trades),
                    "win_rate": round(ul_wins / len(ul_trades), 2),
                }

        logger.info(
            "Fyers backtest complete: %d trades, WR=%.0f%%, PnL=Rs.%.0f [%s]",
            summary["total_trades"], summary["win_rate"] * 100,
            summary["total_pnl"], summary["data_source"],
        )
        return summary
