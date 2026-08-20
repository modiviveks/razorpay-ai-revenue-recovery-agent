"""Reproducible treatment/control simulator for incremental recovery measurement."""

from dataclasses import dataclass
import random

from models import FailureClass
from agent.intelligence import BASE_RECOVERY_PROBABILITY


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    sample_size: int
    treatment_size: int
    control_size: int
    treatment_at_risk: int
    control_at_risk: int
    treatment_recovered: int
    control_recovered: int
    treatment_recovery_rate: float
    control_recovery_rate: float
    incremental_lift: float
    incremental_recovered_revenue: int


def run_experiment(sample_size: int = 10000, seed: int = 42, experiment_id: str = "demo-v1") -> ExperimentResult:
    rng = random.Random(seed)
    treatment_recovered = control_recovered = 0
    treatment_at_risk = control_at_risk = 0
    treatment_size = sample_size // 2
    control_size = sample_size - treatment_size

    classes = list(BASE_RECOVERY_PROBABILITY)
    for index in range(sample_size):
        failure_class = rng.choice(classes)
        amount = rng.randint(5_000, 100_000)
        base = BASE_RECOVERY_PROBABILITY[failure_class]
        treated = index < treatment_size
        # The treatment uplift is intentionally small and bounded to model an
        # intervention effect rather than manufacture implausibly large wins.
        probability = min(0.90, base + (0.08 if treated else 0.0))
        recovered = rng.random() < probability
        if treated:
            treatment_at_risk += amount
            treatment_recovered += amount if recovered else 0
        else:
            control_at_risk += amount
            control_recovered += amount if recovered else 0

    treatment_rate = treatment_recovered / treatment_at_risk if treatment_at_risk else 0.0
    control_rate = control_recovered / control_at_risk if control_at_risk else 0.0
    lift = treatment_rate - control_rate
    expected_control_revenue = round(control_rate * treatment_at_risk)
    incremental = max(0, treatment_recovered - expected_control_revenue)
    return ExperimentResult(
        experiment_id, sample_size, treatment_size, control_size,
        treatment_at_risk, control_at_risk, treatment_recovered, control_recovered,
        round(treatment_rate, 4), round(control_rate, 4), round(lift, 4), incremental,
    )
