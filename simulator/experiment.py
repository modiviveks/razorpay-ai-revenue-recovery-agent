"""Reproducible synthetic control/treatment experiment with statistical significance testing."""

import argparse
import json
import math
import random
import uuid
from collections import defaultdict

from agent.next_best_action import rank_candidates
from agent.recovery_model import load_model
from models import ExperimentRun, FailureClass, RecoveryStrategy


FAILURES = [
    FailureClass.UPI_TIMEOUT,
    FailureClass.BANK_DECLINE,
    FailureClass.INSUFFICIENT_FUNDS,
    FailureClass.CARD_EXPIRED,
    FailureClass.PAYMENT_CANCELLED,
    FailureClass.CHECKOUT_ABANDONED,
    FailureClass.RECEIVABLE_OVERDUE,
]

SEGMENTS = ["standard", "growth", "enterprise"]


def calculate_two_proportion_stats(
    n_treatment: int,
    success_treatment: int,
    n_control: int,
    success_control: int,
) -> dict[str, float]:
    """Calculates difference, standard error, 95% CI, z-score, and p-value for two independent samples."""
    p_t = success_treatment / max(n_treatment, 1)
    p_c = success_control / max(n_control, 1)
    diff = p_t - p_c

    # Pooled standard error for two proportions
    se = math.sqrt(max(1e-12, (p_t * (1 - p_t) / max(n_treatment, 1)) + (p_c * (1 - p_c) / max(n_control, 1))))
    
    ci_lower = round(diff - 1.96 * se, 4)
    ci_upper = round(diff + 1.96 * se, 4)
    z_score = diff / se if se > 0 else 0.0

    # Two-tailed p-value using normal approximation (erfc)
    p_value = math.erfc(abs(z_score) / math.sqrt(2))

    relative_lift = (diff / p_c) if p_c > 0 else 0.0

    return {
        "treatment_rate": round(p_t, 4),
        "control_rate": round(p_c, 4),
        "absolute_lift": round(diff, 4),
        "relative_lift": round(relative_lift, 4),
        "standard_error": round(se, 4),
        "ci_95_lower": ci_lower,
        "ci_95_upper": ci_upper,
        "z_score": round(z_score, 3),
        "p_value": round(p_value, 6),
        "statistically_significant": bool(p_value < 0.05),
    }


def run_experiment(db, sample_size: int = 10_000, seed: int = 2026, experiment_id: str | None = None):
    """Simulate balanced variants. Figures are always explicitly labelled synthetic."""
    rng = random.Random(seed)
    experiment_id = experiment_id or f"sim-{uuid.uuid4().hex[:10]}"

    aggregate = defaultdict(lambda: {
        "events": 0,
        "success_count": 0,
        "at_risk": 0,
        "recovered": 0,
        "interventions": 0,
        "stopped": 0,
    })
    by_failure = defaultdict(lambda: {
        "control": 0,
        "treatment": 0,
        "control_recovered": 0,
        "treatment_recovered": 0,
        "control_success_count": 0,
        "treatment_success_count": 0,
    })
    by_segment = defaultdict(lambda: {
        "at_risk": 0,
        "recovered": 0,
        "interventions": 0,
        "events": 0,
        "control_recovered": 0,
        "treatment_recovered": 0,
        "intervention_types": defaultdict(int),
    })

    # Natural latent recovery probability (control baseline)
    natural_base = {
        FailureClass.UPI_TIMEOUT: 0.12,
        FailureClass.BANK_DECLINE: 0.09,
        FailureClass.INSUFFICIENT_FUNDS: 0.05,
        FailureClass.CARD_EXPIRED: 0.07,
        FailureClass.PAYMENT_CANCELLED: 0.10,
        FailureClass.CHECKOUT_ABANDONED: 0.08,
        FailureClass.RECEIVABLE_OVERDUE: 0.15,
    }

    for index in range(sample_size):
        variant = "treatment" if index % 2 else "control"
        failure = rng.choice(FAILURES)
        amount = rng.choice([5_000, 15_000, 35_000, 75_000, 150_000, 300_000])
        method = rng.choice(["upi", "card", "netbanking"])
        segment = rng.choice(SEGMENTS)
        risk_type = (
            "RECEIVABLE_OVERDUE" if failure == FailureClass.RECEIVABLE_OVERDUE
            else ("CHECKOUT_ABANDONMENT" if failure == FailureClass.CHECKOUT_ABANDONED else "PAYMENT_FAILURE")
        )

        bucket = aggregate[variant]
        bucket["events"] += 1
        bucket["at_risk"] += amount
        by_failure[failure.value][variant] += 1

        seg_bucket = by_segment[segment]
        seg_bucket["events"] += 1
        seg_bucket["at_risk"] += amount

        natural_prob = natural_base[failure]
        intervention = None

        if variant == "treatment":
            candidates = rank_candidates(
                failure_class=failure,
                amount_paise=amount,
                method=method,
                retry_count=0,
                risk_type=risk_type,
                merchant_segment=segment,
            )
            # Select non-NO_ACTION candidate if positive score
            if candidates and candidates[0].strategy != RecoveryStrategy.NO_ACTION and candidates[0].score > 0:
                intervention = candidates[0]
                bucket["interventions"] += 1
                seg_bucket["interventions"] += 1
                seg_bucket["intervention_types"][intervention.strategy.value] += 1
                # Synthetic treatment lift
                natural_prob += min(0.20, 0.05 + intervention.probability * 0.22)
            else:
                bucket["stopped"] += 1

        recovered = rng.random() < natural_prob
        if recovered:
            bucket["recovered"] += amount
            bucket["success_count"] += 1
            by_failure[failure.value][f"{variant}_recovered"] += amount
            by_failure[failure.value][f"{variant}_success_count"] += 1
            seg_bucket["recovered"] += amount
            seg_bucket[f"{variant}_recovered"] += amount

    control = aggregate["control"]
    treatment = aggregate["treatment"]

    control_val_rate = control["recovered"] / max(control["at_risk"], 1)
    treatment_val_rate = treatment["recovered"] / max(treatment["at_risk"], 1)
    incremental_revenue = treatment["recovered"] - round(control_val_rate * treatment["at_risk"])
    intervention_cost = treatment["interventions"] * 45  # average paise cost per intervention

    # Statistical significance on event-level conversion rates
    stat_results = calculate_two_proportion_stats(
        n_treatment=treatment["events"],
        success_treatment=treatment["success_count"],
        n_control=control["events"],
        success_control=control["success_count"],
    )

    # Segment performance breakdown
    segment_analytics = {}
    for seg_name, s_data in by_segment.items():
        top_strat = (
            max(s_data["intervention_types"].items(), key=lambda x: x[1])[0]
            if s_data["intervention_types"] else "RETRY_PAYMENT_LINK"
        )
        c_rec = s_data["control_recovered"]
        t_rec = s_data["treatment_recovered"]
        segment_analytics[seg_name] = {
            "events": s_data["events"],
            "at_risk_rupees": round(s_data["at_risk"] / 100, 2),
            "recovered_rupees": round(s_data["recovered"] / 100, 2),
            "recovery_rate": round(s_data["recovered"] / max(s_data["at_risk"], 1), 4),
            "incremental_recovered_rupees": round(max(0, t_rec - c_rec) / 100, 2),
            "most_effective_intervention": top_strat,
        }

    results = {
        "label": "SIMULATED — not real Razorpay merchant revenue",
        "notice": "Results reflect a synthetic local benchmark designed for buildathon evaluation. Do not imply real-world causal certainty without running an A/B test on production traffic.",
        "experiment_id": experiment_id,
        "sample_size": sample_size,
        "seed": seed,
        "model_version": (load_model() or {"metadata": {"model_version": "fallback-priors-v2"}})["metadata"]["model_version"],
        "control": control,
        "treatment": treatment,
        "control_recovery_rate": round(control_val_rate, 4),
        "treatment_recovery_rate": round(treatment_val_rate, 4),
        "incremental_recovery_rate": round(treatment_val_rate - control_val_rate, 4),
        "incremental_recovered_revenue_paise": incremental_revenue,
        "intervention_cost_paise": intervention_cost,
        "recovery_roi": round((incremental_revenue - intervention_cost) / max(intervention_cost, 1), 2),
        "statistical_inference": {
            "metric": "Event-Level Conversion Rate Difference",
            "control_conversion_rate": stat_results["control_rate"],
            "treatment_conversion_rate": stat_results["treatment_rate"],
            "absolute_lift": stat_results["absolute_lift"],
            "relative_lift": stat_results["relative_lift"],
            "standard_error": stat_results["standard_error"],
            "confidence_interval_95": [stat_results["ci_95_lower"], stat_results["ci_95_upper"]],
            "z_score": stat_results["z_score"],
            "p_value": stat_results["p_value"],
            "statistically_significant": stat_results["statistically_significant"],
            "conclusion": (
                f"Statistically significant treatment lift (p={stat_results['p_value']:.4e} < 0.05, "
                f"95% CI [{stat_results['ci_95_lower']:.1%}, {stat_results['ci_95_upper']:.1%}])."
                if stat_results["statistically_significant"]
                else "Difference is within random sampling noise (p >= 0.05)."
            ),
        },
        "by_failure_class": dict(by_failure),
        "by_merchant_segment": segment_analytics,
    }

    record = ExperimentRun(
        experiment_id=experiment_id,
        sample_size=sample_size,
        seed=seed,
        model_version=results["model_version"],
        results_json=json.dumps(results),
    )
    db.add(record)
    db.commit()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run synthetic revenue recovery A/B experiment.")
    parser.add_argument("--size", type=int, default=10_000, help="Number of simulated events (e.g. 10000)")
    parser.add_argument("--seed", type=int, default=2026, help="Random seed")
    args = parser.parse_args()

    from database import SessionLocal, init_db
    init_db()
    with SessionLocal() as session:
        output = run_experiment(session, sample_size=args.size, seed=args.seed)
        print(json.dumps(output, indent=2))
