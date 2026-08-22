# ⚡ RazorRevive — Autonomous AI Revenue Recovery Agent

> **An Autonomous, Bounded, Closed-Loop Payment & Receivables Recovery Engine for the Razorpay Ecosystem.**
> Diagnoses payment drop-offs, predicts recovery propensity, maximizes expected recovery value (EV) net of intervention costs, and autonomously orchestrates recovery actions directly via Razorpay APIs with full human governance and tamper-proof cryptographic audit trails.

---

## 🌐 Live Interactive Demo
- **Live Agent Console**: [https://ais-pre-k4zaegfcvmgxn2qupdm2iv-152971042002.asia-southeast1.run.app](https://ais-pre-k4zaegfcvmgxn2qupdm2iv-152971042002.asia-southeast1.run.app)
- **Track**: AI Revenue Recovery / Razorpay Buildathon

---

## 📸 Product Screenshots & Live Console Walkthrough

### 1. Interactive Control Hub & Payment Network Degradation Detector

<!-- ========================================================================= -->
<!-- 📍 PASTE YOUR FIRST SCREENSHOT (Control Hub & Health Monitors) HERE -->
<!-- Replace the URL below with your image path or hosted image URL -->
<!-- ========================================================================= -->
<p align="center">
  <img src="<img width="1913" height="853" alt="image" src="https://github.com/user-attachments/assets/b1a55c55-ea07-49f4-bd56-78888667b80b" />
" width="100%" />
</p>

* **Interactive Testing Hub**: Inject failure scenarios (`UPI Timeout`, `Card Expired`, `Bank Decline`, `Checkout Abandonment`, `Receivable Overdue`), test mode link generation, real-time Razorpay Dashboard sync, and 10,000-event synthetic A/B significance tests.
* **Payment Network Degradation Detector**: Real-time sliding window monitoring for `UPI` (96.0% success), `CARD` (94.0%), `NETBANKING` (91.0%), and `WALLET` (95.0%) to prevent redundant retries during gateway outages.
* **Live KPI Metric Cards**: Live tracking of **Revenue at Risk (₹7,149.00 across 6 failure events)**, **Interventions Sent (5 / 83.3% rate)**, and value-weighted **Verified Recovery Rate**.

---

### 2. Live Revenue-Risk Events & Explainable AI Audit Trail

<!-- ========================================================================= -->
<!-- 📍 PASTE YOUR SECOND SCREENSHOT (Events Stream & AI Decision Trail) HERE -->
<!-- Replace the URL below with your image path or hosted image URL -->
<!-- ========================================================================= -->
<p align="center">
  <img src="./docs/screenshots/events-and-explainable-ai.png" alt="Events Stream and Explainable AI" width="100%" />
</p>

* **Recent Revenue-Risk Events Table**: Live classification of failures (e.g. `UPI_TIMEOUT`, `RECEIVABLE_OVERDUE`, `CARD_EXPIRED`, `BANK_DECLINE`, `CHECKOUT_ABANDONED`) with autonomous Next-Best-Actions and direct links to live Razorpay checkout links (`https://rzp.io/...`).
* **Explainable Decision & Opportunity Scoring**:
  * **Expected Value**: `₹435.00`
  * **Cost + Friction**: `₹0.35`
  * **Net Opportunity Score**: `₹434.65`
* **Personalized Outreach Messaging**: Dynamic, bilingual message templates (Hindi/English) generated with direct one-click recovery links (`https://rzp.io/rzp/gxUeBDxI`).
* **Cryptographic Audit Trail**: Step-by-step SHA-256 hashed audit log verifying policy check, ML ranking, and transactional outbox execution.

---

### 3. Razorpay Official Merchant Dashboard Verification & Live Sync

<!-- ========================================================================= -->
<!-- 📍 PASTE YOUR THIRD SCREENSHOT (Razorpay Merchant Dashboard) HERE -->
<!-- Replace the URL below with your image path or hosted image URL -->
<!-- ========================================================================= -->
<p align="center">
  <img src="./docs/screenshots/razorpay-dashboard-payment-links.png" alt="Razorpay Merchant Dashboard Live Sync" width="100%" />
</p>

* **Live Razorpay Test Mode Verification**: Direct proof of real-world integration showing live payment links created on the official Razorpay Merchant Portal (`dashboard.razorpay.com/app/paymentlinks`).
* **Real-time Link Details**:
  * `plink_TSo4WiPL95B0gB` — ₹499.00 (`https://rzp.io/rzp/weMfSNIN`, Ref: `rec_7_7`)
  * `plink_TSo2JysVCffRtG` — ₹450.00 (`https://rzp.io/rzp/mVtsHVo`, Ref: `rec_4_4`)
  * `plink_TSo2Jvx2joMc7A` — ₹3,000.00 (`https://rzp.io/rzp/l4617X7`, Ref: `rec_5_5`)
  * `plink_TSo2K0km4o3zid` — ₹1,200.00 (`https://rzp.io/rzp/wfc4Ing`, Ref: `rec_2_2`)
  * `plink_TSo2JqE8kCG57p` — ₹750.00 (`https://rzp.io/rzp/cCPGPOw`, Ref: `rec_1_1`)
  * `plink_TSo2Jss7NQRqDH` — ₹999.00 (`https://rzp.io/rzp/vwvhezOK`, Ref: `rec_3_3`)
* **Bidirectional Synchronization**: Seamlessly bidirectional — links generated autonomously by the AI agent appear instantly on Razorpay, and customer payments completed on Razorpay sync back to the agent in 1-click or via webhook.

---

---

## 🎯 Executive Overview & Problem Statement

In the Indian digital payments ecosystem (UPI, cards, netbanking, recurring mandates), payment failures cause massive revenue leakage for merchants:
- **UPI Switch Timeouts & Bank Gateway Drops**: Transient network issues account for over 35% of checkout drop-offs.
- **Customer Friction & Alert Fatigue**: Indiscriminate retry spam annoys buyers, increases churn, and risks chargebacks.
- **Negative Expected-Value Interventions**: Sending SMS/WhatsApp payment links on sub-rupee or low-ticket orders costs more in API fees and friction than the order value.
- **Lack of Verification & True Incremental Measurement**: Many systems claim 100% of organic customer retries as "AI recovered" without running a rigorous treatment vs. control benchmark.

**RazorRevive** solves this through a rigorous 9-stage closed-loop architecture:

```
[ Ingest (Idempotent Webhooks) ]
               │
               ▼
[ Diagnose (Rule-Based Classifier + Degradation Detector) ]
               │
               ▼
[ Predict (Calibrated ML Recovery Propensity) ]
               │
               ▼
[ Rank (Next-Best-Action & Opportunity Scoring) ]
               │
               ▼
[ Policy Gate (Bounded Retries, High-Value Approval, Promises) ]
               │
               ▼
[ Execute (Transactional Outbox Worker & Razorpay Payment Links) ]
               │
               ▼
[ Audit (Cryptographic SHA-256 Hash Chain per Action) ]
               │
               ▼
[ Verify & Reconcile (Razorpay payment_link.paid Ingestion) ]
               │
               ▼
[ Measure & Learn (A/B Synthetic Significance & Decile Calibration) ]
```

---

## 🚀 Key Innovations & Architectural Pillars

### 1. Transparent Opportunity Scoring & Explicit `NO_ACTION`
Instead of treating all failed payments equally, the Next-Best-Action (NBA) engine computes the **Net Opportunity Score**:
$$\text{Opportunity Score} = P(\text{Recovery}) \times \text{Amount} - \text{Intervention Cost} - \text{Friction Penalty}$$
- **Explicit `NO_ACTION`**: If all candidate actions yield negative expected value (e.g., micro-transactions < ₹1.00 or severe fraud declines), the engine outputs `NO_ACTION` to protect merchant margins and customer trust.
- **Action-Specific Costs & Friction**: Tailored penalties for instant retries, WhatsApp payment links, alternate method suggestions, and grace period extensions.

### 2. Payment Network Degradation Detector
- Monitors a sliding window of recent transactions per payment method (`UPI`, `CARD`, `NETBANKING`, `WALLET`).
- Flags **MODERATE** (>7% drop from baseline) and **CRITICAL** (>15% drop) network switch outages.
- Automatically suppresses immediate retry actions during upstream bank outages, advising merchants to route users to alternate payment methods.

### 3. Explainable Next-Best-Action
- Generates transparent, human-readable explanations for every recovery decision:
  - **Why Selected**: Net expected value breakdown and primary recovery drivers.
  - **Why Rejected**: Clear mathematical or policy reasons why other candidate strategies were disqualified.
  - **Active Policy Constraints**: Explicit checks for max retry bounds, cooling periods, and active promises-to-pay.

### 4. Human-in-the-Loop High-Value Approval Queue
- High-ticket recovery actions (exceeding ₹5,000 / 500,000 paise) are placed into `PENDING_APPROVAL`.
- Merchant admins can review pending opportunities, inspect proposed strategies and customer details, and either **Approve** or **Reject** with audit trail justification.

### 5. Calibrated Machine Learning Propensity Model
- Powered by `recovery-logreg-v2`, trained on non-PII operational signals (amount, failure class, payment method, retry count, time of day, merchant tier, aggregate historical success).
- Evaluated via ROC-AUC, Brier score, and a 10-decile calibration report comparing predicted probabilities against observed recovery rates.

### 6. Rigorous Statistical Experimentation
- Integrated 10,000-event synthetic treatment/control A/B benchmarking tool (`simulator/experiment.py`).
- Computes two-proportion Z-tests, p-values, 95% Confidence Intervals, and absolute/relative lift to verify that reported recovery gains represent true incremental lift over natural buyer retries.

### 7. Cryptographic Audit Trail & Security
- Every decision, state transition, and API interaction is logged with a **SHA-256 cryptographic hash chain** ($H_i = \text{SHA256}(H_{i-1} \parallel \text{Step} \parallel \text{Payload})$).
- Verifiable at any time via `/api/audit-trail/{action_id}/verify` to guarantee tamper-evident compliance.

---

## 📊 Interactive Dashboard Features

The web interface (`/static/dashboard.html`) provides a real-time command center:
- **Executive Recovery Funnel**: Visual 4-stage conversion tracking (Failed Events → Policy-Eligible → Interventions Attempted → Settled Recoveries) with drop-off accounting (Retries Exceeded, Awaiting Approval, Active Promise Paused, Negative-EV Skipped).
- **Payment Network Degradation Monitor**: Live status cards tracking UPI, Card, Netbanking, and Wallet health with automated root-cause hypotheses.
- **Merchant Segment Analytics**: Granular performance comparisons across Standard, Growth, and Enterprise merchant tiers.
- **Explainable Decision Inspector**: Deep dive into individual events showing EV math, alternative rejection reasons, outreach drafts, and cryptographic audit steps.
- **High-Value Approvals Modal**: Streamlined sign-off queue for merchant operations teams.
- **Model Calibration Modal**: 10-decile predicted vs. observed calibration table with ROC-AUC and Brier metrics.
- **Interactive Failure Simulator Toolbar**: One-click injection of 10+ payment failure scenarios.

---

## 🛠️ Quick Start & Local Execution

### 1. Installation & Environment Setup
```bash
# Clone the repository
git clone https://github.com/modiviveks/razorpay-ai-revenue-recovery-agent.git
cd razorpay-ai-revenue-recovery-agent

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Train the Recovery Model
```bash
python -m agent.train_model
```

### 3. Start the Application Server
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
Open your browser at `http://127.0.0.1:8000/` to access the Enterprise Dashboard.

### 4. Start the Background Outbox Worker (Separate Terminal)
```bash
python -m agent.worker
```

### 5. Run Scenario Simulations & A/B Experiment
```bash
# Trigger simulated failure scenarios (with auto-pay verification)
python simulator/scenario_runner.py --scenario all --mark-recovered

# Run 10,000-event synthetic A/B experiment with statistical confidence
python -m simulator.experiment --size 10000
```

### 6. Run Full Test Suite
```bash
pytest -v
```
All 48 unit and integration tests validate the entire recovery pipeline, degradation detector, opportunity scorer, approval queue, statistical inference engine, and the Razorpay Test Mode integration.

---

## ⚡ Razorpay Runtime Modes: Mock vs. Test Mode

The recovery agent supports two runtime modes configured via `RAZORPAY_MODE`:

### 1. Mock Mode (`RAZORPAY_MODE=mock`, Default)
- **Zero Configuration**: Fully functional out of the box without external dependencies.
- **Local Simulation**: Simulates payment link creation, simulated checkout redirect pages, and instant webhook confirmations.
- **Safe Demonstration**: Allows triggering failure scenarios, B2B promises, high-value approvals, and 10,000-event A/B benchmarks safely offline.

### 2. Razorpay Test Mode (`RAZORPAY_MODE=test`)
- **Authentic Razorpay API Integration**: Communicates directly with the official Razorpay Test API using `razorpay-python` SDK.
- **Real Payment Links**: Generates actual Razorpay Payment Links (`https://rzp.io/i/...`) in Test Mode that can be tested in Razorpay's sandbox.
- **Official Webhook Verification**: Cryptographically verifies `X-Razorpay-Signature` HMAC-SHA256 headers for all incoming webhook events (`payment.failed`, `payment_link.paid`).
- **Strict Safety Boundaries**:
  - **No Live Mode**: The system strictly forbids `rzp_live_...` keys and refuses to start if live credentials are provided.
  - **No Silent Fallback**: If an API call fails in Test Mode, it records an explicit `FAILED` audit record rather than silently falling back to mock behavior.
- **Configuration (.env)**:
  ```env
  RAZORPAY_MODE=test
  RAZORPAY_KEY_ID=rzp_test_YourKeyIdHere
  RAZORPAY_KEY_SECRET=YourTestSecretHere
  RAZORPAY_WEBHOOK_SECRET=YourWebhookSecretHere
  ```

---

## 🔗 Key API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the interactive Enterprise Dashboard UI |
| `POST` | `/webhook/razorpay` | Authenticated webhook intake for payment failures and `payment_link.paid` events (HMAC-SHA256 verified in Test Mode) |
| `POST` | `/demo/razorpay-test/payment-link` | Triggers an end-to-end recovery action generating an authentic Razorpay Test Mode link |
| `GET` | `/api/stats` | High-level recovery metrics, at-risk totals, conversion rates, and runtime mode indicator |
| `GET` | `/api/events` | Stream of recent payment failure events and autonomous agent actions |
| `GET` | `/api/analytics/funnel` | 4-stage executive recovery funnel and drop-off accounting |
| `GET` | `/api/analytics/segments` | Merchant segment performance (Standard, Growth, Enterprise) |
| `GET` | `/api/network/degradation-status` | Real-time payment network health and switch latency metrics |
| `GET` | `/api/actions/pending-approvals` | High-value actions awaiting human sign-off |
| `POST` | `/api/actions/{id}/approve` | Merchant admin approves a high-ticket recovery action |
| `POST` | `/api/actions/{id}/reject` | Merchant admin rejects/cancels a recovery action |
| `GET` | `/api/audit-trail/{id}` | Cryptographic step-by-step audit trail for an action |
| `GET` | `/api/audit-trail/{id}/verify` | Validates SHA-256 hash integrity across the audit chain |
| `GET` | `/api/model/metrics` | Model calibration metrics, ROC-AUC, Brier score, and 10-decile table |
| `POST` | `/api/experiments/simulate` | Executes a synthetic A/B impact benchmark with 95% CI |
| `POST` | `/demo/simulate` | Dispatches simulated webhook failure scenarios in mock mode |
| `POST` | `/demo/reset` | Clears all mock data for a clean demonstration run |

---

## 🛡️ Production & Security Considerations

1. **Deterministic Authority**: The AI model and advisory layers can only suggest candidates and calculate opportunity scores. Hard boundaries (retry caps, cooling intervals, human approvals, customer promises) are strictly enforced in Python code and cannot be bypassed.
2. **PII Minimization**: Audit logs and metric payloads scrub customer email addresses and phone numbers; only non-PII operational features are retained.
3. **Outbox Reliability**: Webhooks persist events into a durable PostgreSQL/SQLite transactional outbox before processing, guaranteeing at-least-once delivery with exponential backoff.
4. **Zero Financial Risk**: The recovery agent only generates payment links; it never stores credentials or initiates customer debits.

---

## 📜 License
MIT License. Developed for the Razorpay Buildathon.
