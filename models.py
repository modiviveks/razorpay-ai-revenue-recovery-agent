"""SQLAlchemy models for payment events, recovery actions, and audit logs."""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Enum as SAEnum,
    ForeignKey, Boolean, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from database import Base


# ─── Enums ───────────────────────────────────────────────────────────────────

class FailureClass(str, enum.Enum):
    GATEWAY_ERROR = "GATEWAY_ERROR"
    UPI_TIMEOUT = "UPI_TIMEOUT"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    CARD_EXPIRED = "CARD_EXPIRED"
    PAYMENT_CANCELLED = "PAYMENT_CANCELLED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    BANK_DECLINE = "BANK_DECLINE"
    SUBSCRIPTION_FAILED = "SUBSCRIPTION_FAILED"
    CHECKOUT_ABANDONED = "CHECKOUT_ABANDONED"
    SUBSCRIPTION_PENDING = "SUBSCRIPTION_PENDING"
    SUBSCRIPTION_HALTED = "SUBSCRIPTION_HALTED"
    RECEIVABLE_OVERDUE = "RECEIVABLE_OVERDUE"
    UNKNOWN = "UNKNOWN"


class RecoveryStrategy(str, enum.Enum):
    RETRY_PAYMENT_LINK = "RETRY_PAYMENT_LINK"
    SEND_REMINDER = "SEND_REMINDER"
    ALTERNATE_METHOD_LINK = "ALTERNATE_METHOD_LINK"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    NO_ACTION = "NO_ACTION"
    COLLECT_RECEIVABLE_LINK = "COLLECT_RECEIVABLE_LINK"
    REQUEST_MANDATE_UPDATE = "REQUEST_MANDATE_UPDATE"


class ActionStatus(str, enum.Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RECOVERED = "RECOVERED"
    SKIPPED = "SKIPPED"
    BOUNDS_EXCEEDED = "BOUNDS_EXCEEDED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    PROMISE_ACTIVE = "PROMISE_ACTIVE"


# ─── Models ──────────────────────────────────────────────────────────────────

class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("webhook_event_id", name="uq_payment_events_webhook_event_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String(50), nullable=False)
    order_id = Column(String(50), nullable=True)
    amount = Column(Integer, nullable=False)  # in paise
    currency = Column(String(10), default="INR")
    method = Column(String(30), nullable=True)  # card, upi, netbanking, wallet
    status = Column(String(20), default="failed")
    # Normalised revenue-risk source. Non-payment signals use their own source
    # reference in ``payment_id`` for backwards-compatible correlation.
    risk_type = Column(String(40), default="PAYMENT_FAILURE", nullable=False)
    source_reference = Column(String(100), nullable=True)
    due_at = Column(DateTime, nullable=True)
    experiment_id = Column(String(80), nullable=True, index=True)
    experiment_variant = Column(String(20), nullable=True, index=True)  # control/treatment
    merchant_segment = Column(String(40), default="standard")

    # Error fields from Razorpay
    error_code = Column(String(50), nullable=True)
    error_description = Column(Text, nullable=True)
    error_source = Column(String(30), nullable=True)  # customer, business, gateway
    error_step = Column(String(50), nullable=True)
    error_reason = Column(String(100), nullable=True)

    # Customer info
    customer_email = Column(String(100), nullable=True)
    customer_contact = Column(String(20), nullable=True)
    customer_name = Column(String(100), nullable=True)

    # Meta
    webhook_event_id = Column(String(100), nullable=True, index=True)
    raw_payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    recovery_actions = relationship("RecoveryAction", back_populates="event")


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("payment_events.id"), nullable=False)

    failure_class = Column(SAEnum(FailureClass), nullable=False)
    strategy = Column(SAEnum(RecoveryStrategy), nullable=False)
    status = Column(SAEnum(ActionStatus), default=ActionStatus.PENDING)

    # Recovery details
    new_payment_link_id = Column(String(50), nullable=True)
    new_payment_link_url = Column(String(500), nullable=True)
    retry_count = Column(Integer, default=0)
    rationale = Column(Text, nullable=True)
    outreach_message = Column(Text, nullable=True)
    # Decision intelligence is explicitly advisory and auditable. It never
    # overrides strategy safety gates or triggers a debit.
    recovery_confidence = Column(Float, nullable=True)
    expected_recovery_amount = Column(Integer, nullable=True)  # paise
    decision_factors = Column(Text, nullable=True)
    # Advisory AI output is stored separately from the deterministic decision.
    # It cannot alter the selected strategy or bypass safety bounds.
    ai_advice = Column(Text, nullable=True)
    ai_advice_source = Column(String(30), nullable=True)
    model_version = Column(String(80), nullable=True)
    model_probability = Column(Float, nullable=True)
    model_features = Column(Text, nullable=True)
    candidate_scores = Column(Text, nullable=True)
    policy_version = Column(String(40), default="policy-v1")
    intervention_cost = Column(Integer, default=0)  # paise
    approved_by = Column(String(100), nullable=True)
    approved_role = Column(String(40), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_reason = Column(Text, nullable=True)

    # Bounds
    is_bounded = Column(Boolean, default=True)
    max_retries_allowed = Column(Integer, default=3)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    event = relationship("PaymentEvent", back_populates="recovery_actions")
    audit_logs = relationship("AuditLog", back_populates="action")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(Integer, ForeignKey("recovery_actions.id"), nullable=False)

    step = Column(String(50), nullable=False)  # CLASSIFY, STRATEGIZE, EXECUTE, COMPLETE
    reasoning = Column(Text, nullable=True)
    api_call = Column(Text, nullable=True)  # e.g., "POST /v1/payment_links"
    api_response = Column(Text, nullable=True)
    outcome = Column(String(20), nullable=True)  # SUCCESS, FAILED, SKIPPED
    error_detail = Column(Text, nullable=True)
    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=True, index=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    action = relationship("RecoveryAction", back_populates="audit_logs")


class PromiseStatus(str, enum.Enum):
    OPEN = "OPEN"
    KEPT = "KEPT"
    BROKEN = "BROKEN"


class PromiseToPay(Base):
    """A customer commitment that pauses automatic receivables escalation."""
    __tablename__ = "promises_to_pay"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(Integer, ForeignKey("recovery_actions.id"), nullable=False)
    amount = Column(Integer, nullable=False)  # paise
    promised_for = Column(DateTime, nullable=False)
    status = Column(SAEnum(PromiseStatus), default=PromiseStatus.OPEN, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    action = relationship("RecoveryAction")


class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class RecoveryOutbox(Base):
    """Durable handoff between verified webhook intake and recovery execution."""
    __tablename__ = "recovery_outbox"
    __table_args__ = (UniqueConstraint("event_id", name="uq_recovery_outbox_event_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("payment_events.id"), nullable=False, index=True)
    failure_class_hint = Column(String(50), nullable=True)
    rationale_hint = Column(Text, nullable=True)
    status = Column(SAEnum(OutboxStatus), default=OutboxStatus.PENDING, nullable=False, index=True)
    attempts = Column(Integer, default=0, nullable=False)
    available_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime, nullable=True)
    event = relationship("PaymentEvent")


class ExperimentRun(Base):
    """Persisted simulated control/treatment measurement, never real merchant revenue."""
    __tablename__ = "experiment_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(String(80), unique=True, nullable=False, index=True)
    sample_size = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=False)
    model_version = Column(String(80), nullable=False)
    results_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
