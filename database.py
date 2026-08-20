"""SQLite database setup via SQLAlchemy."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite needs this for FastAPI
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables and apply additive SQLite upgrades used by the demo."""
    from models import PaymentEvent, RecoveryAction, AuditLog, PromiseToPay, RecoveryOutbox, ExperimentRun  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # ``create_all`` does not add columns to an existing SQLite file. Keep the
    # self-contained demo upgradeable without asking judges to delete data.
    if engine.dialect.name == "sqlite":
        _add_missing_sqlite_columns()


def _add_missing_sqlite_columns():
    required_columns = {
        "risk_type": "VARCHAR(40) NOT NULL DEFAULT 'PAYMENT_FAILURE'",
        "source_reference": "VARCHAR(100)",
        "due_at": "DATETIME",
        "experiment_id": "VARCHAR(80)",
        "experiment_variant": "VARCHAR(20)",
        "merchant_segment": "VARCHAR(40) DEFAULT 'standard'",
    }
    existing_columns = {column["name"] for column in inspect(engine).get_columns("payment_events")}
    with engine.begin() as connection:
        for name, definition in required_columns.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE payment_events ADD COLUMN {name} {definition}"))
    action_columns = {
        "ai_advice": "TEXT",
        "ai_advice_source": "VARCHAR(30)",
        "model_version": "VARCHAR(80)",
        "model_probability": "FLOAT",
        "model_features": "TEXT",
        "candidate_scores": "TEXT",
        "policy_version": "VARCHAR(40) DEFAULT 'policy-v1'",
        "intervention_cost": "INTEGER DEFAULT 0",
        "approved_by": "VARCHAR(100)",
        "approved_role": "VARCHAR(40)",
        "approved_at": "DATETIME",
        "approval_reason": "TEXT",
    }
    existing_action_columns = {column["name"] for column in inspect(engine).get_columns("recovery_actions")}
    with engine.begin() as connection:
        for name, definition in action_columns.items():
            if name not in existing_action_columns:
                connection.execute(text(f"ALTER TABLE recovery_actions ADD COLUMN {name} {definition}"))
    audit_columns = {
        "previous_hash": "VARCHAR(64)",
        "current_hash": "VARCHAR(64)",
    }
    existing_audit_columns = {column["name"] for column in inspect(engine).get_columns("audit_logs")}
    with engine.begin() as connection:
        for name, definition in audit_columns.items():
            if name not in existing_audit_columns:
                connection.execute(text(f"ALTER TABLE audit_logs ADD COLUMN {name} {definition}"))
