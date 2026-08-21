"""Keep integration tests independent from a user's local demo database."""

import os
from pathlib import Path


TEST_DB = Path("test_recovery_agent.db")
os.environ["DATABASE_URL"] = "sqlite:///./test_recovery_agent.db"
os.environ["MOCK_RAZORPAY"] = "true"
os.environ["ALLOW_TEST_WEBHOOK_BYPASS"] = "true"
os.environ["PROCESS_OUTBOX_INLINE"] = "true"


def pytest_sessionstart(session):
    if TEST_DB.exists():
        TEST_DB.unlink()


def pytest_sessionfinish(session, exitstatus):
    # SQLite keeps a handle open on Windows until SQLAlchemy disposes its pool.
    try:
        from database import engine
        engine.dispose()
    except ImportError:
        pass
    if TEST_DB.exists():
        TEST_DB.unlink()
