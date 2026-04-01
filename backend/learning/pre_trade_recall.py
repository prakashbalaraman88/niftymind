"""Pre-trade recall: retrieve relevant past lessons before new trades.

Called by ConsensusOrchestrator before publishing a trade proposal.
Pure database queries — no LLM calls (must be fast, <200ms).
"""

import logging
from learning.lesson_store import LessonStore

logger = logging.getLogger("niftymind.learning.pre_trade_recall")


class PreTradeRecall:
    """Retrieves relevant historical lessons to inform new trade decisions."""

    def __init__(self):
        self.lesson_store = LessonStore()

    async def get_context(
        self,
        underlying: str,
        trade_type: str,
        market_regime: str,
        direction: str,
    ) -> dict:
        """Build recall context from past similar trades.

        Returns a dict with:
        - similar_count: int
        - win_rate: float (of similar trades)
        - top_lessons: list of compact lesson summaries
        - caution_factors: list of things that caused losses in similar situations
        - confidence_factors: list of things that led to wins
        - recommendation: "PROCEED" | "CAUTION" | "AVOID"
        """
        try:
            lessons = self.lesson_store.find_similar_lessons(
                underlying=underlying,
                trade_type=trade_type,
                market_regime=market_regime,
                limit=10,
            )

            if not lessons:
                return {
                    "similar_count": 0,
                    "win_rate": 0.5,
                    "top_lessons": [],
                    "caution_factors": [],
                    "confidence_factors": [],
                    "recommendation": "PROCEED",
                    "note": "No similar trades in history. Proceeding with default confidence.",
                }

            # Calculate stats
            wins = sum(1 for l in lessons if l.get("outcome") == "WIN")
            losses = sum(1 for l in lessons if l.get("outcome") == "LOSS")
            total = len(lessons)
            win_rate = wins / total if total > 0 else 0.5

            # Extract lessons
            caution_factors = []
            confidence_factors = []
            top_lessons = []

            for lesson in lessons[:5]:
                summary = {
                    "outcome": lesson.get("outcome"),
                    "pnl": float(lesson.get("pnl", 0)),
                    "why": lesson.get("why_won_or_lost", "")[:100],
                    "key_factors": lesson.get("key_factors", []),
                }
                top_lessons.append(summary)

                if lesson.get("outcome") == "LOSS":
                    avoid = lesson.get("what_to_avoid", "")
                    if avoid:
                        caution_factors.append(avoid)
                    factors = lesson.get("key_factors", [])
                    caution_factors.extend(factors[:2])

                elif lesson.get("outcome") == "WIN":
                    repeat = lesson.get("what_to_repeat", "")
                    if repeat:
                        confidence_factors.append(repeat)

            # Determine recommendation
            if total >= 3 and win_rate < 0.3:
                recommendation = "AVOID"
            elif total >= 3 and win_rate < 0.5:
                recommendation = "CAUTION"
            else:
                recommendation = "PROCEED"

            # Deduplicate
            caution_factors = list(set(caution_factors))[:5]
            confidence_factors = list(set(confidence_factors))[:5]

            context = {
                "similar_count": total,
                "win_rate": round(win_rate, 2),
                "wins": wins,
                "losses": losses,
                "top_lessons": top_lessons,
                "caution_factors": caution_factors,
                "confidence_factors": confidence_factors,
                "recommendation": recommendation,
            }

            if recommendation == "AVOID":
                context["note"] = (
                    f"WARNING: Only {wins}/{total} similar trades were profitable. "
                    f"Common loss factors: {', '.join(caution_factors[:3])}"
                )
            elif recommendation == "CAUTION":
                context["note"] = (
                    f"Mixed history: {wins}/{total} wins. Review caution factors."
                )
            else:
                context["note"] = (
                    f"Positive history: {wins}/{total} wins in similar conditions."
                )

            logger.info(
                f"Recall for {underlying}/{trade_type}/{market_regime}: "
                f"{wins}/{total} wins → {recommendation}"
            )

            return context

        except Exception as e:
            logger.error(f"Pre-trade recall failed: {e}")
            return {
                "similar_count": 0,
                "win_rate": 0.5,
                "top_lessons": [],
                "caution_factors": [],
                "confidence_factors": [],
                "recommendation": "PROCEED",
                "note": "Recall system error. Proceeding with default confidence.",
            }
