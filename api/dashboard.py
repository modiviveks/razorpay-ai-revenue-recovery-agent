"""Serving the frontend HTML dashboard page."""

import html
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from agent.executor import log_audit_step
from config import settings
from database import get_db
from models import ActionStatus, AuditLog, PaymentEvent, PromiseToPay, RecoveryAction
import os

router = APIRouter(tags=["Dashboard"])

@router.get("/")
def get_dashboard():
    """Serves the static index HTML page."""
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(current_dir, "static", "dashboard.html")
    return FileResponse(file_path)


@router.get("/demo/payment-links/{payment_link_id}", response_class=HTMLResponse)
def get_mock_payment_link(payment_link_id: str, db: Session = Depends(get_db)):
    """Render a clickable checkout only for locally generated mock links."""
    if not settings.MOCK_RAZORPAY:
        raise HTTPException(status_code=404, detail="Mock checkout is unavailable in real mode")
    action = db.query(RecoveryAction).filter(RecoveryAction.new_payment_link_id == payment_link_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Mock payment link not found")

    amount = f"₹{action.event.amount / 100:,.2f}"
    status = action.status.value
    disabled = "disabled" if action.status == ActionStatus.RECOVERED else ""
    button_text = "Payment already verified" if action.status == ActionStatus.RECOVERED else "Simulate successful payment"
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Mock Razorpay Checkout</title><style>
body{{font-family:Arial,sans-serif;background:#f8fafc;margin:0;display:grid;place-items:center;min-height:100vh;color:#172033}}
.card{{background:#fff;width:min(430px,90vw);border-radius:18px;padding:32px;box-shadow:0 15px 45px #0f172a18}}
.tag{{color:#7c3aed;background:#f3e8ff;padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700}}
h1{{margin:18px 0 8px}} .amount{{font-size:32px;font-weight:800;margin:20px 0}} p{{color:#64748b;line-height:1.5}}
button{{width:100%;padding:14px;border:0;border-radius:10px;background:#2563eb;color:#fff;font-size:15px;font-weight:700;cursor:pointer}}
button:disabled{{background:#94a3b8;cursor:default}} #result{{margin-top:16px;font-weight:700}}
</style></head><body><main class='card'>
<span class='tag'>SANDBOX / MOCK MODE · NO REAL MONEY</span><h1>Recovery checkout</h1>
<p>Payment link <code>{html.escape(payment_link_id)}</code></p><div class='amount'>{amount}</div>
<p>Current status: <strong id='status'>{html.escape(status)}</strong>. This page simulates payment checkout in mock mode.</p>
<button id='pay' {disabled} onclick='pay()'>{button_text}</button><div id='result'></div>
<script>async function pay(){{const response=await fetch('/demo/payment-links/{html.escape(payment_link_id)}/pay',{{method:'POST'}});const data=await response.json();document.getElementById('result').textContent=data.message||data.detail;if(response.ok){{document.getElementById('status').textContent='RECOVERED';document.getElementById('pay').disabled=true;document.getElementById('pay').textContent='Payment verified';}}}}</script>
</main></body></html>"""


@router.post("/demo/payment-links/{payment_link_id}/pay")
def pay_mock_payment_link(payment_link_id: str, db: Session = Depends(get_db)):
    """Mark a local mock link as paid; never exposed in real mode."""
    if not settings.MOCK_RAZORPAY:
        raise HTTPException(status_code=404, detail="Mock checkout is unavailable in real mode")
    action = db.query(RecoveryAction).filter(RecoveryAction.new_payment_link_id == payment_link_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Mock payment link not found")
    if action.status == ActionStatus.RECOVERED:
        return {"status": "duplicate", "message": "Payment was already verified."}
    action.status = ActionStatus.RECOVERED
    action.event.status = "recovered"
    db.commit()
    log_audit_step(
        db=db,
        action_id=action.id,
        step="MOCK_PAYMENT_LINK_PAID",
        reasoning="Local demo checkout simulated a successful payment. Revenue is attributed to this recovery action.",
        api_response=json.dumps({"payment_link_id": payment_link_id, "paid_at": datetime.now(timezone.utc).isoformat()}),
        outcome="SUCCESS",
    )
    return {"status": "recovered", "message": "Mock payment verified and attributed to recovery."}


from pydantic import BaseModel
import random
import uuid
from agent.pipeline import run_recovery_pipeline
from models import FailureClass


class SimulatePayload(BaseModel):
    scenario: str
    mark_recovered: bool = False


class BatchEvalPayload(BaseModel):
    batch_size: int = 50
    seed: int = 42
    auto_pay: bool = True
    auto_pay_rate: float = 0.65


@router.post("/demo/batch-evaluation")
def trigger_batch_evaluation_api(payload: BatchEvalPayload = BatchEvalPayload()):
    """Triggers a comprehensive batch evaluation across synthetic events and updates BATCH_REPORT.md."""
    if not settings.MOCK_RAZORPAY:
        raise HTTPException(status_code=403, detail="Batch evaluation is only available in mock mode")
    from simulator.batch_eval import run_batch_evaluation
    results = run_batch_evaluation(
        batch_size=payload.batch_size,
        seed=payload.seed,
        auto_pay=payload.auto_pay,
        auto_pay_rate=payload.auto_pay_rate,
        output_report=True,
        report_path="BATCH_REPORT.md",
    )
    return results


SCENARIOS_DEF = {
    "upi_timeout": {
        "payment_id": "pay_upi_{id}",
        "amount": 120_000,
        "method": "upi",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Payment was not completed by the user on the UPI app within the timeout period.",
        "customer_name": "Priya Patel",
        "risk_type": "PAYMENT_FAILURE",
        "merchant_segment": "growth",
    },
    "card_expired": {
        "payment_id": "pay_card_{id}",
        "amount": 249_900,
        "method": "card",
        "error_code": "GATEWAY_ERROR",
        "error_description": "Card has expired. Customer entered an expired credit card validity.",
        "customer_name": "Vikram Malhotra",
        "risk_type": "PAYMENT_FAILURE",
        "merchant_segment": "standard",
    },
    "insufficient_funds": {
        "payment_id": "pay_funds_{id}",
        "amount": 85_000,
        "method": "card",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Your card has insufficient funds to complete this purchase.",
        "customer_name": "Neha Sharma",
        "risk_type": "PAYMENT_FAILURE",
        "merchant_segment": "standard",
    },
    "user_cancelled": {
        "payment_id": "pay_canc_{id}",
        "amount": 45_000,
        "method": "upi",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Payment was cancelled by the user during authorization.",
        "customer_name": "Aditya Rao",
        "risk_type": "PAYMENT_FAILURE",
        "merchant_segment": "growth",
    },
    "bank_decline": {
        "payment_id": "pay_bank_{id}",
        "amount": 320_000,
        "method": "netbanking",
        "error_code": "GATEWAY_ERROR",
        "error_description": "Transaction declined by customer issuing bank switch.",
        "customer_name": "Rajesh Gupta",
        "risk_type": "PAYMENT_FAILURE",
        "merchant_segment": "enterprise",
    },
    "subscription_failed": {
        "payment_id": "pay_sub_{id}",
        "amount": 99_900,
        "method": "card",
        "error_code": "GATEWAY_ERROR",
        "error_description": "Subscription auto-debit recurring mandate execution failed.",
        "customer_name": "Ananya Roy",
        "risk_type": "SUBSCRIPTION_HALTED",
        "merchant_segment": "growth",
    },
    "below_minimum": {
        "payment_id": "pay_low_{id}",
        "amount": 50,  # ₹0.50 -> Negative EV
        "method": "upi",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Micro-transaction failed on customer PSP app.",
        "customer_name": "Ramesh Kumar",
        "risk_type": "PAYMENT_FAILURE",
        "merchant_segment": "standard",
    },
    "high_value_hold": {
        "payment_id": "pay_high_{id}",
        "amount": 650_000,  # ₹6,500.00 -> High value approval gate
        "method": "card",
        "error_code": "GATEWAY_ERROR",
        "error_description": "High ticket enterprise order authorization failed.",
        "customer_name": "Siddharth Enterprise Ltd",
        "risk_type": "PAYMENT_FAILURE",
        "merchant_segment": "enterprise",
    },
    "checkout_abandoned": {
        "payment_id": "pay_abn_{id}",
        "amount": 180_000,
        "method": "upi",
        "error_code": "CHECKOUT_ABANDONED",
        "error_description": "Customer dropped off at final OTP verification screen.",
        "customer_name": "Sneha Iyer",
        "risk_type": "CHECKOUT_ABANDONMENT",
        "merchant_segment": "growth",
    },
    "receivable_overdue": {
        "payment_id": "inv_overdue_{id}",
        "amount": 450_000,  # ₹4,500.00
        "method": "netbanking",
        "error_code": "RECEIVABLE_OVERDUE",
        "error_description": "B2B net-30 vendor invoice is past due date.",
        "customer_name": "Apex Digital Solutions",
        "risk_type": "RECEIVABLE_OVERDUE",
        "merchant_segment": "enterprise",
    },
}


@router.post("/demo/simulate")
def simulate_scenario(payload: SimulatePayload, db: Session = Depends(get_db)):
    """Triggers realistic simulated failure scenarios for interactive evaluation."""
    if not settings.MOCK_RAZORPAY:
        raise HTTPException(status_code=403, detail="Simulations only available in mock mode")

    scenarios_to_run = (
        list(SCENARIOS_DEF.keys()) if payload.scenario == "all"
        else [payload.scenario] if payload.scenario in SCENARIOS_DEF
        else ["upi_timeout"]
    )

    created_actions = []
    for sc_key in scenarios_to_run:
        defn = SCENARIOS_DEF[sc_key]
        uid = uuid.uuid4().hex[:6]
        pid = defn["payment_id"].format(id=uid)
        
        event = PaymentEvent(
            payment_id=pid,
            order_id=f"order_{uid}",
            amount=defn["amount"],
            currency="INR",
            method=defn["method"],
            status="at_risk",
            risk_type=defn["risk_type"],
            source_reference=pid,
            error_code=defn["error_code"],
            error_description=defn["error_description"],
            customer_name=defn["customer_name"],
            merchant_segment=defn["merchant_segment"],
            customer_email=f"{defn['customer_name'].lower().replace(' ', '')}@example.com",
            customer_contact="+919876543210",
            webhook_event_id=f"evt_{uid}",
            raw_payload=json.dumps({"simulated": True, "scenario": sc_key}),
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        action = run_recovery_pipeline(
            db=db,
            event=event,
            forced_failure_class=None,
            forced_rationale=f"Simulated test scenario: {sc_key}",
        )

        if payload.mark_recovered and action.status in {ActionStatus.SUCCESS, ActionStatus.PENDING}:
            action.status = ActionStatus.RECOVERED
            event.status = "recovered"
            db.commit()
            log_audit_step(
                db=db,
                action_id=action.id,
                step="MOCK_PAYMENT_LINK_PAID",
                reasoning="Simulated immediate customer payment via generated recovery link.",
                outcome="SUCCESS",
            )

        created_actions.append({"payment_id": pid, "action_id": action.id, "status": action.status.value})

    return {
        "status": "success",
        "message": f"Ran {len(created_actions)} simulated scenario(s)",
        "actions": created_actions,
    }


class RazorpayTestTriggerRequest(BaseModel):
    amount_paise: int = 49900  # ₹499.00
    customer_name: str = "Test Customer"
    customer_email: str = "test.customer@example.com"
    customer_contact: str = "+919876543210"
    failure_reason: str = "UPI transaction timed out on customer PSP app"
    method: str = "upi"
    merchant_segment: str = "growth"


@router.post("/demo/razorpay-test/payment-link")
def trigger_razorpay_test_recovery(
    payload: RazorpayTestTriggerRequest = RazorpayTestTriggerRequest(),
    db: Session = Depends(get_db)
):
    """
    Trigger the end-to-end recovery flow generating an authentic Razorpay Test Mode Payment Link.
    This creates an actual Razorpay Payment Link in Test Mode when RAZORPAY_MODE='test' (or mock link in 'mock' mode).
    """
    uid = uuid.uuid4().hex[:6]
    payment_id = f"pay_test_{uid}"
    
    event = PaymentEvent(
        payment_id=payment_id,
        order_id=f"order_test_{uid}",
        amount=payload.amount_paise,
        currency="INR",
        method=payload.method,
        status="at_risk",
        risk_type="PAYMENT_FAILURE",
        source_reference=payment_id,
        error_code="BAD_REQUEST_ERROR" if payload.method == "upi" else "GATEWAY_ERROR",
        error_description=payload.failure_reason,
        customer_name=payload.customer_name,
        customer_email=payload.customer_email,
        customer_contact=payload.customer_contact,
        merchant_segment=payload.merchant_segment,
        webhook_event_id=f"evt_test_{uid}",
        raw_payload=json.dumps({
            "source": "razorpay_test_demo_trigger",
            "amount": payload.amount_paise,
            "mode": settings.RAZORPAY_MODE
        }),
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    action = run_recovery_pipeline(
        db=db,
        event=event,
    )

    return {
        "status": "success",
        "mode": settings.RAZORPAY_MODE,
        "is_test_mode": (settings.RAZORPAY_MODE == "test"),
        "event_id": event.id,
        "payment_id": event.payment_id,
        "action_id": action.id,
        "action_status": action.status.value,
        "failure_class": action.failure_class.value,
        "strategy": action.strategy.value,
        "payment_link_id": action.new_payment_link_id,
        "payment_link_url": action.new_payment_link_url,
        "expected_recovery_amount_rupees": round((action.expected_recovery_amount or 0) / 100, 2),
        "recovery_confidence": action.recovery_confidence,
        "outreach_message": action.outreach_message,
        "rationale": action.rationale,
    }


@router.post("/demo/reset")
def reset_mock_demo(db: Session = Depends(get_db)):
    """Reset only local mock demo data; unavailable whenever real mode is enabled."""
    if not settings.MOCK_RAZORPAY:
        raise HTTPException(status_code=404, detail="Demo reset is unavailable in real mode")
    db.query(AuditLog).delete()
    db.query(PromiseToPay).delete()
    db.query(RecoveryAction).delete()
    db.query(PaymentEvent).delete()
    db.commit()
    return {"status": "reset", "message": "Mock demo data cleared."}
