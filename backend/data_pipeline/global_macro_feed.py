import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

import aiohttp

logger = logging.getLogger("niftymind.global_macro_feed")

IST = timezone(timedelta(hours=5, minutes=30))

GLOBAL_SYMBOLS = {
    "sp500_futures": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/ES=F?interval=1m&range=1d", "name": "S&P 500 Futures"},
    "nasdaq_futures": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/NQ=F?interval=1m&range=1d", "name": "Nasdaq Futures"},
    "dow_futures": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/YM=F?interval=1m&range=1d", "name": "Dow Futures"},
    "crude_oil": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/CL=F?interval=1m&range=1d", "name": "Crude Oil"},
    "gold": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d", "name": "Gold"},
    "dxy": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1m&range=1d", "name": "US Dollar Index"},
    "us_10y": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?interval=1m&range=1d", "name": "US 10Y Yield"},
    "usd_inr": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/USDINR=X?interval=1m&range=1d", "name": "USD/INR"},
    "hang_seng": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/%5EHSI?interval=1m&range=1d", "name": "Hang Seng"},
    "nikkei": {"url": "https://query1.finance.yahoo.com/v8/finance/chart/%5EN225?interval=1m&range=1d", "name": "Nikkei 225"},
}


class GlobalMacroFeed:
    def __init__(self, publisher):
        self.publisher = publisher
        self._session: aiohttp.ClientSession | None = None
        self._latest_data: dict = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0"}
            )
        return self._session

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("Global macro feed starting")
        while not shutdown_event.is_set():
            try:
                await self._fetch_and_publish()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Global macro feed error: {e}")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=600.0)
                break
            except asyncio.TimeoutError:
                continue

        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("Global macro feed stopped")

    async def _fetch_and_publish(self):
        session = await self._get_session()

        tasks = []
        for key, info in GLOBAL_SYMBOLS.items():
            tasks.append(self._fetch_symbol(session, key, info))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for key, result in zip(GLOBAL_SYMBOLS.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {key}: {result}")
            elif result is not None:
                self._latest_data[key] = result

        if self._latest_data:
            macro_payload = {
                "timestamp": datetime.now(IST).isoformat(),
                **self._latest_data,
            }
            await self.publisher.publish_global_macro(macro_payload)
            logger.info(f"Published global macro data for {len(self._latest_data)} symbols")

    async def _fetch_symbol(self, session: aiohttp.ClientSession, key: str, info: dict) -> dict | None:
        try:
            async with session.get(
                info["url"],
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

                chart = data.get("chart", {}).get("result", [{}])[0]
                meta = chart.get("meta", {})
                price = meta.get("regularMarketPrice", 0)
                prev_close = meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0)
                change = price - prev_close if prev_close else 0
                change_pct = (change / prev_close * 100) if prev_close else 0

                return {
                    "name": info["name"],
                    "price": round(price, 4),
                    "prev_close": round(prev_close, 4),
                    "change": round(change, 4),
                    "change_pct": round(change_pct, 2),
                }
        except Exception as e:
            logger.debug(f"Error fetching {key}: {e}")
            return None
