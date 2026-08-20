"""Versioned, local recovery-propensity model.  It is predictive, never authoritative."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction import DictVectorizer

from config import settings

FEATURE_VERSION = "features-v1"
NUMERIC = ["amount_paise", "retry_count", "hours_since_failure", "historical_success_rate", "hour"]
CATEGORICAL = ["failure_class", "method", "merchant_segment", "risk_type", "candidate_strategy"]

@dataclass(frozen=True)
class Prediction:
    probability: float
    confidence: float
    model_version: str
    feature_version: str
    factors: list[str]

def feature_row(**values: Any) -> dict[str, Any]:
    """PII-free feature construction with safe deterministic defaults."""
    return {**{key: 0 for key in NUMERIC}, **{key: "unknown" for key in CATEGORICAL}, **values}

def fallback_probability(row: dict[str, Any]) -> float:
    priors = {"UPI_TIMEOUT": .55, "GATEWAY_ERROR": .50, "CHECKOUT_ABANDONED": .34,
              "BANK_DECLINE": .28, "INSUFFICIENT_FUNDS": .18, "CARD_EXPIRED": .22,
              "RECEIVABLE_OVERDUE": .40, "SUBSCRIPTION_FAILED": .20}
    value = priors.get(row.get("failure_class"), .15)
    value += .05 if row.get("candidate_strategy") == "ALTERNATE_METHOD_LINK" else 0
    value -= min(.25, .10 * float(row.get("retry_count", 0)))
    return round(max(.03, min(.9, value)), 3)

class RecoveryPropensityModel:
    def __init__(self, path: str | None = None):
        self.path = Path(path or settings.MODEL_PATH)
        self.pipeline: Pipeline | None = None
        self.metadata: dict[str, Any] = {}

    def load(self) -> bool:
        if not self.path.exists(): return False
        bundle = joblib.load(self.path)
        self.pipeline, self.metadata = bundle["pipeline"], bundle["metadata"]
        return True

    def predict(self, row: dict[str, Any]) -> Prediction:
        clean = feature_row(**row)
        if self.pipeline is None: self.load()
        if self.pipeline is None:
            p = fallback_probability(clean)
            return Prediction(p, .45, "deterministic-fallback-v1", FEATURE_VERSION,
                              ["No trained local model deployed; deterministic fallback used."])
        p = float(self.pipeline.predict_proba([clean])[0][1])
        return Prediction(round(p, 4), .75, self.metadata["model_version"], FEATURE_VERSION,
                          [f"Model features: failure class={clean['failure_class']}, method={clean['method']}, retry={clean['retry_count']}."])

    def train(self, rows: list[dict[str, Any]], labels: list[int], model_version: str | None = None) -> dict[str, Any]:
        # DictVectorizer keeps the artifact dependency-light and accepts the
        # same explicit PII-free feature dictionary at train and inference.
        pipeline = Pipeline([("features", DictVectorizer(sparse=True)), ("classifier", LogisticRegression(max_iter=500, random_state=42))])
        pipeline.fit(rows, labels)
        predictions = pipeline.predict_proba(rows)[:, 1]
        binary = (predictions >= .5).astype(int)
        metrics = {"precision": round(float(precision_score(labels, binary, zero_division=0)), 3),
                   "recall": round(float(recall_score(labels, binary, zero_division=0)), 3),
                   "brier_score": round(float(brier_score_loss(labels, predictions)), 3)}
        if len(set(labels)) > 1: metrics["roc_auc"] = round(float(roc_auc_score(labels, predictions)), 3)
        self.pipeline = pipeline
        self.metadata = {"model_version": model_version or settings.MODEL_VERSION,
                         "feature_version": FEATURE_VERSION, "trained_at": datetime.now(timezone.utc).isoformat(),
                         "sample_count": len(rows), "metrics": metrics}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": pipeline, "metadata": self.metadata}, self.path)
        return self.metadata

def synthetic_training_data(size: int = 1200, seed: int = 42) -> tuple[list[dict[str, Any]], list[int]]:
    rng = np.random.default_rng(seed); rows=[]; labels=[]
    classes = ["UPI_TIMEOUT", "GATEWAY_ERROR", "BANK_DECLINE", "INSUFFICIENT_FUNDS", "CARD_EXPIRED", "CHECKOUT_ABANDONED", "RECEIVABLE_OVERDUE"]
    methods = ["upi", "card", "netbanking"]
    for _ in range(size):
        fc = str(rng.choice(classes)); retry = int(rng.integers(0, 3)); strategy = "ALTERNATE_METHOD_LINK" if fc in {"CARD_EXPIRED", "INSUFFICIENT_FUNDS"} else "RETRY_PAYMENT_LINK"
        row = feature_row(failure_class=fc, method=str(rng.choice(methods)), amount_paise=int(rng.integers(10_000, 250_000)), retry_count=retry,
                          hours_since_failure=float(rng.uniform(0, 48)), historical_success_rate=float(rng.uniform(.1, .8)), hour=int(rng.integers(0,24)), merchant_segment=str(rng.choice(["standard","growth","enterprise"])), risk_type="PAYMENT_FAILURE", candidate_strategy=strategy)
        p = fallback_probability(row) + .18*(row["historical_success_rate"]-.5) - .06*(row["hours_since_failure"]>24)
        rows.append(row); labels.append(int(rng.random() < max(.03, min(.92,p))))
    return rows, labels
