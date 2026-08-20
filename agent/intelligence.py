"""Transparent recovery-value scoring for merchant prioritisation.

This module is deliberately deterministic. It estimates which *eligible*
recovery actions deserve attention; safety rules in ``strategy.py`` remain the
authority for whether an action may be executed.
"""

from dataclasses import dataclass

from models import FailureClass, RecoveryStrategy


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


def assess_recovery(
    failure_class: FailureClass,
    strategy: RecoveryStrategy,
    amount_paise: int,
    previous_retries: int,
) -> RecoveryAssessment:
    """Estimate recovery likelihood without using customer PII or an LLM."""
    if strategy in (
        RecoveryStrategy.NO_ACTION,
        RecoveryStrategy.ESCALATE_TO_HUMAN,
        RecoveryStrategy.REQUEST_MANDATE_UPDATE,
    ):
        return RecoveryAssessment(0.0, 0, ["No automatic collection opportunity is being scored."])

    confidence = BASE_RECOVERY_PROBABILITY[failure_class]
    factors = [f"Base outcome prior for {failure_class.value}: {confidence:.0%}."]
    if strategy == RecoveryStrategy.ALTERNATE_METHOD_LINK:
        confidence += 0.06
        factors.append("Alternate-method checkout can resolve method-specific failures (+6%).")
    if previous_retries:
        confidence -= 0.12 * previous_retries
        factors.append(f"Prior recovery attempts reduce expected conversion (-{12 * previous_retries}%).")

    confidence = round(max(0.05, min(confidence, 0.90)), 2)
    expected = round(amount_paise * confidence)
    factors.append(f"Expected recovery value: ₹{expected / 100:.2f} at {confidence:.0%} likelihood.")
    return RecoveryAssessment(confidence, expected, factors)
