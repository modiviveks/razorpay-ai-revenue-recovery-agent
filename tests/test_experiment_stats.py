"""Unit tests for synthetic experiment statistical confidence calculations."""

from simulator.experiment import calculate_two_proportion_stats


def test_two_proportion_statistical_significance():
    # 5,000 treatment samples with 30% recovery, 5,000 control samples with 10% recovery
    stats = calculate_two_proportion_stats(
        n_treatment=5000,
        success_treatment=1500,
        n_control=5000,
        success_control=500,
    )
    assert stats["treatment_rate"] == 0.30
    assert stats["control_rate"] == 0.10
    assert stats["absolute_lift"] == 0.20
    assert stats["relative_lift"] == 2.0  # 200% relative lift
    assert stats["statistically_significant"] is True
    assert stats["p_value"] < 0.001
    assert stats["ci_95_lower"] > 0.18
    assert stats["ci_95_upper"] < 0.22


def test_two_proportion_insignificant_noise():
    # Similar rates with high p-value
    stats = calculate_two_proportion_stats(
        n_treatment=100,
        success_treatment=20,
        n_control=100,
        success_control=19,
    )
    assert stats["absolute_lift"] == 0.01
    assert stats["statistically_significant"] is False
    assert stats["p_value"] > 0.05
