"""Fyers TBT (Tick-By-Tick) WebSocket feed for NFO futures data.

Connects to Fyers market data WebSocket, subscribes to NIFTY/BANKNIFTY
front-month futures and index symbols, and publishes to Redis.

Requires: pip install fyers-apiv3
Credentials: Set FYERS_APP_ID and FYERS_ACCESS_TOKEN env vars.
"""

import asyncio
import logging
import threading
from calendar import monthrange
from datetime import date, datetime, timedelta

from data_pipeline.truedata_feed import TickData, OHLCAggregator

logger = logging.getLogger("niftymind.fyers_tbt_feed")

_MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}


def _last_thursday(year: int, month: int) -> date:
    """Return the last Thursday of the given month (NSE expiry day)."""
    last_day = monthrange(year, month)[1]
    d = date(year, month, last_day)
    # weekday(): Monday=0, Thursday=3
    offset = (d.weekday() - 3) % 7
    return d - timedelta(days=offset)


def _front_month_expiry(ref: date | None = None) -> tuple[int, int]:
    """Return (year, month) for the front-month futures contract.

    Rolls to next month 2 calendar days before the last Thursday expiry.
    """
    today = ref or date.today()
    expiry = _last_thursday(today.year, today.month)
    if today >= expiry - timedelta(days=2):
        # Roll to next month
        if today.month == 12:
            return today.year + 1, 1
        return today.year, today.month + 1
    return today.year, today.month


def _fyers_futures_symbol(instrument: str) -> str:
    """Build Fyers futures symbol e.g. NSE:NIFTY25APRFUT."""
    year, month = _front_month_expiry()
    yy = str(year)[-2:]
    mmm = _MONTH_ABBR[month]
    base = instrument.upper()  # NIFTY or BANKNIFTY
    return f"NSE:{base}{yy}{mmm}FUT"


def _fyers_index_symbol(instrument: str) -> str:
    """Map instrument name to Fyers index symbol."""
    mapping = {
        "NIFTY": "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    }
    return mapping.get(instrument.upper(), f"NSE:{instrument.upper()}-INDEX")


def _our_symbol(fyers_sym: str) -> str:
    """Reverse-map a Fyers symbol to our internal symbol name."""
    if "NIFTYBANK" in fyers_sym or "BANKNIFTY" in fyers_sym:
        if "INDEX" in fyers_sym:
            return "BANKNIFTY"
        return "BANKNIFTY-FUT"
    if "NIFTY" in fyers_sym:
        if "INDEX" in fyers_sym:
            return "NIFTY"
        return "NIFTY-FUT"
    return fyers_sym


class FyersTbtFeed:
    """Streams TBT tick data from Fyers WebSocket and publishes to Redis."""

    def __init__(self, config, publisher):
        self.config = config
        self.publisher = publisher
        self._fyers_socket = None
        self._running = False
        # Holds latest quote fields (bid, ask, ohlc, etc.) keyed by our symbol
        self._last_quote: dict[str, dict] = {}
        # Aggregator is initialised in start() once we have the event loop
        self._aggregator: OHLCAggregator | None = None

    async def start(self, instruments: list[str], shutdown_event: asyncio.Event):
        """Start Fyers TBT feed. Runs WebSocket client in a background thread."""
        if not self.config.app_id or not self.config.access_token:
            logger.warning(
                "Fyers credentials not set. TBT feed disabled. "
                "Set FYERS_APP_ID and FYERS_ACCESS_TOKEN."
            )
            return

        try:
            from fyers_apiv3.FyersWebsocket import tbt_ws as fyersModel
        except ImportError:
            logger.error("fyers-apiv3 package not installed. Run: pip install fyers-apiv3")
            return

        # Build subscription symbols list
        fyers_symbols: list[str] = []
        for inst in instruments:
            fyers_symbols.append(_fyers_futures_symbol(inst))
            fyers_symbols.append(_fyers_index_symbol(inst))

        logger.info(f"Fyers TBT: subscribing to {fyers_symbols}")

        access_token = f"{self.config.app_id}:{self.config.access_token}"
        loop = asyncio.get_event_loop()
        self._aggregator = OHLCAggregator(self.publisher, loop)
        self._running = True

        def on_connect():
            logger.info("Fyers WebSocket connected")
            try:
                from fyers_apiv3.FyersWebsocket.tbt_ws import SubscriptionModes
                self._fyers_socket.subscribe(
                    symbol_tickers=set(fyers_symbols),
                    channelNo="1",
                    mode=SubscriptionModes.DEPTH,
                )
                logger.info("Fyers TBT subscription sent for %s", fyers_symbols)
            except Exception as exc:
                logger.error(f"Fyers subscribe error: {exc}")

        def on_close(code, reason):
            logger.info(f"Fyers WebSocket closed: {code} {reason}")

        def on_error(message):
            logger.error(f"Fyers WebSocket error: {message}")

        def on_message(msg):
            if not self._running:
                return
            self._handle_message(msg, loop)

        self._fyers_socket = fyersModel.FyersTbtSocket(
            access_token=access_token,
            write_to_file=False,
            on_open=on_connect,
            on_close=on_close,
            on_error=on_error,
            on_depth_update=on_message,
            reconnect=self.config.reconnect,
        )

        thread = threading.Thread(
            target=self._fyers_socket.connect,
            name="fyers-tbt-socket",
            daemon=True,
        )
        thread.start()
        logger.info("Fyers TBT WebSocket thread started")

        # Wait until shutdown
        await shutdown_event.wait()

        self._running = False
        try:
            self._fyers_socket.close_connection()
            logger.info("Fyers WebSocket connection closed")
        except Exception as exc:
            logger.debug(f"Fyers close_connection: {exc}")

    def _handle_message(self, msg: dict, loop: asyncio.AbstractEventLoop):
        """Parse Fyers WebSocket message and publish TickData to Redis."""
        try:
            if not isinstance(msg, dict):
                return

            msg_type = msg.get("type", "")
            sym = msg.get("symbol", "")
            our_sym = _our_symbol(sym) if sym else ""

            # Quote / depth update (type "sf") — update cached quote fields
            if msg_type == "sf":
                if our_sym not in self._last_quote:
                    self._last_quote[our_sym] = {}
                q = self._last_quote[our_sym]
                q["bid"] = float(msg.get("bid_price", msg.get("bidPrice", q.get("bid", 0))))
                q["ask"] = float(msg.get("ask_price", msg.get("askPrice", q.get("ask", 0))))
                q["bid_qty"] = int(msg.get("bid_qty", msg.get("bidQty", q.get("bid_qty", 0))))
                q["ask_qty"] = int(msg.get("ask_qty", msg.get("askQty", q.get("ask_qty", 0))))
                q["open"] = float(msg.get("open_price", msg.get("openPrice", msg.get("open", q.get("open", 0)))))
                q["high"] = float(msg.get("high_price", msg.get("highPrice", msg.get("high", q.get("high", 0)))))
                q["low"] = float(msg.get("low_price", msg.get("lowPrice", msg.get("low", q.get("low", 0)))))
                q["close"] = float(msg.get("prev_close_price", msg.get("prevClosePrice", msg.get("close", q.get("close", 0)))))
                q["oi"] = int(msg.get("oi", msg.get("openInterest", q.get("oi", 0))))
                q["volume"] = int(msg.get("vol_traded_today", msg.get("volTradedToday", msg.get("volume", q.get("volume", 0)))))
                return

            # Trade tick update (type "tf" or "SymbolUpdate")
            if msg_type in ("tf", "SymbolUpdate") or "ltp" in msg or "trade_price" in msg:
                if not our_sym:
                    return

                ltp = float(msg.get("ltp", msg.get("trade_price", 0)))
                if ltp <= 0:
                    return

                q = self._last_quote.get(our_sym, {})

                # Timestamp
                ts_raw = msg.get("exchange_feed_time", msg.get("exchangeFeedTime", 0))
                if ts_raw:
                    try:
                        timestamp = datetime.fromtimestamp(int(ts_raw)).isoformat()
                    except Exception:
                        timestamp = datetime.now().isoformat()
                else:
                    timestamp = datetime.now().isoformat()

                tick = TickData(
                    symbol=our_sym,
                    ltp=ltp,
                    bid=float(q.get("bid", 0)),
                    ask=float(q.get("ask", 0)),
                    bid_qty=int(q.get("bid_qty", 0)),
                    ask_qty=int(q.get("ask_qty", 0)),
                    volume=int(q.get("volume", msg.get("vol_traded_today", msg.get("volume", 0)))),
                    oi=int(q.get("oi", msg.get("oi", 0))),
                    timestamp=timestamp,
                    open=float(q.get("open", 0)),
                    high=float(q.get("high", 0)),
                    low=float(q.get("low", 0)),
                    close=float(q.get("close", 0)),
                )

                asyncio.run_coroutine_threadsafe(
                    self.publisher.publish_tick(tick), loop
                )

                if self._aggregator is not None:
                    self._aggregator.on_tick(
                        tick.symbol, tick.ltp, tick.volume, tick.oi, datetime.now()
                    )

        except Exception as exc:
            logger.warning(f"Fyers message parse error: {exc}")
