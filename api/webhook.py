"""Webhook handler for Razorpay failed payment events."""

import json
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import get_db
from models import PaymentEvent, RecoveryAction, ActionStatus, FailureClass, RecoveryOutbox
from agent.pipeline import run_recovery_pipeline
from agent.executor import log_audit_step
from razorpay_client.client import razorpay_client
from config import settings

router = APIRouter(prefix="/webhook", tags=["Webhook"])


RISK_SIGNAL_CONFIG = {
    "checkout.abandoned": ("checkout", FailureClass.CHECKOUT_ABANDONED, "CHECKOUT_ABANDONMENT"),
    "subscription.pending": ("subscription", FailureClass.SUBSCRIPTION_PENDING, "SUBSCRIPTION_PENDING"),
    "subscription.halted": ("subscription", FailureClass.SUBSCRIPTION_HALTED, "SUBSCRIPTION_HALTED"),
    # A normalised application event for invoices managed outside a payment
    # gateway. It is intentionally not presented as a native Razorpay event.
    "receivable.overdue": ("receivable", FailureClass.RECEIVABLE_OVERDUE, "RECEIVABLE_OVERDUE"),
}


def _to_datetime(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    return None

@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default=None),
    x_test_simulator: str = Header(default=None),
    x_razorpay_event_id: str = Header(default=None),
    db: Session = Depends(get_db)
):
    """Processes webhook failures from Razorpay."""
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    
    # 1. Parse payload
    try:
        data = json.loads(body_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # The simulator bypass is permitted only for explicit local/mock deployments.
    simulator_request = x_test_simulator == "true"
    if simulator_request and not settings.ALLOW_TEST_WEBHOOK_BYPASS:
        raise HTTPException(status_code=403, detail="Test webhook bypass is disabled")

    # A real webhook must always be authenticated. Starting without a secret is
    # safer than accepting unauthenticated payment events.
    if not simulator_request:
        if not settings.RAZORPAY_WEBHOOK_SECRET:
            raise HTTPException(status_code=503, detail="Webhook secret is not configured")
        if not x_razorpay_signature:
            raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature header")
        try:
            razorpay_client.utility.verify_webhook_signature(
                body_str,
                x_razorpay_signature,
                settings.RAZORPAY_WEBHOOK_SECRET
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Signature verification failed: {e}")

    event_type = data.get("event")
    
    # A payment link is the durable recovery correlation point. When Razorpay
    # confirms it has been paid, move the original recovery action to RECOVERED.
    if event_type == "payment_link.paid":
        payment_link = data.get("payload", {}).get("payment_link", {}).get("entity", {})
        payment_link_id = payment_link.get("id")
        if not payment_link_id:
            raise HTTPException(status_code=400, detail="Invalid payload: missing payment link entity")

        action = (
            db.query(RecoveryAction)
            .filter(RecoveryAction.new_payment_link_id == payment_link_id)
            .order_by(RecoveryAction.created_at.desc())
            .first()
        )
        if not action:
            return {"status": "ignored", "message": "Payment link is not owned by a recovery action."}
        if action.status == ActionStatus.RECOVERED:
            return {"status": "duplicate", "action_id": action.id, "message": "Recovery was already recorded."}
        paid_amount = payment_link.get("amount_paid", payment_link.get("amount"))
        paid_currency = payment_link.get("currency")
        # Payload variants do not always include amount details. When they do,
        # do not silently attribute a mismatched payment to this recovery.
        if (isinstance(paid_amount, int) and paid_amount != action.event.amount) or (
            paid_currency and paid_currency != action.event.currency
        ):
            action.status = ActionStatus.RECONCILIATION_REQUIRED
            db.commit()
            log_audit_step(
                db=db,
                action_id=action.id,
                step="RECONCILIATION_REQUIRED",
                reasoning="Paid link details did not match the recovery opportunity; merchant reconciliation is required.",
                outcome="REVIEW",
            )
            return {"status": "reconciliation_required", "action_id": action.id}

        action.status = ActionStatus.RECOVERED
        action.event.status = "recovered"
        db.commit()
        log_audit_step(
            db=db,
            action_id=action.id,
            step="PAYMENT_LINK_PAID",
            reasoning="Razorpay confirmed payment for the generated recovery link. Revenue recovery is now attributed to this action.",
            api_response=json.dumps({"payment_link_id": payment_link_id, "status": payment_link.get("status", "paid")}),
            outcome="SUCCESS",
        )
        return {"status": "recovered", "action_id": action.id, "payment_link_id": payment_link_id}

    risk_config = RISK_SIGNAL_CONFIG.get(event_type)
    if event_type != "payment.failed" and not risk_config:
        return {"status": "ignored", "message": f"Event type {event_type} not handled."}

    payload = data.get("payload", {})
    if risk_config:
        entity_key, forced_failure_class, risk_type = risk_config
        payment = payload.get(entity_key, {}).get("entity", {})
        forced_rationale = f"Received {event_type} revenue-risk signal and applied its dedicated bounded workflow."
    else:
        payment = payload.get("payment", {}).get("entity", {})
        forced_failure_class = None
        forced_rationale = None
        risk_type = "PAYMENT_FAILURE"
    if not payment:
        raise HTTPException(status_code=400, detail="Invalid payload: missing source entity")

    payment_id = payment.get("id")
    amount = payment.get("amount", payment.get("outstanding_amount"))
    if not payment_id or not isinstance(amount, int) or amount < 0:
        raise HTTPException(status_code=400, detail="Invalid payload: source id and non-negative integer amount are required")

    # Razorpay's event ID header is preferred. A body hash protects local test
    # traffic and providers that omit it from duplicate delivery.
    event_key = x_razorpay_event_id or data.get("id") or hashlib.sha256(body_bytes).hexdigest()
    existing = db.query(PaymentEvent).filter(PaymentEvent.webhook_event_id == event_key).first()
    if existing:
        action = (
            db.query(RecoveryAction)
            .filter(RecoveryAction.event_id == existing.id)
            .order_by(RecoveryAction.created_at.desc())
            .first()
        )
        return {
            "status": "duplicate",
            "event_id": existing.id,
            "failure_class": action.failure_class.value if action else None,
            "strategy": action.strategy.value if action else None,
            "action_status": action.status.value if action else None,
            "new_payment_link": action.new_payment_link_url if action else None,
        }

    notes = payment.get("notes") or {}
    customer_name = notes.get("customer_name") or payment.get("email", "").split("@")[0].capitalize() or None
    # The event record retains structured fields needed for recovery, but audit
    # payloads redact direct contact details to reduce unnecessary PII exposure.
    safe_payload = json.loads(body_str)
    entity_key = "payment" if event_type == "payment.failed" else RISK_SIGNAL_CONFIG[event_type][0]
    safe_payment = safe_payload.get("payload", {}).get(entity_key, {}).get("entity", {})
    safe_payment.pop("email", None)
    safe_payment.pop("contact", None)

    event = PaymentEvent(
        payment_id=payment_id,
        order_id=payment.get("order_id"),
        amount=amount,
        currency=payment.get("currency", "INR"),
        method=payment.get("method"),
        status="at_risk",
        risk_type=risk_type,
        source_reference=payment_id,
        due_at=_to_datetime(payment.get("due_at")),
        error_code=payment.get("error_code"),
        error_description=payment.get("error_description"),
        error_source=payment.get("error_source"),
        error_step=payment.get("error_step"),
        error_reason=payment.get("error_reason"),
        customer_email=payment.get("email"),
        customer_contact=payment.get("contact"),
        customer_name=customer_name,
        webhook_event_id=event_key,
        raw_payload=json.dumps(safe_payload, separators=(",", ":")),
        experiment_id=notes.get("experiment_id"),
        experiment_variant=notes.get("experiment_variant", "treatment"),
        merchant_segment=notes.get("merchant_segment", "standard"),
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        # The unique event key also closes the race between duplicate webhook
        # deliveries arriving on separate request workers.
        db.rollback()
        existing = db.query(PaymentEvent).filter(PaymentEvent.webhook_event_id == event_key).first()
        return {"status": "duplicate", "event_id": existing.id if existing else None}
    db.refresh(event)
    # Persist work separately: webhook acknowledgement stays cheap and reliable.
    # Normalised signal class is saved onto the event so the worker can reapply it.
    if forced_failure_class:
        event.error_reason = forced_failure_class.value
        db.commit()
    outbox = RecoveryOutbox(event_id=event.id)
    db.add(outbox); db.commit(); db.refresh(outbox)
    if settings.PROCESS_OUTBOX_INLINE:
        # Test/demo adapter only; production workers invoke agent.worker.
        from agent.worker import process_pending_jobs
        process_pending_jobs()
        action = db.query(RecoveryAction).filter(RecoveryAction.event_id == event.id).first()
    else:
        action = None
    return {
        "status": "processed" if action else "queued",
        "event_id": event.id,
        "outbox_id": outbox.id,
        "failure_class": action.failure_class.value if action else None,
        "strategy": action.strategy.value if action else None,
        "action_status": action.status.value if action else "QUEUED",
        "new_payment_link": action.new_payment_link_url if action else None,
    }
