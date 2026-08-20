"""Reproducible synthetic control/treatment experiment for incremental impact."""

import json
import random
import uuid
from collections import defaultdict

from agent.next_best_action import rank_candidates
from agent.recovery_model import load_model
from models import ExperimentRun, FailureClass


FAILURES = [FailureClass.UPI_TIMEOUT, FailureClass.BANK_DECLINE, FailureClass.INSUFFICIENT_FUNDS,
            FailureClass.CARD_EXPIRED, FailureClass.PAYMENT_CANCELLED, FailureClass.CHECKOUT_ABANDONED,
            FailureClass.RECEIVABLE_OVERDUE]


def run_experiment(db, sample_size: int = 10_000, seed: int = 2026, experiment_id: str | None = None):
    """Simulate balanced variants. Figures are always labelled synthetic."""
    rng = random.Random(seed)
    experiment_id = experiment_id or f"sim-{uuid.uuid4().hex[:10]}"
    aggregate = defaultdict(lambda: {"events": 0, "at_risk": 0, "recovered": 0, "interventions": 0, "stopped": 0})
    by_failure = defaultdict(lambda: {"control": 0, "treatment": 0, "control_recovered": 0, "treatment_recovered": 0})
    # Latent recovery rate is intentionally modest. Treatment generates a
    # synthetic incremental effect only when an eligible intervention is used.
    natural_base = {FailureClass.UPI_TIMEOUT: .12, FailureClass.BANK_DECLINE: .09,
                    FailureClass.INSUFFICIENT_FUNDS: .05, FailureClass.CARD_EXPIRED: .07,
                    FailureClass.PAYMENT_CANCELLED: .10, FailureClass.CHECKOUT_ABANDONED: .08,
                    FailureClass.RECEIVABLE_OVERDUE: .15}
    for index in range(sample_size):
        variant = "treatment" if index % 2 else "control"
        failure = rng.choice(FAILURES)
        amount = rng.choice([5_000, 15_000, 35_000, 75_000, 150_000, 300_000])
        method = rng.choice(["upi", "card", "netbanking"])
        risk_type = "RECEIVABLE_OVERDUE" if failure == FailureClass.RECEIVABLE_OVERDUE else (
            "CHECKOUT_ABANDONMENT" if failure == FailureClass.CHECKOUT_ABANDONED else "PAYMENT_FAILURE")
        bucket = aggregate[variant]
        bucket["events"] += 1
        bucket["at_risk"] += amount
        by_failure[failure.value][variant] += 1
        natural_probability = natural_base[failure]
        intervention = None
        if variant == "treatment":
            candidates = rank_candidates(failure_class=failure, amount_paise=amount, method=method,
                                         retry_count=0, risk_type=risk_type, merchant_segment="standard")
            if candidates and candidates[0].score > 0:
                intervention = candidates[0]
                bucket["interventions"] += 1
                # Fixed synthetic response model, intentionally distinct from
                # the trained predictor to avoid claiming causal certainty.
                natural_probability += min(.18, .04 + intervention.probability * .20)
            else:
                bucket["stopped"] += 1
        recovered = rng.random() < natural_probability
        if recovered:
            bucket["recovered"] += amount
            by_failure[failure.value][f"{variant}_recovered"] += amount
    control, treatment = aggregate["control"], aggregate["treatment"]
    control_rate = control["recovered"] / max(control["at_risk"], 1)
    treatment_rate = treatment["recovered"] / max(treatment["at_risk"], 1)
    incremental_rate = treatment_rate - control_rate
    incremental_revenue = treatment["recovered"] - round(control_rate * treatment["at_risk"])
    intervention_cost = treatment["interventions"] * 45
    results = {
        "label": "SIMULATED — not real Razorpay merchant revenue",
        "experiment_id": experiment_id,
        "sample_size": sample_size,
        "seed": seed,
        "model_version": (load_model() or {"metadata": {"model_version": "fallback-priors-v1"}})["metadata"]["model_version"],
        "control": control,
        "treatment": treatment,
        "control_recovery_rate": round(control_rate, 4),
        "treatment_recovery_rate": round(treatment_rate, 4),
        "incremental_recovery_rate": round(incremental_rate, 4),
        "incremental_recovered_revenue_paise": incremental_revenue,
        "intervention_cost_paise": intervention_cost,
        "recovery_roi": round((incremental_revenue - intervention_cost) / max(intervention_cost, 1), 2),
        "by_failure_class": by_failure,
    }
    record = ExperimentRun(experiment_id=experiment_id, sample_size=sample_size, seed=seed,
                           model_version=results["model_version"], results_json=json.dumps(results))
    db.add(record)
    db.commit()
    return results


if __name__ == "__main__":
    from database import SessionLocal, init_db
    init_db()
    with SessionLocal() as session:
        print(json.dumps(run_experiment(session), indent=2))
