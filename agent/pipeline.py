"""Recovery Pipeline orchestrator: ties classification, strategy, execution and logging together."""

import json

from sqlalchemy.orm import Session
from models import PaymentEvent, RecoveryAction, ActionStatus, FailureClass
from agent.classifier import classify_failure
from agent.strategy import determine_strategy
from agent.executor import execute_recovery, log_audit_step
from agent.intelligence import assess_recovery

def run_recovery_pipeline(
    db: Session,
    event: PaymentEvent,
    forced_failure_class: FailureClass | None = None,
    forced_rationale: str | None = None,
) -> RecoveryAction:
    """Orchestrates the classification, strategy, and execution steps for a payment event."""
    
    # 1. Classify failure
    if forced_failure_class:
        failure_class = forced_failure_class
        classification_rationale = forced_rationale or "Classified from a normalised revenue-risk signal."
    else:
        failure_class, classification_rationale = classify_failure(
            error_code=event.error_code,
            error_description=event.error_description,
            error_source=event.error_source,
            error_step=event.error_step,
            error_reason=event.error_reason,
            method=event.method,
        )
    
    # Count only actual attempts of the same failure class. Skipped and blocked records
    # must not consume a retry quota.
    retry_query = (
        db.query(RecoveryAction)
        .join(PaymentEvent)
        .filter(
            RecoveryAction.failure_class == failure_class,
            RecoveryAction.status.in_([ActionStatus.SUCCESS, ActionStatus.FAILED, ActionStatus.EXECUTING]),
        )
    )
    if event.order_id:
        retry_query = retry_query.filter(PaymentEvent.order_id == event.order_id)
    else:
        retry_query = retry_query.filter(PaymentEvent.payment_id == event.payment_id)
    previous_retries = retry_query.count()
        
    # 2. Determine Strategy & Enforce Bounds
    strategy_res = determine_strategy(
        failure_class=failure_class,
        previous_retries=previous_retries,
        amount_paise=event.amount
    )
    assessment = assess_recovery(
        failure_class=failure_class,
        strategy=strategy_res.strategy,
        amount_paise=event.amount,
        previous_retries=previous_retries,
    )
    
    # Create the RecoveryAction record
    action = RecoveryAction(
        event_id=event.id,
        failure_class=failure_class,
        strategy=strategy_res.strategy,
        status=strategy_res.status,
        retry_count=previous_retries + 1,
        rationale=classification_rationale if failure_class != FailureClass.UNKNOWN else strategy_res.rationale,
        is_bounded=strategy_res.is_bounded,
        max_retries_allowed=strategy_res.max_retries,
        recovery_confidence=assessment.confidence,
        expected_recovery_amount=assessment.expected_recovery_amount,
        decision_factors=json.dumps(assessment.factors),
    )
    db.add(action)
    db.commit()
    db.refresh(action)

    # 3. Log Strategy Decision Audit Step
    log_audit_step(
        db=db,
        action_id=action.id,
        step="CLASSIFY_AND_STRATEGIZE",
        reasoning=(
            f"Classified payment failure as {failure_class.value}. "
            f"Selected recovery strategy: {strategy_res.strategy.value}. "
            f"Rule rationale: {strategy_res.rationale} "
            f"Previous attempts: {previous_retries}."
        ),
        outcome="SUCCESS"
    )

    # 4. Execute Action if Pending
    if action.status == ActionStatus.PENDING:
        execute_recovery(db, action, event)
    else:
        # Approval, bounded and skipped actions remain observable without an
        # external call being made from the webhook request.
        log_audit_step(
            db=db,
            action_id=action.id,
            step="EXECUTION_SKIPPED",
            reasoning=f"Execution skipped because action status is {action.status.value}.",
            outcome="SKIPPED"
        )
        
    return action
