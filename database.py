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
    from models import PaymentEvent, RecoveryAction, AuditLog, PromiseToPay  # noqa: F401
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
