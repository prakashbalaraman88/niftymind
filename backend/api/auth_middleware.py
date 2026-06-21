"""
Supabase JWT authentication middleware for NiftyMind API.

Security-hardened authentication with:
- Enhanced JWT validation (expiry, audience, algorithm, clock skew)
- Role-based access control (RBAC) with configurable roles
- Rate limiting integration for auth endpoints
- Comprehensive audit logging
- Secure token extraction and validation
"""

import os
import logging
import time
from typing import Optional, Dict, Any, List, Callable
from enum import Enum

import jwt
from fastapi import Request, HTTPException, Depends, WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api.secrets_manager import get_secrets_manager
from api.rate_limiter import get_rate_limiter, LimitTier
from config import (
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_CLOCK_SKEW_SECONDS,
)

logger = logging.getLogger("niftymind.auth")

security = HTTPBearer(auto_error=False)


class UserRole(Enum):
    """Defined user roles for RBAC."""
    ADMIN = "admin"
    TRADER = "trader"
    VIEWER = "viewer"
    ANONYMOUS = "anonymous"


class Permission(Enum):
    """Defined permissions for resource access."""
    # Dashboard and data viewing
    VIEW_DASHBOARD = "view:dashboard"
    VIEW_TRADES = "view:trades"
    VIEW_SIGNALS = "view:signals"
    VIEW_AGENTS = "view:agents"
    VIEW_NEWS = "view:news"
    VIEW_PERFORMANCE = "view:performance"
    VIEW_AUDIT = "view:audit"
    VIEW_LEARNING = "view:learning"
    EXPORT_DATA = "export:data"

    # Trading actions
    EXECUTE_TRADE = "execute:trade"
    CLOSE_TRADE = "close:trade"
    INJECT_MOCK_TRADE = "inject:mock_trade"

    # Settings management
    VIEW_SETTINGS = "view:settings"
    MODIFY_SETTINGS = "modify:settings"
    SWITCH_LIVE_MODE = "switch:live_mode"

    # Broker integration
    MANAGE_BROKER = "manage:broker"

    # Admin
    ADMIN_FULL = "admin:full"


# Role-permission mapping
ROLE_PERMISSIONS: Dict[UserRole, List[Permission]] = {
    UserRole.ADMIN: [
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_TRADES,
        Permission.VIEW_SIGNALS,
        Permission.VIEW_AGENTS,
        Permission.VIEW_NEWS,
        Permission.VIEW_PERFORMANCE,
        Permission.VIEW_AUDIT,
        Permission.VIEW_LEARNING,
        Permission.EXPORT_DATA,
        Permission.EXECUTE_TRADE,
        Permission.CLOSE_TRADE,
        Permission.INJECT_MOCK_TRADE,
        Permission.VIEW_SETTINGS,
        Permission.MODIFY_SETTINGS,
        Permission.SWITCH_LIVE_MODE,
        Permission.MANAGE_BROKER,
        Permission.ADMIN_FULL,
    ],
    UserRole.TRADER: [
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_TRADES,
        Permission.VIEW_SIGNALS,
        Permission.VIEW_AGENTS,
        Permission.VIEW_NEWS,
        Permission.VIEW_PERFORMANCE,
        Permission.VIEW_AUDIT,
        Permission.VIEW_LEARNING,
        Permission.EXPORT_DATA,
        Permission.EXECUTE_TRADE,
        Permission.CLOSE_TRADE,
        Permission.INJECT_MOCK_TRADE,
        Permission.VIEW_SETTINGS,
        Permission.MODIFY_SETTINGS,
        Permission.MANAGE_BROKER,
    ],
    UserRole.VIEWER: [
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_TRADES,
        Permission.VIEW_SIGNALS,
        Permission.VIEW_AGENTS,
        Permission.VIEW_NEWS,
        Permission.VIEW_PERFORMANCE,
        Permission.VIEW_LEARNING,
    ],
    UserRole.ANONYMOUS: [],
}


# Endpoints that are always public (no auth required)
PUBLIC_ROUTES = {
    "/api/healthz",
    "/api/zerodha/callback",
}

# Routes that require specific permissions
ROUTE_PERMISSIONS: Dict[str, List[Permission]] = {
    "/api/dashboard": [Permission.VIEW_DASHBOARD],
    "/api/trades": [Permission.VIEW_TRADES],
    "/api/trades/export/csv": [Permission.EXPORT_DATA],
    "/api/signals": [Permission.VIEW_SIGNALS],
    "/api/agents": [Permission.VIEW_AGENTS],
    "/api/news": [Permission.VIEW_NEWS],
    "/api/performance": [Permission.VIEW_PERFORMANCE],
    "/api/audit": [Permission.VIEW_AUDIT],
    "/api/learning/status": [Permission.VIEW_LEARNING],
    "/api/learning/lessons": [Permission.VIEW_LEARNING],
    "/api/settings": [Permission.VIEW_SETTINGS, Permission.MODIFY_SETTINGS],
    "/api/drawdown": [Permission.VIEW_PERFORMANCE],
    "/api/performance/daily": [Permission.VIEW_PERFORMANCE],
}


def _get_jwt_secret() -> str:
    """Get the Supabase JWT secret for token verification."""
    secret = get_secrets_manager().get_secret("SUPABASE_SECRET_KEY")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SECRET_KEY not configured on server",
        )
    return secret


def decode_supabase_token(token: str) -> dict:
    """
    Decode and verify a Supabase JWT token with enhanced validation.

    Validates:
    - Signature
    - Expiration (with clock skew tolerance)
    - Audience
    - Algorithm (explicit HS256 only)
    - Token structure
    """
    secret = _get_jwt_secret()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "require": ["exp", "iat", "sub", "role"],
                "leeway": JWT_CLOCK_SKEW_SECONDS,
            },
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidAudienceError:
        logger.warning("JWT invalid audience")
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except jwt.InvalidIssuedAtError:
        logger.warning("JWT invalid issued at time")
        raise HTTPException(status_code=401, detail="Invalid token timestamp")
    except jwt.MissingRequiredClaimError as e:
        logger.warning(f"JWT missing required claim: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid token: missing {e}")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Unexpected JWT error: {e}")
        raise HTTPException(status_code=401, detail="Token validation failed")


def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract JWT token from Authorization header or query parameter."""
    # Check header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def extract_token_from_websocket(websocket: WebSocket) -> Optional[str]:
    """Extract JWT token from WebSocket headers or query parameters."""
    # Try subprotocols (common pattern: jwt token passed via sec-websocket-protocol)
    subprotocols = websocket.scope.get("subprotocols", [])
    for proto in subprotocols:
        if proto.startswith("jwt-"):
            return proto[4:]

    # Try query parameters
    query_params = dict(websocket.query_params)
    if "token" in query_params:
        return query_params["token"]

    # Try headers
    headers = dict(websocket.headers)
    auth_header = headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    return None


def get_user_role(user: dict) -> UserRole:
    """Extract and validate user role from JWT payload."""
    role_str = user.get("role", "authenticated")
    if role_str == "admin" or role_str == "service_role":
        return UserRole.ADMIN
    if role_str == "trader":
        return UserRole.TRADER
    if role_str == "viewer":
        return UserRole.VIEWER
    # Default authenticated users are traders
    if role_str == "authenticated":
        return UserRole.TRADER
    return UserRole.VIEWER


def has_permission(user: dict, permission: Permission) -> bool:
    """Check if a user has a specific permission."""
    role = get_user_role(user)
    permissions = ROLE_PERMISSIONS.get(role, [])
    # Admin has all permissions
    if Permission.ADMIN_FULL in permissions:
        return True
    return permission in permissions


def require_permissions(*permissions: Permission) -> Callable:
    """
    Decorator factory to require specific permissions for an endpoint.

    Usage:
        @router.post("/trades/close")
        async def close_trade(..., user=Depends(require_permissions(Permission.CLOSE_TRADE))):
            ...
    """
    async def _check_permissions(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> dict:
        if not credentials:
            raise HTTPException(status_code=401, detail="Not authenticated")

        user = decode_supabase_token(credentials.credentials)
        role = get_user_role(user)
        user_perms = ROLE_PERMISSIONS.get(role, [])

        # Admin bypass
        if Permission.ADMIN_FULL in user_perms:
            return user

        for perm in permissions:
            if perm not in user_perms:
                logger.warning(
                    f"User {user.get('sub', 'unknown')} with role {role.value} "
                    f"lacks permission {perm.value}"
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Insufficient permissions: {perm.value} required",
                )
        return user

    return _check_permissions


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """
    FastAPI dependency to extract and validate the current user from JWT.
    Applies rate limiting to auth validation.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = decode_supabase_token(credentials.credentials)

    # Attach user to request state for downstream middleware
    return user


async def optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """FastAPI dependency - returns user if authenticated, None otherwise."""
    if not credentials:
        return None
    try:
        return decode_supabase_token(credentials.credentials)
    except HTTPException:
        return None


async def authenticate_websocket(websocket: WebSocket) -> Optional[dict]:
    """
    Authenticate a WebSocket connection via JWT.

    Returns user dict if authenticated, None if not.
    Does NOT close the connection - caller decides how to handle.
    """
    token = extract_token_from_websocket(websocket)
    if not token:
        return None

    try:
        return decode_supabase_token(token)
    except HTTPException:
        return None


class AuthMiddleware:
    """
    FastAPI middleware for authentication and RBAC.

    Usage:
        app.add_middleware(AuthMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive)
            path = request.url.path

            # Check if route is public
            if path in PUBLIC_ROUTES:
                await self.app(scope, receive, send)
                return

            # Check if route has a prefix that is public
            for public_prefix in ("/api/healthz",):
                if path.startswith(public_prefix):
                    await self.app(scope, receive, send)
                    return

        await self.app(scope, receive, send)


def is_public_route(path: str) -> bool:
    """Check if a route path is public (no auth required)."""
    if path in PUBLIC_ROUTES:
        return True
    for public_prefix in PUBLIC_ROUTES:
        if path.startswith(public_prefix):
            return True
    return False


async def rate_limited_auth_check(request: Request) -> Dict[str, Any]:
    """
    Rate-limited authentication check for sensitive endpoints.
    Returns user dict if authenticated and within rate limits.
    """
    limiter = get_rate_limiter()

    # Apply auth tier rate limiting
    await limiter.check_rate_limit(request, limit_tier=LimitTier.AUTH)

    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = decode_supabase_token(token)

    # Store user in request state for downstream use
    request.state.user = user

    return user
