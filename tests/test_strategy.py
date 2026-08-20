"""Unit tests for the strategy selector and bounds enforcement."""

import pytest
from models import FailureClass, RecoveryStrategy, ActionStatus
from agent.strategy import determine_strategy

def test_below_minimum_amount_gating():
    # Min amount is set to 100 paise (Rs. 1.00) in settings.
    res = determine_strategy(
        failure_class=FailureClass.UPI_TIMEOUT,
        previous_retries=0,
        amount_paise=50  # ₹0.50
    )
    assert res.strategy == RecoveryStrategy.NO_ACTION
    assert res.status == ActionStatus.SKIPPED
    assert "below minimum" in res.rationale


def test_valid_retry_strategy():
    res = determine_strategy(
        failure_class=FailureClass.UPI_TIMEOUT,
        previous_retries=0,
        amount_paise=50000  # ₹500
    )
    assert res.strategy == RecoveryStrategy.RETRY_PAYMENT_LINK
    assert res.status == ActionStatus.PENDING
    assert res.max_retries == 2


def test_bounds_exceeded_strategy():
    # UPI timeout allows max 2 retries. If previous retries = 2, it should exceed bounds
    res = determine_strategy(
        failure_class=FailureClass.UPI_TIMEOUT,
        previous_retries=2,
        amount_paise=50000
    )
    assert res.strategy == RecoveryStrategy.NO_ACTION
    assert res.status == ActionStatus.BOUNDS_EXCEEDED


def test_high_value_recovery_requires_merchant_approval():
    res = determine_strategy(
        failure_class=FailureClass.UPI_TIMEOUT,
        previous_retries=0,
        amount_paise=1_000_000,
    )
    assert res.status == ActionStatus.PENDING_APPROVAL
    assert res.strategy == RecoveryStrategy.RETRY_PAYMENT_LINK
