from agent.next_best_action import rank_candidates
from agent.recovery_model import build_features, predict, train
from models import FailureClass, RecoveryStrategy


def test_model_trains_and_predicts_probability():
    metadata = train(samples=400, seed=9)
    features = build_features(
        failure_class=FailureClass.UPI_TIMEOUT,
        strategy=RecoveryStrategy.RETRY_PAYMENT_LINK,
        amount_paise=50_000, method="upi", retry_count=0,
        risk_type="PAYMENT_FAILURE",
    )
    result = predict(features)
    assert metadata["training_sample_count"] == 400
    assert result.model_version == "recovery-logreg-v2"
    assert 0 <= result.probability <= 1
    assert "calibration" in metadata["metrics"]


def test_candidate_engine_only_ranks_policy_allowed_actions():
    candidates = rank_candidates(
        failure_class=FailureClass.CARD_EXPIRED, amount_paise=50_000,
        method="card", retry_count=0, risk_type="PAYMENT_FAILURE", merchant_segment="standard",
    )
    strategies = [candidate.strategy for candidate in candidates]
    # Active candidate must be ALTERNATE_METHOD_LINK plus explicit NO_ACTION
    assert RecoveryStrategy.ALTERNATE_METHOD_LINK in strategies
    assert RecoveryStrategy.NO_ACTION in strategies
    assert candidates[0].strategy == RecoveryStrategy.ALTERNATE_METHOD_LINK
    assert candidates[0].expected_value >= 0
