"""TrueData options chain feed using official truedata Python library (v7+).

Streams real-time option chain with Greeks for NIFTY/BANKNIFTY.
Publishes snapshots to Redis for Options Chain agent and Strike Selector.

Requires: pip install truedata
Greeks streaming must be enabled on your TrueData account (contact api@truedata.in).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger("niftymind.options_chain_feed")


@dataclass
class OptionData:
    symbol: str
    underlying: str
    strike: float
    option_type: str  # "CE" or "PE"
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
    """Streams options chain with Greeks from TrueData."""

    # Refresh interval: options chain doesn't need tick-speed updates
    REFRESH_INTERVAL = 5.0  # seconds

    def __init__(self, config, publisher):
        self.config = config
        self.publisher = publisher
        self._td = None
        self._running = False

    async def start(self, instruments: list[str], shutdown_event: asyncio.Event):
        """Start options chain feed with periodic snapshots."""
        if not self.config.username or not self.config.password:
            logger.warning("TrueData credentials not set. Options chain feed disabled.")
            return

        try:
            from truedata import TD_live
        except ImportError:
            logger.error("truedata package not installed. Run: pip install truedata")
            return

        self._running = True
        loop = asyncio.get_event_loop()

        logger.info(f"Connecting to TrueData for options chain...")

        try:
            # TD_live() blocks on WebSocket handshake — run in thread to avoid
            # blocking the event loop and failing Railway health checks.
            self._td = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: TD_live(self.config.username, self.config.password)
                ),
                timeout=30.0,
            )
            logger.info("TrueData options chain connection established")
        except asyncio.TimeoutError:
            logger.error("TrueData options chain connection timed out after 30s — feed disabled")
            return
        except Exception as e:
            logger.error(f"TrueData connection failed: {e}")
            return

        # Find nearest expiry (Thursday for weekly)
        expiry = self._get_nearest_expiry()
        chain_length = 20  # 20 strikes around ATM

        for instrument in instruments:
            td_symbol = "NIFTY" if instrument == "NIFTY" else "BANKNIFTY"
            try:
                self._td.start_option_chain(
                    td_symbol,
                    expiry,
                    chain_length=chain_length,
                    bid_ask=True,
                    greek=True,
                )
                logger.info(
                    f"Subscribed to options chain: {td_symbol}, expiry={expiry.date()}, "
                    f"chain_length={chain_length}, greeks=True"
                )
            except Exception as e:
                logger.error(f"Failed to subscribe to {td_symbol} chain: {e}")

        # Periodic snapshot loop
        while not shutdown_event.is_set():
            try:
                for instrument in instruments:
                    td_symbol = "NIFTY" if instrument == "NIFTY" else "BANKNIFTY"
                    snapshot = self._build_snapshot(td_symbol)
                    if snapshot:
                        await self.publisher.publish_options_chain(snapshot)
            except Exception as e:
                logger.error(f"Error building options chain snapshot: {e}")

            try:
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=self.REFRESH_INTERVAL
                )
                break
            except asyncio.TimeoutError:
                continue

        self._running = False
        try:
            self._td.disconnect()
            logger.info("Options chain feed disconnected")
        except Exception:
            pass

    def _build_snapshot(self, underlying: str) -> OptionsChainSnapshot | None:
        """Build snapshot from TrueData's live option chain data."""
        try:
            chain = self._td.option_chain_data.get(underlying)
            if not chain:
                return None

            options = []
            total_ce_oi = 0
            total_pe_oi = 0
            max_pain_strikes: dict[float, float] = {}

            for strike_data in chain:
                strike = float(getattr(strike_data, "strike", 0))

                for opt_type in ["CE", "PE"]:
                    prefix = "call" if opt_type == "CE" else "put"
                    ltp = float(getattr(strike_data, f"{prefix}_ltp", 0))
                    oi = int(getattr(strike_data, f"{prefix}_oi", 0))
                    volume = int(getattr(strike_data, f"{prefix}_volume", 0))

                    option = OptionData(
                        symbol=f"{underlying}{strike}{opt_type}",
                        underlying=underlying,
                        strike=strike,
                        option_type=opt_type,
                        ltp=ltp,
                        bid=float(getattr(strike_data, f"{prefix}_bid", 0)),
                        ask=float(getattr(strike_data, f"{prefix}_ask", 0)),
                        volume=volume,
                        oi=oi,
                        oi_change=int(getattr(strike_data, f"{prefix}_oi_change", 0)),
                        iv=float(getattr(strike_data, f"{prefix}_iv", 0)),
                        delta=float(getattr(strike_data, f"{prefix}_delta", 0)),
                        gamma=float(getattr(strike_data, f"{prefix}_gamma", 0)),
                        theta=float(getattr(strike_data, f"{prefix}_theta", 0)),
                        vega=float(getattr(strike_data, f"{prefix}_vega", 0)),
                        timestamp=datetime.now().isoformat(),
                    )
                    options.append(option)

                    if opt_type == "CE":
                        total_ce_oi += oi
                    else:
                        total_pe_oi += oi

                    # Max pain calculation: accumulate loss at each strike
                    if strike not in max_pain_strikes:
                        max_pain_strikes[strike] = 0
                    max_pain_strikes[strike] += oi * ltp

            pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0.0

            # Max pain = strike where total premium paid (CE+PE) is minimum
            max_pain = 0.0
            if max_pain_strikes:
                max_pain = min(max_pain_strikes, key=max_pain_strikes.get)

            spot = float(getattr(chain[0], "spot_price", 0)) if chain else 0

            return OptionsChainSnapshot(
                underlying=underlying,
                spot_price=spot,
                options=options,
                pcr=round(pcr, 3),
                max_pain=max_pain,
                iv_rank=0.0,  # Computed by options chain agent from historical IV
                iv_percentile=0.0,
                total_ce_oi=total_ce_oi,
                total_pe_oi=total_pe_oi,
                timestamp=datetime.now().isoformat(),
            )
        except Exception as e:
            logger.warning(f"Failed to build snapshot for {underlying}: {e}")
            return None

    @staticmethod
    def _get_nearest_expiry() -> datetime:
        """Get nearest Thursday (NSE weekly expiry day)."""
        today = datetime.now()
        days_ahead = (3 - today.weekday()) % 7  # Thursday = 3
        if days_ahead == 0 and today.hour >= 16:
            days_ahead = 7  # If Thursday after market close, use next week
        return today + timedelta(days=days_ahead)
