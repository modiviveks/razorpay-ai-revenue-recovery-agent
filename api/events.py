"""Events and audit APIs for dashboard visualization."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import PaymentEvent, RecoveryAction, AuditLog, ActionStatus, RecoveryStrategy

router = APIRouter(prefix="/api", tags=["API"])

@router.get("/events")
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
                "outreach_message": action.outreach_message
            }
            
        result.append({
            "id": e.id,
            "payment_id": e.payment_id,
            "order_id": e.order_id,
            "amount": e.amount,
            "currency": e.currency,
            "method": e.method,
            "error_description": e.error_description,
            "customer_name": e.customer_name,
            "created_at": e.created_at.isoformat(),
            "action": action_data
        })
        
    return result


@router.get("/audit-trail/{action_id}")
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
            "created_at": log.created_at.isoformat()
        }
        for log in logs
    ]


@router.get("/stats")
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
        "total_failures": total_failures,
        "total_failed_amount_rupees": round(total_failed_amount / 100, 2),
        "recovery_links_created": recovery_links_created,
        "linked_amount_rupees": round(linked_amount / 100, 2),
        "link_generation_rate": round((recovery_links_created / total_failures) * 100, 1) if total_failures else 0.0,
        "successful_recoveries": recovered_actions,
        "recovered_amount_rupees": round(recovered_amount / 100, 2),
        "recovery_rate": recovery_rate,
    }
