from agent.advisor import generate_advice
from config import settings
from models import ActionStatus, FailureClass, RecoveryStrategy


def test_advisor_uses_safe_policy_fallback_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "USE_AI_ADVISOR", False)
    result = generate_advice(
        FailureClass.UPI_TIMEOUT,
        RecoveryStrategy.RETRY_PAYMENT_LINK,
        ActionStatus.PENDING,
        0.58,
        0,
    )
    assert result.source == "policy_fallback"
    assert "RETRY_PAYMENT_LINK" in result.summary


def test_advisor_does_not_recommend_action_when_policy_is_stopped(monkeypatch):
    monkeypatch.setattr(settings, "USE_AI_ADVISOR", False)
    result = generate_advice(
        FailureClass.RECEIVABLE_OVERDUE,
        RecoveryStrategy.NO_ACTION,
        ActionStatus.PROMISE_ACTIVE,
        0.0,
        1,
    )
    assert "paused" in result.summary.lower()
