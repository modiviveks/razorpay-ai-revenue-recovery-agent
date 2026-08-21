"""Auditor utility: Helper wrapper around DB audit logging."""

from sqlalchemy.orm import Session
from agent.executor import log_audit_step

def record_audit(
    db: Session,
    action_id: int,
    step: str,
    reasoning: str,
    api_call: str = None,
    api_response: str = None,
    outcome: str = None,
    error_detail: str = None
):
    """Logs a single audit step in the recovery database."""
    log_audit_step(
        db=db,
        action_id=action_id,
        step=step,
        reasoning=reasoning,
        api_call=api_call,
        api_response=api_response,
        outcome=outcome,
        error_detail=error_detail
    )
