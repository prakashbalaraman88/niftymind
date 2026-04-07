"""Post-trade analyzer: Gemini-powered autopsy after every trade closes.

Subscribes to niftymind:trade_closed, analyzes WHY a trade won or lost,
stores structured lessons, and updates agent accuracy scores.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor

from agents.llm_utils import query_llm
from learning.lesson_store import LessonStore

logger = logging.getLogger("niftymind.learning.post_trade_analyzer")

IST = timezone(timedelta(hours=5, minutes=30))

ANALYSIS_PROMPT = """You are analyzing a closed options trade to help an AI trading system learn.
Determine WHY the trade won or lost. Be specific — cite exact factors.

Trade Details:
- Direction: {direction} {underlying} ({trade_type})
- Entry: ₹{entry_price} at {entry_time}
- Exit: ₹{exit_price} at {exit_time}
- PnL: ₹{pnl} ({outcome})
- VIX at entry: {vix}
- Consensus score: {consensus_score}

Agent Votes at Entry:
{agent_votes_text}

Respond in JSON:
{{
  "why_won_or_lost": "2-3 sentence explanation of the primary reason",
  "key_factors": ["factor1", "factor2", "factor3"],
  "agents_correct": ["agent_id1"],
  "agents_wrong": ["agent_id2"],
  "what_to_repeat": "specific actionable lesson to repeat (for wins) or null",
  "what_to_avoid": "specific mistake to avoid (for losses) or null",
  "tags": ["relevant_tag1", "relevant_tag2"]
}}

Tags should include: session time (morning_session/afternoon_session), day type
(expiry_day/normal_day), market condition (trending/ranging/volatile), and any
specific pattern (gap_up/gap_down/vix_spike/earnings_day)."""


class PostTradeAnalyzer:
    """Analyzes every closed trade and stores lessons for future improvement."""

    def __init__(self, redis_publisher, llm_config=None):
        self.publisher = redis_publisher
        self.llm_config = llm_config
        self.lesson_store = LessonStore()

    async def start(self, shutdown_event: asyncio.Event):
        """Subscribe to trade_closed channel and analyze each trade."""
        logger.info("Post-Trade Analyzer starting")

        await self.publisher.subscribe(
            "trade_closed",
            self._on_trade_closed,
        )

        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

    async def _on_trade_closed(self, channel: str, data: dict):
        """Handle a closed trade event."""
        trade_id = data.get("trade_id", "")
        if not trade_id:
            return

        logger.info(f"Analyzing closed trade: {trade_id}")

        try:
            # Get full trade details and agent votes from DB
            trade, votes = self._get_trade_details(trade_id)
            if not trade:
                logger.warning(f"Trade {trade_id} not found in DB")
                return

            # Determine outcome
            pnl = float(trade.get("pnl", 0))
            if pnl > 0:
                outcome = "WIN"
            elif pnl < 0:
                outcome = "LOSS"
            else:
                outcome = "BREAKEVEN"

            # Build agent votes text for the prompt
            votes_lines = []
            for v in votes:
                votes_lines.append(
                    f"  - {v['agent_id']}: {v['direction']} "
                    f"(confidence={v['confidence']:.2f}, weight={v.get('weight', 1.0):.2f}) "
                    f"— {v.get('reasoning', 'no reasoning')[:100]}"
                )
            agent_votes_text = "\n".join(votes_lines) if votes_lines else "  No agent votes recorded"

            # Get VIX (from data or default)
            vix = data.get("vix_at_entry", "N/A")

            # Call Gemini for analysis
            user_msg = ANALYSIS_PROMPT.format(
                direction=trade.get("direction", "UNKNOWN"),
                underlying=trade.get("underlying", ""),
                trade_type=trade.get("trade_type", "INTRADAY"),
                entry_price=trade.get("entry_price", 0),
                entry_time=trade.get("entry_time", ""),
                exit_price=trade.get("exit_price", 0),
                exit_time=trade.get("exit_time", ""),
                pnl=pnl,
                outcome=outcome,
                vix=vix,
                consensus_score=trade.get("consensus_score", 0),
                agent_votes_text=agent_votes_text,
            )

            analysis = await query_llm(
                system_prompt="You are a trading performance analyst. Analyze trades objectively.",
                user_message=user_msg,
                llm_config=self.llm_config,
            )

            # Calculate holding duration
            entry_time = trade.get("entry_time")
            exit_time = trade.get("exit_time")
            holding_minutes = 0
            if entry_time and exit_time:
                try:
                    if isinstance(entry_time, str):
                        entry_time = datetime.fromisoformat(entry_time)
                    if isinstance(exit_time, str):
                        exit_time = datetime.fromisoformat(exit_time)
                    holding_minutes = int((exit_time - entry_time).total_seconds() / 60)
                except Exception:
                    pass

            # Store lesson
            lesson = {
                "trade_id": trade_id,
                "outcome": outcome,
                "pnl": pnl,
                "market_regime": data.get("market_regime", "NORMAL"),
                "underlying": trade.get("underlying", ""),
                "trade_type": trade.get("trade_type", "INTRADAY"),
                "direction": trade.get("direction", ""),
                "vix_at_entry": vix if isinstance(vix, (int, float)) else None,
                "consensus_score": trade.get("consensus_score"),
                "agents_correct": analysis.get("agents_correct", []),
                "agents_wrong": analysis.get("agents_wrong", []),
                "agents_neutral": [],
                "why_won_or_lost": analysis.get("why_won_or_lost", ""),
                "key_factors": analysis.get("key_factors", []),
                "what_to_repeat": analysis.get("what_to_repeat", ""),
                "what_to_avoid": analysis.get("what_to_avoid", ""),
                "entry_time": trade.get("entry_time"),
                "exit_time": trade.get("exit_time"),
                "holding_duration_minutes": holding_minutes,
                "tags": analysis.get("tags", []),
            }

            self.lesson_store.store_lesson(lesson)

            # Update agent accuracy for each voting agent
            # DB uses LONG/SHORT, agents use BULLISH/BEARISH — map between them
            trade_dir = trade.get("direction", "")
            if pnl > 0:
                # Trade won — the trade direction was correct
                winning_direction = "BULLISH" if trade_dir == "LONG" else "BEARISH"
            else:
                # Trade lost — opposite of trade direction was correct
                winning_direction = "BEARISH" if trade_dir == "LONG" else "BULLISH"

            for vote in votes:
                was_correct = vote["direction"] == winning_direction
                self.lesson_store.update_agent_accuracy(
                    agent_id=vote["agent_id"],
                    trade_type=trade.get("trade_type", "INTRADAY"),
                    market_regime=data.get("market_regime", "NORMAL"),
                    was_correct=was_correct,
                    confidence=float(vote.get("confidence", 0.5)),
                )

            logger.info(
                f"Trade {trade_id} analyzed: {outcome} (₹{pnl:+.0f}) — "
                f"{analysis.get('why_won_or_lost', '')[:80]}"
            )

        except Exception as e:
            logger.error(f"Failed to analyze trade {trade_id}: {e}", exc_info=True)

    def _get_trade_details(self, trade_id: str) -> tuple[dict | None, list[dict]]:
        """Fetch trade and agent votes from Supabase."""
        conn = None
        try:
            conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """SELECT trade_id, symbol, underlying, direction, entry_price,
                          exit_price, pnl, status, trade_type, consensus_score,
                          entry_time, exit_time
                   FROM trades WHERE trade_id = %s""",
                (trade_id,),
            )
            trade_row = cur.fetchone()
            trade = dict(trade_row) if trade_row else None

            votes = []
            if trade:
                cur.execute(
                    """SELECT agent_id, direction, confidence, weight, reasoning
                       FROM agent_votes WHERE trade_id = %s""",
                    (trade_id,),
                )
                votes = [dict(r) for r in cur.fetchall()]

            return trade, votes
        except Exception as e:
            logger.error(f"Failed to fetch trade details: {e}")
            return None, []
        finally:
            if conn:
                conn.close()
