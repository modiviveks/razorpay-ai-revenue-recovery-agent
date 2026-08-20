"""SQLAlchemy models for payment events, recovery actions, and audit logs."""

import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Enum as SAEnum, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base

class FailureClass(str, enum.Enum):
    GATEWAY_ERROR="GATEWAY_ERROR"; UPI_TIMEOUT="UPI_TIMEOUT"; INSUFFICIENT_FUNDS="INSUFFICIENT_FUNDS"; CARD_EXPIRED="CARD_EXPIRED"; PAYMENT_CANCELLED="PAYMENT_CANCELLED"; AUTHENTICATION_FAILED="AUTHENTICATION_FAILED"; BANK_DECLINE="BANK_DECLINE"; SUBSCRIPTION_FAILED="SUBSCRIPTION_FAILED"; CHECKOUT_ABANDONED="CHECKOUT_ABANDONED"; SUBSCRIPTION_PENDING="SUBSCRIPTION_PENDING"; SUBSCRIPTION_HALTED="SUBSCRIPTION_HALTED"; RECEIVABLE_OVERDUE="RECEIVABLE_OVERDUE"; UNKNOWN="UNKNOWN"
class RecoveryStrategy(str, enum.Enum):
    RETRY_PAYMENT_LINK="RETRY_PAYMENT_LINK"; SEND_REMINDER="SEND_REMINDER"; ALTERNATE_METHOD_LINK="ALTERNATE_METHOD_LINK"; ESCALATE_TO_HUMAN="ESCALATE_TO_HUMAN"; NO_ACTION="NO_ACTION"; COLLECT_RECEIVABLE_LINK="COLLECT_RECEIVABLE_LINK"; REQUEST_MANDATE_UPDATE="REQUEST_MANDATE_UPDATE"
class ActionStatus(str, enum.Enum):
    PENDING="PENDING"; EXECUTING="EXECUTING"; SUCCESS="SUCCESS"; FAILED="FAILED"; RECOVERED="RECOVERED"; SKIPPED="SKIPPED"; BOUNDS_EXCEEDED="BOUNDS_EXCEEDED"; PENDING_APPROVAL="PENDING_APPROVAL"; RECONCILIATION_REQUIRED="RECONCILIATION_REQUIRED"; PROMISE_ACTIVE="PROMISE_ACTIVE"

class PaymentEvent(Base):
    __tablename__="payment_events"; __table_args__=(UniqueConstraint("webhook_event_id",name="uq_payment_events_webhook_event_id"),)
    id=Column(Integer,primary_key=True,autoincrement=True); payment_id=Column(String(50),nullable=False); order_id=Column(String(50)); amount=Column(Integer,nullable=False); currency=Column(String(10),default="INR"); method=Column(String(30)); status=Column(String(20),default="failed"); risk_type=Column(String(40),default="PAYMENT_FAILURE",nullable=False); source_reference=Column(String(100)); due_at=Column(DateTime); error_code=Column(String(50)); error_description=Column(Text); error_source=Column(String(30)); error_step=Column(String(50)); error_reason=Column(String(100)); customer_email=Column(String(100)); customer_contact=Column(String(20)); customer_name=Column(String(100)); webhook_event_id=Column(String(100),index=True); raw_payload=Column(Text); created_at=Column(DateTime,default=lambda:datetime.now(timezone.utc)); recovery_actions=relationship("RecoveryAction",back_populates="event")

class RecoveryAction(Base):
    __tablename__="recovery_actions"
    id=Column(Integer,primary_key=True,autoincrement=True); event_id=Column(Integer,ForeignKey("payment_events.id"),nullable=False); failure_class=Column(SAEnum(FailureClass),nullable=False); strategy=Column(SAEnum(RecoveryStrategy),nullable=False); status=Column(SAEnum(ActionStatus),default=ActionStatus.PENDING); new_payment_link_id=Column(String(50)); new_payment_link_url=Column(String(500)); retry_count=Column(Integer,default=0); rationale=Column(Text); outreach_message=Column(Text); recovery_confidence=Column(Float); expected_recovery_amount=Column(Integer); decision_factors=Column(Text); ai_advice=Column(Text); ai_advice_source=Column(String(30)); model_version=Column(String(50)); experiment_variant=Column(String(20)); approval_actor=Column(String(100)); approval_timestamp=Column(DateTime); is_bounded=Column(Boolean,default=True); max_retries_allowed=Column(Integer,default=3); created_at=Column(DateTime,default=lambda:datetime.now(timezone.utc)); updated_at=Column(DateTime,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); event=relationship("PaymentEvent",back_populates="recovery_actions"); audit_logs=relationship("AuditLog",back_populates="action")

class AuditLog(Base):
    __tablename__="audit_logs"
    id=Column(Integer,primary_key=True,autoincrement=True); action_id=Column(Integer,ForeignKey("recovery_actions.id"),nullable=False); step=Column(String(50),nullable=False); reasoning=Column(Text); api_call=Column(Text); api_response=Column(Text); outcome=Column(String(20)); error_detail=Column(Text); previous_hash=Column(String(64)); entry_hash=Column(String(64)); created_at=Column(DateTime,default=lambda:datetime.now(timezone.utc)); action=relationship("RecoveryAction",back_populates="audit_logs")

class PromiseStatus(str,enum.Enum): OPEN="OPEN"; KEPT="KEPT"; BROKEN="BROKEN"
class PromiseToPay(Base):
    __tablename__="promises_to_pay"
    id=Column(Integer,primary_key=True,autoincrement=True); action_id=Column(Integer,ForeignKey("recovery_actions.id"),nullable=False); amount=Column(Integer,nullable=False); promised_for=Column(DateTime,nullable=False); status=Column(SAEnum(PromiseStatus),default=PromiseStatus.OPEN,nullable=False); created_at=Column(DateTime,default=lambda:datetime.now(timezone.utc)); updated_at=Column(DateTime,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc)); action=relationship("RecoveryAction")
