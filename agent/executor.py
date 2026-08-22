"""Executor module: Executes selected recovery strategies and logs audit trails."""

import time
import json
import re
import hashlib
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import RecoveryAction, PaymentEvent, AuditLog, ActionStatus, RecoveryStrategy
from razorpay_client.client import razorpay_client, get_razorpay_client
from config import settings


def redact_for_audit(value: str | None) -> str | None:
    """Remove contact details before persisting operational audit evidence."""
    if value is None:
        return None
    value = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", value)
    return re.sub(r"(?<!\w)\+?\d[\d\s-]{7,}\d(?!\w)", "[REDACTED_PHONE]", value)

def log_audit_step(
    db: Session,
    action_id: int,
    step: str,
    reasoning: str,
    api_call: str = None,
    api_response: str = None,
    outcome: str = None,
    error_detail: str = None
):
    """Creates a redacted, tamper-evident audit entry."""
    previous = (
        db.query(AuditLog).filter(AuditLog.action_id == action_id)
        .order_by(AuditLog.id.desc()).first()
    )
    previous_hash = previous.current_hash if previous else "GENESIS"
    # SQLite stores naive datetimes; use the same canonical UTC representation
    # in both hash creation and verification across SQLite/PostgreSQL demos.
    timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
    redacted_reasoning = redact_for_audit(reasoning) or ""
    canonical = json.dumps({"previous_hash": previous_hash, "action_id": action_id,
                            "timestamp": timestamp.isoformat(), "step": step,
                            "reasoning": redacted_reasoning, "outcome": outcome or ""},
                           sort_keys=True, separators=(",", ":"))
    log = AuditLog(
        action_id=action_id,
        step=step,
        reasoning=redacted_reasoning,
        api_call=redact_for_audit(api_call),
        api_response=redact_for_audit(api_response),
        outcome=outcome,
        error_detail=redact_for_audit(error_detail),
        created_at=timestamp,
        previous_hash=previous_hash,
        current_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
    db.add(log)
    db.commit()


def execute_recovery(db: Session, action: RecoveryAction, event: PaymentEvent):
    """Executes the chosen recovery action against the Razorpay API, updating status and database."""
    action.status = ActionStatus.EXECUTING
    db.commit()

    strategy = action.strategy
    amount_in_paise = event.amount

    if strategy in (
        RecoveryStrategy.RETRY_PAYMENT_LINK,
        RecoveryStrategy.ALTERNATE_METHOD_LINK,
        RecoveryStrategy.COLLECT_RECEIVABLE_LINK,
    ):
        # We need to construct a payment link request
        expire_by = int(time.time()) + (settings.PAYMENT_LINK_EXPIRY_HOURS * 3600)
        
        # Prepare customer dictionary, avoiding empty entries
        customer_data = {}
        if event.customer_name:
            customer_data["name"] = event.customer_name
        if event.customer_email:
            customer_data["email"] = event.customer_email
        if event.customer_contact:
            customer_data["contact"] = event.customer_contact

        payload = {
            "amount": amount_in_paise,
            "currency": event.currency or "INR",
            "accept_partial": False,
            "expire_by": expire_by,
            # Razorpay reference IDs must be unique. The action ID also makes audit
            # correlation straightforward for subsequent recovery attempts.
            "reference_id": f"rec_{event.id}_{action.id}",
            "description": f"Recovery checkout for failed payment {event.payment_id}",
            "notify": {"sms": False, "email": False} # Set to false to avoid sending spam in test mode
        }
        if customer_data:
            payload["customer"] = customer_data

        payload_json = json.dumps(payload, indent=2)
        
        log_audit_step(
            db=db,
            action_id=action.id,
            step="EXECUTE_API_START",
            reasoning=f"Initiating Razorpay API payment link creation for amount ₹{amount_in_paise/100:.2f}.",
            api_call=f"POST /v1/payment_links\nPayload:\n{payload_json}"
        )

        try:
            # Make call to Razorpay (test mode or mock client)
            client = razorpay_client or get_razorpay_client()
            response = client.payment_link.create(payload)
            
            # Extract link info
            # Handle both dictionary (dict SDK response) and object types
            plink_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
            short_url = response.get("short_url") if isinstance(response, dict) else getattr(response, "short_url", None)
            
            response_json = json.dumps(response if isinstance(response, dict) else str(response), indent=2)

            action.status = ActionStatus.SUCCESS
            action.new_payment_link_id = plink_id
            action.new_payment_link_url = short_url

            # Generate outreach message
            from agent.outreach import generate_outreach_message
            outreach = generate_outreach_message(
                name=event.customer_name,
                amount_paise=event.amount,
                failure_class=action.failure_class,
                payment_link=short_url,
                error_description=event.error_description
            )
            action.outreach_message = outreach
            db.commit()

            log_audit_step(
                db=db,
                action_id=action.id,
                step="EXECUTE_API_SUCCESS",
                reasoning="Razorpay payment link successfully generated.",
                api_call=f"POST /v1/payment_links",
                api_response=response_json,
                outcome="SUCCESS"
            )

        except Exception as e:
            action.status = ActionStatus.FAILED
            db.commit()

            log_audit_step(
                db=db,
                action_id=action.id,
                step="EXECUTE_API_FAILURE",
                reasoning="Razorpay client threw an error while attempting to create payment link.",
                api_call=f"POST /v1/payment_links",
                api_response=str(e),
                outcome="FAILED",
                error_detail=str(e)
            )

    elif strategy in (RecoveryStrategy.SEND_REMINDER, RecoveryStrategy.REQUEST_MANDATE_UPDATE):
        customer_name = event.customer_name or "Customer"
        action.outreach_message = (
            f"Hi {customer_name}, your recurring payment could not be completed. "
            "Please update or re-authorize your payment mandate from your account settings."
        )
        log_audit_step(
            db=db,
            action_id=action.id,
            step="EXECUTE_REMINDER",
            reasoning="Generated an outreach draft for the customer. Delivery is intentionally not implemented; connect an approved notification provider before enabling sends.",
            outcome="SUCCESS"
        )
        action.status = ActionStatus.SUCCESS
        db.commit()

    elif strategy == RecoveryStrategy.ESCALATE_TO_HUMAN:
        log_audit_step(
            db=db,
            action_id=action.id,
            step="ESCALATE",
            reasoning="Simulation: Escaled recovery task to the customer success team for direct support intervention.",
            outcome="SUCCESS"
        )
        action.status = ActionStatus.SUCCESS
        db.commit()

    else:
        # RecoveryStrategy.NO_ACTION or skipped/bounds exceeded
        log_audit_step(
            db=db,
            action_id=action.id,
            step="NO_ACTION",
            reasoning=f"No automatic execution needed. Rationale: {action.rationale}",
            outcome="SKIPPED"
        )
        # Action is already in BOUNDS_EXCEEDED or SKIPPED status
        db.commit()
