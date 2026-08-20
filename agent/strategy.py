"""Strategy Selector: Determines recovery strategy based on failure classification and bounds."""

from models import FailureClass, RecoveryStrategy, ActionStatus
from config import settings

class StrategyResult:
    def __init__(
        self,
        strategy: RecoveryStrategy,
        status: ActionStatus,
        max_retries: int,
        rationale: str,
        is_bounded: bool = True
    ):
        self.strategy = strategy
        self.status = status
        self.max_retries = max_retries
        self.rationale = rationale
        self.is_bounded = is_bounded


def determine_strategy(
    failure_class: FailureClass,
    previous_retries: int,
    amount_paise: int
) -> StrategyResult:
    """Enforces retry bounds and returns the corresponding RecoveryStrategy."""

    # Rule 1: Lower bound check (gated minimum amount)
    if amount_paise < settings.MIN_RECOVERY_AMOUNT_PAISE:
        return StrategyResult(
            strategy=RecoveryStrategy.NO_ACTION,
            status=ActionStatus.SKIPPED,
            max_retries=0,
            is_bounded=True,
            rationale=f"Skipped recovery: amount (₹{amount_paise/100:.2f}) is below minimum recovery limit of ₹{settings.MIN_RECOVERY_AMOUNT_PAISE/100:.2f}."
        )

    # Define strategy rules, bounds, and rationales for each failure class
    rules = {
        FailureClass.UPI_TIMEOUT: {
            "strategy": RecoveryStrategy.RETRY_PAYMENT_LINK,
            "max_retries": 2,
            "rationale": "UPI timeout detected. Generating a new short-lived payment link so customer can retry."
        },
        FailureClass.AUTHENTICATION_FAILED: {
            "strategy": RecoveryStrategy.RETRY_PAYMENT_LINK,
            "max_retries": 2,
            "rationale": "OTP/3DS authentication failed. Providing a new payment session checkout link."
        },
        FailureClass.PAYMENT_CANCELLED: {
            "strategy": RecoveryStrategy.RETRY_PAYMENT_LINK,
            "max_retries": 1,
            "rationale": "Customer abandoned checkout. Generating a single retry checkout link with payment reminder."
        },
        FailureClass.INSUFFICIENT_FUNDS: {
            "strategy": RecoveryStrategy.ALTERNATE_METHOD_LINK,
            "max_retries": 1,
            "rationale": "Insufficient funds in current method. Generating alternate payment link to allow cards/netbanking."
        },
        FailureClass.CARD_EXPIRED: {
            "strategy": RecoveryStrategy.ALTERNATE_METHOD_LINK,
            "max_retries": 1,
            "rationale": "Stale/Expired card used. Generating link to allow update or selection of another payment method."
        },
        FailureClass.BANK_DECLINE: {
            "strategy": RecoveryStrategy.RETRY_PAYMENT_LINK,
            "max_retries": 2,
            "rationale": "Bank declined the transaction. Regenerating link for retry or alternative method."
        },
        FailureClass.GATEWAY_ERROR: {
            "strategy": RecoveryStrategy.RETRY_PAYMENT_LINK,
            "max_retries": 3,
            "rationale": "Transient gateway failure. Will retry creating payment link up to 3 times."
        },
        FailureClass.SUBSCRIPTION_FAILED: {
            "strategy": RecoveryStrategy.SEND_REMINDER,
            "max_retries": 1,
            "rationale": "Subscription charge failed. Sending reminder to update mandate details manually."
        },
        FailureClass.UNKNOWN: {
            "strategy": RecoveryStrategy.ESCALATE_TO_HUMAN,
            "max_retries": 0,
            "rationale": "Unidentified failure class. Escolating to manual merchant support team."
        }
    }

    rule = rules.get(failure_class, {
        "strategy": RecoveryStrategy.ESCALATE_TO_HUMAN,
        "max_retries": 0,
        "rationale": "Unknown failure class fallback. Escalating to human."
    })

    # Rule 2: Upper bound check (max retries exceeded)
    max_retries = rule["max_retries"]
    if previous_retries >= max_retries:
        return StrategyResult(
            strategy=RecoveryStrategy.NO_ACTION,
            status=ActionStatus.BOUNDS_EXCEEDED,
            max_retries=max_retries,
            is_bounded=True,
            rationale=f"Bounds exceeded: Current retries ({previous_retries}) reached or exceeded maximum limit of {max_retries}."
        )

    return StrategyResult(
        strategy=rule["strategy"],
        status=ActionStatus.PENDING,
        max_retries=max_retries,
        is_bounded=True,
        rationale=rule["rationale"]
    )
