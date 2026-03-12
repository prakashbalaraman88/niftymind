import asyncio
import json
import logging
from datetime import datetime
from dataclasses import dataclass, asdict

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
    def __init__(self, config, publisher):
        self.config = config
        self.publisher = publisher
        self._ws = None
        self._reconnect_count = 0

    async def start(self, instruments: list[str], shutdown_event: asyncio.Event):
        while not shutdown_event.is_set():
            try:
                await self._connect_and_subscribe(instruments, shutdown_event)
            except asyncio.CancelledError:
                logger.info("Tick feed cancelled")
                break
            except Exception as e:
                self._reconnect_count += 1
                if self._reconnect_count > self.config.max_reconnect_attempts:
                    logger.error(
                        f"Max reconnection attempts ({self.config.max_reconnect_attempts}) exceeded. Stopping tick feed."
                    )
                    break
                delay = self.config.reconnect_delay * min(self._reconnect_count, 10)
                logger.warning(
                    f"Tick feed connection error: {e}. Reconnecting in {delay:.1f}s (attempt {self._reconnect_count})"
                )
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=delay)
                    break
                except asyncio.TimeoutError:
                    continue

    async def _connect_and_subscribe(
        self, instruments: list[str], shutdown_event: asyncio.Event
    ):
        import websockets

        url = f"{self.config.ws_url}/TickData"
        logger.info(f"Connecting to TrueData tick feed at {url}")

        async with websockets.connect(url) as ws:
            self._ws = ws
            self._reconnect_count = 0

            auth_msg = json.dumps(
                {
                    "method": "login",
                    "username": self.config.username,
                    "password": self.config.password,
                }
            )
            await ws.send(auth_msg)
            auth_response = await ws.recv()
            logger.info(f"TrueData auth response: {auth_response}")

            for instrument in instruments:
                sub_msg = json.dumps(
                    {
                        "method": "addsymbol",
                        "symbols": [instrument],
                    }
                )
                await ws.send(sub_msg)
                logger.info(f"Subscribed to tick data for {instrument}")

            logger.info("Tick feed connected and subscribed")

            while not shutdown_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    await ws.ping()
                    continue

                try:
                    data = json.loads(raw)
                    tick = self._parse_tick(data)
                    if tick:
                        await self.publisher.publish_tick(tick)
                except json.JSONDecodeError:
                    logger.warning(f"Non-JSON message from TrueData: {raw[:200]}")
                except Exception as e:
                    logger.error(f"Error processing tick: {e}")

    def _parse_tick(self, data: dict) -> TickData | None:
        try:
            return TickData(
                symbol=data.get("symbol", ""),
                ltp=float(data.get("ltp", 0)),
                bid=float(data.get("bid", 0)),
                ask=float(data.get("ask", 0)),
                bid_qty=int(data.get("bidQty", 0)),
                ask_qty=int(data.get("askQty", 0)),
                volume=int(data.get("volume", 0)),
                oi=int(data.get("oi", 0)),
                timestamp=data.get("timestamp", datetime.now().isoformat()),
                open=float(data.get("open", 0)),
                high=float(data.get("high", 0)),
                low=float(data.get("low", 0)),
                close=float(data.get("close", 0)),
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse tick data: {e}")
            return None
