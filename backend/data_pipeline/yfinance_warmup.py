"""yfinance fallback historical warmup for OHLC agent buffers.

Used when TrueData credentials are unavailable. Downloads 5 days of
1m/5m/15m OHLC bars for NIFTY and BANKNIFTY from Yahoo Finance and
publishes them to Redis in the same format as TrueDataFeed.startup_warmup().
"""

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger("niftymind.yfinance_warmup")

# Yahoo Finance tickers → internal symbol names
_TICKER_MAP = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

# yfinance interval strings
_YF_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m"}


def _resample_to_tf(df_1m: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample 1m bars to 5m or 15m; return 1m as-is."""
    if tf == "1m":
        return df_1m
    rule = tf  # "5m" or "15m" — pandas resample rule
    ohlcv = df_1m.resample(rule, origin="start_day").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    ).dropna()
    return ohlcv


async def yfinance_warmup(publisher, instruments: list[str]) -> None:
    """Download 5 days of OHLC bars via yfinance and publish to Redis."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed — fallback warmup skipped")
        return

    logger.info("yfinance fallback warmup starting for %s", instruments)

    for instrument in instruments:
        ticker_sym = _TICKER_MAP.get(instrument.upper())
        if not ticker_sym:
            logger.warning("No yfinance ticker for %s — skipping", instrument)
            continue

        try:
            # Download 5 trading days of 1m data (max allowed by yfinance for 1m)
            df_raw = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda sym=ticker_sym: yf.download(
                    sym, period="5d", interval="1m", progress=False, auto_adjust=True
                ),
            )

            if df_raw.empty:
                logger.warning("yfinance returned no data for %s", ticker_sym)
                continue

            # Flatten multi-level columns if present
            if isinstance(df_raw.columns, pd.MultiIndex):
                df_raw.columns = df_raw.columns.get_level_values(0)

            # Ensure timezone-aware index
            if df_raw.index.tz is None:
                df_raw.index = df_raw.index.tz_localize("UTC")

            bar_count = 0
            for tf in ("1m", "5m", "15m"):
                df = _resample_to_tf(df_raw, tf)

                for bar_time, row in df.iterrows():
                    bar = {
                        "symbol": instrument.upper(),
                        "timeframe": tf,
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row.get("Volume", 0)),
                        "oi": 0,
                        "bar_time": bar_time.isoformat(),
                        "historical": True,
                    }
                    await publisher.publish_ohlc(tf, bar)
                    bar_count += 1

                # Small yield to avoid blocking event loop
                await asyncio.sleep(0)

            logger.info(
                "yfinance warmup: %s — published %d bars (1m/5m/15m)", instrument, bar_count
            )

        except Exception as exc:
            logger.error("yfinance warmup error for %s: %s", instrument, exc)

    logger.info("yfinance fallback warmup complete")
