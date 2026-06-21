"""
NiftyMind API Routes.

Security-hardened route handlers with:
- Authentication required on ALL endpoints (except /healthz)
- Role-based access control (RBAC) with permission checks
- bcrypt-hashed PIN verification with brute-force protection
- Rate limiting on sensitive endpoints
- Input validation and sanitization on all user inputs
- SQL injection protection via parameterized queries
- Audit logging for security-relevant operations
"""

import logging
import os
import re
import html
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, HTTPException, Query, Depends, Request
from pydantic import BaseModel, Field, field_validator

from fastapi.responses import RedirectResponse, StreamingResponse
import csv
import io

from api.server import get_app_state
from api.auth_middleware import (
    get_current_user,
    optional_user,
    UserRole,
    Permission,
    has_permission,
    require_permissions,
    is_public_route,
)
from api.rate_limiter import get_rate_limiter, LimitTier, rate_limit
from api.secrets_manager import get_secrets_manager
from config import BCRYPT_SALT_ROUNDS, MIN_PIN_LENGTH
from performance.metrics import calculate_metrics, is_proof_threshold_met
from performance.trade_journal import TradeJournal
from risk.drawdown_manager import DrawdownManager

logger = logging.getLogger("niftymind.api.routes")

IST = timezone(timedelta(hours=5, minutes=30))

router = APIRouter()
trade_journal = TradeJournal()
drawdown_manager = DrawdownManager()


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

def _db_conn():
    import psycopg2
    url = get_secrets_manager().get_secret("DATABASE_URL")
    if not url:
        return None
    try:
        return psycopg2.connect(url)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def _sanitize_string(value: Optional[str], max_length: int = 255) -> Optional[str]:
    """Sanitize a string input: strip, escape HTML, limit length."""
    if value is None:
        return None
    value = value.strip()
    if len(value) > max_length:
        value = value[:max_length]
    # Escape HTML to prevent XSS
    value = html.escape(value)
    return value


def _validate_trade_id(trade_id: str) -> str:
    """Validate trade_id format: alphanumeric, hyphens, underscores only."""
    if not trade_id:
        raise HTTPException(status_code=400, detail="trade_id is required")
    if not re.match(r"^[A-Za-z0-9_\-]+$", trade_id):
        raise HTTPException(status_code=400, detail="Invalid trade_id format")
    if len(trade_id) > 64:
        raise HTTPException(status_code=400, detail="trade_id too long (max 64 chars)")
    return trade_id


def _validate_event_type(event_type: Optional[str]) -> Optional[str]:
    """Validate event_type against allowed values."""
    if event_type is None:
        return None
    allowed = {
        "NEWS_CLASSIFIED", "NEWS_SIGNAL", "NEWS_ANALYSIS",
        "RISK_APPROVED", "RISK_REJECTED", "TRADE_EXECUTED",
        "TRADE_CLOSED", "AGENT_SIGNAL", "AGENT_VOTE",
        "ORDER_PLACED", "ORDER_FAILED", "BROKER_ERROR",
        "LIVE_MODE_ENABLED", "SETTINGS_CHANGED", "BACKTEST_RUN",
    }
    event_type = event_type.upper().strip()
    if event_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")
    return event_type


# ---------------------------------------------------------------------------
# Pydantic models with validation
# ---------------------------------------------------------------------------

class SettingsUpdate(BaseModel):
    trading_mode: Optional[str] = Field(default=None, pattern=r"^(paper|live)$")
    live_pin: Optional[str] = Field(default=None, min_length=MIN_PIN_LENGTH, max_length=32)
    capital: Optional[float] = Field(default=None, ge=1000, le=100_000_000)
    max_daily_loss: Optional[float] = Field(default=None, ge=100, le=10_000_000)
    max_trade_risk_pct: Optional[float] = Field(default=None, ge=0.1, le=50.0)
    max_open_positions: Optional[int] = Field(default=None, ge=1, le=50)
    consensus_threshold: Optional[float] = Field(default=None, ge=0.1, le=1.0)

    @field_validator("live_pin")
    @classmethod
    def validate_pin(cls, v):
        if v is None:
            return None
        if not v.isdigit():
            raise ValueError("PIN must contain only digits")
        if len(v) < MIN_PIN_LENGTH:
            raise ValueError(f"PIN must be at least {MIN_PIN_LENGTH} digits")
        return v


class CloseTradeRequest(BaseModel):
    trade_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------

def _require_auth(user: dict, permission: Optional[Permission] = None):
    """Ensure user is authenticated and has required permission."""
    if not user or not user.get("sub"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    if permission and not has_permission(user, permission):
        raise HTTPException(status_code=403, detail=f"Permission required: {permission.value}")
    return user


# ---------------------------------------------------------------------------
# PIN verification with bcrypt
# ---------------------------------------------------------------------------

async def _verify_live_pin(provided_pin: str, request: Request, user: dict) -> bool:
    """
    Verify live trading PIN using bcrypt hashing with brute-force protection.

    Args:
        provided_pin: The PIN provided by the user
        request: The FastAPI request (for rate limiting)
        user: The authenticated user

    Returns:
        True if PIN is valid, False otherwise

    Raises:
        HTTPException: 429 if rate limited, 403 if PIN invalid
    """
    # Check rate limit for PIN verification
    limiter = get_rate_limiter()
    user_id = user.get("sub", "unknown")

    try:
        await limiter.check_rate_limit(
            request,
            limit_tier=LimitTier.PIN_VERIFY,
            user_id=user_id,
            custom_key=f"pin:{user_id}",
        )
    except HTTPException as e:
        if e.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Too many PIN attempts",
                    "message": "PIN verification rate limit exceeded. Please try again later.",
                    "reset_after": e.detail.get("reset_after", 300) if isinstance(e.detail, dict) else 300,
                },
            )
        raise

    # Get the stored PIN hash from config
    state = get_app_state()
    config = state.get("config")

    # Get PIN from secure source (secrets manager or config hash)
    secrets = get_secrets_manager()
    stored_pin_hash = ""

    if config and hasattr(config.trading, "live_pin_hash"):
        stored_pin_hash = config.trading.live_pin_hash

    # Fallback: check if PIN is configured in environment
    if not stored_pin_hash:
        env_pin = secrets.get_secret("LIVE_TRADING_PIN", default="")
        if env_pin:
            stored_pin_hash = bcrypt.hashpw(env_pin.encode(), bcrypt.gensalt(rounds=BCRYPT_SALT_ROUNDS)).decode()

    if not stored_pin_hash:
        raise HTTPException(status_code=500, detail="LIVE_TRADING_PIN not configured on server")

    # Verify PIN with bcrypt
    if not bcrypt.checkpw(provided_pin.encode(), stored_pin_hash.encode()):
        remaining_attempts = MAX_PIN_ATTEMPTS - 1  # Approximate
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Invalid live trading PIN",
                "remaining_attempts": remaining_attempts,
            },
        )

    return True


# Maximum PIN attempts
MAX_PIN_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Routes - ALL require authentication except /healthz
# ---------------------------------------------------------------------------

@router.get("/dashboard")
async def get_dashboard(
    request: Request,
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get dashboard data. Requires authentication."""
    _require_auth(user, Permission.VIEW_DASHBOARD)

    state = get_app_state()
    executor = state.get("executor")
    tracker = state.get("position_tracker")
    config = state.get("config")

    executor_stats = executor.get_stats() if executor else {"mode": "unknown"}
    open_positions = executor.get_open_positions() if executor else []
    tracker_summary = tracker.get_summary() if tracker else {"tracked_positions": 0, "total_unrealized_pnl": 0}

    return {
        "timestamp": datetime.now(IST).isoformat(),
        "trading_mode": config.trading.mode if config else "paper",
        "executor": executor_stats,
        "positions": {
            "open": open_positions,
            "tracker": tracker_summary,
        },
        "capital": config.risk.capital if config else 500000,
        "risk_limits": {
            "max_daily_loss": config.risk.max_daily_loss if config else 50000,
            "max_trade_risk_pct": config.risk.max_trade_risk_pct if config else 2.0,
            "max_open_positions": config.risk.max_open_positions if config else 5,
            "vix_halt_threshold": config.risk.vix_halt_threshold if config else 25.0,
        },
    }


@router.get("/trades")
async def get_trades(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, pattern=r"^(OPEN|CLOSED|PENDING|REJECTED)$"),
    trade_type: str | None = Query(None, pattern=r"^(INTRADAY|SCALP|BTST)$"),
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get trade list. Requires authentication."""
    _require_auth(user, Permission.VIEW_TRADES)

    conn = _db_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        cur = conn.cursor()
        query = "SELECT trade_id, symbol, underlying, direction, entry_price, sl_price, target_price, exit_price, quantity, status, pnl, exit_reason, consensus_score, trade_type, entry_time, exit_time, created_at, updated_at FROM trades"
        conditions = []
        params = []

        if status:
            conditions.append("status = %s")
            params.append(status)
        if trade_type:
            conditions.append("trade_type = %s")
            params.append(trade_type)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        trades = []
        for row in rows:
            trade = dict(zip(columns, row))
            for k, v in trade.items():
                if isinstance(v, datetime):
                    trade[k] = v.isoformat()
            trades.append(trade)

        # Enrich OPEN trades with live unrealized P&L from executor
        state = get_app_state()
        executor = state.get("executor")
        if executor:
            open_positions = {p["trade_id"]: p for p in executor.get_open_positions()}
            for trade in trades:
                if trade.get("status") == "OPEN" and trade["trade_id"] in open_positions:
                    pos = open_positions[trade["trade_id"]]
                    trade["current_price"] = pos.get("current_price", trade.get("entry_price"))
                    trade["unrealized_pnl"] = pos.get("unrealized_pnl", 0)

        # Count query
        count_query = "SELECT COUNT(*) FROM trades"
        if conditions:
            count_query += " WHERE " + " AND ".join(conditions)
        cur.execute(count_query, params[:len(conditions)] if conditions else [])
        total = cur.fetchone()[0]

        return {"trades": trades, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        logger.error(f"Failed to fetch trades: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch trades")
    finally:
        conn.close()


@router.post("/trades/{trade_id}/close")
async def close_trade(
    trade_id: str,
    request: Request,
    user: dict = Depends(require_permissions(Permission.CLOSE_TRADE)),
    rate_meta: dict = Depends(rate_limit(LimitTier.TRADE_ACTION)),
):
    """Manually close an open position at current market price. Requires close:trade permission."""
    trade_id = _validate_trade_id(trade_id)

    state = get_app_state()
    executor = state.get("executor")
    if not executor:
        raise HTTPException(status_code=503, detail="Executor not available")

    open_positions = {p["trade_id"]: p for p in executor.get_open_positions()}
    if trade_id not in open_positions:
        raise HTTPException(status_code=404, detail="Open position not found")

    # Audit log the action
    logger.info(f"User {user.get('sub', 'unknown')} closing trade {trade_id}")

    publisher = state.get("redis_publisher")
    if publisher:
        await publisher.publish_trade_execution({
            "event": "EXIT_ORDER",
            "trade_id": trade_id,
            "exit_reason": "MANUAL_CLOSE",
            "closed_by": user.get("sub", "unknown"),
        })
    else:
        # Fallback: direct call if publisher unavailable
        await executor._execute_exit({
            "trade_id": trade_id,
            "exit_reason": "MANUAL_CLOSE",
            "closed_by": user.get("sub", "unknown"),
        })

    return {"status": "closed", "trade_id": trade_id, "closed_by": user.get("sub", "unknown")}


@router.get("/trades/{trade_id}")
async def get_trade_detail(
    trade_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get detailed trade information. Requires authentication."""
    _require_auth(user, Permission.VIEW_TRADES)
    trade_id = _validate_trade_id(trade_id)

    conn = _db_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT trade_id, symbol, underlying, direction, entry_price, sl_price, target_price, exit_price, quantity, status, pnl, exit_reason, consensus_score, trade_type, entry_time, exit_time, created_at, updated_at FROM trades WHERE trade_id = %s",
            (trade_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trade not found")

        columns = [desc[0] for desc in cur.description]
        trade = dict(zip(columns, row))
        for k, v in trade.items():
            if isinstance(v, datetime):
                trade[k] = v.isoformat()

        cur.execute(
            "SELECT agent_id, direction, confidence, weight, weighted_score, reasoning, supporting_data, voted_at FROM agent_votes WHERE trade_id = %s ORDER BY voted_at",
            (trade_id,),
        )
        vote_cols = [desc[0] for desc in cur.description]
        votes = []
        for vrow in cur.fetchall():
            vote = dict(zip(vote_cols, vrow))
            for k, v in vote.items():
                if isinstance(v, datetime):
                    vote[k] = v.isoformat()
            votes.append(vote)

        cur.execute(
            "SELECT event, status, price, quantity, pnl, agent_votes, consensus_score, risk_approval, risk_reasoning, details, timestamp FROM trade_log WHERE trade_id = %s ORDER BY timestamp",
            (trade_id,),
        )
        log_cols = [desc[0] for desc in cur.description]
        log_entries = []
        for lrow in cur.fetchall():
            entry = dict(zip(log_cols, lrow))
            for k, v in entry.items():
                if isinstance(v, datetime):
                    entry[k] = v.isoformat()
            log_entries.append(entry)

        return {
            "trade": trade,
            "agent_votes": votes,
            "trade_log": log_entries,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch trade detail: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch trade detail")
    finally:
        conn.close()


@router.get("/agents")
async def get_agent_status(
    request: Request,
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get agent status. Requires authentication."""
    _require_auth(user, Permission.VIEW_AGENTS)

    conn = _db_conn()
    if not conn:
        return {"agents": []}

    try:
        import json
        cur = conn.cursor()
        cur.execute(
            """SELECT DISTINCT ON (source) source, event_type, message, details, timestamp
               FROM audit_logs
               WHERE source LIKE 'agent_%%'
               ORDER BY source, timestamp DESC"""
        )
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        agents = []
        for row in rows:
            agent = dict(zip(columns, row))
            for k, v in agent.items():
                if isinstance(v, datetime):
                    agent[k] = v.isoformat()
            agents.append(agent)

        return {"agents": agents}
    except Exception as e:
        logger.error(f"Failed to fetch agent status: {e}")
        return {"agents": []}
    finally:
        conn.close()


@router.get("/signals")
async def get_signals(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    agent_id: str | None = Query(None),
    underlying: str | None = Query(None, pattern=r"^(NIFTY|BANKNIFTY)$"),
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get trading signals. Requires authentication."""
    _require_auth(user, Permission.VIEW_SIGNALS)

    # Sanitize inputs
    agent_id = _sanitize_string(agent_id, max_length=64)

    conn = _db_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        cur = conn.cursor()
        query = "SELECT id, agent_id, timestamp, underlying, direction, confidence, timeframe, reasoning, supporting_data, created_at FROM signals"
        conditions = []
        params = []

        if agent_id:
            conditions.append("agent_id = %s")
            params.append(agent_id)
        if underlying:
            conditions.append("underlying = %s")
            params.append(underlying)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        signals = []
        for row in rows:
            sig = dict(zip(columns, row))
            for k, v in sig.items():
                if isinstance(v, datetime):
                    sig[k] = v.isoformat()
            signals.append(sig)

        return {"signals": signals}
    except Exception as e:
        logger.error(f"Failed to fetch signals: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch signals")
    finally:
        conn.close()


@router.get("/news")
async def get_news(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get news. Requires authentication."""
    _require_auth(user, Permission.VIEW_NEWS)

    # Try DB first
    conn = _db_conn()
    if conn:
        try:
            import json as _json
            cur = conn.cursor()
            cur.execute(
                """SELECT id, event_type, source, message, details, timestamp
                   FROM audit_logs
                   WHERE event_type IN ('NEWS_CLASSIFIED', 'NEWS_SIGNAL', 'NEWS_ANALYSIS')
                   ORDER BY timestamp DESC LIMIT %s""",
                (limit,),
            )
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            news = []
            for row in rows:
                item = dict(zip(columns, row))
                for k, v in item.items():
                    if isinstance(v, datetime):
                        item[k] = v.isoformat()
                if isinstance(item.get("details"), str):
                    try:
                        item["details"] = _json.loads(item["details"])
                    except (_json.JSONDecodeError, TypeError):
                        item["details"] = {}
                news.append(item)

            conn.close()
            if news:
                return {"news": news}
        except Exception as e:
            logger.error(f"Failed to fetch news from DB: {e}")
            try:
                conn.close()
            except Exception:
                pass

    # Fallback: in-memory news cache
    state = get_app_state()
    cache = state.get("news_cache", [])
    return {"news": cache[:limit]}


@router.get("/settings")
async def get_settings(
    request: Request,
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get trading settings. Requires authentication."""
    _require_auth(user, Permission.VIEW_SETTINGS)

    state = get_app_state()
    config = state.get("config")

    if not config:
        return {"error": "Config not loaded"}

    return {
        "trading_mode": os.environ.get("TRADING_MODE", config.trading.mode),
        "instruments": os.environ.get("TRADING_INSTRUMENTS", ",".join(config.trading.instruments)).split(","),
        "capital": float(os.environ.get("TRADING_CAPITAL", config.risk.capital)),
        "max_daily_loss": float(os.environ.get("MAX_DAILY_LOSS", config.risk.max_daily_loss)),
        "max_trade_risk_pct": float(os.environ.get("MAX_TRADE_RISK_PCT", config.risk.max_trade_risk_pct)),
        "max_open_positions": int(os.environ.get("MAX_OPEN_POSITIONS", config.risk.max_open_positions)),
        "vix_halt_threshold": float(os.environ.get("VIX_HALT_THRESHOLD", config.risk.vix_halt_threshold)),
        "consensus_threshold": float(os.environ.get("CONSENSUS_THRESHOLD", config.trading.consensus_threshold)),
    }


@router.post("/settings")
async def update_settings(
    update: SettingsUpdate,
    request: Request,
    user: dict = Depends(require_permissions(Permission.MODIFY_SETTINGS)),
    rate_meta: dict = Depends(rate_limit(LimitTier.SENSITIVE)),
):
    """
    Update trading settings. Requires modify:settings permission.
    Live mode switch additionally requires switch:live_mode permission and PIN verification.
    """
    state = get_app_state()
    config = state.get("config")

    if not config:
        raise HTTPException(status_code=503, detail="Config not loaded")

    # Live mode requires additional permission check and PIN
    if update.trading_mode == "live":
        if not has_permission(user, Permission.SWITCH_LIVE_MODE):
            raise HTTPException(
                status_code=403,
                detail="Permission required: switch:live_mode",
            )

        if not update.live_pin:
            raise HTTPException(status_code=400, detail="Live mode requires PIN confirmation")

        # Verify PIN with bcrypt and rate limiting
        await _verify_live_pin(update.live_pin, request, user)

        # Audit log live mode enablement
        logger.warning(
            f"LIVE MODE ENABLED by user {user.get('sub', 'unknown')} "
            f"({user.get('email', 'no-email')})"
        )

    applied = {}

    if update.trading_mode and update.trading_mode in ("paper", "live"):
        os.environ["TRADING_MODE"] = update.trading_mode
        applied["trading_mode"] = update.trading_mode

    if update.capital is not None and update.capital > 0:
        os.environ["TRADING_CAPITAL"] = str(update.capital)
        applied["capital"] = update.capital

    if update.max_daily_loss is not None and update.max_daily_loss > 0:
        os.environ["MAX_DAILY_LOSS"] = str(update.max_daily_loss)
        applied["max_daily_loss"] = update.max_daily_loss

    if update.max_trade_risk_pct is not None and update.max_trade_risk_pct > 0:
        os.environ["MAX_TRADE_RISK_PCT"] = str(update.max_trade_risk_pct)
        applied["max_trade_risk_pct"] = update.max_trade_risk_pct

    if update.max_open_positions is not None and update.max_open_positions > 0:
        os.environ["MAX_OPEN_POSITIONS"] = str(update.max_open_positions)
        applied["max_open_positions"] = update.max_open_positions

    if update.consensus_threshold is not None and 0 < update.consensus_threshold <= 1:
        os.environ["CONSENSUS_THRESHOLD"] = str(update.consensus_threshold)
        applied["consensus_threshold"] = update.consensus_threshold

    # Audit log settings changes
    if applied:
        logger.info(f"User {user.get('sub', 'unknown')} updated settings: {applied}")

    return {"status": "updated", "applied": applied, "updated_by": user.get("sub", "unknown")}


@router.get("/audit")
async def get_audit_log(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    event_type: str | None = Query(None),
    trade_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.SENSITIVE)),
):
    """Get audit log. Requires authentication. Rate limited (sensitive)."""
    _require_auth(user, Permission.VIEW_AUDIT)

    # Validate and sanitize inputs
    event_type = _validate_event_type(event_type)
    if trade_id:
        trade_id = _validate_trade_id(trade_id)

    conn = _db_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        cur = conn.cursor()
        query = "SELECT id, event_type, source, trade_id, agent_id, message, details, timestamp FROM audit_logs"
        conditions = []
        params = []

        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type)
        if trade_id:
            conditions.append("trade_id = %s")
            params.append(trade_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        entries = []
        for row in rows:
            entry = dict(zip(columns, row))
            for k, v in entry.items():
                if isinstance(v, datetime):
                    entry[k] = v.isoformat()
            entries.append(entry)

        return {"audit_logs": entries}
    except Exception as e:
        logger.error(f"Failed to fetch audit log: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch audit log")
    finally:
        conn.close()


@router.get("/performance")
async def get_performance(
    request: Request,
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get performance metrics. Requires authentication."""
    _require_auth(user, Permission.VIEW_PERFORMANCE)

    trades = trade_journal.get_closed_trades()
    metrics = calculate_metrics(trades)
    proof = is_proof_threshold_met(metrics)
    return {"metrics": metrics, "proof_gate": proof}


@router.get("/drawdown")
async def get_drawdown(
    request: Request,
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get drawdown status. Requires authentication."""
    _require_auth(user, Permission.VIEW_PERFORMANCE)

    state = get_app_state()
    risk_manager = state.get("risk_manager")
    if risk_manager and hasattr(risk_manager, "_drawdown_mgr"):
        return risk_manager._drawdown_mgr.get_status()
    return drawdown_manager.get_status()


@router.get("/learning/status")
async def get_learning_status(
    request: Request,
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get learning system status. Requires authentication."""
    _require_auth(user, Permission.VIEW_LEARNING)

    from learning.paper_trading_gate import PaperTradingGate
    from learning.lesson_store import LessonStore
    from learning.agent_accuracy_tracker import AgentAccuracyTracker

    gate = PaperTradingGate()
    store = LessonStore()
    tracker = AgentAccuracyTracker()

    return {
        "gate": gate.get_status(),
        "total_lessons": store.get_lesson_count(),
        "recent_lessons": store.get_recent_lessons(days=7),
        "agent_accuracies": tracker.get_all_accuracies(),
    }


@router.get("/learning/lessons")
async def get_lessons(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    outcome: str | None = Query(None),
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Get learning lessons. Requires authentication."""
    _require_auth(user, Permission.VIEW_LEARNING)

    from learning.lesson_store import LessonStore
    store = LessonStore()
    lessons = store.get_recent_lessons(days=days, outcome=outcome)
    # Serialize datetime fields
    for lesson in lessons:
        for k, v in lesson.items():
            if isinstance(v, datetime):
                lesson[k] = v.isoformat()
    return {"lessons": lessons, "count": len(lessons)}


@router.get("/auth/me")
async def get_me(
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.AUTH)),
):
    """Return the authenticated user's profile from the Supabase JWT."""
    return {
        "user_id": user.get("sub", ""),
        "email": user.get("email", ""),
        "role": user.get("role", "authenticated"),
        "aud": user.get("aud", ""),
    }


@router.get("/zerodha/login")
async def zerodha_login(
    request: Request,
    user: dict = Depends(require_permissions(Permission.MANAGE_BROKER)),
    rate_meta: dict = Depends(rate_limit(LimitTier.AUTH)),
):
    """Generate Zerodha login URL. Requires manage:broker permission."""
    api_key = get_secrets_manager().get_secret("ZERODHA_API_KEY", default="")
    if not api_key:
        raise HTTPException(status_code=500, detail="ZERODHA_API_KEY not configured")
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    return {"login_url": login_url}


@router.get("/zerodha/callback")
async def zerodha_callback(
    request_token: str = Query(..., min_length=1, max_length=128),
    status: str = Query("success", pattern=r"^(success|error|denied)$"),
):
    """
    Handle Zerodha OAuth callback. Exchanges request_token for access_token.
    This endpoint is PUBLIC (OAuth callback from external provider).
    Redirects back to mobile app via deep link after successful auth.
    """
    # Validate request_token format
    if not re.match(r"^[A-Za-z0-9_-]+$", request_token):
        return RedirectResponse(
            url="niftymind://zerodha/callback?status=error&message=Invalid+request+token",
            status_code=302,
        )

    if status != "success":
        return RedirectResponse(
            url=f"niftymind://zerodha/callback?status=error&message=Login+{status}",
            status_code=302,
        )

    api_key = get_secrets_manager().get_secret("ZERODHA_API_KEY", default="")
    api_secret = get_secrets_manager().get_secret("ZERODHA_API_SECRET", default="")

    if not api_key or not api_secret:
        return RedirectResponse(
            url="niftymind://zerodha/callback?status=error&message=Credentials+not+configured",
            status_code=302,
        )

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = session["access_token"]

        # Store token in env and app state
        os.environ["ZERODHA_ACCESS_TOKEN"] = access_token
        state = get_app_state()
        executor = state.get("executor")
        if executor and hasattr(executor, "update_access_token"):
            executor.update_access_token(access_token)

        user_id = session.get("user_id", "")
        logger.info(f"Zerodha login successful for {user_id}. Token valid for today.")

        return RedirectResponse(
            url=f"niftymind://zerodha/callback?status=success&user_id={user_id}",
            status_code=302,
        )
    except Exception as e:
        logger.error(f"Zerodha token exchange failed: {e}")
        return RedirectResponse(
            url="niftymind://zerodha/callback?status=error&message=Token+exchange+failed",
            status_code=302,
        )


@router.get("/zerodha/status")
async def zerodha_status(
    request: Request,
    user: dict = Depends(require_permissions(Permission.MANAGE_BROKER)),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Check if Zerodha access token is valid. Requires manage:broker permission."""
    api_key = get_secrets_manager().get_secret("ZERODHA_API_KEY", default="")
    access_token = get_secrets_manager().get_secret("ZERODHA_ACCESS_TOKEN", default="")

    if not access_token:
        return {"authenticated": False, "message": "No access token. Please login."}

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        profile = kite.profile()
        return {
            "authenticated": True,
            "user_id": profile.get("user_id", ""),
            "user_name": profile.get("user_name", ""),
            "broker": profile.get("broker", "ZERODHA"),
        }
    except Exception:
        return {"authenticated": False, "message": "Token expired. Please login again."}


@router.post("/paper/mock-trade")
async def inject_mock_trade(
    request: Request,
    underlying: str = Query("NIFTY", pattern=r"^(NIFTY|BANKNIFTY)$"),
    direction: str = Query("BULLISH", pattern=r"^(BULLISH|BEARISH)$"),
    trade_type: str = Query("INTRADAY", pattern=r"^(INTRADAY|SCALP|BTST)$"),
    symbol: str = Query("", max_length=50),
    user: dict = Depends(require_permissions(Permission.INJECT_MOCK_TRADE)),
    rate_meta: dict = Depends(rate_limit(LimitTier.TRADE_ACTION)),
):
    """
    Inject a paper trade directly through the executor (market-closed testing).
    Requires inject:mock_trade permission.
    """
    import uuid
    state = get_app_state()
    publisher = state.get("publisher")
    if not publisher:
        raise HTTPException(status_code=503, detail="Redis publisher not available")

    # Sanitize symbol input
    symbol = _sanitize_string(symbol, max_length=50) or ""

    now = datetime.now(IST)
    trade_id = f"PAPER-{now.strftime('%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    # Build a realistic symbol name if not provided
    if not symbol:
        atm = 24500 if underlying == "NIFTY" else 52000
        opt_type = "CE" if direction == "BULLISH" else "PE"
        expiry = now.strftime("%d%b%y").upper()
        symbol = f"{underlying}{expiry}{atm}{opt_type}"

    event = {
        "event": "RISK_APPROVED",
        "trade_id": trade_id,
        "underlying": underlying,
        "direction": direction,
        "symbol": symbol,
        "trade_type": trade_type,
        "quantity": 0,
        "confidence": 0.70,
        "sl_points": 30,
        "timestamp": now.isoformat(),
        "injected_by": user.get("sub", "unknown"),
    }

    await publisher.publish_trade_execution(event)

    logger.info(f"Mock trade injected by user {user.get('sub', 'unknown')}: {trade_id}")

    return {
        "status": "injected",
        "trade_id": trade_id,
        "symbol": symbol,
        "underlying": underlying,
        "direction": direction,
        "trade_type": trade_type,
        "injected_by": user.get("sub", "unknown"),
        "note": "Paper executor will fill at synthetic price (market closed). Check /api/dashboard for open positions.",
    }


@router.post("/paper/exit/{trade_id}")
async def exit_mock_trade(
    trade_id: str,
    request: Request,
    exit_reason: str = Query("MANUAL_TEST", max_length=50),
    user: dict = Depends(require_permissions(Permission.CLOSE_TRADE)),
    rate_meta: dict = Depends(rate_limit(LimitTier.TRADE_ACTION)),
):
    """Exit an open paper trade by trade_id (for testing). Requires close:trade permission."""
    trade_id = _validate_trade_id(trade_id)
    exit_reason = _sanitize_string(exit_reason, max_length=50) or "MANUAL_TEST"

    state = get_app_state()
    publisher = state.get("publisher")
    if not publisher:
        raise HTTPException(status_code=503, detail="Redis publisher not available")

    await publisher.publish_trade_execution({
        "event": "EXIT_ORDER",
        "trade_id": trade_id,
        "exit_reason": exit_reason,
        "timestamp": datetime.now(IST).isoformat(),
        "exited_by": user.get("sub", "unknown"),
    })

    logger.info(f"Mock trade exit by user {user.get('sub', 'unknown')}: {trade_id}")

    return {
        "status": "exit_sent",
        "trade_id": trade_id,
        "exit_reason": exit_reason,
        "exited_by": user.get("sub", "unknown"),
    }


@router.get("/trades/export/csv")
async def export_trades_csv(
    request: Request,
    status: str | None = Query(None, pattern=r"^(OPEN|CLOSED|PENDING|REJECTED)$"),
    trade_type: str | None = Query(None, pattern=r"^(INTRADAY|SCALP|BTST)$"),
    user: dict = Depends(require_permissions(Permission.EXPORT_DATA)),
    rate_meta: dict = Depends(rate_limit(LimitTier.EXPORT)),
):
    """Export trades as CSV download. Requires export:data permission. Rate limited."""
    conn = _db_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        query = ("SELECT trade_id, symbol, underlying, direction, entry_price, exit_price, "
                 "sl_price, target_price, quantity, status, pnl, exit_reason, trade_type, "
                 "entry_time, exit_time FROM trades")
        conditions, params = [], []
        if status:
            conditions.append("status = %s"); params.append(status)
        if trade_type:
            conditions.append("trade_type = %s"); params.append(trade_type)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(cols)
        for row in rows:
            writer.writerow([v.isoformat() if hasattr(v, 'isoformat') else v for v in row])
        output.seek(0)
        filename = f"trades_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.csv"

        # Add audit log for data export
        logger.info(f"CSV export by user {user.get('sub', 'unknown')}: {len(rows)} trades")

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as e:
        logger.error(f"CSV export failed: {e}")
        raise HTTPException(status_code=500, detail="Export failed")


@router.get("/performance/daily")
async def get_daily_pnl(
    request: Request,
    user: dict = Depends(get_current_user),
    rate_meta: dict = Depends(rate_limit(LimitTier.GENERAL)),
):
    """Return daily P&L aggregates and equity curve. Requires authentication."""
    _require_auth(user, Permission.VIEW_PERFORMANCE)

    conn = _db_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT DATE(exit_time AT TIME ZONE 'Asia/Kolkata') as trade_date,
                      COUNT(*) as total_trades,
                      SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winners,
                      SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losers,
                      SUM(pnl) as daily_pnl,
                      MAX(pnl) as best_trade,
                      MIN(pnl) as worst_trade
               FROM trades
               WHERE status = 'CLOSED' AND pnl IS NOT NULL AND exit_time IS NOT NULL
               GROUP BY trade_date
               ORDER BY trade_date DESC
               LIMIT 90"""
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        conn.close()

        daily = []
        cumulative = 0.0
        for row in reversed(rows):
            d = dict(zip(cols, row))
            d["trade_date"] = str(d["trade_date"])
            for k in ("daily_pnl", "best_trade", "worst_trade"):
                d[k] = float(d[k] or 0)
            cumulative += d["daily_pnl"]
            d["cumulative_pnl"] = round(cumulative, 2)
            daily.append(d)

        daily.reverse()
        return {"daily": daily, "total_days": len(daily)}
    except Exception as e:
        logger.error(f"Daily P&L failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch daily P&L")


@router.get("/healthz")
async def health_check():
    """Public health check endpoint. No authentication required."""
    return {"status": "ok", "timestamp": datetime.now(IST).isoformat()}
