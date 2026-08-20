"""Unit tests for the failure classifier module."""

import pytest
from models import FailureClass
from agent.classifier import classify_by_rules

def test_upi_timeout():
    f_class, rationale = classify_by_rules(
        error_code="GATEWAY_ERROR",
        error_description="Payment timed out at the gateway",
        error_source="gateway",
        error_step="payment_initiation",
        error_reason="payment_timeout",
        method="upi"
    )
    assert f_class == FailureClass.UPI_TIMEOUT
    assert "timed out" in rationale.lower()


def test_insufficient_funds():
    f_class, rationale = classify_by_rules(
        error_code="BAD_REQUEST_ERROR",
        error_description="The customer has insufficient funds in their account",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="insufficient_funds",
        method="card"
    )
    assert f_class == FailureClass.INSUFFICIENT_FUNDS
    assert "insufficient" in rationale.lower()


def test_card_expired():
    f_class, rationale = classify_by_rules(
        error_code="BAD_REQUEST_ERROR",
        error_description="Card has expired",
        error_source="customer",
        error_step="payment_initiation",
        error_reason="card_expired",
        method="card"
    )
    assert f_class == FailureClass.CARD_EXPIRED
    assert "expired" in rationale.lower()


def test_user_cancelled():
    f_class, rationale = classify_by_rules(
        error_code="BAD_REQUEST_ERROR",
        error_description="Payment was cancelled by the user",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_cancelled",
        method="upi"
    )
    assert f_class == FailureClass.PAYMENT_CANCELLED
    assert "cancelled" in rationale.lower() or "dismissed" in rationale.lower()


def test_subscription_failure_precedes_authentication_failure():
    f_class, rationale = classify_by_rules(
        error_code="BAD_REQUEST_ERROR",
        error_description="Recurring subscription charge failed due to authentication failure on card mandate.",
        error_source="customer",
        error_step="payment_initiation",
        error_reason="authentication_failed",
        method="card",
    )
    assert f_class == FailureClass.SUBSCRIPTION_FAILED
    assert "recurring" in rationale.lower()
