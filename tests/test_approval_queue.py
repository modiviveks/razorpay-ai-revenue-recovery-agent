"""Unit tests for Human Approval Queue (High-Value Actions approve & reject)."""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from main import app
from database import SessionLocal, init_db
from models import PaymentEvent, RecoveryAction, ActionStatus, FailureClass, RecoveryStrategy


client = TestClient(app)


def setup_module():
    init_db()


def test_pending_approvals_list_and_approval_flow():
    with SessionLocal() as db:
        event = PaymentEvent(
            payment_id="pay_high_val_001",
            amount=500_000,  # ₹5,000.00
            currency="INR",
            method="card",
            risk_type="PAYMENT_FAILURE",
            customer_name="Aarav Sharma",
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        action = RecoveryAction(
            event_id=event.id,
            failure_class=FailureClass.BANK_DECLINE,
            strategy=RecoveryStrategy.ALTERNATE_METHOD_LINK,
            status=ActionStatus.PENDING_APPROVAL,
            retry_count=1,
            rationale="High value threshold triggered",
            recovery_confidence=0.65,
            expected_recovery_amount=325_000,
            decision_factors="{}",
            candidate_scores="[]",
            created_at=datetime.now(timezone.utc),
        )
        db.add(action)
        db.commit()
        db.refresh(action)
        action_id = action.id

    # 1. Fetch pending approvals
    resp = client.get("/api/actions/pending-approvals")
    assert resp.status_code == 200
    items = resp.json()
    assert any(item["action_id"] == action_id for item in items)

    # 2. Approve the action
    app_resp = client.post(
        f"/api/actions/{action_id}/approve",
        json={"reason": "Verified legitimate high-ticket customer via CRM."},
    )
    assert app_resp.status_code == 200

    with SessionLocal() as db:
        refreshed = db.get(RecoveryAction, action_id)
        assert refreshed.status in {ActionStatus.SUCCESS, ActionStatus.PENDING}
        assert "Verified legitimate" in refreshed.approval_reason


def test_rejection_flow():
    with SessionLocal() as db:
        event = PaymentEvent(
            payment_id="pay_high_val_002",
            amount=750_000,
            currency="INR",
            method="upi",
            risk_type="PAYMENT_FAILURE",
            customer_name="Rohan Verma",
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        action = RecoveryAction(
            event_id=event.id,
            failure_class=FailureClass.UPI_TIMEOUT,
            strategy=RecoveryStrategy.RETRY_PAYMENT_LINK,
            status=ActionStatus.PENDING_APPROVAL,
            retry_count=1,
            rationale="High value threshold triggered",
            created_at=datetime.now(timezone.utc),
        )
        db.add(action)
        db.commit()
        db.refresh(action)
        action_id = action.id

    # Reject the action
    rej_resp = client.post(
        f"/api/actions/{action_id}/reject",
        json={"reason": "Suspected duplicate charge order."},
    )
    assert rej_resp.status_code == 200
    assert rej_resp.json()["status"] == "SKIPPED"

    with SessionLocal() as db:
        refreshed = db.get(RecoveryAction, action_id)
        assert refreshed.status == ActionStatus.SKIPPED
        assert "REJECTED: Suspected duplicate" in refreshed.approval_reason
