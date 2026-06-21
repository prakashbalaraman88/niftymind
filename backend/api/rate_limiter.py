"""
Rate Limiter for NiftyMind Trading Application.

Provides per-endpoint rate limiting with IP-based and user-based tracking.
Uses an in-memory store with sliding window algorithm.
Redis backend can be enabled for distributed deployments.

Features:
- Per-endpoint configurable rate limits
- IP-based and authenticated user-based limiting
- Sliding window counter algorithm
- Custom decorators for FastAPI endpoints
- WebSocket connection rate limiting
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Callable, Any, Tuple
from dataclasses import dataclass, field
from functools import wraps
from enum import Enum

from fastapi import Request, HTTPException, WebSocket
from fastapi.responses import JSONResponse

logger = logging.getLogger("niftymind.rate_limiter")


class LimitTier(Enum):
    """Predefined rate limit tiers."""
    GENERAL = "general"           # 100 req/min
    AUTH = "auth"                 # 10 req/min
    PIN_VERIFY = "pin_verify"     # 5 attempts max
    SENSITIVE = "sensitive"       # 30 req/min
    WEBSOCKET = "websocket"       # 10 connections/min per IP
    EXPORT = "export"             # 5 req/min
    TRADE_ACTION = "trade_action" # 20 req/min


@dataclass
class RateLimit:
    """Rate limit configuration."""
    requests: int
    window_seconds: int
    tier: LimitTier

    @property
    def key_suffix(self) -> str:
        return f"{self.tier.value}:{self.requests}:{self.window_seconds}"


# Predefined rate limits
RATE_LIMITS = {
    LimitTier.GENERAL: RateLimit(requests=100, window_seconds=60, tier=LimitTier.GENERAL),
    LimitTier.AUTH: RateLimit(requests=10, window_seconds=60, tier=LimitTier.AUTH),
    LimitTier.PIN_VERIFY: RateLimit(requests=5, window_seconds=300, tier=LimitTier.PIN_VERIFY),
    LimitTier.SENSITIVE: RateLimit(requests=30, window_seconds=60, tier=LimitTier.SENSITIVE),
    LimitTier.WEBSOCKET: RateLimit(requests=10, window_seconds=60, tier=LimitTier.WEBSOCKET),
    LimitTier.EXPORT: RateLimit(requests=5, window_seconds=60, tier=LimitTier.EXPORT),
    LimitTier.TRADE_ACTION: RateLimit(requests=20, window_seconds=60, tier=LimitTier.TRADE_ACTION),
}


@dataclass
class WindowEntry:
    """Entry in the sliding window."""
    count: int = 0
    window_start: float = field(default_factory=time.time)


class InMemoryRateLimitStore:
    """In-memory sliding window rate limit store."""

    def __init__(self, cleanup_interval: int = 300):
        self._windows: Dict[str, WindowEntry] = {}
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str, limit: RateLimit) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if a request is allowed under the rate limit.

        Returns:
            Tuple of (allowed, metadata) where metadata contains
            remaining requests, reset time, etc.
        """
        async with self._lock:
            now = time.time()

            # Periodic cleanup of expired windows
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired(now)
                self._last_cleanup = now

            window_key = f"{key}:{limit.key_suffix}"
            entry = self._windows.get(window_key)

            if entry is None or now - entry.window_start > limit.window_seconds:
                # New window
                self._windows[window_key] = WindowEntry(count=1, window_start=now)
                return True, {
                    "limit": limit.requests,
                    "remaining": limit.requests - 1,
                    "reset_after": limit.window_seconds,
                    "window": limit.window_seconds,
                }

            if entry.count >= limit.requests:
                reset_after = int(limit.window_seconds - (now - entry.window_start)) + 1
                return False, {
                    "limit": limit.requests,
                    "remaining": 0,
                    "reset_after": max(1, reset_after),
                    "window": limit.window_seconds,
                }

            entry.count += 1
            remaining = limit.requests - entry.count
            reset_after = int(limit.window_seconds - (now - entry.window_start)) + 1
            return True, {
                "limit": limit.requests,
                "remaining": remaining,
                "reset_after": max(1, reset_after),
                "window": limit.window_seconds,
            }

    def _cleanup_expired(self, now: float):
        """Remove expired window entries."""
        expired_keys = []
        # Check all windows and find those that are expired across all possible limit configs
        max_window = max(r.window_seconds for r in RATE_LIMITS.values())
        for key, entry in self._windows.items():
            if now - entry.window_start > max_window * 2:
                expired_keys.append(key)
        for key in expired_keys:
            del self._windows[key]
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired rate limit windows")

    async def get_current_count(self, key: str, limit: RateLimit) -> int:
        """Get current request count for a key within the active window."""
        async with self._lock:
            window_key = f"{key}:{limit.key_suffix}"
            entry = self._windows.get(window_key)
            if entry is None:
                return 0
            now = time.time()
            if now - entry.window_start > limit.window_seconds:
                return 0
            return entry.count

    def clear_key(self, key: str):
        """Clear all rate limit windows for a specific key."""
        keys_to_remove = [k for k in self._windows if k.startswith(f"{key}:")]
        for k in keys_to_remove:
            del self._windows[k]


class RateLimiter:
    """
    Rate limiter with support for IP-based and user-based limiting.
    """

    def __init__(self, store: Optional[InMemoryRateLimitStore] = None):
        self._store = store or InMemoryRateLimitStore()

    def _get_client_key(self, request: Request, user_id: Optional[str] = None) -> str:
        """
        Build a rate limit key from the request.

        Priority:
        1. Authenticated user ID (if provided)
        2. X-Forwarded-For header (for proxied requests)
        3. X-Real-IP header
        4. Direct client IP
        """
        if user_id:
            return f"user:{user_id}"

        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Take the first IP in the chain
            client_ip = forwarded.split(",")[0].strip()
            return f"ip:{client_ip}"

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return f"ip:{real_ip}"

        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"

    async def check_rate_limit(
        self,
        request: Request,
        limit_tier: LimitTier = LimitTier.GENERAL,
        user_id: Optional[str] = None,
        custom_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check if the request is within rate limits.

        Args:
            request: The FastAPI request
            limit_tier: The rate limit tier to apply
            user_id: Optional authenticated user ID for user-based limiting
            custom_key: Optional custom key override

        Returns:
            Rate limit metadata

        Raises:
            HTTPException: 429 if rate limit exceeded
        """
        limit = RATE_LIMITS[limit_tier]
        key = custom_key or self._get_client_key(request, user_id)

        allowed, metadata = await self._store.is_allowed(key, limit)

        if not allowed:
            logger.warning(
                f"Rate limit exceeded for {key} on tier {limit_tier.value}: "
                f"{limit.requests} requests per {limit.window_seconds}s"
            )
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": metadata["limit"],
                    "reset_after": metadata["reset_after"],
                    "window_seconds": metadata["window"],
                },
            )

        return metadata

    async def check_ws_rate_limit(
        self,
        websocket: WebSocket,
        limit_tier: LimitTier = LimitTier.WEBSOCKET,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Check WebSocket connection rate limit.

        Returns True if connection is allowed, False otherwise.
        """
        limit = RATE_LIMITS[limit_tier]

        # Build key from WebSocket connection info
        if user_id:
            key = f"user:{user_id}"
        else:
            client_ip = websocket.client.host if websocket.client else "unknown"
            key = f"ip:{client_ip}"

        allowed, _ = await self._store.is_allowed(key, limit)
        if not allowed:
            logger.warning(f"WebSocket rate limit exceeded for {key}")
        return allowed

    def get_store(self) -> InMemoryRateLimitStore:
        """Get the underlying rate limit store."""
        return self._store


# Global singleton
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the global rate limiter singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def reset_rate_limiter():
    """Reset the global rate limiter singleton."""
    global _rate_limiter
    _rate_limiter = None


# FastAPI dependency factories
def rate_limit(tier: LimitTier = LimitTier.GENERAL):
    """
    FastAPI dependency for rate limiting.

    Usage:
        @router.get("/endpoint")
        async def my_endpoint(rate=Depends(rate_limit(LimitTier.GENERAL))):
            ...
    """
    async def _check(request: Request) -> Dict[str, Any]:
        limiter = get_rate_limiter()

        # Try to get user ID from request state (set by auth middleware)
        user_id = None
        if hasattr(request.state, "user") and request.state.user:
            user_id = request.state.user.get("sub")

        return await limiter.check_rate_limit(request, limit_tier=tier, user_id=user_id)

    return _check


def require_rate_limit(tier: LimitTier = LimitTier.GENERAL):
    """
    Decorator-style rate limiter for use with Depends.
    This version enforces the limit and raises 429 if exceeded.
    """
    return rate_limit(tier)
