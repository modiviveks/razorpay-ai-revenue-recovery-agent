"""Deterministic, explicitly SIMULATED control/treatment revenue experiment."""
from __future__ import annotations
import argparse, json
import numpy as np
from agent.recovery_model import RecoveryPropensityModel, feature_row

def run_experiment(size: int = 10_000, seed: int = 7) -> dict:
    rng=np.random.default_rng(seed); model=RecoveryPropensityModel(); model.load()
    variants={"control": {"at_risk":0,"recovered":0,"interventions":0,"stopped":0}, "treatment": {"at_risk":0,"recovered":0,"interventions":0,"stopped":0}}
    classes=["UPI_TIMEOUT","BANK_DECLINE","INSUFFICIENT_FUNDS","CARD_EXPIRED","CHECKOUT_ABANDONED","SUBSCRIPTION_FAILED","RECEIVABLE_OVERDUE"]
    for i in range(size):
        variant="treatment" if i % 2 else "control"; amount=int(rng.integers(5_000, 200_000)); fc=str(rng.choice(classes)); method=str(rng.choice(["upi","card","netbanking"]))
        natural={"UPI_TIMEOUT":.16,"BANK_DECLINE":.07,"INSUFFICIENT_FUNDS":.03,"CARD_EXPIRED":.04,"CHECKOUT_ABANDONED":.09,"SUBSCRIPTION_FAILED":.05,"RECEIVABLE_OVERDUE":.12}[fc]
        row=feature_row(failure_class=fc,method=method,amount_paise=amount,retry_count=0,hours_since_failure=1,historical_success_rate=.4,hour=12,merchant_segment="standard",risk_type="PAYMENT_FAILURE",candidate_strategy="RETRY_PAYMENT_LINK")
        p=model.predict(row).probability
        allowed=fc not in {"SUBSCRIPTION_FAILED"} and amount >= 100
        recovered = rng.random() < (natural if variant=="control" or not allowed else min(.92, natural + .35*p))
        item=variants[variant]; item["at_risk"] += amount; item["recovered"] += amount if recovered else 0
        item["interventions"] += int(variant=="treatment" and allowed); item["stopped"] += int(variant=="treatment" and not allowed)
    for item in variants.values(): item["recovery_rate"] = round(item["recovered"]/item["at_risk"],4)
    control, treatment=variants["control"],variants["treatment"]
    return {"label":"SIMULATED — not real Razorpay revenue", "experiment_id":f"sim-{seed}","sample_size":size,"variants":variants,
            "incremental_recovered_revenue_paise":treatment["recovered"]-control["recovered"], "incremental_lift":round(treatment["recovery_rate"]-control["recovery_rate"],4),
            "recovery_roi":round((treatment["recovered"]-control["recovered"])/max(1,treatment["interventions"]*100),2)}
if __name__ == "__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--size",type=int,default=10_000); args=parser.parse_args(); print(json.dumps(run_experiment(args.size),indent=2))
