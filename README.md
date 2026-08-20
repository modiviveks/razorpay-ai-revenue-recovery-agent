# Razorpay AI Revenue Recovery Agent

A bounded, closed-loop payment and receivables recovery prototype. It learns and measures which **safe** intervention produces incremental recovered revenue; it never initiates a debit or grants itself financial authority.

## The problem and solution

Merchants lose revenue across payment failures, checkout abandonment, subscriptions, and overdue receivables. This service turns those signals into a measured recovery loop:

`Detect → Diagnose → Predict → Select → Policy → Execute → Verify → Measure → Learn`

The model estimates a recovery propensity from non-PII operational features (failure class, method, amount, retries, timing, segment, historical aggregate rate, and signal type). Candidate actions are scored by expected value after friction. The deterministic policy layer remains final authority: it applies retry caps, minimum amounts, approval gates, active promises-to-pay, and customer-experience suppression before an executor can create a payment link.

LLM output is advisory only. It cannot initiate a debit, change retry limits, bypass approval, contact a customer, or override a policy decision.

## Measurement

The dashboard distinguishes at-risk revenue, linked revenue, **verified recovered revenue**, and expected recoverable revenue. `simulator.experiment` runs a deterministic 10,000-event synthetic treatment/control cohort and reports **SIMULATED** incremental recovered revenue. Control recovery is natural recovery and is not attributed to AI.

## Architecture and operations

Webhooks authenticate, validate, persist an idempotent event plus a transactional outbox job, and return. `python -m agent.worker` processes pending jobs with retry/backoff and dead-letter status. `PROCESS_OUTBOX_INLINE=true` is a test-only local adapter. SQLite is the default; use any SQLAlchemy PostgreSQL `DATABASE_URL` for PostgreSQL. Schema initialization uses additive local migrations.

Every decision records model version, feature version, probability, factors, candidates, policy/action versions, and an audit hash chain. Verify an action through `/api/audit-trail/{action_id}/verify`.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
python -m agent.train_model
uvicorn main:app --reload
# separate terminal
python -m agent.worker
python simulator/scenario_runner.py --scenario all --mark-recovered
python -m simulator.experiment --size 10000
pytest -q
```

Keep `MOCK_RAZORPAY=true` for the complete local demo. Real mode requires Razorpay Test Mode credentials and a webhook secret. The test simulator bypass must never be enabled in a deployment.

## Current prototype limits

The model trains only on synthetic/local outcome data and is not automatically deployed or retrained. The experiment is simulated unless events are explicitly sourced from a real experiment. Outreach remains a draft; no notification provider is connected. Production needs managed migrations, a durable worker deployment, authentication/authorization integration, monitoring, and privacy review for each merchant deployment.
