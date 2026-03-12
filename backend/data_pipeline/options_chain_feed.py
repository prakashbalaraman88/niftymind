import asyncio
import json
import logging
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger("niftymind.options_chain_feed")


@dataclass
class OptionData:
    symbol: str
    underlying: str
    strike: float
    option_type: str
    ltp: float
    bid: float
    ask: float
    volume: int
    oi: int
    oi_change: int
    iv: float
    delta: float
    gamma: float
    theta: float
    vega: float
    timestamp: str


@dataclass
class OptionsChainSnapshot:
    underlying: str
    spot_price: float
    options: list[OptionData]
    pcr: float
    max_pain: float
    iv_rank: float
    iv_percentile: float
    total_ce_oi: int
    total_pe_oi: int
    timestamp: str


class OptionsChainFeed:
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
                logger.info("Options chain feed cancelled")
                break
            except Exception as e:
                self._reconnect_count += 1
                if self._reconnect_count > self.config.max_reconnect_attempts:
                    logger.error(
                        f"Max reconnection attempts exceeded. Stopping options chain feed."
                    )
                    break
                delay = self.config.reconnect_delay * min(self._reconnect_count, 10)
                logger.warning(
                    f"Options chain feed error: {e}. Reconnecting in {delay:.1f}s (attempt {self._reconnect_count})"
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

        url = f"{self.config.ws_url}/OptionChain"
        logger.info(f"Connecting to TrueData options chain feed at {url}")

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
            logger.info(f"Options chain auth response: {auth_response}")

            for instrument in instruments:
                sub_msg = json.dumps(
                    {
                        "method": "getoptionchain",
                        "symbol": instrument,
                        "expiry": "nearest",
                    }
                )
                await ws.send(sub_msg)
                logger.info(f"Subscribed to options chain for {instrument}")

            logger.info("Options chain feed connected and subscribed")

            while not shutdown_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                except asyncio.TimeoutError:
                    await ws.ping()
                    continue

                try:
                    data = json.loads(raw)
                    snapshot = self._parse_chain(data)
                    if snapshot:
                        await self.publisher.publish_options_chain(snapshot)
                except json.JSONDecodeError:
                    logger.warning(
                        f"Non-JSON message from options chain: {raw[:200]}"
                    )
                except Exception as e:
                    logger.error(f"Error processing options chain: {e}")

    def _parse_chain(self, data: dict) -> OptionsChainSnapshot | None:
        try:
            underlying = data.get("symbol", "")
            spot = float(data.get("spotPrice", 0))
            raw_options = data.get("options", [])

            options = []
            total_ce_oi = 0
            total_pe_oi = 0

            for opt in raw_options:
                option = OptionData(
                    symbol=opt.get("symbol", ""),
                    underlying=underlying,
                    strike=float(opt.get("strike", 0)),
                    option_type=opt.get("optionType", ""),
                    ltp=float(opt.get("ltp", 0)),
                    bid=float(opt.get("bid", 0)),
                    ask=float(opt.get("ask", 0)),
                    volume=int(opt.get("volume", 0)),
                    oi=int(opt.get("oi", 0)),
                    oi_change=int(opt.get("oiChange", 0)),
                    iv=float(opt.get("iv", 0)),
                    delta=float(opt.get("delta", 0)),
                    gamma=float(opt.get("gamma", 0)),
                    theta=float(opt.get("theta", 0)),
                    vega=float(opt.get("vega", 0)),
                    timestamp=data.get("timestamp", datetime.now().isoformat()),
                )
                options.append(option)
                if option.option_type == "CE":
                    total_ce_oi += option.oi
                elif option.option_type == "PE":
                    total_pe_oi += option.oi

            pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0.0
            max_pain = float(data.get("maxPain", 0))
            iv_rank = float(data.get("ivRank", 0))
            iv_percentile = float(data.get("ivPercentile", 0))

            return OptionsChainSnapshot(
                underlying=underlying,
                spot_price=spot,
                options=options,
                pcr=pcr,
                max_pain=max_pain,
                iv_rank=iv_rank,
                iv_percentile=iv_percentile,
                total_ce_oi=total_ce_oi,
                total_pe_oi=total_pe_oi,
                timestamp=data.get("timestamp", datetime.now().isoformat()),
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse options chain data: {e}")
            return None
