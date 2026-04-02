import asyncio
import json
import logging
import sys
import os
from dataclasses import asdict

import redis.asyncio as aioredis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS as CHANNELS

logger = logging.getLogger("niftymind.redis_publisher")


class _SubscriberHandle:
    """Drop-in replacement for PubSub that reads from a shared multiplexer."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=256)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 0):
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def unsubscribe(self, *args):
        pass  # cleanup handled by RedisPublisher._remove_subscriber

    async def aclose(self):
        pass


class RedisPublisher:
    def __init__(self, redis_config):
        self._config = redis_config
        self._client: aioredis.Redis | None = None
        # Shared PubSub multiplexer state
        self._shared_pubsub: aioredis.client.PubSub | None = None
        self._subscribed_channels: set[str] = set()
        self._subscribers: dict[str, list[_SubscriberHandle]] = {}  # channel -> handles
        self._dispatcher_task: asyncio.Task | None = None
        self._mux_lock = asyncio.Lock()

    async def connect(self):
        self._client = aioredis.from_url(
            self._config.url,
            decode_responses=True,
            max_connections=3,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        await self._client.ping()
        logger.info(f"Redis publisher connected to {self._config.url}")

    async def disconnect(self):
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
        if self._shared_pubsub:
            await self._shared_pubsub.aclose()
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

    async def publish_fii_dii(self, data: dict):
        await self._publish(CHANNELS["fii_dii"], data)

    async def publish_market_breadth(self, data: dict):
        await self._publish(CHANNELS["market_breadth"], data)

    async def publish_news(self, data: dict):
        await self._publish(CHANNELS["news"], data)

    async def publish_economic_calendar(self, data: dict):
        await self._publish(CHANNELS["economic_calendar"], data)

    async def publish_global_macro(self, data: dict):
        await self._publish(CHANNELS["global_macro"], data)

    async def publish_depth(self, snapshot) -> None:
        data = asdict(snapshot) if hasattr(snapshot, "__dataclass_fields__") else snapshot
        await self._publish(CHANNELS["depth"], data)

    async def subscribe(self, *channel_keys) -> _SubscriberHandle:
        """Return a lightweight handle sharing ONE PubSub connection."""
        if not self._client:
            raise RuntimeError("Redis client not connected")

        handle = _SubscriberHandle()
        channels = [CHANNELS[k] for k in channel_keys if k in CHANNELS]

        async with self._mux_lock:
            # Lazily create shared PubSub
            if self._shared_pubsub is None:
                self._shared_pubsub = self._client.pubsub()

            # Register handle for each channel
            new_channels = []
            for ch in channels:
                if ch not in self._subscribers:
                    self._subscribers[ch] = []
                    new_channels.append(ch)
                self._subscribers[ch].append(handle)

            # Subscribe only to genuinely new channels
            if new_channels:
                await self._shared_pubsub.subscribe(*new_channels)
                self._subscribed_channels.update(new_channels)
                logger.info(f"Shared PubSub subscribed to new channels: {new_channels}")

            # Start dispatcher if not running
            if self._dispatcher_task is None or self._dispatcher_task.done():
                self._dispatcher_task = asyncio.create_task(self._dispatch_loop())

        logger.info(f"Subscriber registered for channels: {channels} (total connections: 1 shared)")
        return handle

    async def _dispatch_loop(self):
        """Single loop reading the shared PubSub and fanning out to handles."""
        try:
            while True:
                if self._shared_pubsub is None:
                    break
                msg = await self._shared_pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0,
                )
                if msg is None or msg["type"] != "message":
                    await asyncio.sleep(0.01)
                    continue

                channel = msg["channel"]
                handles = self._subscribers.get(channel, [])
                for h in handles:
                    try:
                        h._queue.put_nowait(msg)
                    except asyncio.QueueEmpty:
                        pass  # subscriber too slow, drop message
                    except asyncio.QueueFull:
                        pass  # subscriber too slow, drop message
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"PubSub dispatch loop error: {e}")
