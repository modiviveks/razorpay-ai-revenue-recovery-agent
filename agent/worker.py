"""Small durable outbox worker; no infrastructure is needed for local demos."""
from datetime import datetime, timedelta, timezone
from database import SessionLocal
from models import RecoveryOutbox, OutboxStatus, PaymentEvent, FailureClass
from agent.pipeline import run_recovery_pipeline

def process_pending_jobs(limit: int = 100) -> int:
    processed = 0
    with SessionLocal() as db:
        jobs = db.query(RecoveryOutbox).filter(RecoveryOutbox.status == OutboxStatus.PENDING, RecoveryOutbox.available_at <= datetime.now(timezone.utc)).order_by(RecoveryOutbox.id).limit(limit).all()
        for job in jobs:
            job.status = OutboxStatus.PROCESSING; job.attempts += 1; db.commit()
            try:
                event = db.get(PaymentEvent, job.event_id)
                forced = {"CHECKOUT_ABANDONMENT": FailureClass.CHECKOUT_ABANDONED, "SUBSCRIPTION_PENDING": FailureClass.SUBSCRIPTION_PENDING,
                          "SUBSCRIPTION_HALTED": FailureClass.SUBSCRIPTION_HALTED, "RECEIVABLE_OVERDUE": FailureClass.RECEIVABLE_OVERDUE}.get(event.risk_type) if event else None
                if event: run_recovery_pipeline(db, event, forced_failure_class=forced)
                job.status = OutboxStatus.COMPLETE; job.completed_at = datetime.now(timezone.utc); db.commit(); processed += 1
            except Exception as exc:
                db.rollback(); job = db.get(RecoveryOutbox, job.id)
                job.last_error = str(exc)[:500]
                if job.attempts >= 3: job.status = OutboxStatus.DEAD_LETTER
                else:
                    job.status = OutboxStatus.PENDING; job.available_at = datetime.now(timezone.utc) + timedelta(seconds=2 ** job.attempts)
                db.commit()
    return processed

if __name__ == "__main__": print({"processed": process_pending_jobs()})
