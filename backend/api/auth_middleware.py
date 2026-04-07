"""
Supabase JWT authentication middleware for NiftyMind API.

Verifies the Supabase access token from the Authorization header
using the Supabase JWT secret (SUPABASE_SECRET_KEY).
"""

import os
import logging
from typing import Optional

import jwt
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("niftymind.auth")

security = HTTPBearer(auto_error=False)

# Routes that don't require authentication
PUBLIC_ROUTES = {
    "/api/healthz",
    "/api/zerodha/callback",  # OAuth callback from Zerodha
}


def _get_jwt_secret() -> str:
    """Get the Supabase JWT secret for token verification."""
    secret = os.getenv("SUPABASE_SECRET_KEY", "")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SECRET_KEY not configured on server",
        )
    return secret


def decode_supabase_token(token: str) -> dict:
    """Decode and verify a Supabase JWT token."""
    secret = _get_jwt_secret()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """FastAPI dependency to extract and validate the current user from JWT."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return decode_supabase_token(credentials.credentials)


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
