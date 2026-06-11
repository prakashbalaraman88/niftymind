"""Lightweight GradientBoosting model for trade win probability prediction.

Features: market conditions + agent signals → binary win/loss prediction.
Retrained daily by DailyRetrainer. Returns 0.5 when insufficient data.
"""

import io
import logging
import os
import pickle
from datetime import datetime

import numpy as np

logger = logging.getLogger("niftymind.learning.trade_outcome_model")

FEATURE_NAMES = [
    "vix_at_entry",
    "consensus_score",
    "is_scalp",
    "is_intraday",
    "is_btst",
    "is_nifty",
    "is_banknifty",
    "direction_sign",  # 1 = BULLISH, -1 = BEARISH
    "hour_of_day",
    "agent_1_confidence",
    "agent_2_confidence",
    "agent_3_confidence",
    "agent_4_confidence",
    "agent_5_confidence",
    "agent_6_confidence",
    "agent_7_confidence",
    "agent_1_agrees",
    "agent_2_agrees",
    "agent_3_agrees",
    "agent_4_agrees",
    "agent_5_agrees",
    "agent_6_agrees",
    "agent_7_agrees",
    "num_agents_reporting",
]

AGENT_ID_MAP = {
    "agent_1_options_chain": 1,
    "agent_2_order_flow": 2,
    "agent_3_volume_profile": 3,
    "agent_4_technical": 4,
    "agent_5_sentiment": 5,
    "agent_6_news": 6,
    "agent_7_macro": 7,
}

AGENT_NUM_TO_ID = {f"agent_{n}": aid for aid, n in AGENT_ID_MAP.items()}

MIN_TRAINING_SAMPLES = 50

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
MODEL_FILE = os.path.join(MODEL_DIR, "latest.pkl")

MODEL_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS model_snapshots (
    id SERIAL PRIMARY KEY,
    model_version INTEGER NOT NULL,
    training_trades INTEGER,
    accuracy DOUBLE PRECISION,
    precision_val DOUBLE PRECISION,
    recall_val DOUBLE PRECISION,
    f1_score DOUBLE PRECISION,
    feature_importances JSONB,
    model_blob BYTEA,
    created_at TIMESTAMPTZ DEFAULT NOW()
)
"""


class TradeOutcomeModel:
    """Predicts trade win probability using GradientBoosting."""

    def __init__(self):
        self._model = None
        self._scaler = None
        self._model_version = 0
        self._is_loaded = False

    def load_latest(self) -> bool:
        """Load the latest model: Supabase first, local file fallback."""
        if self._load_from_db():
            return True
        return self._load_from_file()

    def _load_from_db(self) -> bool:
        import psycopg2

        try:
            conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
            cur = conn.cursor()
            cur.execute(
                """SELECT model_version, model_blob
                   FROM model_snapshots
                   ORDER BY created_at DESC LIMIT 1"""
            )
            row = cur.fetchone()
            conn.close()

            if row and row[1]:
                blob = bytes(row[1])
                data = pickle.loads(blob)
                self._model = data["model"]
                self._scaler = data.get("scaler")
                self._model_version = row[0]
                self._is_loaded = True
                logger.info(f"Loaded model v{self._model_version} from DB")
                return True
            logger.info("No model snapshot in DB.")
            return False
        except Exception as e:
            logger.error(f"Failed to load model from DB: {e}")
            return False

    def _load_from_file(self) -> bool:
        try:
            if not os.path.exists(MODEL_FILE):
                logger.info("No local model file. Will return default predictions.")
                return False
            with open(MODEL_FILE, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._scaler = data.get("scaler")
            self._model_version = int(data.get("version", 1))
            self._is_loaded = True
            logger.info(f"Loaded model v{self._model_version} from local file")
            return True
        except Exception as e:
            logger.error(f"Failed to load model from file: {e}")
            return False

    def predict(self, proposal: dict) -> float:
        """Predict win probability for a trade proposal. Returns 0.5 if no model.

        Accepts either the full consensus proposal (preferred — has underlying,
        direction and the votes list) or a bare supporting_data dict.
        """
        if not self._is_loaded or self._model is None:
            return 0.5

        try:
            supporting = proposal.get("supporting_data", proposal)
            votes = supporting.get("votes") or []
            if not votes and supporting.get("agent_votes"):
                # Legacy dict format {"agent_1": {...}}
                votes = [
                    {"agent_id": AGENT_NUM_TO_ID.get(k, k), **v}
                    for k, v in supporting["agent_votes"].items()
                ]

            trade_like = {
                "vix_at_entry": supporting.get("vix_at_entry", 15),
                "consensus_score": supporting.get("consensus_score",
                                                  proposal.get("confidence", 0.5)),
                "trade_type": supporting.get("trade_type",
                                             proposal.get("timeframe", "INTRADAY")),
                "underlying": proposal.get("underlying",
                                           supporting.get("underlying", "")),
                "direction": proposal.get("direction",
                                          supporting.get("direction", "BULLISH")),
                "entry_time": datetime.now().isoformat(),
                "votes": votes,
            }
            features = self._extract_features_from_trade(trade_like)
            X = np.array([features])
            if self._scaler:
                X = self._scaler.transform(X)
            proba = self._model.predict_proba(X)[0]
            # proba[1] = probability of class 1 (win)
            return float(proba[1]) if len(proba) > 1 else 0.5
        except Exception as e:
            logger.warning(f"Prediction failed: {e}")
            return 0.5

    def train(self, trades_with_votes: list[dict]) -> dict | None:
        """Train on accumulated trade data. Returns metrics or None if insufficient data."""
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

        if len(trades_with_votes) < MIN_TRAINING_SAMPLES:
            logger.info(
                f"Only {len(trades_with_votes)} trades. "
                f"Need {MIN_TRAINING_SAMPLES} to train. Skipping."
            )
            return None

        # Per-type chronological split: within each trade type the holdout is
        # strictly in the future of its training window (no lookahead leakage),
        # while the train/test TYPE mix stays comparable — different types have
        # very different history depths (BTST: years of daily bars; SCALP: ~60
        # days of 5m bars), so a single global time cut would make the test set
        # all-recent-intraday and measure distribution shift, not skill.
        def _entry_key(t):
            return str(t.get("entry_time") or "")

        by_type: dict[str, list[dict]] = {}
        for t in trades_with_votes:
            by_type.setdefault(t.get("trade_type", "INTRADAY"), []).append(t)

        train_trades: list[dict] = []
        test_trades: list[dict] = []
        for tt_trades in by_type.values():
            tt_sorted = sorted(tt_trades, key=_entry_key)
            cut = max(1, int(len(tt_sorted) * 0.8))
            train_trades.extend(tt_sorted[:cut])
            test_trades.extend(tt_sorted[cut:])

        def _features_and_labels(trades):
            X_rows, labels = [], []
            for trade in trades:
                X_rows.append(self._extract_features_from_trade(trade))
                labels.append(1 if float(trade.get("pnl", 0)) > 0 else 0)
            return np.array(X_rows), np.array(labels)

        X_train, y_train = _features_and_labels(train_trades)
        X_test, y_test = _features_and_labels(test_trades)
        if len(X_test) == 0 or len(set(y_train.tolist())) < 2:
            logger.info("Not enough class diversity for training. Skipping.")
            return None

        # Scale
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # Train — conservative settings: shallow trees, subsampling and a low
        # learning rate generalize better on noisy market data than the
        # previous deeper/faster configuration.
        model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=2,
            min_samples_leaf=20,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )
        model.fit(X_train_scaled, y_train)

        # Evaluate
        y_pred = model.predict(X_test_scaled)
        try:
            auc = float(roc_auc_score(y_test, model.predict_proba(X_test_scaled)[:, 1]))
        except Exception:
            auc = 0.5
        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "auc": auc,
            "baseline_win_rate": float(np.mean(y_test)),
            "test_trades": int(len(y_test)),
            "training_trades": len(trades_with_votes),
            "feature_importances": {
                name: float(imp)
                for name, imp in zip(FEATURE_NAMES, model.feature_importances_)
            },
        }

        # Save
        self._model = model
        self._scaler = scaler
        self._model_version += 1
        self._is_loaded = True

        # Persist to DB
        self._save_snapshot(metrics)

        logger.info(
            f"Model v{self._model_version} trained: "
            f"accuracy={metrics['accuracy']:.2f}, f1={metrics['f1']:.2f}, "
            f"trades={len(trades_with_votes)}"
        )

        return metrics

    def _save_snapshot(self, metrics: dict):
        """Persist the model: local file always, Supabase when reachable."""
        import json
        import psycopg2

        blob = pickle.dumps({"model": self._model, "scaler": self._scaler})

        # Local file — survives DB outages, used as load fallback
        try:
            os.makedirs(MODEL_DIR, exist_ok=True)
            with open(MODEL_FILE, "wb") as f:
                pickle.dump(
                    {"model": self._model, "scaler": self._scaler,
                     "version": self._model_version, "metrics": metrics,
                     "saved_at": datetime.now().isoformat()},
                    f,
                )
            logger.info(f"Model v{self._model_version} saved to {MODEL_FILE}")
        except Exception as e:
            logger.error(f"Failed to save model file: {e}")

        try:
            conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
            cur = conn.cursor()
            cur.execute(MODEL_SNAPSHOTS_DDL)
            cur.execute(
                """INSERT INTO model_snapshots
                   (model_version, training_trades, accuracy, precision_val,
                    recall_val, f1_score, feature_importances, model_blob)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    self._model_version,
                    metrics["training_trades"],
                    metrics["accuracy"],
                    metrics["precision"],
                    metrics["recall"],
                    metrics["f1"],
                    json.dumps(metrics["feature_importances"]),
                    psycopg2.Binary(blob),
                ),
            )
            conn.commit()
            conn.close()
            logger.info(f"Model v{self._model_version} snapshot saved to DB")
        except Exception as e:
            logger.error(f"Failed to save model snapshot to DB: {e}")

    def _extract_features(self, supporting_data: dict) -> list[float]:
        """Extract features from a trade proposal's supporting_data."""
        trade_type = supporting_data.get("trade_type", "INTRADAY")
        underlying = supporting_data.get("underlying", "")
        direction = supporting_data.get("direction", "BULLISH")
        agent_votes = supporting_data.get("agent_votes", {})

        features = [
            float(supporting_data.get("vix_at_entry", 15)),
            float(supporting_data.get("consensus_score", 0.5)),
            1.0 if trade_type == "SCALP" else 0.0,
            1.0 if trade_type == "INTRADAY" else 0.0,
            1.0 if trade_type == "BTST" else 0.0,
            1.0 if "NIFTY" in underlying and "BANK" not in underlying else 0.0,
            1.0 if "BANKNIFTY" in underlying else 0.0,
            1.0 if direction == "BULLISH" else -1.0,
            float(supporting_data.get("hour_of_day", 12)),
        ]

        # Agent confidences and agreement
        num_reporting = 0
        for i in range(1, 8):
            agent_key = f"agent_{i}"
            vote = agent_votes.get(agent_key, {})
            conf = float(vote.get("confidence", 0))
            agrees = 1.0 if vote.get("direction") == direction and conf > 0 else 0.0
            features.append(conf)
            if conf > 0:
                num_reporting += 1

        for i in range(1, 8):
            agent_key = f"agent_{i}"
            vote = agent_votes.get(agent_key, {})
            agrees = 1.0 if vote.get("direction") == direction else 0.0
            features.append(agrees)

        features.append(float(num_reporting))

        return features

    def _extract_features_from_trade(self, trade: dict) -> list[float]:
        """Extract features from a historical trade record (for training)."""
        trade_type = trade.get("trade_type", "INTRADAY")
        underlying = trade.get("underlying", "")
        direction = trade.get("direction", "BULLISH")
        votes = trade.get("votes", [])

        entry_time = trade.get("entry_time")
        hour = 12
        if entry_time:
            try:
                if isinstance(entry_time, str):
                    from datetime import datetime as dt
                    entry_time = dt.fromisoformat(entry_time)
                hour = entry_time.hour
            except Exception:
                pass

        features = [
            float(trade.get("vix_at_entry", 15)),
            float(trade.get("consensus_score", 0.5)),
            1.0 if trade_type == "SCALP" else 0.0,
            1.0 if trade_type == "INTRADAY" else 0.0,
            1.0 if trade_type == "BTST" else 0.0,
            1.0 if "NIFTY" in underlying and "BANK" not in underlying else 0.0,
            1.0 if "BANKNIFTY" in underlying else 0.0,
            1.0 if direction == "BULLISH" else -1.0,
            float(hour),
        ]

        # Build agent lookup
        vote_by_agent = {}
        for v in votes:
            aid = v.get("agent_id", "")
            idx = AGENT_ID_MAP.get(aid, 0)
            if idx:
                vote_by_agent[idx] = v

        # Agent confidences
        num_reporting = 0
        for i in range(1, 8):
            v = vote_by_agent.get(i, {})
            conf = float(v.get("confidence", 0))
            features.append(conf)
            if conf > 0:
                num_reporting += 1

        # Agent agreement
        for i in range(1, 8):
            v = vote_by_agent.get(i, {})
            agrees = 1.0 if v.get("direction") == direction else 0.0
            features.append(agrees)

        features.append(float(num_reporting))

        return features
