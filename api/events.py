"""Events and audit APIs for dashboard visualization."""

import json
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import case, func
from database import get_db
from models import (
    PaymentEvent, RecoveryAction, AuditLog, ActionStatus, RecoveryStrategy,
    PromiseToPay, PromiseStatus,
)
from agent.executor import execute_recovery, log_audit_step
from config import settings
from simulator.experiment import run_experiment
from models import ExperimentRun

router = APIRouter(prefix="/api", tags=["API"])


class PromiseToPayRequest(BaseModel):
    promised_for: datetime
    amount: int | None = Field(default=None, ge=1)


class ApprovalRequest(BaseModel):
    reason: str = Field(default="Merchant approved high-value recovery", min_length=3, max_length=300)


def require_dashboard_key(x_dashboard_key: str = Header(default=None)):
    """Optionally protect merchant data outside local demos."""
    if settings.DASHBOARD_API_KEY and x_dashboard_key != settings.DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid dashboard API key")

@router.get("/events", dependencies=[Depends(require_dashboard_key)])
def get_events(limit: int = 50, db: Session = Depends(get_db)):
    """Fetches list of failed payment events and their recovery actions."""
    events = (
        db.query(PaymentEvent)
        .order_by(PaymentEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    
    result = []
    for e in events:
        # Get the latest recovery action for this event
        action = (
            db.query(RecoveryAction)
            .filter(RecoveryAction.event_id == e.id)
            .order_by(RecoveryAction.created_at.desc())
            .first()
        )
        
        action_data = None
        if action:
            action_data = {
                "id": action.id,
                "failure_class": action.failure_class.value,
                "strategy": action.strategy.value,
                "status": action.status.value,
                "new_payment_link_url": action.new_payment_link_url,
                "retry_count": action.retry_count,
                "rationale": action.rationale,
                "outreach_message": action.outreach_message,
                "recovery_confidence": action.recovery_confidence,
                "expected_recovery_amount": action.expected_recovery_amount,
                "decision_factors": json.loads(action.decision_factors or "[]"),
                "ai_advice": action.ai_advice,
                "ai_advice_source": action.ai_advice_source,
            }
            
        result.append({
            "id": e.id,
            "payment_id": e.payment_id,
            "order_id": e.order_id,
            "amount": e.amount,
            "currency": e.currency,
            "method": e.method,
            "risk_type": e.risk_type,
            "due_at": e.due_at.isoformat() if e.due_at else None,
            "error_description": e.error_description,
            "customer_name": e.customer_name,
            "created_at": e.created_at.isoformat(),
            "action": action_data
        })
        
    return result


@router.get("/audit-trail/{action_id}", dependencies=[Depends(require_dashboard_key)])
def get_audit_trail(action_id: int, db: Session = Depends(get_db)):
    """Fetches full audit steps for a specific recovery action."""
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.action_id == action_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    return [
        {
            "id": log.id,
            "step": log.step,
            "reasoning": log.reasoning,
            "api_call": log.api_call,
            "api_response": log.api_response,
            "outcome": log.outcome,
            "error_detail": log.error_detail,
            "previous_hash": log.previous_hash,
            "current_hash": log.current_hash,
            "created_at": log.created_at.isoformat()
        }
        for log in logs
    ]


@router.get("/stats", dependencies=[Depends(require_dashboard_key)])
def get_stats(db: Session = Depends(get_db)):
    """Computes high level metrics for dashboard KPI cards."""
    total_failures = db.query(PaymentEvent).count()
    
    # Total failed amount
    total_failed_amount = db.query(func.sum(PaymentEvent.amount)).scalar() or 0
    
    # A generated checkout link is an opportunity to recover revenue. A
    # RECOVERED action is only created after a verified payment_link.paid event.
    recovery_links_created = (
        db.query(RecoveryAction)
        .filter(
            RecoveryAction.status.in_([ActionStatus.SUCCESS, ActionStatus.RECOVERED]),
            RecoveryAction.strategy.in_([
                RecoveryStrategy.RETRY_PAYMENT_LINK,
                RecoveryStrategy.ALTERNATE_METHOD_LINK,
            ]),
        )
        .count()
    )
    
    # This is the value represented by created links, not settled revenue.
    linked_amount = (
        db.query(func.sum(PaymentEvent.amount))
        .join(RecoveryAction)
        .filter(
            RecoveryAction.status.in_([ActionStatus.SUCCESS, ActionStatus.RECOVERED]),
            RecoveryAction.strategy.in_([
                RecoveryStrategy.RETRY_PAYMENT_LINK,
                RecoveryStrategy.ALTERNATE_METHOD_LINK,
            ]),
        )
        .scalar() or 0
    )
    
    recovered_actions = (
        db.query(RecoveryAction)
        .filter(RecoveryAction.status == ActionStatus.RECOVERED)
        .count()
    )
    recovered_amount = (
        db.query(func.sum(PaymentEvent.amount))
        .join(RecoveryAction)
        .filter(RecoveryAction.status == ActionStatus.RECOVERED)
        .scalar() or 0
    )
    recovery_rate = 0.0
    if total_failures > 0:
        recovery_rate = round((recovered_actions / total_failures) * 100, 1)

    return {
        "runtime_mode": "MOCK" if settings.MOCK_RAZORPAY else "LIVE",
        "total_failures": total_failures,
        "total_failed_amount_rupees": round(total_failed_amount / 100, 2),
        "recovery_links_created": recovery_links_created,
        "linked_amount_rupees": round(linked_amount / 100, 2),
        "link_generation_rate": round((recovery_links_created / total_failures) * 100, 1) if total_failures else 0.0,
        "successful_recoveries": recovered_actions,
        "recovered_amount_rupees": round(recovered_amount / 100, 2),
        "recovery_rate": recovery_rate,
        "expected_recovery_amount_rupees": round(
            (db.query(func.sum(RecoveryAction.expected_recovery_amount)).scalar() or 0) / 100,
            2,
        ),
    }


@router.get("/outcomes", dependencies=[Depends(require_dashboard_key)])
def get_outcomes_by_signal(db: Session = Depends(get_db)):
    """Batch impact by revenue-risk source, without overstating non-recovered value."""
    rows = (
        db.query(
            PaymentEvent.risk_type.label("risk_type"),
            func.count(PaymentEvent.id).label("events"),
            func.coalesce(func.sum(PaymentEvent.amount), 0).label("at_risk"),
            func.coalesce(
                func.sum(case((RecoveryAction.status == ActionStatus.RECOVERED, PaymentEvent.amount), else_=0)),
                0,
            ).label("recovered"),
            func.coalesce(
                func.sum(case((RecoveryAction.new_payment_link_id.is_not(None), 1), else_=0)),
                0,
            ).label("interventions"),
            func.coalesce(
                func.sum(case((RecoveryAction.status.in_([ActionStatus.SKIPPED, ActionStatus.BOUNDS_EXCEEDED, ActionStatus.PROMISE_ACTIVE]), 1), else_=0)),
                0,
            ).label("stopped"),
        )
        .outerjoin(RecoveryAction, RecoveryAction.event_id == PaymentEvent.id)
        .group_by(PaymentEvent.risk_type)
        .order_by(PaymentEvent.risk_type)
        .all()
    )
    return [
        {
            "risk_type": row.risk_type,
            "events": row.events,
            "at_risk_rupees": round(row.at_risk / 100, 2),
            "interventions": row.interventions,
            "recovered_rupees": round(row.recovered / 100, 2),
            "stopped": row.stopped,
        }
        for row in rows
    ]


@router.post("/experiments/simulate", dependencies=[Depends(require_dashboard_key)])
def simulate_experiment(sample_size: int = 10_000, seed: int = 2026, db: Session = Depends(get_db)):
    if not settings.MOCK_RAZORPAY:
        raise HTTPException(status_code=403, detail="Synthetic experiments are only available in mock mode")
    if not 100 <= sample_size <= 50_000:
        raise HTTPException(status_code=422, detail="sample_size must be between 100 and 50000")
    return run_experiment(db, sample_size=sample_size, seed=seed)


@router.get("/experiments/latest", dependencies=[Depends(require_dashboard_key)])
def latest_experiment(db: Session = Depends(get_db)):
    record = db.query(ExperimentRun).order_by(ExperimentRun.created_at.desc()).first()
    return json.loads(record.results_json) if record else None


@router.get("/audit-trail/{action_id}/verify", dependencies=[Depends(require_dashboard_key)])
def verify_audit_chain(action_id: int, db: Session = Depends(get_db)):
    logs = db.query(AuditLog).filter(AuditLog.action_id == action_id).order_by(AuditLog.id.asc()).all()
    previous_hash = "GENESIS"
    for log in logs:
        canonical = json.dumps({"previous_hash": previous_hash, "action_id": log.action_id,
                                "timestamp": log.created_at.isoformat(), "step": log.step,
                                "reasoning": log.reasoning or "", "outcome": log.outcome or ""},
                               sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if log.previous_hash != previous_hash or log.current_hash != expected:
            return {"status": "INVALID", "invalid_log_id": log.id}
        previous_hash = log.current_hash
    return {"status": "VALID", "entries": len(logs), "head_hash": previous_hash if logs else None}


@router.post("/actions/{action_id}/approve", dependencies=[Depends(require_dashboard_key)])
def approve_recovery_action(
    action_id: int,
    request_data: ApprovalRequest = ApprovalRequest(),
    x_actor_id: str = Header(default=None),
    x_actor_role: str = Header(default=None),
    db: Session = Depends(get_db),
):
    """Execute a high-value action only after explicit merchant approval."""
    action = db.get(RecoveryAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Recovery action not found")
    if action.status != ActionStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail=f"Action is {action.status.value}, not awaiting approval")
    if datetime.now(timezone.utc) > action.created_at.replace(tzinfo=timezone.utc) + timedelta(hours=settings.PAYMENT_LINK_EXPIRY_HOURS):
        raise HTTPException(status_code=409, detail="Approval window has expired")
    actor_id = x_actor_id or ("local-demo-merchant" if settings.MOCK_RAZORPAY else None)
    actor_role = x_actor_role or ("merchant_admin" if settings.MOCK_RAZORPAY else None)
    if not actor_id or actor_role not in {"merchant_admin", "finance_admin"}:
        raise HTTPException(status_code=403, detail="A merchant_admin or finance_admin actor is required")

    action.status = ActionStatus.PENDING
    action.approved_by = actor_id
    action.approved_role = actor_role
    action.approved_at = datetime.now(timezone.utc)
    action.approval_reason = request_data.reason
    db.commit()
    log_audit_step(
        db=db,
        action_id=action.id,
        step="MERCHANT_APPROVED",
        reasoning=f"{actor_role} {actor_id} explicitly approved this high-value recovery action: {request_data.reason}",
        outcome="SUCCESS",
    )
    execute_recovery(db, action, action.event)
    return {"status": action.status.value, "action_id": action.id}


@router.post("/actions/{action_id}/promise-to-pay", dependencies=[Depends(require_dashboard_key)])
def record_promise_to_pay(action_id: int, request_data: PromiseToPayRequest, db: Session = Depends(get_db)):
    """Record a B2B payment commitment and stop automatic chasers for that promise."""
    action = db.get(RecoveryAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Recovery action not found")
    if action.event.risk_type != "RECEIVABLE_OVERDUE":
        raise HTTPException(status_code=409, detail="Promises to pay are only supported for overdue receivables")
    if action.status == ActionStatus.RECOVERED:
        raise HTTPException(status_code=409, detail="A promise cannot be recorded after this receivable is recovered")
    promised_for = request_data.promised_for
    if promised_for.tzinfo is None:
        promised_for = promised_for.replace(tzinfo=timezone.utc)
    if promised_for <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Promised date must be in the future")

    promise = PromiseToPay(
        action_id=action.id,
        amount=request_data.amount or action.event.amount,
        promised_for=promised_for,
        status=PromiseStatus.OPEN,
    )
    db.add(promise)
    db.commit()
    db.refresh(promise)
    log_audit_step(
        db=db,
        action_id=action.id,
        step="PROMISE_TO_PAY_RECORDED",
        reasoning=f"Customer promise recorded for ₹{promise.amount / 100:.2f} by {promise.promised_for.isoformat()}. Automatic chasers are paused for this commitment.",
        outcome="SUCCESS",
    )
    return {"id": promise.id, "status": promise.status.value, "promised_for": promise.promised_for.isoformat()}


@router.post("/promises/{promise_id}/mark-broken", dependencies=[Depends(require_dashboard_key)])
def mark_promise_broken(promise_id: int, db: Session = Depends(get_db)):
    """Escalate a broken promise without attempting an automatic debit."""
    promise = db.get(PromiseToPay, promise_id)
    if not promise:
        raise HTTPException(status_code=404, detail="Promise not found")
    if promise.status != PromiseStatus.OPEN:
        raise HTTPException(status_code=409, detail=f"Promise is already {promise.status.value}")
    promise.status = PromiseStatus.BROKEN
    db.commit()
    log_audit_step(
        db=db,
        action_id=promise.action_id,
        step="PROMISE_TO_PAY_BROKEN",
        reasoning="Promise-to-pay was not met. Escalated to merchant collections review; no automatic debit attempted.",
        outcome="REVIEW",
    )
    return {"id": promise.id, "status": promise.status.value, "next_step": "MERCHANT_COLLECTIONS_REVIEW"}


@router.get("/promises", dependencies=[Depends(require_dashboard_key)])
def get_promises(db: Session = Depends(get_db)):
    promises = db.query(PromiseToPay).order_by(PromiseToPay.promised_for.asc()).all()
    return [
        {
            "id": promise.id,
            "action_id": promise.action_id,
            "amount": promise.amount,
            "promised_for": promise.promised_for.isoformat(),
            "status": promise.status.value,
        }
        for promise in promises
    ]
