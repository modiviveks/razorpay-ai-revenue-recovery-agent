"""Integration tests for the complete webhook recovery lifecycle."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from main import app
from simulator.scenarios import (
    get_payment_link_paid_payload,
    get_checkout_abandoned_payload,
    get_subscription_pending_payload,
    get_receivable_overdue_payload,
)
from config import settings


@pytest.fixture(scope="module")
def client():
    """Run the application lifespan so a clean checkout creates its tables."""
    with TestClient(app) as test_client:
        yield test_client


def test_failed_payment_becomes_recovered_after_payment_link_paid(client):
    suffix = uuid.uuid4().hex
    payload = {
        "entity": "event",
        "event": "payment.failed",
        "created_at": 1600000000,
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_test_upi_timeout_{suffix}",
                    "order_id": f"order_test_upi_timeout_{suffix}",
                    "amount": 50000,
                    "currency": "INR",
                    "method": "upi",
                    "error_code": "GATEWAY_ERROR",
                    "error_description": "Payment timed out",
                    "error_source": "gateway",
                    "error_step": "payment_initiation",
                    "error_reason": "payment_timeout",
                    "email": "test@example.com",
                    "contact": "+919999999999",
                    "notes": {"customer_name": "Test User"},
                }
            }
        },
    }
    headers = {
        "X-Test-Simulator": "true",
        "X-Razorpay-Event-Id": f"evt_test_{uuid.uuid4().hex}",
    }

    response = client.post("/webhook/razorpay", json=payload, headers=headers)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "processed"
    assert result["failure_class"] == "UPI_TIMEOUT"
    assert result["strategy"] == "RETRY_PAYMENT_LINK"
    assert result["action_status"] == "SUCCESS"

    payment_link_id = result["new_payment_link"].rstrip("/").split("/")[-1]
    paid_response = client.post(
        "/webhook/razorpay",
        json=get_payment_link_paid_payload(payment_link_id),
        headers={"X-Test-Simulator": "true"},
    )
    assert paid_response.status_code == 200
    assert paid_response.json()["status"] == "recovered"

    duplicate = client.post(
        "/webhook/razorpay",
        json=payload,
        headers=headers,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"


def test_dashboard_apis_return_recovery_data(client):
    stats = client.get("/api/stats")
    assert stats.status_code == 200
    assert stats.json()["recovered_amount_rupees"] >= 500

    events = client.get("/api/events")
    assert events.status_code == 200
    event = next(item for item in events.json() if item["action"] and item["action"]["status"] == "RECOVERED")

    audit = client.get(f"/api/audit-trail/{event['action']['id']}")
    assert audit.status_code == 200
    assert any(step["step"] == "PAYMENT_LINK_PAID" for step in audit.json())


def test_high_value_action_requires_then_accepts_merchant_approval(client):
    suffix = uuid.uuid4().hex
    payload = {
        "entity": "event",
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": f"pay_high_value_{suffix}",
            "order_id": f"order_high_value_{suffix}",
            "amount": settings.REQUIRE_APPROVAL_OVER_PAISE,
            "currency": "INR",
            "method": "upi",
            "error_description": "Payment timed out",
            "error_reason": "payment_timeout",
        }}},
    }
    response = client.post(
        "/webhook/razorpay",
        json=payload,
        headers={"X-Test-Simulator": "true", "X-Razorpay-Event-Id": f"evt_high_value_{suffix}"},
    )
    assert response.status_code == 200
    assert response.json()["action_status"] == "PENDING_APPROVAL"

    event = next(item for item in client.get("/api/events").json() if item["payment_id"] == payload["payload"]["payment"]["entity"]["id"])
    approval = client.post(f"/api/actions/{event['action']['id']}/approve")
    assert approval.status_code == 200
    assert approval.json()["status"] == "SUCCESS"


def test_dashboard_key_restricts_dashboard_apis(client):
    original_key = settings.DASHBOARD_API_KEY
    settings.DASHBOARD_API_KEY = "demo-key"
    try:
        assert client.get("/api/stats").status_code == 401
        assert client.get("/api/stats", headers={"X-Dashboard-Key": "demo-key"}).status_code == 200
    finally:
        settings.DASHBOARD_API_KEY = original_key


def test_checkout_abandonment_creates_one_bounded_recovery_link(client):
    payload = get_checkout_abandoned_payload()
    payload["payload"]["checkout"]["entity"]["id"] += uuid.uuid4().hex
    payload["payload"]["checkout"]["entity"]["order_id"] += uuid.uuid4().hex
    response = client.post(
        "/webhook/razorpay",
        json=payload,
        headers={"X-Test-Simulator": "true", "X-Razorpay-Event-Id": f"evt_checkout_{uuid.uuid4().hex}"},
    )
    assert response.status_code == 200
    assert response.json()["failure_class"] == "CHECKOUT_ABANDONED"
    assert response.json()["strategy"] == "RETRY_PAYMENT_LINK"
    assert response.json()["new_payment_link"]


def test_subscription_pending_requests_mandate_update_without_auto_charge(client):
    payload = get_subscription_pending_payload()
    payload["payload"]["subscription"]["entity"]["id"] += uuid.uuid4().hex
    response = client.post(
        "/webhook/razorpay",
        json=payload,
        headers={"X-Test-Simulator": "true", "X-Razorpay-Event-Id": f"evt_subscription_{uuid.uuid4().hex}"},
    )
    assert response.status_code == 200
    assert response.json()["failure_class"] == "SUBSCRIPTION_PENDING"
    assert response.json()["strategy"] == "REQUEST_MANDATE_UPDATE"
    assert response.json()["new_payment_link"] is None


def test_receivable_promise_to_pay_is_recorded_and_can_be_escalated(client):
    payload = get_receivable_overdue_payload()
    invoice_id = payload["payload"]["receivable"]["entity"]["id"] + uuid.uuid4().hex
    payload["payload"]["receivable"]["entity"]["id"] = invoice_id
    response = client.post(
        "/webhook/razorpay",
        json=payload,
        headers={"X-Test-Simulator": "true", "X-Razorpay-Event-Id": f"evt_invoice_{uuid.uuid4().hex}"},
    )
    assert response.status_code == 200
    assert response.json()["strategy"] == "COLLECT_RECEIVABLE_LINK"
    event = next(item for item in client.get("/api/events").json() if item["payment_id"] == invoice_id)
    assert event["risk_type"] == "RECEIVABLE_OVERDUE"

    promise = client.post(
        f"/api/actions/{event['action']['id']}/promise-to-pay",
        json={"promised_for": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()},
    )
    assert promise.status_code == 200
    broken = client.post(f"/api/promises/{promise.json()['id']}/mark-broken")
    assert broken.status_code == 200
    assert broken.json()["next_step"] == "MERCHANT_COLLECTIONS_REVIEW"
