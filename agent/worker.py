"""Small durable outbox worker; suitable for local demo or a separate process."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from agent.pipeline import run_recovery_pipeline
from models import FailureClass, OutboxStatus, RecoveryOutbox


MAX_OUTBOX_ATTEMPTS = 3


def process_outbox_job(db: Session, job: RecoveryOutbox):
    if job.status not in (OutboxStatus.PENDING, OutboxStatus.FAILED):
        return None
    job.status = OutboxStatus.PROCESSING
    job.attempts += 1
    db.commit()
    try:
        hint = FailureClass(job.failure_class_hint) if job.failure_class_hint else None
        action = run_recovery_pipeline(db, job.event, forced_failure_class=hint, forced_rationale=job.rationale_hint)
        job.status = OutboxStatus.COMPLETED
        job.processed_at = datetime.now(timezone.utc)
        db.commit()
        return action
    except Exception as exc:
        job.last_error = str(exc)[:1000]
        job.status = OutboxStatus.DEAD_LETTER if job.attempts >= MAX_OUTBOX_ATTEMPTS else OutboxStatus.FAILED
        job.available_at = datetime.now(timezone.utc) + timedelta(seconds=2 ** job.attempts)
        db.commit()
        raise


def process_available_jobs(db: Session, limit: int = 20) -> int:
    jobs = (db.query(RecoveryOutbox).filter(RecoveryOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.FAILED]),
                                             RecoveryOutbox.available_at <= datetime.now(timezone.utc))
            .order_by(RecoveryOutbox.id.asc()).limit(limit).all())
    completed = 0
    for job in jobs:
        try:
            process_outbox_job(db, job)
            completed += 1
        except Exception:
            continue
    return completed


if __name__ == "__main__":
    from database import SessionLocal, init_db
    init_db()
    with SessionLocal() as session:
        print({"processed": process_available_jobs(session)})
