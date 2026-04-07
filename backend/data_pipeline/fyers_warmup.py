"""Fyers historical OHLC warmup — fetches 1m candles and resamples to 5m/15m.

Called at startup when TrueData credentials are unavailable, so agents have
pre-filled OHLC buffers from the first tick.

Requires: pip install fyers-apiv3 pandas
"""

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("niftymind.fyers_warmup")

_FYERS_SYMBOL = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
}

# How many calendar days back to fetch
_LOOKBACK_DAYS = 5


async def fyers_warmup(fyers_config, publisher, instruments: list[str]) -> None:
    """Fetch 1m candles from Fyers, resample to 5m/15m, publish as historical bars."""
    if not fyers_config.app_id or not fyers_config.access_token:
        logger.warning("Fyers credentials not set — warmup skipped.")
        return

    try:
        from fyers_apiv3 import fyersModel
    except ImportError:
        logger.error("fyers-apiv3 not installed — warmup skipped. Run: pip install fyers-apiv3")
        return

    try:
        import pandas as pd
    except ImportError:
        logger.error("pandas not installed — warmup skipped. Run: pip install pandas")
        return

    fyers = fyersModel.FyersModel(
        client_id=fyers_config.app_id,
        token=fyers_config.access_token,
        log_path="",
    )

    loop = asyncio.get_event_loop()
    today = datetime.now().date()
    range_from = (today - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    range_to = today.strftime("%Y-%m-%d")

    logger.info(
        "Fyers warmup: fetching 1m candles %s → %s for %s",
        range_from, range_to, instruments,
    )

    for instrument in instruments:
        fyers_sym = _FYERS_SYMBOL.get(instrument.upper())
        if not fyers_sym:
            logger.warning("No Fyers symbol mapping for %s — skipping warmup", instrument)
            continue

        try:
            resp = await loop.run_in_executor(
                None,
                lambda sym=fyers_sym: fyers.history(
                    {
                        "symbol": sym,
                        "resolution": "1",
                        "date_format": "1",
                        "range_from": range_from,
                        "range_to": range_to,
                        "cont_flag": "1",
                    }
                ),
            )
        except Exception as exc:
            logger.error("Fyers history fetch failed for %s: %s", instrument, exc)
            continue

        candles = resp.get("candles", []) if isinstance(resp, dict) else []
        if not candles:
            logger.warning("No 1m candles returned for %s: %s", instrument, resp)
            continue

        # Build DataFrame from [[epoch, o, h, l, c, v], ...]
        df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="s")
        df = df.set_index("ts").sort_index()

        # OI is not available from Fyers history — default to 0
        df["oi"] = 0

        total_published = 0

        for tf_label, rule in [("1m", "1min"), ("5m", "5min"), ("15m", "15min")]:
            if rule == "1min":
                resampled = df.copy()
            else:
                resampled = df.resample(rule, closed="left", label="left").agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                        "oi": "last",
                    }
                ).dropna(subset=["open"])

            # Keep most recent 200 bars
            resampled = resampled.tail(200)

            for bar_ts, row in resampled.iterrows():
                bar = {
                    "symbol": instrument,
                    "timeframe": tf_label,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                    "oi": int(row["oi"]),
                    "bar_time": bar_ts.isoformat(),
                    "historical": True,
                }
                await publisher.publish_ohlc(tf_label, bar)
                await asyncio.sleep(0)  # yield to event loop
                total_published += 1

            logger.info(
                "Warmup: %d %s bars published for %s",
                len(resampled), tf_label, instrument,
            )

        logger.info(
            "Fyers warmup complete for %s: %d total bars published",
            instrument, total_published,
        )

    logger.info("Fyers warmup finished for all instruments")
