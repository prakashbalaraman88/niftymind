"""
NiftyMind API Server.

Security-hardened FastAPI server with:
- Strict CORS policy (explicit origins only, no wildcards)
- Rate limiting middleware
- Request ID tracking
- Secure lifecycle management
"""

import logging
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import (
    ALLOWED_ORIGINS,
    ALLOW_CREDENTIALS,
    ALLOW_METHODS,
    ALLOW_HEADERS,
)
from api.rate_limiter import get_rate_limiter, LimitTier

logger = logging.getLogger("niftymind.api")

_app_state = {}


def get_app_state():
    return _app_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI server starting")
    yield
    logger.info("FastAPI server shutting down")


class RateLimitMiddleware:
    """
    Global rate limiting middleware applied to all incoming requests.

    Applies different rate limit tiers based on request path:
    - Auth endpoints: strict limits
    - Export/sensitive: moderate limits
    - General: standard limits
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path
        method = request.method

        # Skip rate limiting for OPTIONS (CORS preflight)
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # Determine rate limit tier based on path
        limit_tier = self._get_limit_tier(path, method)

        try:
            limiter = get_rate_limiter()
            metadata = await limiter.check_rate_limit(request, limit_tier=limit_tier)

            # Store rate limit info in scope for response headers
            scope["rate_limit_metadata"] = metadata

        except HTTPException as e:
            if e.status_code == 429:
                response_body = e.detail if isinstance(e.detail, dict) else {"error": e.detail}
                response = JSONResponse(
                    status_code=429,
                    content=response_body,
                    headers={
                        "Retry-After": str(response_body.get("reset_after", 60)),
                        "X-RateLimit-Limit": str(response_body.get("limit", 100)),
                        "X-RateLimit-Remaining": "0",
                    },
                )
                await response(scope, receive, send)
                return
            raise

        await self.app(scope, receive, send)

    def _get_limit_tier(self, path: str, method: str) -> LimitTier:
        """Determine rate limit tier based on request path and method."""
        # Auth endpoints
        if path.startswith("/api/auth"):
            return LimitTier.AUTH

        # Settings modifications (especially live mode switch)
        if path == "/api/settings" and method == "POST":
            return LimitTier.SENSITIVE

        # Trade actions (close, inject, exit)
        if path.startswith("/api/trades/") and method == "POST":
            return LimitTier.TRADE_ACTION
        if path.startswith("/api/paper/"):
            return LimitTier.TRADE_ACTION

        # Export endpoints
        if path.startswith("/api/trades/export"):
            return LimitTier.EXPORT

        # Broker management
        if path.startswith("/api/zerodha/"):
            return LimitTier.SENSITIVE

        # Default
        return LimitTier.GENERAL


class RequestIDMiddleware:
    """
    Attach a unique request ID to each incoming request for tracing.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope["request_id"] = request_id

        # Wrap send to add request ID header to response
        original_send = send

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"x-request-id", request_id.encode()])

                # Add rate limit headers if available
                rate_meta = scope.get("rate_limit_metadata")
                if rate_meta:
                    headers.append([b"x-ratelimit-limit", str(rate_meta["limit"]).encode()])
                    headers.append([b"x-ratelimit-remaining", str(rate_meta["remaining"]).encode()])

                message["headers"] = headers
            await original_send(message)

        await self.app(scope, receive, send_with_headers)


class SecurityHeadersMiddleware:
    """
    Add security headers to all responses.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        original_send = send

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                security_headers = [
                    [b"x-content-type-options", b"nosniff"],
                    [b"x-frame-options", b"DENY"],
                    [b"x-xss-protection", b"1; mode=block"],
                    [b"referrer-policy", b"strict-origin-when-cross-origin"],
                    [b"permissions-policy", b"accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"],
                ]
                headers.extend(security_headers)
                message["headers"] = headers
            await original_send(message)

        await self.app(scope, receive, send_with_security_headers)


def create_app(
    executor=None,
    position_tracker=None,
    redis_publisher=None,
    config=None,
) -> FastAPI:
    app = FastAPI(
        title="NiftyMind API",
        version="1.0.0",
        description="Multi-agent AI options trading system for NSE Nifty 50 & BankNifty",
        lifespan=lifespan,
        docs_url=None,      # Disable Swagger UI in production (security)
        redoc_url=None,     # Disable ReDoc in production (security)
        openapi_url=None,   # Disable OpenAPI schema in production (security)
    )

    # CORS: Strict origin whitelist - NO wildcards allowed
    # Only https://niftymind.app, https://app.niftymind.app, and localhost:3000
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=ALLOW_CREDENTIALS,
        allow_methods=ALLOW_METHODS,
        allow_headers=ALLOW_HEADERS,
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
        max_age=600,  # 10 minutes preflight cache
    )

    # Security middleware stack (order matters - applied in reverse)
    # These are ASGI middleware so they wrap the app directly
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RateLimitMiddleware)

    _app_state["executor"] = executor
    _app_state["position_tracker"] = position_tracker
    _app_state["publisher"] = redis_publisher
    _app_state["redis_publisher"] = redis_publisher
    _app_state["config"] = config
    _app_state["news_cache"] = []  # In-memory news cache (fallback when DB unavailable)

    from api.routes import router
    app.include_router(router, prefix="/api")

    from api.websocket_handler import ws_router
    app.include_router(ws_router)

    return app
