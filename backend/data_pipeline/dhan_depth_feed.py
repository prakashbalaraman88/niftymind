"""Dhan market depth feed using dhanhq WebSocket.

Subscribes to NIFTY/BANKNIFTY Full packet (200-depth equivalent) via Dhan's
free WebSocket API and publishes both tick data and depth snapshots to Redis.

Requires: pip install dhanhq>=2.0.0
Credentials: Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN env vars.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from data_pipeline.truedata_feed import TickData

logger = logging.getLogger("niftymind.dhan_depth_feed")

_RECONNECT_BASE = 2.0
_RECONNECT_MAX = 60.0


@dataclass
class DepthSnapshot:
    symbol: str
    timestamp: str
    ltp: float
    bids: list  # [{"price": float, "quantity": int}, ...]
    asks: list
    total_bid_qty: int
    total_ask_qty: int
    oi: int
    volume: int


class DhanDepthFeed:
    """Streams Full market depth packets from Dhan WebSocket and publishes to Redis."""

    def __init__(self, config, publisher):
        self.config = config
        self.publisher = publisher

    def _build_instruments(self, instruments: list[str]) -> list[tuple]:
        """Build Dhan instrument tuples from instrument names.

        Returns list of (exchange_segment, security_id_str, subscription_type).
        """
        try:
            from dhanhq import marketfeed
        except ImportError:
            return []

        result = []
        for inst in instruments:
            inst_upper = inst.upper()
            if inst_upper == "NIFTY":
                # Index
                result.append((marketfeed.IDX, self.config.nifty_security_id, marketfeed.Full))
                # Futures (NSE_FNO uses same security_id for the front-month futures)
                result.append((marketfeed.NSE_FNO, self.config.nifty_security_id, marketfeed.Full))
            elif inst_upper == "BANKNIFTY":
                result.append((marketfeed.IDX, self.config.banknifty_security_id, marketfeed.Full))
                result.append((marketfeed.NSE_FNO, self.config.banknifty_security_id, marketfeed.Full))
        return result

    def _make_symbol_map(self, instruments: list[str]) -> dict[str, str]:
        """Build reverse lookup: (exchange_segment, security_id) -> our symbol."""
        try:
            from dhanhq import marketfeed
        except ImportError:
            return {}

        mapping: dict[str, str] = {}
        for inst in instruments:
            inst_upper = inst.upper()
            if inst_upper == "NIFTY":
                mapping[f"{marketfeed.IDX}:{self.config.nifty_security_id}"] = "NIFTY"
                mapping[f"{marketfeed.NSE_FNO}:{self.config.nifty_security_id}"] = "NIFTY-FUT"
            elif inst_upper == "BANKNIFTY":
                mapping[f"{marketfeed.IDX}:{self.config.banknifty_security_id}"] = "BANKNIFTY"
                mapping[f"{marketfeed.NSE_FNO}:{self.config.banknifty_security_id}"] = "BANKNIFTY-FUT"
        return mapping

    async def start(self, instruments: list[str], shutdown_event: asyncio.Event):
        """Start Dhan depth feed with reconnect on error."""
        if not self.config.client_id or not self.config.access_token:
            logger.warning(
                "Dhan credentials not set. Depth feed disabled. "
                "Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN."
            )
            return

        try:
            from dhanhq import marketfeed
        except ImportError:
            logger.error("dhanhq package not installed. Run: pip install dhanhq>=2.0.0")
            return

        dhan_instruments = self._build_instruments(instruments)
        if not dhan_instruments:
            logger.warning("No Dhan instruments configured; depth feed disabled.")
            return

        symbol_map = self._make_symbol_map(instruments)
        reconnect_delay = _RECONNECT_BASE

        logger.info(f"Dhan depth feed starting for instruments: {instruments}")

        while not shutdown_event.is_set():
            feed = None
            try:
                feed = marketfeed.DhanFeed(
                    self.config.client_id,
                    self.config.access_token,
                    dhan_instruments,
                )
                await feed.connect()
                logger.info("Dhan WebSocket connected")
                reconnect_delay = _RECONNECT_BASE  # reset on successful connect

                while not shutdown_event.is_set():
                    data = await asyncio.wait_for(feed.get_data(), timeout=30.0)
                    if data is None:
                        continue
                    tick, depth = self._parse_depth_packet(data, symbol_map)
                    if tick is not None:
                        await self.publisher.publish_tick(tick)
                    if depth is not None:
                        await self.publisher.publish_depth(depth)

            except asyncio.TimeoutError:
                logger.warning("Dhan WebSocket: no data for 30s, reconnecting...")
            except asyncio.CancelledError:
                logger.info("Dhan depth feed cancelled")
                break
            except Exception as exc:
                logger.error(f"Dhan WebSocket error: {exc}")
            finally:
                if feed is not None:
                    try:
                        await feed.disconnect()
                    except Exception:
                        pass

            if shutdown_event.is_set():
                break

            logger.info(f"Dhan depth feed reconnecting in {reconnect_delay:.0f}s...")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=reconnect_delay)
            except asyncio.TimeoutError:
                pass
            reconnect_delay = min(reconnect_delay * 2, _RECONNECT_MAX)

        logger.info("Dhan depth feed stopped")

    def _parse_depth_packet(
        self, data: dict, symbol_map: dict[str, str]
    ) -> tuple:
        """Parse a Dhan Full packet into (TickData | None, DepthSnapshot | None)."""
        try:
            exchange_segment = data.get("exchange_segment", data.get("exchangeSegment"))
            security_id = str(data.get("security_id", data.get("securityId", "")))
            key = f"{exchange_segment}:{security_id}"
            symbol = symbol_map.get(key, security_id)

            ltp = float(data.get("LTP", data.get("ltp", 0)))
            open_ = float(data.get("open", 0))
            high = float(data.get("high", 0))
            low = float(data.get("low", 0))
            close = float(data.get("close", 0))
            volume = int(data.get("volume", 0))
            oi = int(data.get("OI", data.get("oi", 0)))

            timestamp = datetime.now().isoformat()

            # Depth levels
            raw_bids: list = data.get("best_bid", [])
            raw_asks: list = data.get("best_ask", [])

            bids = [
                {"price": float(level.get("price", 0)), "quantity": int(level.get("quantity", 0))}
                for level in raw_bids
            ]
            asks = [
                {"price": float(level.get("price", 0)), "quantity": int(level.get("quantity", 0))}
                for level in raw_asks
            ]

            total_bid_qty = sum(b["quantity"] for b in bids)
            total_ask_qty = sum(a["quantity"] for a in asks)

            best_bid = bids[0] if bids else {"price": 0.0, "quantity": 0}
            best_ask = asks[0] if asks else {"price": 0.0, "quantity": 0}

            tick: TickData | None = None
            if ltp > 0:
                tick = TickData(
                    symbol=symbol,
                    ltp=ltp,
                    bid=best_bid["price"],
                    ask=best_ask["price"],
                    bid_qty=best_bid["quantity"],
                    ask_qty=best_ask["quantity"],
                    volume=volume,
                    oi=oi,
                    timestamp=timestamp,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                )

            depth: DepthSnapshot | None = None
            if bids or asks:
                depth = DepthSnapshot(
                    symbol=symbol,
                    timestamp=timestamp,
                    ltp=ltp,
                    bids=bids,
                    asks=asks,
                    total_bid_qty=total_bid_qty,
                    total_ask_qty=total_ask_qty,
                    oi=oi,
                    volume=volume,
                )

            return tick, depth

        except Exception as exc:
            logger.warning(f"Dhan packet parse error: {exc}")
            return None, None
