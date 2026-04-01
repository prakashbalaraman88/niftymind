"""NiftyMind Self-Improving Learning System.

Components:
- PostTradeAnalyzer: Gemini-powered trade autopsy after every close
- LessonStore: CRUD for structured lessons in Supabase
- PreTradeRecall: Retrieve relevant past lessons before new trades
- AgentAccuracyTracker: Track per-agent hit rates, adjust consensus weights
- TradeOutcomeModel: Lightweight GradientBoosting model for win probability
- DailyRetrainer: End-of-day batch retraining + accuracy recalculation
- PaperTradingGate: Enforce 5-day warmup period
"""
