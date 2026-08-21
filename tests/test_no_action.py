"""Unit tests for explicit NO_ACTION / Negative-EV decisions."""

import pytest
from models import FailureClass, RecoveryStrategy, ActionStatus
from agent.next_best_action import rank_candidates, build_decision_explanation
from agent.strategy import determine_strategy


def test_no_action_selected_when_opportunity_score_negative():
    # Very small amount at risk with high retry count where expected recovery < cost + friction
    candidates = rank_candidates(
        failure_class=FailureClass.UNKNOWN,
        amount_paise=100,  # ₹1.00
        method="netbanking",
        retry_count=4,
        risk_type="PAYMENT_FAILURE",
        merchant_segment="standard",
    )
    # ESCALATE_TO_HUMAN costs ₹2.50 + ₹1.00 friction = ₹3.50, but EV is ~₹0.10.
    # Therefore NO_ACTION (score = 0) must be ranked above ESCALATE_TO_HUMAN (score < 0).
    assert candidates[0].strategy == RecoveryStrategy.NO_ACTION
    assert candidates[0].score == 0


def test_no_action_explanation_clarity():
    candidates = rank_candidates(
        failure_class=FailureClass.UNKNOWN,
        amount_paise=150,
        method="card",
        retry_count=4,
        risk_type="PAYMENT_FAILURE",
    )
    explanation = build_decision_explanation(
        ranked_candidates=candidates,
        failure_class=FailureClass.UNKNOWN,
        amount_paise=150,
        retry_count=4,
        is_bounded=True,
        max_retries=0,
        is_high_value=False,
    )
    assert explanation.recommended_action == RecoveryStrategy.NO_ACTION
    assert "Do nothing because expected recovery value is lower than intervention cost/friction" in explanation.why_selected


def test_strategy_determines_skipped_status_for_no_action():
    res = determine_strategy(
        failure_class=FailureClass.UPI_TIMEOUT,
        previous_retries=0,
        amount_paise=5000,
        proposed_strategy=RecoveryStrategy.NO_ACTION,
    )
    assert res.strategy == RecoveryStrategy.NO_ACTION
    assert res.status == ActionStatus.SKIPPED
    assert "Do nothing because expected recovery value is lower than intervention cost/friction." in res.rationale
