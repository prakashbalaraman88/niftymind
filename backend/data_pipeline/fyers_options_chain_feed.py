"""Fyers options chain feed — polls REST API every 30s during market hours.

Publishes OptionsChainSnapshot to Redis for the Options Chain agent and
Strike Selector.  Runs independently of TrueData; no TrueData credentials
are required.

Requires: pip install fyers-apiv3
Credentials: Set FYERS_APP_ID and FYERS_ACCESS_TOKEN env vars.
"""

import asyncio
import dataclasses
import logging
from datetime import datetime

from data_pipeline.options_chain_feed import OptionData, OptionsChainSnapshot

logger = logging.getLogger("niftymind.fyers_options_chain_feed")

# Fyers symbol for each instrument
_FYERS_SYMBOL = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
}

# Market hours (IST) — 09:15 to 15:35
_MARKET_OPEN = (9, 15)
_MARKET_CLOSE = (15, 35)

_POLL_INTERVAL = 30   # seconds inside market hours
_SLEEP_OUTSIDE = 60   # seconds outside market hours
_RETRY_DELAY = 5      # seconds after an error


def _is_market_hours() -> bool:
    now = datetime.now()
    t = (now.hour, now.minute)
    return _MARKET_OPEN <= t <= _MARKET_CLOSE


def _build_snapshot(instrument: str, chain_data: list) -> OptionsChainSnapshot | None:
    """Build an OptionsChainSnapshot from Fyers optionchain() response data."""
    if not chain_data:
        return None

    # First entry (strike_price == -1) is the index row; take fp as spot proxy
    spot_price = 0.0
    first = chain_data[0]
    if first.get("strike_price", 0) == -1:
        spot_price = float(first.get("fp", 0) or first.get("ltp", 0))
        entries = chain_data[1:]
    else:
        entries = chain_data

    options: list[OptionData] = []
    total_ce_oi = 0
    total_pe_oi = 0
    # strike -> {CE_OI, PE_OI} for max pain
    strike_oi: dict[float, dict[str, int]] = {}

    ts = datetime.now().isoformat()

    for entry in entries:
        strike = float(entry.get("strike_price", 0))
        if strike <= 0:
            continue
        opt_type = entry.get("option_type", "").upper()
        if opt_type not in ("CE", "PE"):
            continue

        ltp = float(entry.get("ltp", 0) or 0)
        oi = int(entry.get("oi", 0) or 0)

        option = OptionData(
            symbol=str(entry.get("symbol", "")),
            underlying=instrument,
            strike=strike,
            option_type=opt_type,
            ltp=ltp,
            bid=float(entry.get("bid", 0) or 0),
            ask=float(entry.get("ask", 0) or 0),
            volume=int(entry.get("volume", 0) or 0),
            oi=oi,
            oi_change=int(entry.get("oich", 0) or 0),
            iv=0.0,
            delta=0.0,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            timestamp=ts,
        )
        options.append(option)

        if opt_type == "CE":
            total_ce_oi += oi
        else:
            total_pe_oi += oi

        if strike not in strike_oi:
            strike_oi[strike] = {"CE": 0, "PE": 0}
        strike_oi[strike][opt_type] += oi

    pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0.0

    # Max pain: strike where total ITM loss to option buyers is minimum
    max_pain = 0.0
    if strike_oi:
        min_pain = None
        for k, oi_map in strike_oi.items():
            pain = 0.0
            for s, s_oi in strike_oi.items():
                pain += s_oi["CE"] * max(0.0, s - k)   # CE holders lose if spot < strike
                pain += s_oi["PE"] * max(0.0, k - s)   # PE holders lose if spot > strike
            if min_pain is None or pain < min_pain:
                min_pain = pain
                max_pain = k

    return OptionsChainSnapshot(
        underlying=instrument,
        spot_price=spot_price,
        options=options,
        pcr=round(pcr, 3),
        max_pain=max_pain,
        iv_rank=0.0,
        iv_percentile=0.0,
        total_ce_oi=total_ce_oi,
        total_pe_oi=total_pe_oi,
        timestamp=ts,
    )


class FyersOptionsChainFeed:
    """Polls Fyers REST API for options chain data and publishes to Redis."""

    def __init__(self, fyers_config, publisher):
        self.config = fyers_config
        self.publisher = publisher

    async def start(self, instruments: list[str], shutdown_event: asyncio.Event):
        """Poll options chain until shutdown_event is set."""
        if not self.config.app_id or not self.config.access_token:
            logger.warning(
                "Fyers credentials not set — options chain feed disabled. "
                "Set FYERS_APP_ID and FYERS_ACCESS_TOKEN."
            )
            return

        try:
            from fyers_apiv3 import fyersModel
        except ImportError:
            logger.error("fyers-apiv3 package not installed. Run: pip install fyers-apiv3")
            return

        fyers = fyersModel.FyersModel(
            client_id=self.config.app_id,
            token=self.config.access_token,
            log_path="",
        )

        logger.info("Fyers options chain feed started for %s", instruments)
        loop = asyncio.get_event_loop()

        while not shutdown_event.is_set():
            if not _is_market_hours():
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=_SLEEP_OUTSIDE)
                    return
                except asyncio.TimeoutError:
                    continue

            try:
                for instrument in instruments:
                    fyers_sym = _FYERS_SYMBOL.get(instrument.upper())
                    if not fyers_sym:
                        logger.warning("No Fyers symbol mapping for instrument: %s", instrument)
                        continue

                    try:
                        resp = await loop.run_in_executor(
                            None,
                            lambda sym=fyers_sym: fyers.optionchain(
                                {"symbol": sym, "strikecount": 10, "timestamp": ""}
                            ),
                        )

                        chain_data = (
                            resp.get("data", {}).get("optionsChain", [])
                            if isinstance(resp, dict)
                            else []
                        )

                        if not chain_data:
                            logger.warning(
                                "Empty options chain response for %s: %s", instrument, resp
                            )
                            continue

                        snapshot = _build_snapshot(instrument, chain_data)
                        if snapshot:
                            await self.publisher.publish_options_chain(
                                dataclasses.asdict(snapshot)
                            )
                            logger.debug(
                                "Options chain published: %s, spot=%.2f, strikes=%d",
                                instrument, snapshot.spot_price, len(snapshot.options),
                            )
                    except Exception as exc:
                        logger.error("Error fetching options chain for %s: %s", instrument, exc)

            except Exception as exc:
                logger.error("Fyers options chain feed error: %s — retrying in %ds", exc, _RETRY_DELAY)
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=_RETRY_DELAY)
                    return
                except asyncio.TimeoutError:
                    continue

            # Wait for next poll interval
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=_POLL_INTERVAL)
                return
            except asyncio.TimeoutError:
                continue
