import logging
import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from fastapi.responses import RedirectResponse

from api.server import get_app_state
from api.auth_middleware import get_current_user, optional_user
from performance.metrics import calculate_metrics, is_proof_threshold_met
from performance.trade_journal import TradeJournal
from risk.drawdown_manager import DrawdownManager

logger = logging.getLogger("niftymind.api.routes")

IST = timezone(timedelta(hours=5, minutes=30))

router = APIRouter()

trade_journal = TradeJournal()
drawdown_manager = DrawdownManager()


def _db_conn():
    import psycopg2
    url = os.getenv("DATABASE_URL", "")
    if not url:
        return None
    try:
        return psycopg2.connect(url)
    except Exception:
        return None


class SettingsUpdate(BaseModel):
    trading_mode: str | None = None
    live_pin: str | None = None
    capital: float | None = None
    max_daily_loss: float | None = None
    max_trade_risk_pct: float | None = None
    max_open_positions: int | None = None
    consensus_threshold: float | None = None


@router.get("/dashboard")
async def get_dashboard():
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
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    trade_type: str | None = Query(None),
):
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

        cur.execute("SELECT COUNT(*) FROM trades" + (" WHERE " + " AND ".join(conditions[:len(conditions)]) if conditions else ""), params[:len(conditions)] if conditions else [])
        total = cur.fetchone()[0]

        return {"trades": trades, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        logger.error(f"Failed to fetch trades: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch trades")
    finally:
        conn.close()


@router.post("/trades/{trade_id}/close")
async def close_trade(trade_id: str):
    """Manually close an open position at current market price."""
    state = get_app_state()
    executor = state.get("executor")
    if not executor:
        raise HTTPException(status_code=503, detail="Executor not available")

    open_positions = {p["trade_id"]: p for p in executor.get_open_positions()}
    if trade_id not in open_positions:
        raise HTTPException(status_code=404, detail="Open position not found")

    await executor._execute_exit({
        "trade_id": trade_id,
        "exit_reason": "MANUAL_CLOSE",
    })

    return {"status": "closed", "trade_id": trade_id}


@router.get("/trades/{trade_id}")
async def get_trade_detail(trade_id: str):
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
async def get_agent_status():
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
    limit: int = Query(50, ge=1, le=500),
    agent_id: str | None = Query(None),
    underlying: str | None = Query(None),
):
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
async def get_news(limit: int = Query(20, ge=1, le=100)):
    conn = _db_conn()
    if not conn:
        return {"news": []}

    try:
        import json
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
            # Parse details JSON string into dict for frontend
            if isinstance(item.get("details"), str):
                try:
                    item["details"] = json.loads(item["details"])
                except (json.JSONDecodeError, TypeError):
                    item["details"] = {}
            news.append(item)

        return {"news": news}
    except Exception as e:
        logger.error(f"Failed to fetch news: {e}")
        return {"news": []}
    finally:
        conn.close()


@router.get("/settings")
async def get_settings():
    state = get_app_state()
    config = state.get("config")

    if not config:
        return {"error": "Config not loaded"}

    # Read live values from env (POST /settings writes to env, not to frozen config)
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
async def update_settings(update: SettingsUpdate):
    state = get_app_state()
    config = state.get("config")

    if not config:
        raise HTTPException(status_code=503, detail="Config not loaded")

    if update.trading_mode == "live":
        if not update.live_pin:
            raise HTTPException(status_code=400, detail="Live mode requires PIN confirmation")
        # Re-read .env to pick up LIVE_TRADING_PIN even if added after server start
        from dotenv import dotenv_values
        fresh_env = dotenv_values()
        expected_pin = (
            os.environ.get("LIVE_TRADING_PIN")
            or fresh_env.get("LIVE_TRADING_PIN")
            or config.trading.live_pin
        )
        if not expected_pin:
            raise HTTPException(status_code=500, detail="LIVE_TRADING_PIN not configured on server")
        if update.live_pin != expected_pin:
            raise HTTPException(status_code=403, detail="Invalid live trading PIN")

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

    return {"status": "updated", "applied": applied}


@router.get("/audit")
async def get_audit_log(
    limit: int = Query(50, ge=1, le=500),
    event_type: str | None = Query(None),
    trade_id: str | None = Query(None),
):
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
async def get_performance():
    trades = trade_journal.get_closed_trades()
    metrics = calculate_metrics(trades)
    proof = is_proof_threshold_met(metrics)
    return {"metrics": metrics, "proof_gate": proof}


@router.get("/drawdown")
async def get_drawdown():
    return drawdown_manager.get_status()


@router.get("/learning/status")
async def get_learning_status():
    """Get learning system status: gate, model, agent accuracy."""
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
    days: int = Query(7, ge=1, le=90),
    outcome: str | None = Query(None),
):
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
async def get_me(user: dict = Depends(get_current_user)):
    """Return the authenticated user's profile from the Supabase JWT."""
    return {
        "user_id": user.get("sub", ""),
        "email": user.get("email", ""),
        "role": user.get("role", "authenticated"),
        "aud": user.get("aud", ""),
    }


@router.get("/zerodha/login")
async def zerodha_login():
    """Generate Zerodha login URL. User opens this in browser to authenticate."""
    api_key = os.getenv("ZERODHA_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ZERODHA_API_KEY not configured")
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    return {"login_url": login_url}


@router.get("/zerodha/callback")
async def zerodha_callback(request_token: str = Query(...), status: str = Query("success")):
    """Handle Zerodha OAuth callback. Exchanges request_token for access_token.
    Redirects back to mobile app via deep link after successful auth."""
    if status != "success":
        # Redirect back to app with error
        return RedirectResponse(
            url=f"niftymind://zerodha/callback?status=error&message=Login+failed",
            status_code=302,
        )

    api_key = os.getenv("ZERODHA_API_KEY", "")
    api_secret = os.getenv("ZERODHA_API_SECRET", "")

    if not api_key or not api_secret:
        return RedirectResponse(
            url=f"niftymind://zerodha/callback?status=error&message=Credentials+not+configured",
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

        # Redirect back to mobile app with success
        return RedirectResponse(
            url=f"niftymind://zerodha/callback?status=success&user_id={user_id}",
            status_code=302,
        )
    except Exception as e:
        logger.error(f"Zerodha token exchange failed: {e}")
        return RedirectResponse(
            url=f"niftymind://zerodha/callback?status=error&message=Token+exchange+failed",
            status_code=302,
        )


@router.get("/zerodha/status")
async def zerodha_status():
    """Check if Zerodha access token is valid."""
    api_key = os.getenv("ZERODHA_API_KEY", "")
    access_token = os.getenv("ZERODHA_ACCESS_TOKEN", "")

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
    underlying: str = Query("NIFTY", regex="^(NIFTY|BANKNIFTY)$"),
    direction: str = Query("BULLISH", regex="^(BULLISH|BEARISH)$"),
    trade_type: str = Query("INTRADAY", regex="^(INTRADAY|SCALP|BTST)$"),
    symbol: str = Query(""),
):
    """Inject a paper trade directly through the executor (market-closed testing).

    Publishes a RISK_APPROVED event to niftymind:trade_executions so the
    PaperExecutor picks it up exactly as it would from the live pipeline.
    Falls back to synthetic prices when no tick data is available.
    """
    import uuid
    state = get_app_state()
    publisher = state.get("publisher")
    if not publisher:
        raise HTTPException(status_code=503, detail="Redis publisher not available")

    now = datetime.now(IST)
    trade_id = f"PAPER-{now.strftime('%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    # Build a realistic symbol name if not provided
    if not symbol:
        # e.g. NIFTY24500CE or BANKNIFTY52000PE
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
        "quantity": 0,          # paper executor fills from lot size
        "confidence": 0.70,
        "sl_points": 30,
        "timestamp": now.isoformat(),
    }

    await publisher.publish_trade_execution(event)

    return {
        "status": "injected",
        "trade_id": trade_id,
        "symbol": symbol,
        "underlying": underlying,
        "direction": direction,
        "trade_type": trade_type,
        "note": "Paper executor will fill at synthetic price (market closed). Check /api/dashboard for open positions.",
    }


@router.post("/paper/exit/{trade_id}")
async def exit_mock_trade(trade_id: str, exit_reason: str = Query("MANUAL_TEST")):
    """Exit an open paper trade by trade_id (for testing)."""
    state = get_app_state()
    publisher = state.get("publisher")
    if not publisher:
        raise HTTPException(status_code=503, detail="Redis publisher not available")

    await publisher.publish_trade_execution({
        "event": "EXIT_ORDER",
        "trade_id": trade_id,
        "exit_reason": exit_reason,
        "timestamp": datetime.now(IST).isoformat(),
    })

    return {"status": "exit_sent", "trade_id": trade_id, "exit_reason": exit_reason}


@router.get("/healthz")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(IST).isoformat()}
