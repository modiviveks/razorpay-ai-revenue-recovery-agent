"""Application configuration — loads from .env or environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    """Read a conventional boolean environment variable."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    """Read a positive integer setting without making startup fragile."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class Settings:
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "rzp_test_placeholder")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "placeholder_secret")
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./recovery_agent.db")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()

    # Agent bounds
    MAX_RETRY_COUNT: int = 3
    PAYMENT_LINK_EXPIRY_HOURS: int = 24
    MIN_RECOVERY_AMOUNT_PAISE: int = 100  # ₹1
    # High-value recovery actions are held for merchant review. This is a
    # guardrail, not a risk decision or a reason to collect payment.
    REQUIRE_APPROVAL_OVER_PAISE: int = env_int("REQUIRE_APPROVAL_OVER_PAISE", 1_000_000)

    # Feature flags
    USE_LLM_EXPLANATIONS: bool = env_bool("USE_LLM_EXPLANATIONS", bool(OPENAI_API_KEY))
    USE_AI_ADVISOR: bool = env_bool("USE_AI_ADVISOR", bool(OPENAI_API_KEY))
    AI_ADVISOR_MODEL: str = os.getenv("AI_ADVISOR_MODEL", "gpt-4o-mini")
    MOCK_RAZORPAY: bool = env_bool("MOCK_RAZORPAY", True)
    # Explicitly restricted to local/mock environments. Never enable this in production.
    ALLOW_TEST_WEBHOOK_BYPASS: bool = env_bool("ALLOW_TEST_WEBHOOK_BYPASS", MOCK_RAZORPAY)
    CORS_ORIGINS: list[str] = [
        origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
        if origin.strip()
    ]
    # Set this in a shared/deployed environment. Empty intentionally keeps the
    # bundled local demo frictionless.
    DASHBOARD_API_KEY: str = os.getenv("DASHBOARD_API_KEY", "")


settings = Settings()
