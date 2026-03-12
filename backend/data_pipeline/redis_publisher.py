import json
import logging
import sys
import os
from dataclasses import asdict

import redis.asyncio as aioredis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS as CHANNELS

logger = logging.getLogger("niftymind.redis_publisher")


class RedisPublisher:
    def __init__(self, redis_config):
        self._config = redis_config
        self._client: aioredis.Redis | None = None

    async def connect(self):
        self._client = aioredis.from_url(
            self._config.url,
            decode_responses=True,
            max_connections=20,
        )
        await self._client.ping()
        logger.info(f"Redis publisher connected to {self._config.url}")

    async def disconnect(self):
        if self._client:
            await self._client.aclose()
            logger.info("Redis publisher disconnected")

    async def _publish(self, channel: str, data: dict):
        if not self._client:
            logger.error("Redis client not connected")
            return
        try:
            message = json.dumps(data, default=str)
            await self._client.publish(channel, message)
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")

    async def publish_tick(self, tick):
        await self._publish(CHANNELS["ticks"], asdict(tick))

    async def publish_options_chain(self, snapshot):
        data = {
            "underlying": snapshot.underlying,
            "spot_price": snapshot.spot_price,
            "pcr": snapshot.pcr,
            "max_pain": snapshot.max_pain,
            "iv_rank": snapshot.iv_rank,
            "iv_percentile": snapshot.iv_percentile,
            "total_ce_oi": snapshot.total_ce_oi,
            "total_pe_oi": snapshot.total_pe_oi,
            "timestamp": snapshot.timestamp,
            "options": [asdict(opt) for opt in snapshot.options],
        }
        await self._publish(CHANNELS["options_chain"], data)

    async def publish_ohlc(self, timeframe: str, ohlc_data: dict):
        channel_key = f"ohlc_{timeframe}"
        if channel_key in CHANNELS:
            await self._publish(CHANNELS[channel_key], ohlc_data)

    async def publish_signal(self, signal_data: dict):
        await self._publish(CHANNELS["signals"], signal_data)

    async def publish_trade_proposal(self, proposal: dict):
        await self._publish(CHANNELS["trade_proposals"], proposal)

    async def publish_trade_execution(self, execution: dict):
        await self._publish(CHANNELS["trade_executions"], execution)

    async def publish_agent_status(self, status: dict):
        await self._publish(CHANNELS["agent_status"], status)

    async def subscribe(self, *channel_keys) -> aioredis.client.PubSub:
        if not self._client:
            raise RuntimeError("Redis client not connected")
        pubsub = self._client.pubsub()
        channels = [CHANNELS[k] for k in channel_keys if k in CHANNELS]
        if channels:
            await pubsub.subscribe(*channels)
            logger.info(f"Subscribed to Redis channels: {channels}")
        return pubsub
