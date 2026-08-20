"""Recovery Pipeline orchestrator: ties classification, strategy, execution and logging together."""

import json
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from models import (
    PaymentEvent, RecoveryAction, ActionStatus, FailureClass, RecoveryStrategy,
    PromiseToPay, PromiseStatus,
)
from agent.classifier import classify_failure
from agent.strategy import determine_strategy
from agent.executor import execute_recovery, log_audit_step
from agent.intelligence import assess_recovery
from agent.advisor import generate_advice
from agent.recovery_model import RecoveryPropensityModel, feature_row, FEATURE_VERSION
from agent.next_best_action import rank_candidates
from config import settings

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

    # Customer-experience gate: we only create drafts/links; still, repeated
    # recovery interventions are suppressed before a model can rank them.
    recent_cutoff = datetime.now(timezone.utc).replace(microsecond=0)
    recent_actions = db.query(RecoveryAction).join(PaymentEvent).filter(
        PaymentEvent.customer_email == event.customer_email,
        RecoveryAction.status.in_([ActionStatus.SUCCESS, ActionStatus.EXECUTING, ActionStatus.RECOVERED]),
    ).count() if event.customer_email else 0

    # An active B2B promise-to-pay is a hard stopping rule. We still record the
    # new overdue signal, but do not issue another collection link before the
    # customer commitment expires or is explicitly marked broken.
    active_promise = None
    if failure_class == FailureClass.RECEIVABLE_OVERDUE:
        active_promise = (
            db.query(PromiseToPay)
            .join(RecoveryAction, PromiseToPay.action_id == RecoveryAction.id)
            .join(PaymentEvent, RecoveryAction.event_id == PaymentEvent.id)
            .filter(
                PaymentEvent.risk_type == "RECEIVABLE_OVERDUE",
                PaymentEvent.source_reference == event.source_reference,
                PromiseToPay.status == PromiseStatus.OPEN,
                PromiseToPay.promised_for > datetime.now(timezone.utc),
            )
            .order_by(PromiseToPay.promised_for.desc())
            .first()
        )
        
    # 2. Determine Strategy & Enforce Bounds
    strategy_res = determine_strategy(
        failure_class=failure_class,
        previous_retries=previous_retries,
        amount_paise=event.amount
    )
    if active_promise:
        from agent.strategy import StrategyResult
        strategy_res = StrategyResult(
            strategy=RecoveryStrategy.NO_ACTION,
            status=ActionStatus.PROMISE_ACTIVE,
            max_retries=0,
            is_bounded=True,
            rationale=(
                f"Automatic collections paused: open promise-to-pay #{active_promise.id} "
                f"is due on {active_promise.promised_for.isoformat()}."
            ),
        )
    elif recent_actions >= settings.MAX_CUSTOMER_INTERVENTIONS:
        from agent.strategy import StrategyResult
        strategy_res = StrategyResult(RecoveryStrategy.ESCALATE_TO_HUMAN, ActionStatus.SKIPPED, 0, "Customer-experience safety: intervention limit reached; suppress automated contact and escalate.")
    assessment = assess_recovery(
        failure_class=failure_class,
        strategy=strategy_res.strategy,
        amount_paise=event.amount,
        previous_retries=previous_retries,
    )
    historical_success_rate = (db.query(RecoveryAction).filter(RecoveryAction.status == ActionStatus.RECOVERED).count() /
                               max(1, db.query(RecoveryAction).count()))
    model = RecoveryPropensityModel()
    prediction = model.predict(feature_row(failure_class=failure_class.value, method=event.method or "unknown", amount_paise=event.amount,
        retry_count=previous_retries, hours_since_failure=0, historical_success_rate=historical_success_rate,
        hour=datetime.now(timezone.utc).hour, merchant_segment=event.merchant_segment, risk_type=event.risk_type,
        candidate_strategy=strategy_res.strategy.value))
    candidates = rank_candidates(failure_class, event.amount, event.method, previous_retries, event.risk_type, event.merchant_segment)
    advice = generate_advice(
        failure_class=failure_class,
        strategy=strategy_res.strategy,
        status=strategy_res.status,
        confidence=assessment.confidence,
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
        recovery_confidence=prediction.confidence,
        predicted_probability=prediction.probability,
        expected_recovery_amount=round(event.amount * prediction.probability),
        expected_recovery_value=next((c.expected_value for c in candidates if c.strategy == strategy_res.strategy), 0),
        decision_factors=json.dumps(prediction.factors + assessment.factors),
        candidate_scores=json.dumps([c.__dict__ | {"strategy": c.strategy.value} for c in candidates]),
        model_version=prediction.model_version, feature_version=FEATURE_VERSION,
        policy_version=settings.POLICY_VERSION, action_version=settings.ACTION_VERSION,
        approval_expires_at=(datetime.now(timezone.utc) + timedelta(hours=settings.APPROVAL_TTL_HOURS)) if strategy_res.status == ActionStatus.PENDING_APPROVAL else None,
        ai_advice=advice.summary,
        ai_advice_source=advice.source,
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
            f"Previous attempts: {previous_retries}. Model top candidate: {candidates[0].strategy.value}; "
            f"final action is policy-controlled ({strategy_res.strategy.value})."
        ),
        outcome="SUCCESS"
    )
    log_audit_step(
        db=db,
        action_id=action.id,
        step="AI_ADVISOR",
        reasoning=f"{advice.source}: {advice.summary}",
        outcome="ADVISORY",
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
