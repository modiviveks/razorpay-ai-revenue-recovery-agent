"""Rank only policy-allowed recovery candidates using propensity, costs, friction, and explicit NO_ACTION."""

from dataclasses import dataclass, field

from agent.recovery_model import build_features, predict
from models import FailureClass, RecoveryStrategy


INTERVENTION_COST_PAISE = {
    RecoveryStrategy.RETRY_PAYMENT_LINK: 35,        # ₹0.35 messaging & link processing
    RecoveryStrategy.ALTERNATE_METHOD_LINK: 45,     # ₹0.45 custom checkout link processing
    RecoveryStrategy.COLLECT_RECEIVABLE_LINK: 60,   # ₹0.60 collection notification & portal fee
    RecoveryStrategy.REQUEST_MANDATE_UPDATE: 15,    # ₹0.15 mandate update webhook / notification
    RecoveryStrategy.ESCALATE_TO_HUMAN: 250,        # ₹2.50 agent / human triage overhead
    RecoveryStrategy.NO_ACTION: 0,                  # ₹0.00 zero marginal cost
}

FRICTION_PENALTY_PAISE = {
    RecoveryStrategy.RETRY_PAYMENT_LINK: 0,
    RecoveryStrategy.ALTERNATE_METHOD_LINK: 50,     # ₹0.50 customer friction for switching methods
    RecoveryStrategy.COLLECT_RECEIVABLE_LINK: 20,   # ₹0.20 commercial relationship friction
    RecoveryStrategy.REQUEST_MANDATE_UPDATE: 10,    # ₹0.10 customer interaction friction
    RecoveryStrategy.ESCALATE_TO_HUMAN: 100,        # ₹1.00 merchant operation friction
    RecoveryStrategy.NO_ACTION: 0,
}

POLICY_CANDIDATES = {
    FailureClass.UPI_TIMEOUT: [RecoveryStrategy.RETRY_PAYMENT_LINK],
    FailureClass.BANK_DECLINE: [RecoveryStrategy.RETRY_PAYMENT_LINK, RecoveryStrategy.ALTERNATE_METHOD_LINK],
    FailureClass.PAYMENT_CANCELLED: [RecoveryStrategy.RETRY_PAYMENT_LINK],
    FailureClass.CARD_EXPIRED: [RecoveryStrategy.ALTERNATE_METHOD_LINK],
    FailureClass.INSUFFICIENT_FUNDS: [RecoveryStrategy.ALTERNATE_METHOD_LINK],
    FailureClass.CHECKOUT_ABANDONED: [RecoveryStrategy.RETRY_PAYMENT_LINK],
    FailureClass.RECEIVABLE_OVERDUE: [RecoveryStrategy.COLLECT_RECEIVABLE_LINK],
    FailureClass.SUBSCRIPTION_PENDING: [RecoveryStrategy.REQUEST_MANDATE_UPDATE],
    FailureClass.SUBSCRIPTION_HALTED: [RecoveryStrategy.REQUEST_MANDATE_UPDATE],
    FailureClass.SUBSCRIPTION_FAILED: [RecoveryStrategy.REQUEST_MANDATE_UPDATE],
    FailureClass.GATEWAY_ERROR: [RecoveryStrategy.RETRY_PAYMENT_LINK],
    FailureClass.AUTHENTICATION_FAILED: [RecoveryStrategy.RETRY_PAYMENT_LINK],
    FailureClass.UNKNOWN: [RecoveryStrategy.ESCALATE_TO_HUMAN],
}


@dataclass(frozen=True)
class CandidateScore:
    strategy: RecoveryStrategy
    probability: float
    expected_value: int         # paise (probability * amount_at_risk)
    cost: int                   # paise (intervention_cost)
    friction_penalty: int       # paise (customer / operational friction)
    score: int                  # paise (expected_value - cost - friction_penalty)
    model_version: str
    features: dict[str, object]
    rejection_reason: str | None = None


@dataclass(frozen=True)
class DecisionExplanation:
    recommended_action: RecoveryStrategy
    probability: float
    expected_recovery_paise: int
    intervention_cost_paise: int
    friction_penalty_paise: int
    opportunity_score_paise: int
    why_selected: str
    why_rejected: dict[str, str] = field(default_factory=dict)
    policy_constraints: list[str] = field(default_factory=list)


def rank_candidates(
    *,
    failure_class: FailureClass,
    amount_paise: int,
    method: str | None,
    retry_count: int,
    risk_type: str,
    merchant_segment: str = "standard",
) -> list[CandidateScore]:
    """Evaluates and ranks all policy-eligible candidates including explicit NO_ACTION."""
    eligible_strategies = list(POLICY_CANDIDATES.get(failure_class, [RecoveryStrategy.ESCALATE_TO_HUMAN]))
    
    candidate_scores: list[CandidateScore] = []
    
    # 1. Score active intervention candidates
    for strategy in eligible_strategies:
        features = build_features(
            failure_class=failure_class,
            strategy=strategy,
            amount_paise=amount_paise,
            method=method,
            retry_count=retry_count,
            risk_type=risk_type,
            merchant_segment=merchant_segment,
        )
        prediction = predict(features)
        cost = INTERVENTION_COST_PAISE.get(strategy, 0)
        friction = FRICTION_PENALTY_PAISE.get(strategy, 0)
        
        # Transparent opportunity score: Expected Value - Marginal Cost - Customer Friction
        expected_value = round(prediction.probability * amount_paise)
        opportunity_score = expected_value - cost - friction
        
        candidate_scores.append(
            CandidateScore(
                strategy=strategy,
                probability=prediction.probability,
                expected_value=expected_value,
                cost=cost,
                friction_penalty=friction,
                score=opportunity_score,
                model_version=prediction.model_version,
                features=features,
            )
        )
    
    # 2. Always evaluate explicit NO_ACTION candidate (Zero cost, Zero friction, Zero EV)
    no_action_features = build_features(
        failure_class=failure_class,
        strategy=RecoveryStrategy.NO_ACTION,
        amount_paise=amount_paise,
        method=method,
        retry_count=retry_count,
        risk_type=risk_type,
        merchant_segment=merchant_segment,
    )
    no_action_candidate = CandidateScore(
        strategy=RecoveryStrategy.NO_ACTION,
        probability=0.0,
        expected_value=0,
        cost=0,
        friction_penalty=0,
        score=0,
        model_version="deterministic-policy-v1",
        features=no_action_features,
    )
    candidate_scores.append(no_action_candidate)
    
    # 3. Sort candidates descending by net opportunity score
    ranked = sorted(candidate_scores, key=lambda c: c.score, reverse=True)
    return ranked


def build_decision_explanation(
    ranked_candidates: list[CandidateScore],
    failure_class: FailureClass,
    amount_paise: int,
    retry_count: int,
    is_bounded: bool,
    max_retries: int,
    is_high_value: bool,
    active_promise_id: int | None = None,
) -> DecisionExplanation:
    """Produces a deterministic, transparent explanation for why the selected action won and others were rejected."""
    if not ranked_candidates:
        return DecisionExplanation(
            recommended_action=RecoveryStrategy.NO_ACTION,
            probability=0.0,
            expected_recovery_paise=0,
            intervention_cost_paise=0,
            friction_penalty_paise=0,
            opportunity_score_paise=0,
            why_selected="No candidate available; defaulting to NO_ACTION.",
            why_rejected={},
            policy_constraints=["No eligible recovery candidates defined for this failure class."],
        )
    
    winner = ranked_candidates[0]
    why_rejected: dict[str, str] = {}
    policy_constraints: list[str] = []
    
    # Policy constraint checks
    if retry_count >= max_retries:
        policy_constraints.append(f"Retry quota exceeded ({retry_count}/{max_retries} attempts).")
    if is_high_value:
        policy_constraints.append(f"Amount ₹{amount_paise/100:,.2f} exceeds high-value threshold; merchant approval required.")
    if active_promise_id:
        policy_constraints.append(f"Active Promise-to-Pay #{active_promise_id} in effect; automated chasers paused.")
        
    for candidate in ranked_candidates[1:]:
        if candidate.strategy == RecoveryStrategy.NO_ACTION:
            why_rejected[candidate.strategy.value] = f"Active intervention {winner.strategy.value} yields positive Net EV (+₹{winner.score/100:,.2f})."
        elif candidate.score <= 0:
            why_rejected[candidate.strategy.value] = f"Negative expected opportunity value (₹{candidate.score/100:,.2f} <= ₹0.00)."
        else:
            why_rejected[candidate.strategy.value] = (
                f"Lower opportunity score (₹{candidate.score/100:,.2f} vs ₹{winner.score/100:,.2f}) "
                f"due to lower propensity ({candidate.probability:.1%}) or higher friction/cost."
            )
            
    if winner.strategy == RecoveryStrategy.NO_ACTION:
        why_selected = "Do nothing because expected recovery value is lower than intervention cost/friction."
    else:
        amount_fmt = f"₹{amount_paise/100:,.2f}"
        ev_fmt = f"₹{winner.expected_value/100:,.2f}"
        cost_fmt = f"₹{winner.cost/100:,.2f}"
        friction_fmt = f"₹{winner.friction_penalty/100:,.2f}"
        score_fmt = f"₹{winner.score/100:,.2f}"
        why_selected = (
            f"{winner.strategy.value} selected: recovery probability is {winner.probability:.1%}, "
            f"expected recovery is {ev_fmt} on {amount_fmt} at risk. Net opportunity score is {score_fmt} "
            f"(after intervention cost {cost_fmt} and friction penalty {friction_fmt})."
        )
        
    return DecisionExplanation(
        recommended_action=winner.strategy,
        probability=winner.probability,
        expected_recovery_paise=winner.expected_value,
        intervention_cost_paise=winner.cost,
        friction_penalty_paise=winner.friction_penalty,
        opportunity_score_paise=winner.score,
        why_selected=why_selected,
        why_rejected=why_rejected,
        policy_constraints=policy_constraints,
    )

