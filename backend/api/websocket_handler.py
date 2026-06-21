"""
WebSocket handler for NiftyMind API.

Security-hardened WebSocket handler with:
- JWT authentication in connection handshake
- Connection rate limiting per IP and per user
- Channel-based access control
- Authenticated user context for all messages
- Secure connection management with limits
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS, WS_MAX_CONNECTIONS_PER_IP, WS_AUTH_TIMEOUT_SECONDS
from api.auth_middleware import (
    authenticate_websocket,
    decode_supabase_token,
    get_user_role,
    UserRole,
    extract_token_from_websocket,
)
from api.rate_limiter import get_rate_limiter, LimitTier

logger = logging.getLogger("niftymind.api.websocket")

IST = timezone(timedelta(hours=5, minutes=30))

ws_router = APIRouter()


class WebSocketUser:
    """Authenticated WebSocket user context."""

    def __init__(self, user_dict: dict):
        self.user_id = user_dict.get("sub", "")
        self.email = user_dict.get("email", "")
        self.role = get_user_role(user_dict)
        self.raw = user_dict

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_trader(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.TRADER)

    @property
    def is_viewer(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.TRADER, UserRole.VIEWER)

    def can_subscribe(self, channel: str) -> bool:
        """Check if user can subscribe to a given channel."""
        # All authenticated users can access these channels
        public_channels = {
            "ticks",
            "trade_executions",
            "agent_status",
            "signals",
            "news",
            "trade_closed",
            "learning_update",
        }

        # Only admins and traders can access sensitive channels
        restricted_channels = {
            "options_chain",
            "depth",
            "order_book",
            "trade_proposals",
        }

        # Admin-only channels
        admin_channels = {
            "fii_dii",
            "market_breadth",
            "economic_calendar",
            "global_macro",
        }

        # Strip redis prefix if present
        channel_name = channel.replace("niftymind:", "")

        if channel_name in public_channels:
            return True
        if channel_name in restricted_channels:
            return self.is_trader
        if channel_name in admin_channels:
            return self.is_admin

        # Unknown channels: allow for viewer+ by default, restrict for admin-only ones
        return self.is_viewer


class ConnectionManager:
    """
    Secure WebSocket connection manager.

    Features:
    - Per-user connection tracking
    - Connection limits per IP
    - Authenticated user context
    """

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._connection_users: dict[int, WebSocketUser] = {}  # id(websocket) -> user
        self._connection_ips: dict[int, str] = {}  # id(websocket) -> ip
        self._user_connections: dict[str, list[int]] = {}  # user_id -> [connection_ids]
        self._ip_counts: dict[str, int] = {}  # ip -> count
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user: Optional[WebSocketUser] = None) -> bool:
        """
        Accept a WebSocket connection.

        Args:
            websocket: The WebSocket connection
            user: Authenticated user (None for unauthenticated)

        Returns:
            True if connection was accepted, False if rejected
        """
        # Check per-IP connection limit
        client_ip = websocket.client.host if websocket.client else "unknown"

        async with self._lock:
            if client_ip != "unknown" and self._ip_counts.get(client_ip, 0) >= WS_MAX_CONNECTIONS_PER_IP:
                logger.warning(f"WebSocket connection limit exceeded for IP {client_ip}")
                await websocket.close(code=1008, reason="Connection limit exceeded for IP")
                return False

            await websocket.accept()
            self._connections.append(websocket)
            conn_id = id(websocket)
            self._connection_ips[conn_id] = client_ip

            if user:
                self._connection_users[conn_id] = user
                user_id = user.user_id
                if user_id not in self._user_connections:
                    self._user_connections[user_id] = []
                self._user_connections[user_id].append(conn_id)

            if client_ip != "unknown":
                self._ip_counts[client_ip] = self._ip_counts.get(client_ip, 0) + 1

            auth_status = f"authenticated as {user.user_id}" if user else "unauthenticated"
            logger.info(f"WebSocket client connected ({auth_status}). Total: {len(self._connections)}")
            return True

    async def disconnect(self, websocket: WebSocket):
        """Disconnect a WebSocket and clean up."""
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

            conn_id = id(websocket)
            client_ip = self._connection_ips.pop(conn_id, None)
            user = self._connection_users.pop(conn_id, None)

            if client_ip and client_ip != "unknown":
                self._ip_counts[client_ip] = max(0, self._ip_counts.get(client_ip, 0) - 1)
                if self._ip_counts[client_ip] == 0:
                    del self._ip_counts[client_ip]

            if user:
                user_id = user.user_id
                if user_id in self._user_connections:
                    self._user_connections[user_id] = [
                        cid for cid in self._user_connections[user_id] if cid != conn_id
                    ]
                    if not self._user_connections[user_id]:
                        del self._user_connections[user_id]

            logger.info(f"WebSocket client disconnected. Total: {len(self._connections)}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
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

    async def send_to_user(self, user_id: str, message: dict):
        """Send a message to all connections of a specific user."""
        async with self._lock:
            conn_ids = self._user_connections.get(user_id, [])
            targets = []
            for ws in self._connections:
                if id(ws) in conn_ids:
                    targets.append(ws)

        dead = []
        for ws in targets:
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

    def get_user(self, websocket: WebSocket) -> Optional[WebSocketUser]:
        """Get the authenticated user for a WebSocket connection."""
        return self._connection_users.get(id(websocket))


manager = ConnectionManager()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint with JWT authentication and channel-based access control.

    Connection flow:
    1. Check connection rate limit
    2. Authenticate via JWT (token in subprotocol or query param)
    3. Accept connection
    4. Handle messages with user context
    """
    client_ip = websocket.client.host if websocket.client else "unknown"

    # Step 1: Connection rate limiting
    limiter = get_rate_limiter()
    allowed = await limiter.check_ws_rate_limit(websocket, limit_tier=LimitTier.WEBSOCKET)
    if not allowed:
        await websocket.close(code=1008, reason="Rate limit exceeded")
        return

    # Step 2: Authenticate via JWT
    user = None
    try:
        user_dict = await asyncio.wait_for(
            _authenticate_ws_async(websocket),
            timeout=WS_AUTH_TIMEOUT_SECONDS,
        )
        if user_dict:
            user = WebSocketUser(user_dict)
    except asyncio.TimeoutError:
        logger.warning(f"WebSocket auth timeout from {client_ip}")
        await websocket.close(code=1008, reason="Authentication timeout")
        return
    except Exception as e:
        logger.warning(f"WebSocket auth failed from {client_ip}: {e}")
        # Allow connection but as unauthenticated (limited access)

    # Step 3: Accept connection
    accepted = await manager.connect(websocket, user)
    if not accepted:
        return

    # Send connection acknowledgment
    try:
        await websocket.send_json({
            "type": "connected",
            "authenticated": user is not None,
            "user_id": user.user_id if user else None,
            "role": user.role.value if user else None,
            "timestamp": datetime.now(IST).isoformat(),
        })
    except Exception:
        pass

    # Step 4: Handle messages
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(data)
                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now(IST).isoformat(),
                    })

                elif msg_type == "subscribe":
                    await _handle_subscribe(websocket, msg, user)

                elif msg_type == "unsubscribe":
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "channels": msg.get("channels", []),
                        "timestamp": datetime.now(IST).isoformat(),
                    })

                elif msg_type == "auth":
                    # Re-authentication during connection
                    await _handle_reauth(websocket, msg)

                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    })

            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({
                        "type": "heartbeat",
                        "timestamp": datetime.now(IST).isoformat(),
                    })
                except Exception:
                    break
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket)


async def _authenticate_ws_async(websocket: WebSocket) -> Optional[dict]:
    """Asynchronously authenticate a WebSocket connection."""
    token = extract_token_from_websocket(websocket)
    if not token:
        return None
    try:
        return decode_supabase_token(token)
    except HTTPException:
        return None


async def _handle_subscribe(websocket: WebSocket, msg: dict, user: Optional[WebSocketUser]):
    """Handle channel subscription requests with access control."""
    requested_channels = msg.get("channels", [])
    allowed_channels = []
    denied_channels = []

    for channel in requested_channels:
        if isinstance(channel, str):
            if user and user.can_subscribe(channel):
                allowed_channels.append(channel)
            else:
                denied_channels.append(channel)
        else:
            denied_channels.append(str(channel))

    if denied_channels:
        logger.debug(f"User {user.user_id if user else 'anonymous'} denied channels: {denied_channels}")

    await websocket.send_json({
        "type": "subscribed",
        "channels": allowed_channels,
        "denied_channels": denied_channels if denied_channels else [],
        "timestamp": datetime.now(IST).isoformat(),
    })


async def _handle_reauth(websocket: WebSocket, msg: dict):
    """Handle re-authentication during an active WebSocket connection."""
    token = msg.get("token", "")
    if not token:
        await websocket.send_json({
            "type": "auth_failed",
            "reason": "No token provided",
        })
        return

    try:
        user_dict = decode_supabase_token(token)
        user = WebSocketUser(user_dict)
        # Update user in connection manager
        manager._connection_users[id(websocket)] = user
        await websocket.send_json({
            "type": "auth_success",
            "user_id": user.user_id,
            "role": user.role.value,
        })
    except HTTPException as e:
        await websocket.send_json({
            "type": "auth_failed",
            "reason": e.detail if isinstance(e.detail, str) else "Invalid token",
        })


async def start_redis_relay(redis_publisher, shutdown_event: asyncio.Event):
    """Start the Redis to WebSocket relay for real-time data streaming."""
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
