"""Versioned, local recovery-propensity model.

The model estimates recovery likelihood for an already policy-eligible candidate.
It does not select, approve, or execute a financial action.

Includes a decoupled latent data-generating process (DGP) for credible synthetic training,
and a multi-bucket calibration evaluator.
"""

import json
import math
import random
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, precision_score, recall_score, roc_auc_score

from models import FailureClass, RecoveryStrategy


ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "recovery_propensity.joblib"
MODEL_VERSION = "recovery-logreg-v2"
FEATURE_VERSION = "recovery-features-v2"


@dataclass(frozen=True)
class Prediction:
    probability: float
    model_version: str
    features: dict[str, object]
    source: str


def build_features(
    *,
    failure_class: FailureClass,
    strategy: RecoveryStrategy,
    amount_paise: int,
    method: str | None,
    retry_count: int,
    risk_type: str,
    merchant_segment: str = "standard",
    hour: int = 12,
) -> dict[str, object]:
    """Create non-PII model features shared by training and serving."""
    return {
        "failure_class": failure_class.value,
        "strategy": strategy.value,
        "payment_method": (method or "unknown").lower(),
        "risk_type": risk_type,
        "merchant_segment": merchant_segment.lower(),
        "amount_log": round(math.log1p(max(amount_paise, 0)), 4),
        "retry_count": min(max(retry_count, 0), 5),
        "hour_bucket": f"{(hour % 24) // 6 * 6:02d}-{((hour % 24) // 6 + 1) * 6:02d}",
    }


def _fallback_probability(features: dict[str, object]) -> float:
    """Transparent heuristic fallback used when model artifact is missing or during cold start."""
    priors = {
        "UPI_TIMEOUT": 0.56,
        "GATEWAY_ERROR": 0.49,
        "PAYMENT_CANCELLED": 0.34,
        "CARD_EXPIRED": 0.25,
        "INSUFFICIENT_FUNDS": 0.18,
        "BANK_DECLINE": 0.28,
        "CHECKOUT_ABANDONED": 0.35,
        "RECEIVABLE_OVERDUE": 0.40,
        "SUBSCRIPTION_FAILED": 0.30,
        "SUBSCRIPTION_PENDING": 0.32,
        "SUBSCRIPTION_HALTED": 0.22,
        "AUTHENTICATION_FAILED": 0.38,
        "UNKNOWN": 0.12,
    }
    probability = priors.get(str(features.get("failure_class")), 0.20)
    strategy = str(features.get("strategy"))
    if strategy == RecoveryStrategy.ALTERNATE_METHOD_LINK.value:
        probability += 0.05
    elif strategy == RecoveryStrategy.NO_ACTION.value:
        probability = 0.0
    
    retries = int(features.get("retry_count", 0))
    probability -= 0.10 * retries
    return round(max(0.02, min(0.92, probability)), 4)


@lru_cache(maxsize=1)
def load_model():
    if not ARTIFACT_PATH.exists():
        return None
    try:
        return joblib.load(ARTIFACT_PATH)
    except Exception:
        return None


def predict(features: dict[str, object]) -> Prediction:
    if features.get("strategy") == RecoveryStrategy.NO_ACTION.value:
        return Prediction(0.0, "deterministic-policy-v1", features, "deterministic_policy")

    bundle = load_model()
    if bundle is None:
        return Prediction(_fallback_probability(features), "fallback-priors-v2", features, "deterministic_fallback")
    
    try:
        vector = bundle["vectorizer"].transform([features])
        probability = float(bundle["model"].predict_proba(vector)[0][1])
        return Prediction(round(probability, 4), bundle["metadata"]["model_version"], features, "sklearn_logistic_regression")
    except Exception:
        return Prediction(_fallback_probability(features), "fallback-priors-v2", features, "deterministic_fallback")


def _latent_synthetic_outcome_process(
    rng: random.Random,
    failure_class: FailureClass,
    strategy: RecoveryStrategy,
    method: str,
    amount_paise: int,
    retry_count: int,
    merchant_segment: str,
    hour: int,
) -> int:
    """Decoupled latent outcome generator.

    Uses latent variables, channel dynamics, and environmental noise rather than
    serving fallback probabilities, eliminating circular self-training.
    """
    # 1. Latent customer responsiveness baseline
    latent_customer_intent = rng.gauss(0.0, 0.8)

    # 2. Failure severity friction
    failure_friction = {
        FailureClass.UPI_TIMEOUT: 0.35,          # User wanted to pay; network timed out
        FailureClass.AUTHENTICATION_FAILED: 0.15, # OTP issue; recoverable with fresh session
        FailureClass.CHECKOUT_ABANDONED: 0.05,    # Partial intent
        FailureClass.PAYMENT_CANCELLED: -0.10,   # Active hesitation
        FailureClass.BANK_DECLINE: -0.20,        # Issuer declined; needs retry or alternate
        FailureClass.RECEIVABLE_OVERDUE: 0.10,   # Business relationship
        FailureClass.CARD_EXPIRED: -0.30,        # Physical card is invalid
        FailureClass.INSUFFICIENT_FUNDS: -0.65,  # Real liquidity constraint
        FailureClass.GATEWAY_ERROR: 0.40,        # Transient gateway issue
        FailureClass.SUBSCRIPTION_FAILED: -0.15,
        FailureClass.SUBSCRIPTION_PENDING: -0.05,
        FailureClass.SUBSCRIPTION_HALTED: -0.40,
        FailureClass.UNKNOWN: -0.80,
    }.get(failure_class, -0.20)

    # 3. Strategy / failure match efficacy
    strategy_efficacy = 0.0
    if strategy == RecoveryStrategy.NO_ACTION:
        strategy_efficacy = -1.5  # Without intervention, natural recovery is very low
    elif strategy == RecoveryStrategy.RETRY_PAYMENT_LINK:
        if failure_class in {FailureClass.UPI_TIMEOUT, FailureClass.GATEWAY_ERROR, FailureClass.AUTHENTICATION_FAILED}:
            strategy_efficacy = 0.70
        elif failure_class in {FailureClass.CARD_EXPIRED, FailureClass.INSUFFICIENT_FUNDS}:
            strategy_efficacy = -0.40  # Same card will fail again
    elif strategy == RecoveryStrategy.ALTERNATE_METHOD_LINK:
        if failure_class in {FailureClass.CARD_EXPIRED, FailureClass.INSUFFICIENT_FUNDS, FailureClass.BANK_DECLINE}:
            strategy_efficacy = 0.65
        else:
            strategy_efficacy = 0.30
    elif strategy == RecoveryStrategy.COLLECT_RECEIVABLE_LINK:
        strategy_efficacy = 0.55 if failure_class == FailureClass.RECEIVABLE_OVERDUE else -0.20
    elif strategy == RecoveryStrategy.REQUEST_MANDATE_UPDATE:
        strategy_efficacy = 0.50 if "SUBSCRIPTION" in failure_class.value else -0.30
    elif strategy == RecoveryStrategy.ESCALATE_TO_HUMAN:
        strategy_efficacy = 0.35

    # 4. Merchant segment affinity
    segment_effect = {"enterprise": 0.20, "growth": 0.08, "standard": 0.0}.get(merchant_segment.lower(), 0.0)

    # 5. Temporal / circadian effect (business hours vs late night)
    hour_effect = 0.20 if (9 <= hour <= 19) else (-0.25 if hour < 6 else 0.0)

    # 6. Retry fatigue (sub-linear degradation)
    retry_penalty = -0.45 * (retry_count ** 1.1)

    # 7. Amount sensitivity (larger tickets create customer second-thoughts)
    amount_rupees = amount_paise / 100.0
    amount_friction = -0.06 * math.log1p(amount_rupees)

    # 8. Channel noise
    channel_noise = rng.gauss(0.0, 0.4)

    # Combine into latent log-odds
    latent_z = (
        -0.40
        + latent_customer_intent
        + failure_friction
        + strategy_efficacy
        + segment_effect
        + hour_effect
        + retry_penalty
        + amount_friction
        + channel_noise
    )

    # Logistic sigmoid
    prob = 1.0 / (1.0 + math.exp(-latent_z))
    return 1 if rng.random() < prob else 0


def generate_synthetic_dataset(samples: int = 8000, seed: int = 42):
    """Generate a reproducible, decoupled synthetic training set for local builds and demos."""
    rng = random.Random(seed)
    failure_classes = [
        FailureClass.UPI_TIMEOUT,
        FailureClass.BANK_DECLINE,
        FailureClass.INSUFFICIENT_FUNDS,
        FailureClass.CARD_EXPIRED,
        FailureClass.PAYMENT_CANCELLED,
        FailureClass.CHECKOUT_ABANDONED,
        FailureClass.RECEIVABLE_OVERDUE,
        FailureClass.GATEWAY_ERROR,
        FailureClass.AUTHENTICATION_FAILED,
        FailureClass.SUBSCRIPTION_FAILED,
    ]
    methods = ["upi", "card", "netbanking", "wallet"]
    strategies = [
        RecoveryStrategy.RETRY_PAYMENT_LINK,
        RecoveryStrategy.ALTERNATE_METHOD_LINK,
        RecoveryStrategy.COLLECT_RECEIVABLE_LINK,
        RecoveryStrategy.REQUEST_MANDATE_UPDATE,
        RecoveryStrategy.NO_ACTION,
    ]
    segments = ["standard", "growth", "enterprise"]

    records, labels = [], []
    for _ in range(samples):
        failure = rng.choice(failure_classes)
        strategy = rng.choice(strategies)
        method = rng.choice(methods)
        segment = rng.choice(segments)
        amount = rng.choice([2_500, 7_500, 15_000, 45_000, 95_000, 250_000, 600_000])
        retries = rng.choice([0, 0, 0, 1, 1, 2, 3])
        hour = rng.randrange(24)
        risk_type = (
            "RECEIVABLE_OVERDUE" if failure == FailureClass.RECEIVABLE_OVERDUE
            else ("CHECKOUT_ABANDONMENT" if failure == FailureClass.CHECKOUT_ABANDONED else "PAYMENT_FAILURE")
        )

        features = build_features(
            failure_class=failure,
            strategy=strategy,
            amount_paise=amount,
            method=method,
            retry_count=retries,
            risk_type=risk_type,
            merchant_segment=segment,
            hour=hour,
        )

        label = _latent_synthetic_outcome_process(
            rng=rng,
            failure_class=failure,
            strategy=strategy,
            method=method,
            amount_paise=amount,
            retry_count=retries,
            merchant_segment=segment,
            hour=hour,
        )

        records.append(features)
        labels.append(label)

    return records, labels


def evaluate_calibration(labels: Sequence[int], probabilities: Sequence[float], n_bins: int = 10) -> list[dict[str, object]]:
    """Evaluates probability calibration across 10 decile buckets (0-10%, 10-20%, etc.)."""
    labels_arr = np.array(labels)
    probs_arr = np.array(probabilities)
    
    calibration_buckets = []
    for i in range(n_bins):
        low = i / n_bins
        high = (i + 1) / n_bins
        mask = (probs_arr >= low) & (probs_arr < high) if i < n_bins - 1 else (probs_arr >= low) & (probs_arr <= high)
        bin_samples = int(np.sum(mask))
        
        if bin_samples > 0:
            mean_pred = float(np.mean(probs_arr[mask]))
            obs_rate = float(np.mean(labels_arr[mask]))
        else:
            mean_pred = round((low + high) / 2, 4)
            obs_rate = 0.0

        calibration_buckets.append({
            "bucket": f"{int(low*100)}-{int(high*100)}%",
            "range_low": round(low, 2),
            "range_high": round(high, 2),
            "samples": bin_samples,
            "mean_predicted_probability": round(mean_pred, 4),
            "observed_recovery_rate": round(obs_rate, 4),
            "calibration_gap": round(abs(mean_pred - obs_rate), 4),
        })

    return calibration_buckets


def train(samples: int = 8000, seed: int = 42) -> dict[str, object]:
    records, labels = generate_synthetic_dataset(samples, seed)
    split = int(samples * 0.8)
    
    vectorizer = DictVectorizer(sparse=True)
    x_train = vectorizer.fit_transform(records[:split])
    x_test = vectorizer.transform(records[split:])
    y_train = labels[:split]
    y_test = labels[split:]

    model = LogisticRegression(max_iter=500, random_state=seed, class_weight="balanced", solver="liblinear")
    model.fit(x_train, y_train)

    probabilities = model.predict_proba(x_test)[:, 1]
    predicted = (probabilities >= 0.5).astype(int)

    calibration_table = evaluate_calibration(y_test, probabilities)

    metrics = {
        "precision": round(float(precision_score(y_test, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, predicted, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4),
        "brier_score": round(float(brier_score_loss(y_test, probabilities)), 4),
        "calibration": calibration_table,
    }

    metadata = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "training_timestamp": datetime.now(timezone.utc).isoformat(),
        "training_sample_count": samples,
        "synthetic": True,
        "data_generating_process": "decoupled_latent_factor_process",
        "metrics": metrics,
    }

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "vectorizer": vectorizer, "metadata": metadata}, ARTIFACT_PATH)
    load_model.cache_clear()
    return metadata


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
