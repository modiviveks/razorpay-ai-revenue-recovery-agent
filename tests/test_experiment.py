from agent.experiment import run_experiment
from agent.intelligence import predict_recovery, MODEL_VERSION
from models import FailureClass, RecoveryStrategy


def test_propensity_prediction_is_bounded_and_versioned():
    result = predict_recovery(FailureClass.UPI_TIMEOUT, RecoveryStrategy.RETRY_PAYMENT_LINK, 50000, 0)
    assert 0.05 <= result.confidence <= 0.90
    assert result.expected_recovery_amount >= 0
    assert result.model_version in {MODEL_VERSION, "rule-baseline-v1"}


def test_control_treatment_experiment_is_reproducible_and_reports_incremental_value():
    first = run_experiment(sample_size=1000, seed=7)
    second = run_experiment(sample_size=1000, seed=7)
    assert first == second
    assert first.treatment_size + first.control_size == 1000
    assert 0 <= first.control_recovery_rate <= 1
    assert 0 <= first.treatment_recovery_rate <= 1
    assert first.incremental_recovered_revenue >= 0
