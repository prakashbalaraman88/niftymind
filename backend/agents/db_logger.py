import logging
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger("niftymind.db_logger")

IST = timezone(timedelta(hours=5, minutes=30))


def _get_conn():
    import psycopg2
    url = os.getenv("DATABASE_URL", "")
    if not url:
        logger.warning("DATABASE_URL not set, DB logging disabled")
        return None
    try:
        return psycopg2.connect(url)
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        return None


def log_agent_vote(trade_id: str, agent_id: str, direction: str,
                   confidence: float, weight: float, weighted_score: float,
                   reasoning: str, supporting_data: dict | None = None):
    conn = _get_conn()
    if not conn:
        return
    try:
        import json
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO agent_votes (id, trade_id, agent_id, direction, confidence,
               weight, weighted_score, reasoning, supporting_data, voted_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (str(uuid.uuid4()), trade_id, agent_id, direction, confidence,
             weight, weighted_score, reasoning,
             json.dumps(supporting_data) if supporting_data else None,
             datetime.now(IST)),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to log agent vote: {e}")
        conn.rollback()
    finally:
        conn.close()


def log_trade_event(trade_id: str, event: str, status: str,
                    price: float | None = None, quantity: int | None = None,
                    pnl: float | None = None, agent_votes: dict | None = None,
                    consensus_score: float | None = None,
                    risk_approval: str | None = None,
                    risk_reasoning: str | None = None,
                    details: dict | None = None):
    conn = _get_conn()
    if not conn:
        return
    try:
        import json
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO trade_log (id, trade_id, event, status, price, quantity,
               pnl, agent_votes, consensus_score, risk_approval, risk_reasoning,
               details, timestamp)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (str(uuid.uuid4()), trade_id, event, status, price, quantity, pnl,
             json.dumps(agent_votes) if agent_votes else None,
             consensus_score, risk_approval, risk_reasoning,
             json.dumps(details) if details else None,
             datetime.now(IST)),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to log trade event: {e}")
        conn.rollback()
    finally:
        conn.close()


def log_audit(event_type: str, source: str, message: str,
              trade_id: str | None = None, agent_id: str | None = None,
              details: dict | None = None):
    conn = _get_conn()
    if not conn:
        return
    try:
        import json
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO audit_logs (event_type, source, trade_id, agent_id,
               message, details, timestamp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (event_type, source, trade_id, agent_id,
             message, json.dumps(details) if details else None,
             datetime.now(IST)),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to log audit: {e}")
        conn.rollback()
    finally:
        conn.close()


def insert_trade(trade_id: str, symbol: str, underlying: str, direction: str,
                 quantity: int, trade_type: str, consensus_score: float,
                 entry_price: float | None = None,
                 sl_price: float | None = None,
                 target_price: float | None = None,
                 status: str = "PROPOSED"):
    """Insert a new trade row. Uses ON CONFLICT DO NOTHING — caller is responsible
    for uniqueness (e.g., ConsensusOrchestrator creating placeholder rows)."""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO trades (id, trade_id, symbol, underlying, direction,
               entry_price, sl_price, target_price, quantity, status,
               consensus_score, trade_type, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (trade_id) DO NOTHING""",
            (str(uuid.uuid4()), trade_id, symbol, underlying, direction,
             entry_price, sl_price, target_price, quantity, status,
             consensus_score, trade_type, datetime.now(IST), datetime.now(IST)),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to insert trade: {e}")
        conn.rollback()
    finally:
        conn.close()


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
    """Insert or update a trade row. On trade_id conflict, updates status, quantity,
    consensus_score, lifecycle fields (entry_price, sl_price, target_price, exit_price,
    pnl, exit_reason, entry_time, exit_time), and updated_at. Used by RiskManager to
    record final verdicts and by executors to persist full trade lifecycle."""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO trades (id, trade_id, symbol, underlying, direction,
               entry_price, sl_price, target_price, exit_price, quantity, status,
               pnl, exit_reason, consensus_score, trade_type,
               entry_time, exit_time, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                 updated_at = EXCLUDED.updated_at""",
            (str(uuid.uuid4()), trade_id, symbol, underlying, direction,
             entry_price, sl_price, target_price, exit_price, quantity, status,
             pnl, exit_reason, consensus_score, trade_type,
             entry_time, exit_time, datetime.now(IST), datetime.now(IST)),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to upsert trade: {e}")
        conn.rollback()
    finally:
        conn.close()
