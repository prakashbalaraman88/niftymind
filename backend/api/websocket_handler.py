import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS

logger = logging.getLogger("niftymind.api.websocket")

IST = timezone(timedelta(hours=5, minutes=30))

ws_router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self._connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self._connections)}")

    async def broadcast(self, message: dict):
        async with self._lock:
            connections = list(self._connections)

        dead = []
        for ws in connections:
            try:
                await asyncio.wait_for(ws.send_json(message), timeout=2.0)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    if ws in self._connections:
                        self._connections.remove(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(data)
                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now(IST).isoformat()})
                elif msg_type == "subscribe":
                    await websocket.send_json({"type": "subscribed", "channels": msg.get("channels", [])})

            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "heartbeat", "timestamp": datetime.now(IST).isoformat()})
                except Exception:
                    break
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket)


async def start_redis_relay(redis_publisher, shutdown_event: asyncio.Event):
    logger.info("WebSocket Redis relay starting")

    relay_channels = [
        "ticks", "trade_executions", "agent_status", "signals", "news",
    ]
    pubsub = await redis_publisher.subscribe(*relay_channels)

    channel_to_type = {
        REDIS_CHANNELS["ticks"]: "tick",
        REDIS_CHANNELS["trade_executions"]: "trade_execution",
        REDIS_CHANNELS["agent_status"]: "agent_status",
        REDIS_CHANNELS["signals"]: "signal",
        REDIS_CHANNELS["news"]: "news",
    }

    try:
        while not shutdown_event.is_set():
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue

            if message is None or message["type"] != "message":
                continue

            if manager.client_count == 0:
                continue

            try:
                data = json.loads(message["data"])
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                msg_type = channel_to_type.get(channel, "unknown")

                await manager.broadcast({
                    "type": msg_type,
                    "data": data,
                    "timestamp": datetime.now(IST).isoformat(),
                })
            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"Redis relay error: {e}")

    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        logger.info("WebSocket Redis relay stopped")
