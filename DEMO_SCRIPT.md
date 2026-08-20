# Razorpay AI Revenue Recovery — demo

Open with: **“A merchant has ₹10 lakh at risk. The question is not whether to chase every failure; it is which safe intervention creates incremental recovered revenue.”**

1. Start the local server in mock mode and open the dashboard.
2. Run `python -m agent.train_model`, then `python -m simulator.experiment --size 10000`. State clearly that its output is **SIMULATED**, not Razorpay revenue.
3. Point out control's natural recovery and treatment's recovered amount separately. The hero metric is `incremental_recovered_revenue_paise`.
4. Post a failed UPI payment. Show: detect → classification → model probability → candidate scores → policy-approved payment-link action.
5. Post the same failure until retry bounds stop it. The model can rank an action, but it cannot add retries or bypass policy.
6. Complete the mock link. Show the verified payment-success audit record and recovered revenue—not merely linked revenue.
7. Open `/api/audit-trail/{action_id}/verify`; it returns `VALID` for the tamper-evident hash chain.
8. Finish with: **“The system optimizes incremental recovered revenue, while deterministic policy remains the authority over every financial action.”**
