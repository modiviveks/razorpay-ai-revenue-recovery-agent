"""Razorpay API client wrapper supporting both real API calls and mock responses."""

import time
import random
import razorpay
from config import settings

class MockPaymentLink:
    """Mock Razorpay payment link entity."""
    def __init__(self, data):
        self.id = data.get("id") or f"plink_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=14))}"
        # A local hosted checkout makes mock-mode demos clickable. Real mode
        # continues to return the Razorpay URL supplied by the SDK.
        self.short_url = f"/demo/payment-links/{self.id}"
        self.status = "created"
        self.amount = data.get("amount")
        self.currency = data.get("currency")
        self.description = data.get("description")
        self.customer = data.get("customer")
        self.expire_by = data.get("expire_by")
        self.created_at = int(time.time())

    def __getitem__(self, key):
        return getattr(self, key, None)

    def get(self, key, default=None):
        return getattr(self, key, default)


class MockPaymentLinkModule:
    """Mock client.payment_link module."""
    def create(self, data):
        return MockPaymentLink(data)

    def cancel(self, plink_id):
        return {"id": plink_id, "status": "cancelled"}

    def fetch(self, plink_id):
        return {
            "id": plink_id,
            "status": "created",
            "short_url": f"/demo/payment-links/{plink_id}",
            "amount": 50000,
            "currency": "INR"
        }

    def notify(self, plink_id, medium):
        return {"success": True, "medium": medium}


class MockClient:
    """Mock Razorpay Client that returns mock objects."""
    def __init__(self):
        self.payment_link = MockPaymentLinkModule()
        self.utility = self

    def verify_webhook_signature(self, body, signature, secret):
        # Always verify in mock mode
        return True


# Global client instance initialization
if settings.MOCK_RAZORPAY:
    print("[Razorpay Client] Running in MOCK Mode")
    razorpay_client = MockClient()
else:
    print("[Razorpay Client] Running in REAL Mode")
    try:
        razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        razorpay_client.enable_retry(True)
    except Exception as e:
        print(f"[Razorpay Client] Initialization failed. Falling back to MOCK mode. Error: {e}")
        razorpay_client = MockClient()
