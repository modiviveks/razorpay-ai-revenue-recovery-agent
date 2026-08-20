"""Integration tests for the complete webhook recovery lifecycle."""

import uuid

import pytest
from fastapi.testclient import TestClient

from main import app
from simulator.scenarios import get_payment_link_paid_payload


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
