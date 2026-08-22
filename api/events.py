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
        "runtime_mode": "MOCK" if settings.MOCK_RAZORPAY else "RAZORPAY_TEST_MODE",
        "is_test_mode": (settings.RAZORPAY_MODE == "test"),
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


class RejectionRequest(BaseModel):
    reason: str = Field(default="Merchant rejected recovery action", min_length=3, max_length=300)


@router.get("/actions/pending-approvals", dependencies=[Depends(require_dashboard_key)])
def get_pending_approvals(db: Session = Depends(get_db)):
    """Fetches high-value actions awaiting merchant sign-off with rich explainability data."""
    actions = (
        db.query(RecoveryAction)
        .filter(RecoveryAction.status == ActionStatus.PENDING_APPROVAL)
        .order_by(RecoveryAction.created_at.desc())
        .all()
    )
    results = []
    now_utc = datetime.now(timezone.utc)
    for act in actions:
        expiry = act.created_at.replace(tzinfo=timezone.utc) + timedelta(hours=settings.PAYMENT_LINK_EXPIRY_HOURS)
        is_expired = now_utc > expiry
        event = act.event
        factors = {}
        if act.decision_factors:
            try:
                factors = json.loads(act.decision_factors)
            except Exception:
                pass
        candidates = []
        if act.candidate_scores:
            try:
                candidates = json.loads(act.candidate_scores)
            except Exception:
                pass

        results.append({
            "action_id": act.id,
            "event_id": event.id,
            "payment_id": event.payment_id,
            "order_id": event.order_id,
            "customer_name": event.customer_name,
            "amount_rupees": round(event.amount / 100, 2),
            "amount_paise": event.amount,
            "method": event.method,
            "failure_class": act.failure_class.value,
            "proposed_strategy": act.strategy.value,
            "recovery_confidence": act.recovery_confidence,
            "expected_recovery_amount_rupees": round((act.expected_recovery_amount or 0) / 100, 2),
            "rationale": act.rationale,
            "created_at": act.created_at.isoformat(),
            "expires_at": expiry.isoformat(),
            "is_expired": is_expired,
            "decision_factors": factors,
            "candidate_scores": candidates,
            "ai_advice": act.ai_advice,
        })
    return results


@router.post("/actions/{action_id}/reject", dependencies=[Depends(require_dashboard_key)])
def reject_recovery_action(
    action_id: int,
    request_data: RejectionRequest = RejectionRequest(),
    x_actor_id: str = Header(default=None),
    x_actor_role: str = Header(default=None),
    db: Session = Depends(get_db),
):
    """Explicitly decline a pending high-value recovery action."""
    action = db.get(RecoveryAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Recovery action not found")
    if action.status != ActionStatus.PENDING_APPROVAL:
        raise HTTPException(status_code=409, detail=f"Action is {action.status.value}, not awaiting approval")

    actor_id = x_actor_id or ("local-demo-merchant" if settings.MOCK_RAZORPAY else None)
    actor_role = x_actor_role or ("merchant_admin" if settings.MOCK_RAZORPAY else None)
    if not actor_id or actor_role not in {"merchant_admin", "finance_admin"}:
        raise HTTPException(status_code=403, detail="A merchant_admin or finance_admin actor is required")

    action.status = ActionStatus.SKIPPED
    action.approved_by = actor_id
    action.approved_role = actor_role
    action.approved_at = datetime.now(timezone.utc)
    action.approval_reason = f"REJECTED: {request_data.reason}"
    db.commit()

    log_audit_step(
        db=db,
        action_id=action.id,
        step="MERCHANT_REJECTED",
        reasoning=f"{actor_role} {actor_id} declined recovery action: {request_data.reason}. Action cancelled.",
        outcome="REJECTED",
    )
    return {"status": action.status.value, "action_id": action.id, "reason": request_data.reason}


@router.get("/analytics/funnel", dependencies=[Depends(require_dashboard_key)])
def get_executive_recovery_funnel(db: Session = Depends(get_db)):
    """Produces the 4-stage Executive Recovery Funnel with drop-off analytics."""
    total_events = db.query(PaymentEvent).count()
    total_at_risk_paise = db.query(func.coalesce(func.sum(PaymentEvent.amount), 0)).scalar() or 0

    # Stage 2: Eligible Candidates Evaluated
    eligible_count = (
        db.query(RecoveryAction)
        .filter(RecoveryAction.strategy != RecoveryStrategy.NO_ACTION)
        .count()
    )
    eligible_at_risk_paise = (
        db.query(func.coalesce(func.sum(PaymentEvent.amount), 0))
        .join(RecoveryAction, RecoveryAction.event_id == PaymentEvent.id)
        .filter(RecoveryAction.strategy != RecoveryStrategy.NO_ACTION)
        .scalar() or 0
    )

    # Stage 3: Attempted Interventions
    interventions_count = (
        db.query(RecoveryAction)
        .filter(RecoveryAction.status.in_([ActionStatus.SUCCESS, ActionStatus.RECOVERED]))
        .count()
    )
    interventions_at_risk_paise = (
        db.query(func.coalesce(func.sum(PaymentEvent.amount), 0))
        .join(RecoveryAction, RecoveryAction.event_id == PaymentEvent.id)
        .filter(RecoveryAction.status.in_([ActionStatus.SUCCESS, ActionStatus.RECOVERED]))
        .scalar() or 0
    )

    # Stage 4: Settled Recoveries
    settled_count = (
        db.query(RecoveryAction)
        .filter(RecoveryAction.status == ActionStatus.RECOVERED)
        .count()
    )
    settled_paise = (
        db.query(func.coalesce(func.sum(PaymentEvent.amount), 0))
        .join(RecoveryAction, RecoveryAction.event_id == PaymentEvent.id)
        .filter(RecoveryAction.status == ActionStatus.RECOVERED)
        .scalar() or 0
    )

    # Drop-off analysis
    bounds_exceeded = db.query(RecoveryAction).filter(RecoveryAction.status == ActionStatus.BOUNDS_EXCEEDED).count()
    pending_approval = db.query(RecoveryAction).filter(RecoveryAction.status == ActionStatus.PENDING_APPROVAL).count()
    promise_paused = db.query(RecoveryAction).filter(RecoveryAction.status == ActionStatus.PROMISE_ACTIVE).count()
    skipped_negative_ev = db.query(RecoveryAction).filter(
        RecoveryAction.status == ActionStatus.SKIPPED,
        RecoveryAction.strategy == RecoveryStrategy.NO_ACTION,
    ).count()
    customer_unconverted = max(0, interventions_count - settled_count)

    stages = [
        {
            "stage_id": "failed_events",
            "name": "1. Failed Revenue Events",
            "count": total_events,
            "amount_rupees": round(total_at_risk_paise / 100, 2),
            "conversion_from_total": 100.0 if total_events else 0.0,
            "description": "Total payment failures, checkout dropoffs & overdue receivables ingested",
        },
        {
            "stage_id": "eligible_candidates",
            "name": "2. Policy-Eligible Opportunities",
            "count": eligible_count,
            "amount_rupees": round(eligible_at_risk_paise / 100, 2),
            "conversion_from_total": round((eligible_count / total_events) * 100, 1) if total_events else 0.0,
            "description": "Passed fraud bounds, retry quotas, and negative-EV filters",
        },
        {
            "stage_id": "attempted_interventions",
            "name": "3. Attempted Interventions",
            "count": interventions_count,
            "amount_rupees": round(interventions_at_risk_paise / 100, 2),
            "conversion_from_total": round((interventions_count / total_events) * 100, 1) if total_events else 0.0,
            "description": "Smart payment links, alternate rails & mandate requests dispatched",
        },
        {
            "stage_id": "settled_recoveries",
            "name": "4. Settled Recoveries",
            "count": settled_count,
            "amount_rupees": round(settled_paise / 100, 2),
            "conversion_from_total": round((settled_count / total_events) * 100, 1) if total_events else 0.0,
            "description": "Verified settled revenue confirmed via payment_link.paid webhook",
        },
    ]

    return {
        "stages": stages,
        "overall_conversion_rate": round((settled_count / total_events) * 100, 1) if total_events else 0.0,
        "value_recovery_rate": round((settled_paise / total_at_risk_paise) * 100, 1) if total_at_risk_paise else 0.0,
        "drop_offs": {
            "bounds_and_retries_exceeded": bounds_exceeded,
            "high_value_awaiting_approval": pending_approval,
            "promise_to_pay_active_paused": promise_paused,
            "negative_ev_no_action_skipped": skipped_negative_ev,
            "customer_pending_or_unconverted": customer_unconverted,
        },
    }


@router.get("/analytics/segments", dependencies=[Depends(require_dashboard_key)])
def get_merchant_segment_analytics(db: Session = Depends(get_db)):
    """Calculates granular merchant segment recovery metrics."""
    events = db.query(PaymentEvent).all()
    seg_data = {
        "standard": {"events": 0, "at_risk": 0, "recovered": 0, "interventions": 0, "failures": {}},
        "growth": {"events": 0, "at_risk": 0, "recovered": 0, "interventions": 0, "failures": {}},
        "enterprise": {"events": 0, "at_risk": 0, "recovered": 0, "interventions": 0, "failures": {}},
    }

    for e in events:
        seg = (e.merchant_segment or "standard").lower()
        if seg not in seg_data:
            seg_data[seg] = {"events": 0, "at_risk": 0, "recovered": 0, "interventions": 0, "failures": {}}
        
        seg_data[seg]["events"] += 1
        seg_data[seg]["at_risk"] += e.amount

        # Check action status
        for act in e.recovery_actions:
            if act.status == ActionStatus.RECOVERED:
                seg_data[seg]["recovered"] += e.amount
            if act.status in {ActionStatus.SUCCESS, ActionStatus.RECOVERED}:
                seg_data[seg]["interventions"] += 1
            fc = act.failure_class.value
            seg_data[seg]["failures"][fc] = seg_data[seg]["failures"].get(fc, 0) + 1

    results = []
    for name, data in seg_data.items():
        top_fc = max(data["failures"].items(), key=lambda x: x[1])[0] if data["failures"] else "UPI_TIMEOUT"
        best_strat = "RETRY_PAYMENT_LINK" if name != "growth" else "ALTERNATE_METHOD_LINK"
        avg_ticket = (data["at_risk"] / max(data["events"], 1)) / 100.0

        results.append({
            "segment": name.capitalize(),
            "events_count": data["events"],
            "at_risk_rupees": round(data["at_risk"] / 100, 2),
            "recovered_rupees": round(data["recovered"] / 100, 2),
            "recovery_rate": round((data["recovered"] / max(data["at_risk"], 1)) * 100, 1),
            "interventions_count": data["interventions"],
            "average_ticket_rupees": round(avg_ticket, 2),
            "top_failure_class": top_fc,
            "most_effective_strategy": best_strat,
        })
    return results


@router.get("/network/degradation-status", dependencies=[Depends(require_dashboard_key)])
def get_network_degradation_status(db: Session = Depends(get_db)):
    """Returns real-time payment network health and degradation detector state."""
    from agent.degradation import global_degradation_detector
    
    # Query recent 100 events
    recent_events = (
        db.query(PaymentEvent)
        .order_by(PaymentEvent.created_at.desc())
        .limit(100)
        .all()
    )
    event_dicts = []
    for e in recent_events:
        act = db.query(RecoveryAction).filter(RecoveryAction.event_id == e.id).first()
        event_dicts.append({
            "method": e.method,
            "status": "recovered" if act and act.status == ActionStatus.RECOVERED else "failed",
            "failure_class": act.failure_class.value if act else None,
        })

    reports = global_degradation_detector.evaluate_event_stream(event_dicts)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evaluated_window_events": len(recent_events),
        "methods": {
            k: {
                "method": v.method,
                "baseline_success_rate": v.baseline_success_rate,
                "current_success_rate": v.current_success_rate,
                "degradation_magnitude": v.degradation_magnitude,
                "is_degraded": v.is_degraded,
                "severity": v.severity,
                "affected_failure_classes": v.affected_failure_classes,
                "root_cause_hypothesis": v.root_cause_hypothesis,
                "recommended_action": v.recommended_action.value,
                "suppress_immediate_retry": v.suppress_immediate_retry,
                "explanation": v.explanation,
            }
            for k, v in reports.items()
        },
    }


@router.get("/model/metrics", dependencies=[Depends(require_dashboard_key)])
def get_model_metrics():
    """Returns the trained recovery propensity model calibration and evaluation metrics."""
    from agent.recovery_model import load_model, ARTIFACT_PATH, train
    bundle = load_model()
    if bundle is None:
        metadata = train(samples=8000, seed=42)
        return metadata
    return bundle.get("metadata", {})


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
