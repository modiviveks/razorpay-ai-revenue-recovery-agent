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
from models import ActionStatus, RecoveryAction
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
<span class='tag'>LOCAL DEMO · NO REAL MONEY</span><h1>Recovery checkout</h1>
<p>Payment link <code>{html.escape(payment_link_id)}</code></p><div class='amount'>{amount}</div>
<p>Current status: <strong id='status'>{html.escape(status)}</strong>. This page exists only in mock mode for a clickable buildathon demonstration.</p>
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
