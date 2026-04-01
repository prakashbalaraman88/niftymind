"""TrueData tick feed using official truedata Python library (v7+).

Connects to TrueData Market Data API, subscribes to NIFTY/BANKNIFTY tick data
with bid-ask quotes, and publishes to Redis for all agents to consume.

Requires: pip install truedata
Credentials: Set TRUEDATA_USERNAME and TRUEDATA_PASSWORD env vars.
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger("niftymind.truedata_feed")


@dataclass
class TickData:
    symbol: str
    ltp: float
    bid: float
    ask: float
    bid_qty: int
    ask_qty: int
    volume: int
    oi: int
    timestamp: str
    open: float
    high: float
    low: float
    close: float


class TrueDataFeed:
    """Connects to TrueData Market Data API and streams tick data to Redis."""

    def __init__(self, config, publisher):
        self.config = config
        self.publisher = publisher
        self._td = None
        self._running = False
        self._symbols_map: dict[str, str] = {}  # TrueData symbol -> our symbol

    async def start(self, instruments: list[str], shutdown_event: asyncio.Event):
        """Start tick feed. Runs TrueData client in a background thread."""
        if not self.config.username or not self.config.password:
            logger.warning("TrueData credentials not set. Tick feed disabled. Set TRUEDATA_USERNAME and TRUEDATA_PASSWORD.")
            return

        try:
            from truedata import TD_live
        except ImportError:
            logger.error("truedata package not installed. Run: pip install truedata")
            return

        self._running = True
        loop = asyncio.get_event_loop()

        # Map instruments to TrueData symbols
        # NIFTY -> "NIFTY 50", BANKNIFTY -> "NIFTY BANK"
        # Futures: NIFTY-I (current month), BANKNIFTY-I
        td_symbols = []
        for inst in instruments:
            if inst == "NIFTY":
                td_symbols.extend(["NIFTY 50", "NIFTY-I"])
                self._symbols_map["NIFTY 50"] = "NIFTY"
                self._symbols_map["NIFTY-I"] = "NIFTY-FUT"
            elif inst == "BANKNIFTY":
                td_symbols.extend(["NIFTY BANK", "BANKNIFTY-I"])
                self._symbols_map["NIFTY BANK"] = "BANKNIFTY"
                self._symbols_map["BANKNIFTY-I"] = "BANKNIFTY-FUT"
            else:
                td_symbols.append(inst)
                self._symbols_map[inst] = inst

        logger.info(f"Connecting to TrueData as '{self.config.username}'...")

        try:
            self._td = TD_live(self.config.username, self.config.password)
            logger.info("TrueData connection established")
        except Exception as e:
            logger.error(f"TrueData connection failed: {e}")
            return

        # Register callbacks
        @self._td.trade_callback
        def on_trade(symbol_id, tick_data):
            if not self._running:
                return
            try:
                tick = self._parse_live_tick(symbol_id, tick_data)
                if tick:
                    asyncio.run_coroutine_threadsafe(
                        self.publisher.publish_tick(tick), loop
                    )
            except Exception as e:
                logger.error(f"Error in trade callback: {e}")

        @self._td.bidask_callback
        def on_bidask(symbol_id, tick_data):
            if not self._running:
                return
            try:
                # Bid-ask updates are handled via live_data dict
                # The trade callback already reads bid/ask from there
                pass
            except Exception as e:
                logger.error(f"Error in bidask callback: {e}")

        # Subscribe
        try:
            self._td.start_live_data(td_symbols)
            logger.info(f"Subscribed to tick data: {td_symbols}")
        except Exception as e:
            logger.error(f"Failed to subscribe: {e}")
            return

        # Keep running until shutdown
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

        self._running = False
        try:
            self._td.disconnect()
            logger.info("TrueData disconnected")
        except Exception:
            pass

    def _parse_live_tick(self, symbol_id, tick_data) -> TickData | None:
        """Parse tick from TrueData callback into our TickData format."""
        try:
            # TrueData tick_data attributes: ltp, volume, oi, timestamp, open, high, low, close
            # Bid/ask come from live_data dict
            symbol_name = getattr(tick_data, "symbol", str(symbol_id))
            our_symbol = self._symbols_map.get(symbol_name, symbol_name)

            # Get bid/ask from live_data
            live = self._td.live_data.get(symbol_name)
            bid = getattr(live, "bid", 0) if live else 0
            ask = getattr(live, "ask", 0) if live else 0
            bid_qty = getattr(live, "bid_qty", 0) if live else 0
            ask_qty = getattr(live, "ask_qty", 0) if live else 0

            return TickData(
                symbol=our_symbol,
                ltp=float(getattr(tick_data, "ltp", 0)),
                bid=float(bid),
                ask=float(ask),
                bid_qty=int(bid_qty),
                ask_qty=int(ask_qty),
                volume=int(getattr(tick_data, "volume", 0)),
                oi=int(getattr(tick_data, "oi", 0)),
                timestamp=str(getattr(tick_data, "timestamp", datetime.now().isoformat())),
                open=float(getattr(tick_data, "open", 0)),
                high=float(getattr(tick_data, "high", 0)),
                low=float(getattr(tick_data, "low", 0)),
                close=float(getattr(tick_data, "close", 0)),
            )
        except Exception as e:
            logger.warning(f"Failed to parse tick: {e}")
            return None

    async def get_historical_data(self, symbol: str, duration: str = "1 D", bar_size: str = "5 min"):
        """Fetch historical OHLCV data as pandas DataFrame (for technical agent warmup)."""
        try:
            from truedata import TD_hist
        except ImportError:
            logger.error("truedata package not installed")
            return None

        try:
            td_hist = TD_hist(self.config.username, self.config.password)
            df = td_hist.get_historic_data(symbol, duration=duration, bar_size=bar_size)
            td_hist.disconnect()
            return df
        except Exception as e:
            logger.error(f"Historical data fetch failed for {symbol}: {e}")
            return None
