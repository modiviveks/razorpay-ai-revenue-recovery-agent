"""SQLAlchemy database setup."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from models import PaymentEvent, RecoveryAction, AuditLog, PromiseToPay  # noqa: F401
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        _add_missing_sqlite_columns()

def _add_missing_sqlite_columns():
    upgrades = {
        "payment_events": {
            "risk_type": "VARCHAR(40) NOT NULL DEFAULT 'PAYMENT_FAILURE'",
            "source_reference": "VARCHAR(100)",
            "due_at": "DATETIME",
        },
        "recovery_actions": {
            "ai_advice": "TEXT",
            "ai_advice_source": "VARCHAR(30)",
            "model_version": "VARCHAR(50)",
            "experiment_variant": "VARCHAR(20)",
        },
    }
    with engine.begin() as connection:
        for table, columns in upgrades.items():
            existing = {c["name"] for c in inspect(engine).get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
