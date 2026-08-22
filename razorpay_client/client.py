"""Razorpay API client wrapper supporting Mock mode and realistic Razorpay Test Mode."""

import time
import random
import hmac
import hashlib
from abc import ABC, abstractmethod
import razorpay
from razorpay.errors import SignatureVerificationError
from config import settings


class RazorpayPaymentLinkInterface(ABC):
    """Abstract interface for Razorpay payment link operations."""
    @abstractmethod
    def create(self, data: dict):
        pass

    @abstractmethod
    def fetch(self, plink_id: str):
        pass

    @abstractmethod
    def cancel(self, plink_id: str):
        pass

    @abstractmethod
    def notify(self, plink_id: str, medium: str):
        pass


class RazorpayUtilityInterface(ABC):
    """Abstract interface for Razorpay utility and signature verification."""
    @abstractmethod
    def verify_webhook_signature(self, body: str, signature: str, secret: str) -> bool:
        pass


class RazorpayPaymentInterface(ABC):
    """Abstract interface for Razorpay payment resource operations."""
    @abstractmethod
    def fetch(self, payment_id: str):
        pass


class RazorpayClientInterface(ABC):
    """Unified client contract implemented by both MockClient and RazorpayTestClient."""
    payment_link: RazorpayPaymentLinkInterface
    utility: RazorpayUtilityInterface
    payment: RazorpayPaymentInterface
    mode: str


# ─── Mock Implementation ───────────────────────────────────────────────────────

class MockPaymentLink:
    """Mock Razorpay payment link entity for local simulated workflows."""
    def __init__(self, data: dict):
        self.id = data.get("id") or f"plink_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=14))}"
        # Local hosted checkout makes mock-mode demos interactive and clickable without external network calls
        self.short_url = f"/demo/payment-links/{self.id}"
        self.status = "created"
        self.amount = data.get("amount")
        self.currency = data.get("currency", "INR")
        self.description = data.get("description")
        self.customer = data.get("customer")
        self.expire_by = data.get("expire_by")
        self.created_at = int(time.time())

    def __getitem__(self, key):
        return getattr(self, key, None)

    def get(self, key, default=None):
        return getattr(self, key, default)


class MockPaymentLinkModule(RazorpayPaymentLinkInterface):
    """Mock implementation of the payment_link module."""
    def create(self, data: dict):
        return MockPaymentLink(data)

    def cancel(self, plink_id: str):
        return {"id": plink_id, "status": "cancelled"}

    def fetch(self, plink_id: str):
        return {
            "id": plink_id,
            "status": "created",
            "short_url": f"/demo/payment-links/{plink_id}",
            "amount": 50000,
            "currency": "INR",
        }

    def notify(self, plink_id: str, medium: str):
        return {"success": True, "medium": medium}


class MockPaymentModule(RazorpayPaymentInterface):
    """Mock implementation of the payment module."""
    def fetch(self, payment_id: str):
        return {
            "id": payment_id,
            "entity": "payment",
            "amount": 50000,
            "currency": "INR",
            "status": "failed",
            "method": "upi",
        }


class MockUtilityModule(RazorpayUtilityInterface):
    """Mock utility module that simulates webhook verification."""
    def verify_webhook_signature(self, body: str, signature: str, secret: str) -> bool:
        # In mock mode, permit verification for simulated events
        return True


class MockClient(RazorpayClientInterface):
    """Mock Razorpay Client simulating API responses in offline/local environments."""
    def __init__(self):
        self.payment_link = MockPaymentLinkModule()
        self.payment = MockPaymentModule()
        self.utility = MockUtilityModule()
        self.mode = "mock"

    def verify_webhook_signature(self, body: str, signature: str, secret: str) -> bool:
        return self.utility.verify_webhook_signature(body, signature, secret)


# ─── Razorpay Test Mode Implementation ────────────────────────────────────────

class RazorpayTestPaymentLinkModule(RazorpayPaymentLinkInterface):
    """Adapter for official Razorpay SDK payment_link in Test Mode."""
    def __init__(self, sdk_client: razorpay.Client):
        self._sdk_client = sdk_client

    def create(self, data: dict):
        # Calls the official Razorpay SDK create payment link endpoint
        return self._sdk_client.payment_link.create(data)

    def fetch(self, plink_id: str):
        return self._sdk_client.payment_link.fetch(plink_id)

    def cancel(self, plink_id: str):
        return self._sdk_client.payment_link.cancel(plink_id)

    def notify(self, plink_id: str, medium: str):
        return self._sdk_client.payment_link.notifyBy(plink_id, medium)


class RazorpayTestPaymentModule(RazorpayPaymentInterface):
    """Adapter for official Razorpay SDK payment entity in Test Mode."""
    def __init__(self, sdk_client: razorpay.Client):
        self._sdk_client = sdk_client

    def fetch(self, payment_id: str):
        return self._sdk_client.payment.fetch(payment_id)


class RazorpayTestUtilityModule(RazorpayUtilityInterface):
    """Adapter for official Razorpay SDK webhook signature verification in Test Mode."""
    def __init__(self, sdk_client: razorpay.Client):
        self._sdk_client = sdk_client

    def verify_webhook_signature(self, body: str, signature: str, secret: str) -> bool:
        if not secret:
            raise ValueError("Webhook secret is required for signature verification in Test Mode.")
        if not signature:
            raise SignatureVerificationError("Missing X-Razorpay-Signature header.")
        
        # Verify using HMAC-SHA256 matching Razorpay's exact specification
        expected_signature = hmac.new(
            key=secret.encode("utf-8"),
            msg=body.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, signature):
            raise SignatureVerificationError("Razorpay webhook signature verification failed.")
        return True


class RazorpayTestClient(RazorpayClientInterface):
    """
    Official Razorpay Test Mode Client.
    Connects to Razorpay APIs using test credentials (rzp_test_...).
    Strictly forbids live credentials and never falls back silently to mock.
    """
    def __init__(self, key_id: str, key_secret: str):
        self._validate_credentials(key_id, key_secret)
        self.key_id = key_id
        self.key_secret = key_secret
        self._sdk_client = razorpay.Client(auth=(key_id, key_secret))

        self.payment_link = RazorpayTestPaymentLinkModule(self._sdk_client)
        self.payment = RazorpayTestPaymentModule(self._sdk_client)
        self.utility = RazorpayTestUtilityModule(self._sdk_client)
        self.mode = "test"

    def _validate_credentials(self, key_id: str, key_secret: str):
        if not key_id or not key_secret:
            raise ValueError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be configured when running in 'test' mode."
            )
        if key_id.startswith("rzp_live_"):
            raise ValueError(
                "Live Razorpay credentials ('rzp_live_...') are strictly prohibited. "
                "This buildathon implementation only supports Razorpay Test Mode ('rzp_test_...')."
            )
        if not key_id.startswith("rzp_test_"):
            # Provide helpful guidance if placeholder is left in test mode
            if "placeholder" in key_id.lower():
                raise ValueError(
                    "Placeholder credentials detected in RAZORPAY_MODE='test'. "
                    "Please provide valid Razorpay Test Mode key ID (rzp_test_...) and secret."
                )

    def verify_webhook_signature(self, body: str, signature: str, secret: str) -> bool:
        return self.utility.verify_webhook_signature(body, signature, secret)


# ─── Client Factory & Global Instance ─────────────────────────────────────────

def get_razorpay_client(
    mode: str = None,
    key_id: str = None,
    key_secret: str = None,
) -> RazorpayClientInterface:
    """
    Factory function to create the appropriate Razorpay client.
    Supports 'mock' and 'test' modes. Rejects 'live' mode.
    """
    target_mode = (mode or settings.RAZORPAY_MODE).strip().lower()

    if target_mode == "live":
        raise ValueError(
            "Live mode is prohibited. This buildathon implementation strictly supports only 'mock' and 'test' modes."
        )

    if target_mode == "test":
        target_key_id = key_id or settings.RAZORPAY_KEY_ID
        target_key_secret = key_secret or settings.RAZORPAY_KEY_SECRET
        return RazorpayTestClient(target_key_id, target_key_secret)

    if target_mode == "mock":
        return MockClient()

    raise ValueError(f"Unknown Razorpay mode '{target_mode}'. Supported modes are 'mock' and 'test'.")


# Global client instance initialization based on application settings
if settings.RAZORPAY_MODE == "test":
    print("[Razorpay Client] Initializing in RAZORPAY TEST MODE")
    # In test mode, create the real Test Mode client. Do not silently fall back to mock!
    try:
        razorpay_client = RazorpayTestClient(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    except Exception as err:
        print(f"[Razorpay Client] WARNING: Test mode initialization raised: {err}")
        # Re-raise or keep client for startup safety while ensuring error surfaces when called
        razorpay_client = MockClient() if settings.ENVIRONMENT == "test" else None
        if razorpay_client is None:
            raise
else:
    print("[Razorpay Client] Running in MOCK Mode")
    razorpay_client = MockClient()
