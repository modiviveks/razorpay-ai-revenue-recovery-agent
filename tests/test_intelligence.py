from agent.intelligence import assess_recovery
from models import FailureClass, RecoveryStrategy


def test_timeout_has_higher_value_than_repeated_insufficient_funds_attempt():
    timeout = assess_recovery(
        FailureClass.UPI_TIMEOUT, RecoveryStrategy.RETRY_PAYMENT_LINK, 50_000, 0
    )
    low_intent = assess_recovery(
        FailureClass.INSUFFICIENT_FUNDS, RecoveryStrategy.ALTERNATE_METHOD_LINK, 50_000, 1
    )

    assert timeout.confidence > low_intent.confidence
    assert timeout.expected_recovery_amount == 29_000
    assert "Expected recovery value" in timeout.factors[-1]


def test_human_escalation_is_not_scored_as_automatic_collection():
    assessment = assess_recovery(
        FailureClass.UNKNOWN, RecoveryStrategy.ESCALATE_TO_HUMAN, 50_000, 0
    )
    assert assessment.confidence == 0
    assert assessment.expected_recovery_amount == 0
