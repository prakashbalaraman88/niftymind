import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("niftymind.db_logger")

IST = timezone(timedelta(hours=5, minutes=30))

# Write-Ahead Log: trades that failed DB persistence are saved here
_WAL_DIR = Path(os.path.dirname(__file__)).parent / "data" / "wal"
_WAL_DIR.mkdir(parents=True, exist_ok=True)
_WAL_FILE = _WAL_DIR / "pending_trades.jsonl"

_MAX_RETRIES = 3
_RETRY_DELAY = 2  # seconds between retries

_db_fail_count = 0
_db_fail_lock = threading.Lock()


def get_db_fail_count() -> int:
    return _db_fail_count


def _get_conn():
    import psycopg2
    url = os.getenv("DATABASE_URL", "")
    if not url:
        logger.warning("DATABASE_URL not set, DB logging disabled")
        return None
    try:
        return psycopg2.connect(url, connect_timeout=10)
    except Exception as e:
        global _db_fail_count
        with _db_fail_lock:
            _db_fail_count += 1
        logger.error(f"DB connection failed (total failures: {_db_fail_count}): {e}")
        return None


def _execute_with_retry(func_name: str, sql: str, params: tuple, max_retries: int = _MAX_RETRIES) -> bool:
    """Execute SQL with retry logic. Returns True if successful."""
    global _db_fail_count
    for attempt in range(1, max_retries + 1):
        conn = _get_conn()
        if not conn:
            if attempt < max_retries:
                time.sleep(_RETRY_DELAY)
            continue
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            return True
        except Exception as e:
            with _db_fail_lock:
                _db_fail_count += 1
            logger.error(f"{func_name} attempt {attempt}/{max_retries} failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            if attempt < max_retries:
                time.sleep(_RETRY_DELAY)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return False


def _write_to_wal(operation: str, data: dict):
    """Append failed trade data to WAL file for later recovery."""
    try:
        entry = {"operation": operation, "data": data, "timestamp": datetime.now(IST).isoformat()}
        with open(_WAL_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.warning(f"Trade written to WAL for recovery: {operation} {data.get('trade_id', '?')}")
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to write WAL — trade may be lost: {e}")


def replay_wal():
    """Replay pending WAL entries. Call on startup."""
    if not _WAL_FILE.exists():
        return
    try:
        with open(_WAL_FILE, "r") as f:
            lines = f.readlines()
        if not lines:
            return
        logger.info(f"Replaying {len(lines)} WAL entries...")
        remaining = []
        for line in lines:
            try:
                entry = json.loads(line.strip())
                op = entry["operation"]
                data = entry["data"]
                if op == "upsert_trade":
                    upsert_trade(**data)
                elif op == "insert_trade":
                    insert_trade(**data)
                # If we get here without exception, it succeeded
            except Exception as e:
                logger.error(f"WAL replay failed for entry: {e}")
                remaining.append(line)
        # Rewrite WAL with only failed entries
        with open(_WAL_FILE, "w") as f:
            f.writelines(remaining)
        replayed = len(lines) - len(remaining)
        logger.info(f"WAL replay complete: {replayed} succeeded, {len(remaining)} still pending")
    except Exception as e:
        logger.error(f"WAL replay error: {e}")


def log_agent_vote(trade_id: str, agent_id: str, direction: str,
                   confidence: float, weight: float, weighted_score: float,
                   reasoning: str, supporting_data: dict | None = None):
    sql = """INSERT INTO agent_votes (trade_id, agent_id, direction, confidence,
               weight, weighted_score, reasoning, supporting_data, voted_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    params = (trade_id, agent_id, direction, confidence,
              weight, weighted_score, reasoning,
              json.dumps(supporting_data) if supporting_data else None,
              datetime.now(IST))
    _execute_with_retry("log_agent_vote", sql, params, max_retries=2)


def log_trade_event(trade_id: str, event: str, status: str,
                    price: float | None = None, quantity: int | None = None,
                    pnl: float | None = None, agent_votes: dict | None = None,
                    consensus_score: float | None = None,
                    risk_approval: str | None = None,
                    risk_reasoning: str | None = None,
                    details: dict | None = None):
    sql = """INSERT INTO trade_log (trade_id, event, status, price, quantity,
               pnl, agent_votes, consensus_score, risk_approval, risk_reasoning,
               details, timestamp)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    params = (trade_id, event, status, price, quantity, pnl,
              json.dumps(agent_votes) if agent_votes else None,
              consensus_score, risk_approval, risk_reasoning,
              json.dumps(details) if details else None,
              datetime.now(IST))
    _execute_with_retry("log_trade_event", sql, params, max_retries=2)


def log_audit(event_type: str, source: str, message: str,
              trade_id: str | None = None, agent_id: str | None = None,
              details: dict | None = None):
    sql = """INSERT INTO audit_logs (event_type, source, trade_id, agent_id,
               message, details, timestamp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)"""
    params = (event_type, source, trade_id, agent_id,
              message, json.dumps(details) if details else None,
              datetime.now(IST))
    _execute_with_retry("log_audit", sql, params, max_retries=1)


def insert_trade(trade_id: str, symbol: str, underlying: str, direction: str,
                 quantity: int, trade_type: str, consensus_score: float,
                 entry_price: float | None = None,
                 sl_price: float | None = None,
                 target_price: float | None = None,
                 status: str = "PROPOSED"):
    sql = """INSERT INTO trades (trade_id, symbol, underlying, direction,
               entry_price, sl_price, target_price, quantity, status,
               consensus_score, trade_type, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (trade_id) DO NOTHING"""
    params = (trade_id, symbol, underlying, direction,
              entry_price, sl_price, target_price, quantity, status,
              consensus_score, trade_type, datetime.now(IST), datetime.now(IST))
    success = _execute_with_retry("insert_trade", sql, params)
    if not success:
        _write_to_wal("insert_trade", {
            "trade_id": trade_id, "symbol": symbol, "underlying": underlying,
            "direction": direction, "quantity": quantity, "trade_type": trade_type,
            "consensus_score": consensus_score, "entry_price": entry_price,
            "sl_price": sl_price, "target_price": target_price, "status": status,
        })


def upsert_trade(trade_id: str, symbol: str, underlying: str, direction: str,
                 quantity: int, trade_type: str, consensus_score: float,
                 entry_price: float | None = None,
                 sl_price: float | None = None,
                 target_price: float | None = None,
                 exit_price: float | None = None,
                 pnl: float | None = None,
                 exit_reason: str | None = None,
                 entry_time: str | None = None,
                 exit_time: str | None = None,
                 status: str = "PROPOSED"):
    sql = """INSERT INTO trades (trade_id, symbol, underlying, direction,
               entry_price, sl_price, target_price, exit_price, quantity, status,
               pnl, exit_reason, consensus_score, trade_type,
               entry_time, exit_time, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (trade_id) DO UPDATE SET
                 status = EXCLUDED.status,
                 quantity = EXCLUDED.quantity,
                 consensus_score = CASE WHEN EXCLUDED.consensus_score > 0 THEN EXCLUDED.consensus_score ELSE trades.consensus_score END,
                 entry_price = COALESCE(EXCLUDED.entry_price, trades.entry_price),
                 sl_price = COALESCE(EXCLUDED.sl_price, trades.sl_price),
                 target_price = COALESCE(EXCLUDED.target_price, trades.target_price),
                 exit_price = COALESCE(EXCLUDED.exit_price, trades.exit_price),
                 pnl = COALESCE(EXCLUDED.pnl, trades.pnl),
                 exit_reason = COALESCE(EXCLUDED.exit_reason, trades.exit_reason),
                 entry_time = COALESCE(EXCLUDED.entry_time, trades.entry_time),
                 exit_time = COALESCE(EXCLUDED.exit_time, trades.exit_time),
                 updated_at = EXCLUDED.updated_at"""
    params = (trade_id, symbol, underlying, direction,
              entry_price, sl_price, target_price, exit_price, quantity, status,
              pnl, exit_reason, consensus_score, trade_type,
              entry_time, exit_time, datetime.now(IST), datetime.now(IST))
    success = _execute_with_retry("upsert_trade", sql, params)
    if not success:
        _write_to_wal("upsert_trade", {
            "trade_id": trade_id, "symbol": symbol, "underlying": underlying,
            "direction": direction, "quantity": quantity, "trade_type": trade_type,
            "consensus_score": consensus_score, "entry_price": entry_price,
            "sl_price": sl_price, "target_price": target_price,
            "exit_price": exit_price, "pnl": pnl, "exit_reason": exit_reason,
            "entry_time": entry_time, "exit_time": exit_time, "status": status,
        })
