"""Rank only policy-allowed recovery candidates using propensity and friction."""

from dataclasses import dataclass

from agent.recovery_model import build_features, predict
from models import FailureClass, RecoveryStrategy


INTERVENTION_COST_PAISE = {
    RecoveryStrategy.RETRY_PAYMENT_LINK: 35,
    RecoveryStrategy.ALTERNATE_METHOD_LINK: 45,
    RecoveryStrategy.COLLECT_RECEIVABLE_LINK: 60,
    RecoveryStrategy.REQUEST_MANDATE_UPDATE: 15,
    RecoveryStrategy.ESCALATE_TO_HUMAN: 250,
    RecoveryStrategy.NO_ACTION: 0,
}


POLICY_CANDIDATES = {
    FailureClass.UPI_TIMEOUT: [RecoveryStrategy.RETRY_PAYMENT_LINK],
    FailureClass.BANK_DECLINE: [RecoveryStrategy.RETRY_PAYMENT_LINK, RecoveryStrategy.ALTERNATE_METHOD_LINK],
    FailureClass.PAYMENT_CANCELLED: [RecoveryStrategy.RETRY_PAYMENT_LINK],
    FailureClass.CARD_EXPIRED: [RecoveryStrategy.ALTERNATE_METHOD_LINK],
    FailureClass.INSUFFICIENT_FUNDS: [RecoveryStrategy.ALTERNATE_METHOD_LINK],
    FailureClass.CHECKOUT_ABANDONED: [RecoveryStrategy.RETRY_PAYMENT_LINK],
    FailureClass.RECEIVABLE_OVERDUE: [RecoveryStrategy.COLLECT_RECEIVABLE_LINK],
    FailureClass.SUBSCRIPTION_PENDING: [RecoveryStrategy.REQUEST_MANDATE_UPDATE],
    FailureClass.SUBSCRIPTION_HALTED: [RecoveryStrategy.REQUEST_MANDATE_UPDATE],
    FailureClass.SUBSCRIPTION_FAILED: [RecoveryStrategy.REQUEST_MANDATE_UPDATE],
}


@dataclass(frozen=True)
class CandidateScore:
    strategy: RecoveryStrategy
    probability: float
    expected_value: int
    cost: int
    score: int
    model_version: str
    features: dict[str, object]


def rank_candidates(*, failure_class: FailureClass, amount_paise: int, method: str | None,
                    retry_count: int, risk_type: str, merchant_segment: str) -> list[CandidateScore]:
    candidates = POLICY_CANDIDATES.get(failure_class, [RecoveryStrategy.ESCALATE_TO_HUMAN])
    scores = []
    for strategy in candidates:
        features = build_features(failure_class=failure_class, strategy=strategy, amount_paise=amount_paise,
                                  method=method, retry_count=retry_count, risk_type=risk_type,
                                  merchant_segment=merchant_segment)
        prediction = predict(features)
        cost = INTERVENTION_COST_PAISE[strategy]
        expected = round(prediction.probability * amount_paise)
        # A transparent friction penalty avoids treating every action as free.
        friction_penalty = 50 if strategy == RecoveryStrategy.ALTERNATE_METHOD_LINK else 0
        scores.append(CandidateScore(strategy, prediction.probability, expected, cost,
                                     expected - cost - friction_penalty, prediction.model_version, features))
    return sorted(scores, key=lambda score: score.score, reverse=True)
