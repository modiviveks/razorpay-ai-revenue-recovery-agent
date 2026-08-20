"""Recovery pipeline orchestrator."""

import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import PaymentEvent, RecoveryAction, ActionStatus, FailureClass, RecoveryStrategy, PromiseToPay, PromiseStatus
from agent.classifier import classify_failure
from agent.strategy import determine_strategy
from agent.executor import execute_recovery, log_audit_step
from agent.intelligence import assess_recovery
from agent.advisor import generate_advice


def run_recovery_pipeline(db: Session, event: PaymentEvent,
                          forced_failure_class: FailureClass | None = None,
                          forced_rationale: str | None = None) -> RecoveryAction:
    if forced_failure_class:
        failure_class = forced_failure_class
        classification_rationale = forced_rationale or "Classified from a normalised revenue-risk signal."
    else:
        failure_class, classification_rationale = classify_failure(
            error_code=event.error_code, error_description=event.error_description,
            error_source=event.error_source, error_step=event.error_step,
            error_reason=event.error_reason, method=event.method,
        )

    retry_query = db.query(RecoveryAction).join(PaymentEvent).filter(
        RecoveryAction.failure_class == failure_class,
        RecoveryAction.status.in_([ActionStatus.SUCCESS, ActionStatus.FAILED, ActionStatus.EXECUTING]),
    )
    if event.order_id:
        retry_query = retry_query.filter(PaymentEvent.order_id == event.order_id)
    else:
        retry_query = retry_query.filter(PaymentEvent.payment_id == event.payment_id)
    previous_retries = retry_query.count()

    active_promise = None
    if failure_class == FailureClass.RECEIVABLE_OVERDUE:
        active_promise = (db.query(PromiseToPay).join(RecoveryAction, PromiseToPay.action_id == RecoveryAction.id)
            .join(PaymentEvent, RecoveryAction.event_id == PaymentEvent.id)
            .filter(PaymentEvent.risk_type == "RECEIVABLE_OVERDUE", PaymentEvent.source_reference == event.source_reference,
                    PromiseToPay.status == PromiseStatus.OPEN, PromiseToPay.promised_for > datetime.now(timezone.utc))
            .order_by(PromiseToPay.promised_for.desc()).first())

    strategy_res = determine_strategy(failure_class=failure_class, previous_retries=previous_retries, amount_paise=event.amount)
    if active_promise:
        from agent.strategy import StrategyResult
        strategy_res = StrategyResult(RecoveryStrategy.NO_ACTION, ActionStatus.PROMISE_ACTIVE, 0, 
            f"Automatic collections paused: open promise-to-pay #{active_promise.id} is due on {active_promise.promised_for.isoformat()}.", True)

    assessment = assess_recovery(failure_class, strategy_res.strategy, event.amount, previous_retries)
    advice = generate_advice(failure_class, strategy_res.strategy, strategy_res.status, assessment.confidence, previous_retries)
    variant = "treatment" if event.risk_type != "CONTROL" else "control"

    action = RecoveryAction(
        event_id=event.id, failure_class=failure_class, strategy=strategy_res.strategy, status=strategy_res.status,
        retry_count=previous_retries + 1,
        rationale=classification_rationale if failure_class != FailureClass.UNKNOWN else strategy_res.rationale,
        is_bounded=strategy_res.is_bounded, max_retries_allowed=strategy_res.max_retries,
        recovery_confidence=assessment.confidence, expected_recovery_amount=assessment.expected_recovery_amount,
        decision_factors=json.dumps(assessment.factors), ai_advice=advice.summary, ai_advice_source=advice.source,
        model_version=assessment.model_version, experiment_variant=variant,
    )
    db.add(action); db.commit(); db.refresh(action)

    log_audit_step(db, action.id, "CLASSIFY_AND_STRATEGIZE",
        f"Classified payment failure as {failure_class.value}. Selected {strategy_res.strategy.value}. Rule rationale: {strategy_res.rationale} Previous attempts: {previous_retries}. Model: {assessment.model_version}.", outcome="SUCCESS")
    log_audit_step(db, action.id, "AI_ADVISOR", f"{advice.source}: {advice.summary}", outcome="ADVISORY")

    if action.status == ActionStatus.PENDING:
        execute_recovery(db, action, event)
    else:
        log_audit_step(db, action.id, "EXECUTION_SKIPPED", f"Execution skipped because action status is {action.status.value}.", outcome="SKIPPED")
    return action
