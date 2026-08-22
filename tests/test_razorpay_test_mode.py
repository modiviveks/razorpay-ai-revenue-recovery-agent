"""Tests for Razorpay Test Mode integration, security validation, and client contracts."""

import hmac
import hashlib
import json
import uuid
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from razorpay.errors import SignatureVerificationError

from main import app
from config import settings, Settings
from razorpay_client.client import (
    MockClient,
    RazorpayTestClient,
    get_razorpay_client,
)
from database import SessionLocal
from models import PaymentEvent, RecoveryAction, ActionStatus, RecoveryStrategy
from agent.executor import execute_recovery


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_mock_client_contract():
    """Verify MockClient satisfies standard operations in offline/mock mode."""
    mock_c = MockClient()
    assert mock_c.mode == "mock"

    link = mock_c.payment_link.create({"amount": 50000, "currency": "INR", "description": "Test"})
    assert link.id.startswith("plink_")
    assert link.short_url.startswith("/demo/payment-links/")
    assert mock_c.verify_webhook_signature("body", "sig", "secret") is True


def test_razorpay_test_client_validation():
    """Verify credentials validation for RazorpayTestClient."""
    # 1. Missing credentials
    with pytest.raises(ValueError, match="RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be configured"):
        RazorpayTestClient(key_id="", key_secret="")

    # 2. Live credentials must be strictly rejected
    with pytest.raises(ValueError, match="Live Razorpay credentials"):
        RazorpayTestClient(key_id="rzp_live_1234567890", key_secret="live_secret")

    # 3. Valid test mode credentials
    test_c = RazorpayTestClient(key_id="rzp_test_abc123xyz456", key_secret="secret_test_xyz")
    assert test_c.mode == "test"
    assert test_c.key_id == "rzp_test_abc123xyz456"


def test_get_razorpay_client_factory():
    """Verify factory dispatches clients appropriately and rejects live mode."""
    # Mock
    c_mock = get_razorpay_client("mock")
    assert isinstance(c_mock, MockClient)

    # Test
    c_test = get_razorpay_client("test", key_id="rzp_test_factory123", key_secret="secret123")
    assert isinstance(c_test, RazorpayTestClient)

    # Live mode is prohibited
    with pytest.raises(ValueError, match="Live mode is prohibited"):
        get_razorpay_client("live")


def test_webhook_signature_verification_test_mode():
    """Verify HMAC-SHA256 signature verification in Test Mode."""
    test_c = RazorpayTestClient(key_id="rzp_test_valid123", key_secret="secret123")
    secret = "rzp_webhook_secret_key"
    payload = json.dumps({"event": "payment_link.paid", "id": "evt_123"})

    # Compute valid signature
    valid_signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

    # Valid check passes
    assert test_c.verify_webhook_signature(payload, valid_signature, secret) is True

    # Invalid signature raises SignatureVerificationError
    with pytest.raises(SignatureVerificationError):
        test_c.verify_webhook_signature(payload, "invalid_signature_hex", secret)

    # Missing signature raises SignatureVerificationError
    with pytest.raises(SignatureVerificationError):
        test_c.verify_webhook_signature(payload, "", secret)


def test_payment_link_creation_test_mode():
    """Verify payment link generation payload structure using RazorpayTestClient."""
    test_c = RazorpayTestClient(key_id="rzp_test_12345", key_secret="secret_abc")

    # Mock the internal SDK client
    mock_sdk = MagicMock()
    mock_sdk.payment_link.create.return_value = {
        "id": "plink_test_999888",
        "short_url": "https://rzp.io/i/test999",
        "status": "created",
        "amount": 75000,
        "currency": "INR"
    }
    test_c.payment_link._sdk_client = mock_sdk

    result = test_c.payment_link.create({
        "amount": 75000,
        "currency": "INR",
        "reference_id": "rec_test_1",
        "description": "Recovery checkout",
        "notify": {"sms": False, "email": False}
    })

    mock_sdk.payment_link.create.assert_called_once()
    assert result["id"] == "plink_test_999888"
    assert result["short_url"] == "https://rzp.io/i/test999"


def test_executor_never_falls_back_on_test_mode_failure():
    """Verify that a failure in Test Mode does NOT fall back to mock client, but records FAILED."""
    db = SessionLocal()
    try:
        event = PaymentEvent(
            payment_id=f"pay_fail_{uuid.uuid4().hex[:6]}",
            amount=49900,
            currency="INR",
            method="upi",
            status="at_risk",
            risk_type="PAYMENT_FAILURE",
            customer_name="Failing Test Customer",
            created_at=datetime_now()
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        action = RecoveryAction(
            event_id=event.id,
            failure_class="UPI_TIMEOUT",
            strategy=RecoveryStrategy.RETRY_PAYMENT_LINK,
            status=ActionStatus.PENDING,
            rationale="Test failure scenario",
            created_at=datetime_now()
        )
        db.add(action)
        db.commit()
        db.refresh(action)

        # Mock client to simulate Razorpay API error
        failing_client = MagicMock()
        failing_client.payment_link.create.side_effect = Exception("Razorpay API Error: 401 Unauthorized")

        with patch("agent.executor.razorpay_client", failing_client):
            execute_recovery(db, action, event)

        db.refresh(action)
        # Action must be marked FAILED, not silently converted to mock SUCCESS
        assert action.status == ActionStatus.FAILED
        assert action.new_payment_link_id is None
    finally:
        db.close()


def test_demo_razorpay_test_endpoint(client):
    """Verify development endpoint POST /demo/razorpay-test/payment-link."""
    payload = {
        "amount_paise": 85000,
        "customer_name": "Rohan Deshmukh",
        "customer_email": "rohan.deshmukh@example.com",
        "customer_contact": "+919876543210",
        "failure_reason": "UPI timeout",
        "method": "upi"
    }
    response = client.post("/demo/razorpay-test/payment-link", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["payment_id"].startswith("pay_test_")
    assert data["action_status"] in {"SUCCESS", "PENDING_APPROVAL"}
    assert "payment_link_id" in data
    assert "payment_link_url" in data
    assert "outreach_message" in data


def test_stats_returns_runtime_mode(client):
    """Verify /api/stats reports runtime_mode and is_test_mode accurately."""
    response = client.post(
        "/api/stats",
        # Note: /api/stats is GET in our router, let's test GET
    )
    # If POST is not allowed, do GET
    get_res = client.get("/api/stats")
    assert get_res.status_code == 200
    stats = get_res.json()
    assert "runtime_mode" in stats
    assert stats["runtime_mode"] in {"MOCK", "RAZORPAY_TEST_MODE"}
    assert "is_test_mode" in stats


def datetime_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
