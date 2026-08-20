"""Versioned, local recovery-propensity model.

The model estimates recovery likelihood for an already policy-eligible candidate.
It does not select, approve, or execute a financial action.
"""

import json
import math
import random
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, precision_score, recall_score, roc_auc_score

from config import settings
from models import FailureClass, RecoveryStrategy


ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "recovery_propensity.joblib"
MODEL_VERSION = "recovery-logreg-v1"
FEATURE_VERSION = "recovery-features-v1"


@dataclass(frozen=True)
class Prediction:
    probability: float
    model_version: str
    features: dict[str, object]
    source: str


def build_features(
    *, failure_class: FailureClass, strategy: RecoveryStrategy, amount_paise: int,
    method: str | None, retry_count: int, risk_type: str, merchant_segment: str = "standard",
    hour: int = 12,
) -> dict[str, object]:
    """Create non-PII model features shared by training and serving."""
    return {
        "failure_class": failure_class.value,
        "strategy": strategy.value,
        "payment_method": (method or "unknown").lower(),
        "risk_type": risk_type,
        "merchant_segment": merchant_segment,
        "amount_log": round(math.log1p(max(amount_paise, 0)), 4),
        "retry_count": min(max(retry_count, 0), 5),
        "hour_bucket": f"{(hour % 24) // 6 * 6:02d}-{((hour % 24) // 6 + 1) * 6:02d}",
    }


def _fallback_probability(features: dict[str, object]) -> float:
    priors = {"UPI_TIMEOUT": .56, "GATEWAY_ERROR": .49, "PAYMENT_CANCELLED": .34,
              "CARD_EXPIRED": .25, "INSUFFICIENT_FUNDS": .18, "BANK_DECLINE": .28,
              "CHECKOUT_ABANDONED": .35, "RECEIVABLE_OVERDUE": .40}
    probability = priors.get(str(features["failure_class"]), .12)
    if features["strategy"] == RecoveryStrategy.ALTERNATE_METHOD_LINK.value:
        probability += .05
    probability -= .10 * int(features["retry_count"])
    return round(max(.03, min(.9, probability)), 4)


@lru_cache(maxsize=1)
def load_model():
    if not ARTIFACT_PATH.exists():
        return None
    return joblib.load(ARTIFACT_PATH)


def predict(features: dict[str, object]) -> Prediction:
    bundle = load_model()
    if bundle is None:
        return Prediction(_fallback_probability(features), "fallback-priors-v1", features, "deterministic_fallback")
    vector = bundle["vectorizer"].transform([features])
    probability = float(bundle["model"].predict_proba(vector)[0][1])
    return Prediction(round(probability, 4), bundle["metadata"]["model_version"], features, "sklearn_logistic_regression")


def generate_synthetic_dataset(samples: int = 6000, seed: int = 42):
    """Generate a reproducible, explicitly synthetic training set for local demos."""
    rng = random.Random(seed)
    failure_classes = [FailureClass.UPI_TIMEOUT, FailureClass.BANK_DECLINE, FailureClass.INSUFFICIENT_FUNDS,
                       FailureClass.CARD_EXPIRED, FailureClass.PAYMENT_CANCELLED, FailureClass.CHECKOUT_ABANDONED,
                       FailureClass.RECEIVABLE_OVERDUE]
    methods = ["upi", "card", "netbanking"]
    strategies = [RecoveryStrategy.RETRY_PAYMENT_LINK, RecoveryStrategy.ALTERNATE_METHOD_LINK,
                  RecoveryStrategy.COLLECT_RECEIVABLE_LINK, RecoveryStrategy.NO_ACTION]
    records, labels = [], []
    for _ in range(samples):
        failure = rng.choice(failure_classes)
        strategy = rng.choice(strategies)
        method = rng.choice(methods)
        amount = rng.choice([5_000, 15_000, 35_000, 75_000, 150_000, 300_000])
        retries = rng.choice([0, 0, 0, 1, 1, 2])
        risk_type = "RECEIVABLE_OVERDUE" if failure == FailureClass.RECEIVABLE_OVERDUE else (
            "CHECKOUT_ABANDONMENT" if failure == FailureClass.CHECKOUT_ABANDONED else "PAYMENT_FAILURE"
        )
        features = build_features(failure_class=failure, strategy=strategy, amount_paise=amount,
                                  method=method, retry_count=retries, risk_type=risk_type,
                                  merchant_segment=rng.choice(["standard", "growth", "enterprise"]), hour=rng.randrange(24))
        p = _fallback_probability(features)
        # Synthetic treatment mechanism: a suitable intervention increases
        # recovery over natural/control recovery; noisy outcomes prevent a toy-perfect model.
        if strategy == RecoveryStrategy.NO_ACTION:
            p *= .55
        if strategy == RecoveryStrategy.COLLECT_RECEIVABLE_LINK and failure == FailureClass.RECEIVABLE_OVERDUE:
            p += .10
        records.append(features)
        labels.append(int(rng.random() < min(.95, p)))
    return records, labels


def train(samples: int = 6000, seed: int = 42) -> dict[str, object]:
    records, labels = generate_synthetic_dataset(samples, seed)
    split = int(samples * .8)
    vectorizer = DictVectorizer(sparse=True)
    x_train = vectorizer.fit_transform(records[:split])
    x_test = vectorizer.transform(records[split:])
    model = LogisticRegression(max_iter=400, random_state=seed, class_weight="balanced", solver="liblinear")
    model.fit(x_train, labels[:split])
    probabilities = model.predict_proba(x_test)[:, 1]
    predicted = (probabilities >= .5).astype(int)
    metrics = {
        "precision": round(float(precision_score(labels[split:], predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(labels[split:], predicted, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(labels[split:], probabilities)), 4),
        "brier_score": round(float(brier_score_loss(labels[split:], probabilities)), 4),
    }
    metadata = {"model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION,
                "training_timestamp": datetime.now(timezone.utc).isoformat(), "training_sample_count": samples,
                "synthetic": True, "metrics": metrics}
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "vectorizer": vectorizer, "metadata": metadata}, ARTIFACT_PATH)
    load_model.cache_clear()
    return metadata


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
