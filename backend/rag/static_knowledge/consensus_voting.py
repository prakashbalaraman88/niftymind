"""
Expert Knowledge: Multi-Agent Consensus and Signal Aggregation

Sources: Prediction market research, ensemble learning theory,
Bayesian inference, wisdom of crowds literature.
"""
from . import KnowledgeChunk

DOMAIN = "consensus_voting"

CHUNKS = [
    KnowledgeChunk(
        domain=DOMAIN,
        source="Wisdom of Crowds + Prediction Market Research",
        title="Multi-Agent Signal Aggregation Theory and Weight Assignment",
        content="""
WISDOM OF CROWDS (James Surowiecki, 2004):
  Core finding: Aggregation of diverse, independent judgments beats individual experts.
  Requirements for crowd wisdom:
  1. DIVERSITY: Each agent must use different data/methodology (✓ in NiftyMind).
  2. INDEPENDENCE: Agents must not influence each other (✓ via Redis pub/sub isolation).
  3. DECENTRALIZATION: Agents specialize in their domain (✓ domain isolation).
  4. AGGREGATION: Weighted consensus mechanism.

ENSEMBLE LEARNING ANALOGY:
  Multi-agent voting ≈ ensemble machine learning (boosting, bagging, stacking).
  Random forest: Many decision trees, each with different features. Vote by majority.
  Key lesson: Models that are individually 60% accurate can reach 80%+ in ensemble IF:
    - Errors are UNCORRELATED (each model fails in different conditions).
    - All base models are BETTER than random (> 50% accuracy).

BAYESIAN SIGNAL COMBINATION:
  Prior: Base probability (e.g., 50-50 market direction).
  Likelihood ratio: Signal confidence from each agent.
  Posterior: Updated probability after combining all signals.

  Example:
  Prior: 50% bullish.
  Agent 1 (Options, 0.70 confidence bullish): Posterior = 65% bullish.
  Agent 4 (Technical, 0.65 confidence bullish): Posterior = 75% bullish.
  Agent 5 (Sentiment, 0.55 confidence bullish): Posterior = 80% bullish.
  Above 65% posterior (threshold): Execute trade.

WEIGHT ASSIGNMENT PRINCIPLES:
  Higher weight = more reliable signal in this trade type's context.
  SCALP: Order flow dominates (most immediate, real-time signal).
  INTRADAY: Balanced — no single agent dominates.
  BTST: Macro and sentiment dominate (overnight positioning context).
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Signal Quality and Confidence Interpretation",
        title="Interpreting Agent Confidence Scores and Consensus Thresholds",
        content="""
CONFIDENCE SCORE INTERPRETATION (0.0 - 1.0 scale):

0.0-0.30: LOW confidence. Agent sees no clear signal. Market is ambiguous.
          Weight this agent's vote heavily discounted.
0.30-0.50: MILD confidence. Slight lean in one direction. Uncertain.
           Don't trade on this alone. Consider as weak supporting evidence.
0.50-0.65: MODERATE confidence. Agent has a reasonable thesis.
           Good supporting signal when combined with others.
0.65-0.80: HIGH confidence. Agent sees clear directional evidence.
           This signal MOVES THE NEEDLE on final consensus score.
0.80-1.00: VERY HIGH confidence. Agent is strongly convinced.
           Extremely rare in real markets. Treat 0.85+ with extra scrutiny
           (overconfidence can indicate agent malfunction or data anomaly).

CONSENSUS THRESHOLD LOGIC:
  Weighted score = Σ(agent_confidence × agent_direction_sign × agent_weight)
  Direction sign: BULLISH = +1, BEARISH = -1, NEUTRAL = 0.
  Final score range: -1.0 to +1.0.

  Score > +0.65: STRONG BUY. Execute with full position size.
  Score 0.40 to 0.65: WEAK BUY. Execute with half size, or wait for confirmation.
  Score -0.40 to +0.40: NEUTRAL. Do NOT trade. Market unclear.
  Score -0.40 to -0.65: WEAK SELL. Execute short with half size.
  Score < -0.65: STRONG SELL. Execute short with full position size.

MINIMUM AGENT COUNT REQUIREMENTS:
  SCALP: Minimum 3 agents (order flow + 2 others). Missing technical = dealbreaker.
  INTRADAY: Minimum 5 of 7 agents. Below 5 = insufficient data.
  BTST: Minimum 6 of 7 agents (including BOTH macro and sentiment).
  If agents are absent/stale: Lower threshold, reduce confidence by 0.10 per missing agent.

SIGNAL STALENESS:
  Signal TTL:
  - Scalp: 60 seconds (market changes fast).
  - Intraday: 300 seconds (5 minutes).
  - BTST: 600 seconds (10 minutes, using EOD data).
  Stale signal = reduce its weight by 50%. Expired = remove from consensus.
        """,
    ),
    KnowledgeChunk(
        domain=DOMAIN,
        source="Conflict Resolution in Multi-Agent Systems",
        title="Handling Contradictory Signals and Edge Case Scenarios",
        content="""
SIGNAL CONFLICT RESOLUTION FRAMEWORK:

SCENARIO 1 — Two HIGH-CONFIDENCE contradictory signals:
  Options Chain: 0.80 BULLISH
  Order Flow: 0.75 BEARISH
  Resolution: NEUTRAL. These are the two most real-time signals. Contradiction = uncertainty.
  Action: Do NOT trade. Wait for signals to converge.

SCENARIO 2 — Majority weak signals + one strong opposing signal:
  5 agents: 0.50-0.60 BULLISH
  1 agent (Macro): 0.80 BEARISH (global risk-off)
  Resolution: Lean toward the STRONG signal. Market structure may be bullish but macro is warning.
  Action: Reduce position size by 50%, tighten stop.

SCENARIO 3 — All signals NEUTRAL:
  6 of 7 agents: NEUTRAL, confidence 0.30-0.40.
  Resolution: Market is in accumulation/distribution phase. No directional edge.
  Action: Skip all trades. Wait for next signal cycle.

SCENARIO 4 — News Agent flags avoid_trading:
  Overrides ALL other signals. Trading window blocked.
  Even if 6 of 7 agents are 0.80 BULLISH, News Agent's avoid_trading = VETO.
  This is a hard stop, not a suggestion.

SCENARIO 5 — India VIX spike during consensus:
  Risk Manager raises VIX halt flag (VIX > 25).
  All trade proposals blocked regardless of consensus score.
  Resolution: Even perfect consensus cannot override VIX halt.

SCENARIO 6 — Rapidly changing signals:
  Agent changes direction multiple times in 1 minute (e.g., BULLISH → NEUTRAL → BEARISH).
  Resolution: Use smoothed signal = weighted average of last 3 signals per agent.
  Rapidly changing signals = high uncertainty = reduce all position sizes.
        """,
    ),
]
