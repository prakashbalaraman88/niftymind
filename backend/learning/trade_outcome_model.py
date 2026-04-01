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

MIN_TRAINING_SAMPLES = 50


class TradeOutcomeModel:
    """Predicts trade win probability using GradientBoosting."""

    def __init__(self):
        self._model = None
        self._scaler = None
        self._model_version = 0
        self._is_loaded = False

    def load_latest(self) -> bool:
        """Load the latest model from Supabase."""
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
                logger.info(f"Loaded model v{self._model_version}")
                return True
            else:
                logger.info("No model snapshot found. Will return default predictions.")
                return False
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    def predict(self, supporting_data: dict) -> float:
        """Predict win probability. Returns 0.5 if no model loaded."""
        if not self._is_loaded or self._model is None:
            return 0.5

        try:
            features = self._extract_features(supporting_data)
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
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

        if len(trades_with_votes) < MIN_TRAINING_SAMPLES:
            logger.info(
                f"Only {len(trades_with_votes)} trades. "
                f"Need {MIN_TRAINING_SAMPLES} to train. Skipping."
            )
            return None

        # Build feature matrix
        X_rows = []
        y = []
        for trade in trades_with_votes:
            features = self._extract_features_from_trade(trade)
            X_rows.append(features)
            y.append(1 if float(trade.get("pnl", 0)) > 0 else 0)

        X = np.array(X_rows)
        y = np.array(y)

        # Split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y if sum(y) > 5 else None,
        )

        # Scale
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # Train
        model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,
            min_samples_leaf=10,
            learning_rate=0.1,
            random_state=42,
        )
        model.fit(X_train_scaled, y_train)

        # Evaluate
        y_pred = model.predict(X_test_scaled)
        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
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
        """Save model to Supabase model_snapshots table."""
        import json
        import psycopg2

        try:
            blob = pickle.dumps({"model": self._model, "scaler": self._scaler})
            conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
            cur = conn.cursor()
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
        except Exception as e:
            logger.error(f"Failed to save model snapshot: {e}")

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
