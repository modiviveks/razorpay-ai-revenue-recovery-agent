# Razorpay AI Revenue Recovery Agent

> A safe, auditable recovery workflow that turns failed-payment signals into bounded recovery actions and verified recovered-revenue attribution.

An intelligent revenue recovery agent built to automate payment failure recovery loops on Razorpay APIs. It listens to payment failures, classifies the error cause, enforces recovery rules & safety bounds, generates alternate payment links via Razorpay APIs, and maintains a detailed step-by-step decision audit trail on a dashboard.

It also accepts normalised merchant signals for checkout abandonment and overdue receivables, plus Razorpay-style subscription lifecycle events. Each signal enters the same bounded, auditable recovery policy.

This project was built for **Track 03 — AI Revenue Recovery** for the Razorpay hackathon.

---

## Safety and metric semantics

- The default integration is **mock mode**. Set `MOCK_RAZORPAY=false` only with Razorpay Test Mode credentials and a configured webhook secret.
- `X-Test-Simulator: true` is accepted only when `ALLOW_TEST_WEBHOOK_BYPASS=true`; never enable it in a deployed environment.
- Webhook deliveries are idempotent using Razorpay's event ID header (or a payload hash fallback), preventing duplicate recovery links.
- The dashboard's **Amount Linked** and **Link Generation Rate** measure recovery opportunities, not collected revenue. Recovered-revenue reporting requires a verified payment-success webhook and reconciliation to the recovery action.
- Outreach is generated as a draft only. No SMS, email, or WhatsApp message is sent by this service.
- High-value actions require explicit merchant approval before a payment link is created. Configure the threshold using `REQUIRE_APPROVAL_OVER_PAISE`.
- Decision confidence is a transparent, rule-based prioritisation signal. It never overrides safety gates or triggers a debit.
- Audit evidence redacts email addresses and phone numbers before persistence. Set `DASHBOARD_API_KEY` when exposing dashboard APIs outside a local demo.
- The dashboard visibly labels Mock Mode and marks its recovery metrics as simulated. Only a real signed Razorpay payment-success webhook should be presented as recovered revenue in production.

## Key Features

1. **Failure Classification Engine**: Maps error details to high-level failure classes (e.g. UPI timeout, insufficient funds, card expired).
2. **Strategy Selector**: Automatically determines appropriate recovery actions based on failure type, amount limit, and retry count.
3. **Execution Engine**: Interfaces with Razorpay API (or simulator mock mode) to create short-lived payment links.
4. **Safety & Bounds Enforcement**: 
   - **Lower Bound (Gated Minimum)**: Prevents action for transactions below ₹1.00.
   - **Upper Bound (Max Retries)**: Strict retry limits (e.g., maximum 2 retry links for UPI timeouts) to prevent spamming customers.
   - **Safety Gating**: Does *not* auto-charge accounts on insufficient funds or card failures; instead, sends standard alternative payment links.
5. **Detailed Decision Audit Trail**: A complete step-by-step reasoning log for every money action, showing raw API payloads and outcomes.
6. **Live Interactive Dashboard**: Built with FastAPI, Tailwind CSS, and HTML5 to monitor recovery status, success rates, and inspect agent audit logs.
7. **Webhook Failure Simulator**: A built-in CLI tool simulating 7 payment failure scenarios.
8. **Multi-Source Revenue Risk**: Supports `payment.failed`, `checkout.abandoned`, `subscription.pending`, `subscription.halted` and normalised `receivable.overdue` signals.
9. **Promise-to-Pay Tracker**: Records a B2B customer commitment, pauses automatic chasers, and escalates a broken promise to merchant collections review without an auto-debit.

---

## Directory Structure

```
razorpay-recovery-agent/
├── main.py                  # FastAPI server entrypoint
├── config.py                # Environment configuration & constants
├── database.py              # SQLite & SQLAlchemy engine setup
├── models.py                # Database schemas (PaymentEvent, RecoveryAction, AuditLog)
│
├── agent/
│   ├── classifier.py        # Failure classification module
│   ├── strategy.py          # Strategy & bounds enforcement rules
│   ├── executor.py          # Action execution against Razorpay client
│   ├── pipeline.py          # Orchestrates classifier -> strategy -> executor
│   └── auditor.py           # Helper for logging audit trail steps
│
├── razorpay_client/
│   └── client.py            # Custom Razorpay client with built-in MOCK mode support
│
├── simulator/
│   ├── scenarios.py         # Realistic webhook JSON payloads for 7 scenarios
│   └── scenario_runner.py   # CLI tool to fire webhook simulations
│
├── api/
│   ├── webhook.py           # Webhook receiver endpoint
│   ├── events.py            # Events list, stats, and audit log endpoints
│   └── dashboard.py         # Static HTML dashboard page server
│
├── static/
│   └── dashboard.html       # Web browser interface (JS + Tailwind CSS)
│
└── tests/
    ├── test_classifier.py   # Unit tests for classification rules
    ├── test_strategy.py     # Unit tests for bounds and strategies
    └── test_e2e.py          # Integration tests for live API endpoints
```

---

## Getting Started

### 1. Requirements
- Python 3.10+ (tested on Python 3.12)
- SQLite3

### 2. Environment Setup
1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   source .venv/bin/activate # macOS/Linux
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### 3. Configuration
Copy `.env.example` to `.env` and fill in your keys:
```ini
RAZORPAY_KEY_ID=rzp_test_xxxxxx
RAZORPAY_KEY_SECRET=yyyyyy
RAZORPAY_WEBHOOK_SECRET=zzzzzz
OPENAI_API_KEY=sk-xxxxxx
MOCK_RAZORPAY=true  # Set to false to use actual Razorpay Test Mode keys
```
*Note: If `MOCK_RAZORPAY=true` (default), the agent will operate fully using fake/mock payment links without hitting the live Razorpay servers.*

### Recovery intelligence and approval

The agent exposes a deterministic recovery-confidence score and expected recovery value for each eligible action. The score uses the failure class, recovery strategy and prior attempts; it deliberately does not use customer PII or allow an LLM to decide whether money actions are taken.

To approve a high-value action after merchant review, call `POST /api/actions/{action_id}/approve`. When `DASHBOARD_API_KEY` is configured, pass it as the `X-Dashboard-Key` header to all `/api` endpoints.

For production deployment, use a transactional database and migrations, move webhook execution to an outbox/worker, and integrate consented delivery plus holdout-group measurement. `checkout.abandoned` and `receivable.overdue` are intentionally normalised merchant/ERP signals, not claimed to be native Razorpay webhooks.

### Revenue-risk coverage

| Signal | Bounded intervention | Stop condition |
| --- | --- | --- |
| `payment.failed` | Retry or alternate-method Payment Link | Error-specific retry cap / recovery confirmation |
| `checkout.abandoned` | One short-lived recovery link | One attempt only |
| `subscription.pending` / `subscription.halted` | Mandate-update outreach draft | Never auto-charge; preserve subscription lifecycle controls |
| `receivable.overdue` | Time-bound collection link and promise-to-pay record | Promise pauses chasers; broken promise goes to merchant review |

Record a promise using `POST /api/actions/{action_id}/promise-to-pay` with `promised_for` as an ISO timestamp. A broken promise is escalated through `POST /api/promises/{promise_id}/mark-broken`.

While an open promise exists for the same receivable, repeat overdue signals are recorded but no new collection link is created. This is an enforced stopping rule, not only an audit message.

---

## Running the Project

### Step 1: Start the Web Server
Launch the FastAPI server on port 8000:
```bash
.venv\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8000
```
Open your browser and navigate to: **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.

### Step 2: Trigger Simulated Failures
Keep the server running and open a new terminal window to trigger all simulator scenarios:
```bash
.venv\Scripts\python.exe simulator\scenario_runner.py --scenario all
```
*Tip: Watch the live dashboard automatically update with the events, metrics, and recovery statuses!*

### Step 3: Run the Test Suite
Ensure that the server is running on port 8000, then execute pytest to verify both unit and integration tests:
```bash
.venv\Scripts\pytest.exe tests/ -v
```

## Demo flow for judges

Start the server, open the dashboard, and run the following command:

```bash
.venv\Scripts\python.exe simulator\scenario_runner.py --scenario all --mark-recovered
```

The dashboard will show the full lifecycle:

1. Razorpay sends a `payment.failed` event.
2. The agent classifies the cause and applies safety/retry rules.
3. It generates a short-lived recovery payment link (mocked by default).
4. The simulator sends a verified `payment_link.paid` event for generated links.
5. The corresponding action moves to `RECOVERED`; the dashboard updates **Amount Recovered** and **Recovery Rate**.

Use the audit icon for any event to show the classification rationale, recovery rule, API request, and eventual payment confirmation. The below-minimum and bounded-retry cases intentionally remain blocked, demonstrating that the agent is safe by default.

For a concise presentation narrative, use [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

---

## Verification Scenarios Logged

1. **UPI Timeout**: Generates fresh UPI link.
2. **Card Expired**: Generates alternate checkout link.
3. **Insufficient Funds**: Enforces safety boundary (no auto-charges, returns alternate checkout link).
4. **User Cancelled**: Generates single checkout link reminder.
5. **Bank Decline**: Generates alternate retry link.
6. **Subscription Failed**: Identifies card mandate failure and triggers recovery check.
7. **Below Minimum**: Gated safety rule triggers, action is skipped (e.g., amount is 50 paise, which is < ₹1.00 minimum limit).
8. **Max Retries Exceeded**: Fires UPI Timeout scenario 3 times. The 3rd attempt is blocked with status `BOUNDS_EXCEEDED` because the maximum retry limit of 2 was reached.
