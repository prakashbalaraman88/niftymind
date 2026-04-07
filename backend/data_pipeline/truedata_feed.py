"""TrueData tick feed using official truedata Python library (v7+).

Connects to TrueData Market Data API, subscribes to NIFTY/BANKNIFTY tick data
with bid-ask quotes, and publishes to Redis for all agents to consume.

Publishes:
  - niftymind:ticks      — every tick (1-second aggregated from TrueData)
  - niftymind:ohlc:1m    — 1-minute OHLC bars (on bar close)
  - niftymind:ohlc:5m    — 5-minute OHLC bars
  - niftymind:ohlc:15m   — 15-minute OHLC bars

Options chain is handled separately by options_chain_feed.py.

Requires: pip install truedata
Credentials: Set TRUEDATA_USERNAME and TRUEDATA_PASSWORD env vars.
"""

import asyncio
import logging
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger("niftymind.truedata_feed")

# Bar timeframes: label -> minutes
_TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15}


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
    change_pct: float = 0.0


@dataclass
class OHLCBar:
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int
    bar_time: str  # ISO timestamp of bar open


class _BarState:
    """Mutable accumulator for a single symbol+timeframe bar."""

    __slots__ = ("open", "high", "low", "close", "volume", "oi", "bar_ts")

    def __init__(self, ltp: float, volume: int, oi: int, bar_ts: datetime):
        self.open = ltp
        self.high = ltp
        self.low = ltp
        self.close = ltp
        self.volume = volume
        self.oi = oi
        self.bar_ts = bar_ts

    def update(self, ltp: float, volume: int, oi: int) -> None:
        if ltp > self.high:
            self.high = ltp
        if ltp < self.low:
            self.low = ltp
        self.close = ltp
        self.volume = volume  # TrueData volume is cumulative intraday; keep latest
        self.oi = oi


def _bar_open_time(ts: datetime, minutes: int) -> datetime:
    """Floor a datetime to the nearest bar boundary (minute-aligned)."""
    floored = (ts.minute // minutes) * minutes
    return ts.replace(minute=floored, second=0, microsecond=0)


class OHLCAggregator:
    """Aggregates ticks into 1m/5m/15m OHLC bars and publishes closed bars."""

    def __init__(self, publisher, loop: asyncio.AbstractEventLoop):
        self._publisher = publisher
        self._loop = loop
        self._bars: dict[tuple[str, str], _BarState] = {}

    def on_tick(self, symbol: str, ltp: float, volume: int, oi: int, ts: datetime) -> None:
        for tf, minutes in _TIMEFRAMES.items():
            bar_ts = _bar_open_time(ts, minutes)
            key = (symbol, tf)
            state = self._bars.get(key)

            if state is None:
                self._bars[key] = _BarState(ltp, volume, oi, bar_ts)
            elif bar_ts > state.bar_ts:
                # Bar closed — publish and open new one
                closed = OHLCBar(
                    symbol=symbol,
                    timeframe=tf,
                    open=state.open,
                    high=state.high,
                    low=state.low,
                    close=state.close,
                    volume=state.volume,
                    oi=state.oi,
                    bar_time=state.bar_ts.isoformat(),
                )
                asyncio.run_coroutine_threadsafe(
                    self._publisher.publish_ohlc(tf, asdict(closed)),
                    self._loop,
                )
                logger.debug(
                    "Bar closed [%s] %s: O=%.2f H=%.2f L=%.2f C=%.2f",
                    tf, symbol, closed.open, closed.high, closed.low, closed.close,
                )
                self._bars[key] = _BarState(ltp, volume, oi, bar_ts)
            else:
                state.update(ltp, volume, oi)


class TrueDataFeed:
    """Connects to TrueData Market Data API and streams tick data to Redis."""

    def __init__(self, config, publisher):
        self.config = config
        self.publisher = publisher
        self._td = None
        self._running = False
        self._symbols_map: dict[str, str] = {}  # TrueData symbol -> our symbol

    async def start(self, instruments: list[str], shutdown_event: asyncio.Event):
        """Start tick feed. Connects in foreground; callbacks fire on TrueData threads."""
        if not self.config.username or not self.config.password:
            logger.warning(
                "TrueData credentials not set — tick feed disabled. "
                "Set TRUEDATA_USERNAME and TRUEDATA_PASSWORD."
            )
            return

        try:
            from truedata import TD_live
        except ImportError:
            logger.error("truedata package not installed. Run: pip install truedata")
            return

        # Build symbol maps once
        td_symbols = self._build_symbol_map(instruments)

        loop = asyncio.get_event_loop()
        aggregator = OHLCAggregator(self.publisher, loop)

        attempt = 0
        delay = self.config.reconnect_delay

        while not shutdown_event.is_set():
            if attempt >= self.config.max_reconnect_attempts:
                logger.error(
                    "TrueData: exceeded %d reconnect attempts — feed stopped.",
                    self.config.max_reconnect_attempts,
                )
                return

            logger.info(
                "Connecting to TrueData as '%s' (attempt %d)...",
                self.config.username, attempt + 1,
            )

            try:
                # TD_live() blocks on WebSocket handshake — run in thread to avoid
                # blocking the event loop (which would fail the Railway health check).
                # Timeout prevents the thread from retrying forever on auth errors.
                self._td = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, lambda: TD_live(self.config.username, self.config.password, url="push.truedata.in")
                    ),
                    timeout=30.0,
                )
                logger.info("TrueData connection established")
            except Exception as exc:
                logger.error("TrueData connection failed: %s — retrying in %.0fs", exc, delay)
                attempt += 1
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=delay)
                    return
                except asyncio.TimeoutError:
                    delay = min(delay * 2, 60.0)
                    continue

            # Successful connect — reset backoff
            attempt = 0
            delay = self.config.reconnect_delay
            self._running = True

            # Capture locals for closures
            td_ref = self._td

            @td_ref.trade_callback
            def on_trade(symbol_id, tick_data):
                if not self._running:
                    return
                try:
                    tick = self._parse_live_tick(symbol_id, tick_data)
                    if tick is None:
                        return
                    asyncio.run_coroutine_threadsafe(
                        self.publisher.publish_tick(tick), loop
                    )
                    raw_ts = getattr(tick_data, "timestamp", None)
                    try:
                        ts = datetime.fromisoformat(str(raw_ts)) if raw_ts else datetime.now()
                    except ValueError:
                        ts = datetime.now()
                    aggregator.on_tick(tick.symbol, tick.ltp, tick.volume, tick.oi, ts)
                except Exception as exc:
                    logger.error("Error in trade callback: %s", exc)

            @td_ref.bidask_callback
            def on_bidask(symbol_id, tick_data):
                pass  # bid/ask already read from live_data in on_trade

            try:
                await loop.run_in_executor(
                    None, lambda: self._td.start_live_data(td_symbols)
                )
                logger.info("Subscribed to TrueData tick feed: %s", td_symbols)
            except Exception as exc:
                logger.error("Failed to subscribe: %s", exc)
                self._running = False
                self._disconnect()
                attempt += 1
                continue

            # Hold here until shutdown or detected disconnect
            while not shutdown_event.is_set():
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue

            self._running = False
            self._disconnect()
            return  # clean shutdown

    def _build_symbol_map(self, instruments: list[str]) -> list[str]:
        """Populate _symbols_map and return list of TrueData symbol strings."""
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
        return td_symbols

    def _disconnect(self) -> None:
        try:
            if self._td:
                self._td.disconnect()
                logger.info("TrueData disconnected")
        except Exception:
            pass
        self._td = None

    def _parse_live_tick(self, symbol_id, tick_data) -> TickData | None:
        """Parse a TrueData trade callback into our TickData format."""
        try:
            symbol_name = getattr(tick_data, "symbol", str(symbol_id))
            our_symbol = self._symbols_map.get(symbol_name, symbol_name)

            live = self._td.live_data.get(symbol_name) if self._td else None
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
        except Exception as exc:
            logger.warning("Failed to parse tick: %s", exc)
            return None

    async def startup_warmup(self, instruments: list[str]) -> None:
        """Publish historical OHLC bars so agents have full buffers from first tick.

        Uses TD_hist to fetch the last 5 days of 1m/5m/15m bars and publishes
        them to the OHLC Redis channels.  Agents receive these if they are
        already subscribed (i.e., call this after a brief startup delay).

        Outside market hours agents sleep and won't process the messages —
        that is acceptable since warmup is only meaningful when market is open.
        """
        if not self.config.username or not self.config.password:
            logger.warning("Warmup skipped: no TrueData credentials")
            return

        try:
            from truedata import TD_hist
        except ImportError:
            logger.error("truedata package not installed — warmup skipped")
            return

        # TrueData uses continuous-futures symbols for historical bar data
        td_symbol_map = {"NIFTY": "NIFTY-I", "BANKNIFTY": "BANKNIFTY-I"}
        # label → TD bar_size string
        timeframes = [("1m", "1 min"), ("5m", "5 min"), ("15m", "15 min")]
        duration = "5 D"   # trial gives 15 days; 5 days is enough for 200-bar buffers

        logger.info("Historical warmup starting (fetching %s of bars)...", duration)

        for instrument in instruments:
            td_symbol = td_symbol_map.get(instrument, instrument)
            td_hist = None
            try:
                td_hist = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: TD_hist(self.config.username, self.config.password)
                )
            except Exception as exc:
                logger.error("Warmup: TD_hist connection failed: %s", exc)
                continue

            for tf_label, bar_size in timeframes:
                try:
                    df = td_hist.get_historic_data(
                        td_symbol, duration=duration, bar_size=bar_size
                    )
                    if df is None or len(df) == 0:
                        logger.warning("Warmup: no data for %s %s", td_symbol, tf_label)
                        continue

                    # Keep only the most recent bars needed to fill the agent buffer
                    df = df.tail(200)

                    for ts, row in df.iterrows():
                        bar = {
                            "symbol": instrument,
                            "timeframe": tf_label,
                            "open": float(row.get("open", 0) or 0),
                            "high": float(row.get("high", 0) or 0),
                            "low": float(row.get("low", 0) or 0),
                            "close": float(row.get("close", 0) or 0),
                            "volume": int(row.get("volume", 0) or 0),
                            "oi": int(row.get("oi", 0) or 0),
                            "bar_time": str(ts),
                            "historical": True,
                        }
                        await self.publisher.publish_ohlc(tf_label, bar)
                        await asyncio.sleep(0)  # yield so event loop can drain queues

                    logger.info(
                        "Warmup: %d %s bars published for %s",
                        len(df), tf_label, instrument,
                    )
                except Exception as exc:
                    logger.warning("Warmup failed for %s %s: %s", td_symbol, tf_label, exc)

            try:
                td_hist.disconnect()
            except Exception:
                pass

        logger.info("Historical warmup complete")

    async def get_historical_data(self, symbol: str, duration: str = "1 D", bar_size: str = "5 min"):
        """Fetch historical OHLCV data as pandas DataFrame (for agent warmup)."""
        try:
            from truedata import TD_hist
        except ImportError:
            logger.error("truedata package not installed")
            return None

        try:
            loop = asyncio.get_event_loop()
            td_hist = await loop.run_in_executor(
                None, lambda: TD_hist(self.config.username, self.config.password)
            )
            df = await loop.run_in_executor(
                None, lambda: td_hist.get_historic_data(symbol, duration=duration, bar_size=bar_size)
            )
            td_hist.disconnect()
            return df
        except Exception as exc:
            logger.error("Historical data fetch failed for %s: %s", symbol, exc)
            return None
