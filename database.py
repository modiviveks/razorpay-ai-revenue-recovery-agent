"""SQLite database setup via SQLAlchemy."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from config import settings

engine_options = {"echo": False, "pool_pre_ping": True}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
engine = create_engine(settings.DATABASE_URL, **engine_options)

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
    from models import PaymentEvent, RecoveryAction, AuditLog, PromiseToPay, RecoveryOutbox  # noqa: F401
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
    }
    existing_columns = {column["name"] for column in inspect(engine).get_columns("payment_events")}
    with engine.begin() as connection:
        for name, definition in required_columns.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE payment_events ADD COLUMN {name} {definition}"))
    action_columns = {
        "ai_advice": "TEXT",
        "ai_advice_source": "VARCHAR(30)",
        "model_version": "VARCHAR(80)", "feature_version": "VARCHAR(40)",
        "predicted_probability": "FLOAT", "expected_recovery_value": "INTEGER",
        "candidate_scores": "TEXT", "policy_version": "VARCHAR(40)", "action_version": "VARCHAR(40)",
        "approval_actor_id": "VARCHAR(100)", "approval_actor_role": "VARCHAR(50)",
        "approval_reason": "TEXT", "approval_timestamp": "DATETIME", "approval_expires_at": "DATETIME",
    }
    existing_action_columns = {column["name"] for column in inspect(engine).get_columns("recovery_actions")}
    with engine.begin() as connection:
        for name, definition in action_columns.items():
            if name not in existing_action_columns:
                connection.execute(text(f"ALTER TABLE recovery_actions ADD COLUMN {name} {definition}"))
    for table, columns in {
        "payment_events": {"experiment_id": "VARCHAR(100)", "experiment_variant": "VARCHAR(20) NOT NULL DEFAULT 'treatment'", "merchant_segment": "VARCHAR(30) NOT NULL DEFAULT 'standard'"},
        "audit_logs": {"previous_hash": "VARCHAR(64)", "current_hash": "VARCHAR(64)"},
    }.items():
        existing = {column["name"] for column in inspect(engine).get_columns(table)}
        with engine.begin() as connection:
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
