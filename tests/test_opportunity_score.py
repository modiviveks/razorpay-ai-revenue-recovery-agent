"""Unit tests for Recovery Opportunity Scoring and transparent ranking."""

from models import FailureClass, RecoveryStrategy
from agent.next_best_action import rank_candidates, INTERVENTION_COST_PAISE, FRICTION_PENALTY_PAISE


def test_opportunity_score_formula_and_transparency():
    amount = 100_000  # ₹1,000.00
    candidates = rank_candidates(
        failure_class=FailureClass.BANK_DECLINE,
        amount_paise=amount,
        method="card",
        retry_count=0,
        risk_type="PAYMENT_FAILURE",
        merchant_segment="enterprise",
    )
    assert len(candidates) >= 2
    for c in candidates:
        # Check that score = expected_value - cost - friction
        assert c.score == c.expected_value - c.cost - c.friction_penalty
        assert c.cost == INTERVENTION_COST_PAISE.get(c.strategy, 0)
        assert c.friction_penalty == FRICTION_PENALTY_PAISE.get(c.strategy, 0)


def test_ranking_prefers_higher_net_opportunity():
    candidates = rank_candidates(
        failure_class=FailureClass.UPI_TIMEOUT,
        amount_paise=50_000,
        method="upi",
        retry_count=0,
        risk_type="PAYMENT_FAILURE",
    )
    # Check descending order of scores
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)
