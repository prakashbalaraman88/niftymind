import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiohttp

logger = logging.getLogger("niftymind.sentiment_feed")

IST = timezone(timedelta(hours=5, minutes=30))

NSE_FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
NSE_ADVANCE_DECLINE_URL = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
NSE_VIX_URL = "https://www.nseindia.com/api/allIndices"

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


class SentimentFeed:
    def __init__(self, publisher):
        self.publisher = publisher
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=NSE_HEADERS)
            try:
                await self._session.get(
                    "https://www.nseindia.com/",
                    timeout=REQUEST_TIMEOUT,
                )
            except Exception as e:
                logger.warning(f"NSE cookie bootstrap failed: {e}")
        return self._session

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("Sentiment feed (FII/DII + breadth + VIX) starting")
        while not shutdown_event.is_set():
            try:
                await self._fetch_and_publish()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sentiment feed error: {e}")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=300.0)
                break
            except asyncio.TimeoutError:
                continue

        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("Sentiment feed stopped")

    async def _fetch_and_publish(self):
        session = await self._get_session()

        try:
            async with session.get(NSE_FII_DII_URL, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    fii_dii = self._parse_fii_dii(data)
                    if fii_dii:
                        await self.publisher.publish_fii_dii(fii_dii)
                        logger.info(f"Published FII/DII data: FII net={fii_dii.get('fii_net')}, DII net={fii_dii.get('dii_net')}")
                else:
                    logger.warning(f"FII/DII fetch returned status {resp.status}")
        except Exception as e:
            logger.error(f"Failed to fetch FII/DII data: {e}")

        try:
            async with session.get(NSE_ADVANCE_DECLINE_URL, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    breadth = self._parse_breadth(data)
                    if breadth:
                        await self.publisher.publish_market_breadth(breadth)
                        logger.info(f"Published breadth: advances={breadth.get('advances')}, declines={breadth.get('declines')}")
                else:
                    logger.warning(f"Breadth fetch returned status {resp.status}")
        except Exception as e:
            logger.error(f"Failed to fetch breadth data: {e}")

        try:
            async with session.get(NSE_VIX_URL, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    vix = self._parse_vix(data)
                    if vix:
                        await self.publisher.publish_market_breadth({
                            **vix,
                            "_merge_key": "vix_data",
                        })
                        # Also publish VIX as a tick so the frontend can display it
                        vix_val = vix.get("india_vix", 0)
                        if vix_val:
                            from data_pipeline.truedata_feed import TickData
                            vix_tick = TickData(
                                symbol="INDIA VIX", ltp=float(vix_val),
                                bid=0, ask=0, bid_qty=0, ask_qty=0,
                                volume=0, oi=0,
                                timestamp=datetime.now(IST).isoformat(),
                                open=0, high=0, low=0, close=0,
                            )
                            await self.publisher.publish_tick(vix_tick)
                        logger.info(f"Published VIX data: {vix.get('india_vix')}")
                else:
                    logger.warning(f"VIX/indices fetch returned status {resp.status}")
        except Exception as e:
            logger.error(f"Failed to fetch VIX data: {e}")

    def _parse_fii_dii(self, data: list | dict) -> dict | None:
        try:
            records = data if isinstance(data, list) else [data]
            result = {
                "timestamp": datetime.now(IST).isoformat(),
                "fii_buy": 0,
                "fii_sell": 0,
                "fii_net": 0,
                "dii_buy": 0,
                "dii_sell": 0,
                "dii_net": 0,
            }
            for rec in records:
                category = rec.get("category", "").upper()
                buy_val = float(rec.get("buyValue", 0))
                sell_val = float(rec.get("sellValue", 0))
                if "FII" in category or "FPI" in category:
                    result["fii_buy"] += buy_val
                    result["fii_sell"] += sell_val
                    result["fii_net"] += buy_val - sell_val
                elif "DII" in category:
                    result["dii_buy"] += buy_val
                    result["dii_sell"] += sell_val
                    result["dii_net"] += buy_val - sell_val
            return result
        except Exception as e:
            logger.warning(f"Failed to parse FII/DII data: {e}")
            return None

    def _parse_breadth(self, data: dict) -> dict | None:
        try:
            stocks = data.get("data", [])
            advances = sum(1 for s in stocks if float(s.get("pChange", 0)) > 0)
            declines = sum(1 for s in stocks if float(s.get("pChange", 0)) < 0)
            unchanged = len(stocks) - advances - declines
            ad_ratio = advances / declines if declines > 0 else float(advances)
            return {
                "timestamp": datetime.now(IST).isoformat(),
                "advances": advances,
                "declines": declines,
                "unchanged": unchanged,
                "ad_ratio": round(ad_ratio, 2),
                "total_stocks": len(stocks),
            }
        except Exception as e:
            logger.warning(f"Failed to parse breadth data: {e}")
            return None

    def _parse_vix(self, data: dict) -> dict | None:
        try:
            indices = data.get("data", [])
            for idx in indices:
                name = idx.get("index", "").upper()
                if "VIX" in name:
                    return {
                        "timestamp": datetime.now(IST).isoformat(),
                        "india_vix": float(idx.get("last", 0)),
                        "vix_change": float(idx.get("percentChange", 0)),
                        "vix_prev_close": float(idx.get("previousClose", 0)),
                    }
            return None
        except Exception as e:
            logger.warning(f"Failed to parse VIX data: {e}")
            return None
