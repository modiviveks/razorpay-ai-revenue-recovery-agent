"""Deterministic safety-aware recovery intelligence.

The model is deliberately lightweight and dependency-free so the buildathon demo
works in a clean Python environment. It uses a calibrated logistic-style model
trained from reproducible synthetic outcomes. Policy remains authoritative.
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from models import FailureClass, RecoveryStrategy

MODEL_VERSION = "recovery-propensity-v1"
MODEL_PATH = Path(__file__).resolve().parent / "recovery_model.json"

BASE_RECOVERY_PROBABILITY = {
    FailureClass.UPI_TIMEOUT: 0.58,
    FailureClass.AUTHENTICATION_FAILED: 0.46,
    FailureClass.PAYMENT_CANCELLED: 0.34,
    FailureClass.GATEWAY_ERROR: 0.51,
    FailureClass.BANK_DECLINE: 0.29,
    FailureClass.INSUFFICIENT_FUNDS: 0.18,
    FailureClass.CARD_EXPIRED: 0.22,
    FailureClass.SUBSCRIPTION_FAILED: 0.20,
    FailureClass.SUBSCRIPTION_PENDING: 0.24,
    FailureClass.SUBSCRIPTION_HALTED: 0.14,
    FailureClass.CHECKOUT_ABANDONED: 0.36,
    FailureClass.RECEIVABLE_OVERDUE: 0.42,
    FailureClass.UNKNOWN: 0.05,
}


@dataclass(frozen=True)
class RecoveryAssessment:
    confidence: float
    expected_recovery_amount: int
    factors: list[str]
    model_version: str = MODEL_VERSION


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, value))))


def _load_model() -> dict[str, Any] | None:
    if not MODEL_PATH.exists():
        return None
    try:
        return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _features(failure_class: FailureClass, strategy: RecoveryStrategy,
              amount_paise: int, previous_retries: int) -> list[float]:
    amount_bucket = min(amount_paise / 100_000.0, 10.0)
    return [
        1.0,
        BASE_RECOVERY_PROBABILITY[failure_class],
        1.0 if strategy == RecoveryStrategy.ALTERNATE_METHOD_LINK else 0.0,
        1.0 if strategy == RecoveryStrategy.RETRY_PAYMENT_LINK else 0.0,
        min(previous_retries, 3) / 3.0,
        amount_bucket / 10.0,
    ]


def predict_recovery(failure_class: FailureClass, strategy: RecoveryStrategy,
                     amount_paise: int, previous_retries: int) -> RecoveryAssessment:
    """Predict recovery likelihood; this never authorizes an action."""
    if strategy in (RecoveryStrategy.NO_ACTION, RecoveryStrategy.ESCALATE_TO_HUMAN,
                    RecoveryStrategy.REQUEST_MANDATE_UPDATE):
        return RecoveryAssessment(0.0, 0, ["No automatic collection opportunity is being scored."])

    model = _load_model()
    if model and model.get("weights"):
        weights = model["weights"]
        score = sum(w * x for w, x in zip(weights, _features(failure_class, strategy, amount_paise, previous_retries)))
        probability = _sigmoid(score)
        version = str(model.get("model_version", MODEL_VERSION))
        factors = [f"Learned recovery propensity: {probability:.0%} ({version})."]
    else:
        probability = BASE_RECOVERY_PROBABILITY[failure_class]
        version = "rule-baseline-v1"
        factors = [f"Rule baseline prior for {failure_class.value}: {probability:.0%}."]

    if strategy == RecoveryStrategy.ALTERNATE_METHOD_LINK:
        probability += 0.06
        factors.append("Alternate-method checkout adjustment: +6%.")
    if previous_retries:
        probability -= 0.12 * previous_retries
        factors.append(f"Prior attempts adjustment: -{12 * previous_retries}%.")

    probability = round(max(0.05, min(probability, 0.90)), 2)
    expected = round(amount_paise * probability)
    factors.append(f"Expected recovery value: ₹{expected / 100:.2f} at {probability:.0%} likelihood.")
    return RecoveryAssessment(probability, expected, factors, version)


def assess_recovery(failure_class: FailureClass, strategy: RecoveryStrategy,
                    amount_paise: int, previous_retries: int) -> RecoveryAssessment:
    """Backward-compatible entry point used by the recovery pipeline."""
    return predict_recovery(failure_class, strategy, amount_paise, previous_retries)
