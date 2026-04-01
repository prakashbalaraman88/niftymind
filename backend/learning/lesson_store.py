"""Data access layer for trade lessons and agent accuracy in Supabase."""

import json
import logging
import os
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("niftymind.learning.lesson_store")


def _get_conn():
    url = os.getenv("DATABASE_URL", "")
    if not url:
        return None
    try:
        return psycopg2.connect(url)
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        return None


class LessonStore:
    """CRUD for trade_lessons and agent_accuracy tables."""

    def store_lesson(self, lesson: dict) -> bool:
        conn = _get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO trade_lessons
                (trade_id, outcome, pnl, market_regime, underlying, trade_type,
                 direction, vix_at_entry, consensus_score, agents_correct,
                 agents_wrong, agents_neutral, why_won_or_lost, key_factors,
                 what_to_repeat, what_to_avoid, entry_time, exit_time,
                 holding_duration_minutes, tags)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    lesson["trade_id"],
                    lesson["outcome"],
                    lesson.get("pnl", 0),
                    lesson.get("market_regime", "NORMAL"),
                    lesson.get("underlying", ""),
                    lesson.get("trade_type", "INTRADAY"),
                    lesson.get("direction", ""),
                    lesson.get("vix_at_entry"),
                    lesson.get("consensus_score"),
                    json.dumps(lesson.get("agents_correct", [])),
                    json.dumps(lesson.get("agents_wrong", [])),
                    json.dumps(lesson.get("agents_neutral", [])),
                    lesson.get("why_won_or_lost", ""),
                    json.dumps(lesson.get("key_factors", [])),
                    lesson.get("what_to_repeat", ""),
                    lesson.get("what_to_avoid", ""),
                    lesson.get("entry_time"),
                    lesson.get("exit_time"),
                    lesson.get("holding_duration_minutes", 0),
                    json.dumps(lesson.get("tags", [])),
                ),
            )
            conn.commit()
            logger.info(f"Stored lesson for trade {lesson['trade_id']}: {lesson['outcome']}")
            return True
        except Exception as e:
            logger.error(f"Failed to store lesson: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def find_similar_lessons(
        self,
        underlying: str,
        trade_type: str,
        market_regime: str,
        limit: int = 5,
    ) -> list[dict]:
        conn = _get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT outcome, pnl, why_won_or_lost, key_factors,
                          what_to_repeat, what_to_avoid, agents_correct, agents_wrong,
                          consensus_score, vix_at_entry, tags, created_at
                   FROM trade_lessons
                   WHERE underlying = %s AND trade_type = %s AND market_regime = %s
                   ORDER BY created_at DESC LIMIT %s""",
                (underlying, trade_type, market_regime, limit),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to find similar lessons: {e}")
            return []
        finally:
            conn.close()

    def get_recent_lessons(self, days: int = 7, outcome: str | None = None) -> list[dict]:
        conn = _get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            since = datetime.utcnow() - timedelta(days=days)
            if outcome:
                cur.execute(
                    """SELECT * FROM trade_lessons
                       WHERE created_at >= %s AND outcome = %s
                       ORDER BY created_at DESC""",
                    (since, outcome),
                )
            else:
                cur.execute(
                    """SELECT * FROM trade_lessons
                       WHERE created_at >= %s ORDER BY created_at DESC""",
                    (since,),
                )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get recent lessons: {e}")
            return []
        finally:
            conn.close()

    def get_all_lessons_for_training(self) -> list[dict]:
        conn = _get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM trade_lessons ORDER BY created_at")
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get training lessons: {e}")
            return []
        finally:
            conn.close()

    def update_agent_accuracy(
        self, agent_id: str, trade_type: str, market_regime: str,
        was_correct: bool, confidence: float,
    ):
        conn = _get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            # Upsert
            cur.execute(
                """INSERT INTO agent_accuracy
                   (agent_id, trade_type, market_regime, total_signals,
                    correct_signals, accuracy, avg_confidence_when_correct,
                    avg_confidence_when_wrong, weight_multiplier, last_updated)
                   VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, now())
                   ON CONFLICT (agent_id, trade_type, market_regime) DO UPDATE SET
                     total_signals = agent_accuracy.total_signals + 1,
                     correct_signals = agent_accuracy.correct_signals + %s,
                     accuracy = (agent_accuracy.correct_signals + %s)::numeric
                                / (agent_accuracy.total_signals + 1),
                     avg_confidence_when_correct = CASE
                       WHEN %s THEN (agent_accuracy.avg_confidence_when_correct *
                         agent_accuracy.correct_signals + %s) /
                         (agent_accuracy.correct_signals + 1)
                       ELSE agent_accuracy.avg_confidence_when_correct END,
                     avg_confidence_when_wrong = CASE
                       WHEN NOT %s THEN (agent_accuracy.avg_confidence_when_wrong *
                         (agent_accuracy.total_signals - agent_accuracy.correct_signals) + %s) /
                         (agent_accuracy.total_signals - agent_accuracy.correct_signals + 1)
                       ELSE agent_accuracy.avg_confidence_when_wrong END,
                     weight_multiplier = 0.5 + (agent_accuracy.correct_signals + %s)::numeric
                                         / (agent_accuracy.total_signals + 1),
                     last_updated = now()""",
                (
                    agent_id, trade_type, market_regime,
                    1 if was_correct else 0,
                    1.0 if was_correct else 0.0,
                    confidence if was_correct else 0,
                    confidence if not was_correct else 0,
                    1.0 if was_correct else 0.5,
                    # ON CONFLICT params
                    1 if was_correct else 0,
                    1 if was_correct else 0,
                    was_correct, confidence,
                    was_correct, confidence,
                    1 if was_correct else 0,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to update agent accuracy: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_agent_multipliers(
        self, trade_type: str, market_regime: str, min_signals: int = 10,
    ) -> dict[str, float]:
        conn = _get_conn()
        if not conn:
            return {}
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT agent_id, weight_multiplier, total_signals
                   FROM agent_accuracy
                   WHERE trade_type = %s AND market_regime = %s
                     AND total_signals >= %s""",
                (trade_type, market_regime, min_signals),
            )
            return {r["agent_id"]: float(r["weight_multiplier"]) for r in cur.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get agent multipliers: {e}")
            return {}
        finally:
            conn.close()

    def get_lesson_count(self) -> int:
        conn = _get_conn()
        if not conn:
            return 0
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM trade_lessons")
            return cur.fetchone()[0]
        except Exception:
            return 0
        finally:
            conn.close()

    def get_earliest_trade_date(self) -> datetime | None:
        conn = _get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT MIN(created_at) FROM trades")
            result = cur.fetchone()[0]
            return result
        except Exception:
            return None
        finally:
            conn.close()
