"""Fyers REST quotes poller — reliable fallback for tick data.

Polls Fyers REST API every 2 seconds for NIFTY/BANKNIFTY/VIX quotes
and publishes them as ticks to Redis. This works even when the TBT
WebSocket fails to connect.
"""

import asyncio
import logging
from datetime import datetime

from data_pipeline.truedata_feed import TickData

logger = logging.getLogger("niftymind.fyers_quotes_poller")

# Fyers symbol -> our symbol name (must match frontend expectations)
_SYMBOL_MAP = {
    "NSE:NIFTY50-INDEX": "NIFTY 50",
    "NSE:NIFTYBANK-INDEX": "BANKNIFTY",
    "NSE:NIFTY26APRFUT": "NIFTY-FUT",
    "NSE:BANKNIFTY26APRFUT": "BANKNIFTY-FUT",
}

POLL_INTERVAL = 2  # seconds


async def start_quotes_poller(fyers_config, publisher, instruments, shutdown_event):
    """Poll Fyers REST API for quotes and publish as ticks."""
    if not fyers_config.app_id or not fyers_config.access_token:
        logger.warning("Fyers credentials not set — quotes poller disabled.")
        return

    # Wait for agents to subscribe first
    await asyncio.sleep(8)

    try:
        from fyers_apiv3 import fyersModel
    except ImportError:
        logger.error("fyers-apiv3 not installed")
        return

    fyers = fyersModel.FyersModel(
        client_id=fyers_config.app_id,
        token=fyers_config.access_token,
        is_async=False,
    )

    symbols = "NSE:NIFTY50-INDEX,NSE:NIFTYBANK-INDEX,NSE:NIFTY26APRFUT,NSE:BANKNIFTY26APRFUT"
    logger.info("Fyers quotes poller started (every %ds) for %s", POLL_INTERVAL, symbols)

    while not shutdown_event.is_set():
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None, lambda: fyers.quotes({"symbols": symbols})
            )

            if resp.get("s") != "ok" or "d" not in resp:
                logger.warning("Quotes API error: %s", resp.get("message", resp.get("s")))
                await asyncio.sleep(POLL_INTERVAL)
                continue

            for quote in resp["d"]:
                fyers_sym = quote.get("n", "")
                our_sym = _SYMBOL_MAP.get(fyers_sym, "")
                if not our_sym:
                    continue

                v = quote.get("v", {})
                ltp = float(v.get("lp", 0))
                if ltp <= 0:
                    continue

                prev_close = float(v.get("prev_close_price", 0))
                chp = round(((ltp - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0.0

                tick = TickData(
                    symbol=our_sym,
                    ltp=ltp,
                    bid=float(v.get("bid", 0)),
                    ask=float(v.get("ask", 0)),
                    bid_qty=0,
                    ask_qty=0,
                    volume=int(v.get("volume", 0)),
                    oi=0,
                    timestamp=datetime.now().isoformat(),
                    open=float(v.get("open_price", 0)),
                    high=float(v.get("high_price", 0)),
                    low=float(v.get("low_price", 0)),
                    close=prev_close,
                    change_pct=chp,
                )

                await publisher.publish_tick(tick)

        except Exception as e:
            logger.error("Quotes poller error: %s", e)

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=POLL_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass

    logger.info("Fyers quotes poller stopped")
