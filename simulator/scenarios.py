"""Webhook payload scenarios for simulating payment failures."""

import time

def get_base_payload(payment_id, amount_paise=50000, method="card"):
    """Generates standard webhook wrapper envelope."""
    return {
        "entity": "event",
        "account_id": "acc_mockmerchant",
        "event": "payment.failed",
        "contains": ["payment"],
        "created_at": int(time.time()),
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": f"order_{payment_id[4:]}",
                    "invoice_id": None,
                    "international": False,
                    "method": method,
                    "amount_refunded": 0,
                    "refund_status": None,
                    "captured": False,
                    "description": "Mock Purchase Description",
                    "card_id": "card_mock" if method == "card" else None,
                    "bank": "HDFC" if method == "netbanking" else None,
                    "wallet": None,
                    "vpa": "customer@pay" if method == "upi" else None,
                    "email": "customer.test@example.com",
                    "contact": "+919876543210",
                    "notes": {
                        "customer_name": "Rajesh Kumar"
                    },
                    "fee": None,
                    "tax": None,
                    "error_code": None,
                    "error_description": None,
                    "error_source": None,
                    "error_step": None,
                    "error_reason": None,
                    "created_at": int(time.time())
                }
            }
        }
    }


def get_upi_timeout_payload():
    payload = get_base_payload("pay_upi_timeout_123", amount_paise=75000, method="upi")
    pay_entity = payload["payload"]["payment"]["entity"]
    pay_entity.update({
        "error_code": "GATEWAY_ERROR",
        "error_description": "Payment timed out at the payment gateway provider side.",
        "error_source": "gateway",
        "error_step": "payment_initiation",
        "error_reason": "payment_timeout"
    })
    return payload


def get_card_expired_payload():
    payload = get_base_payload("pay_card_expired_123", amount_paise=120000, method="card")
    pay_entity = payload["payload"]["payment"]["entity"]
    pay_entity.update({
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Card has expired. Please use a valid card.",
        "error_source": "customer",
        "error_step": "payment_initiation",
        "error_reason": "card_expired"
    })
    return payload


def get_insufficient_funds_payload():
    payload = get_base_payload("pay_no_funds_123", amount_paise=35000, method="upi")
    pay_entity = payload["payload"]["payment"]["entity"]
    pay_entity.update({
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Customer has insufficient funds in their bank account.",
        "error_source": "customer",
        "error_step": "payment_authentication",
        "error_reason": "insufficient_funds"
    })
    return payload


def get_user_cancelled_payload():
    payload = get_base_payload("pay_cancelled_123", amount_paise=150000, method="card")
    pay_entity = payload["payload"]["payment"]["entity"]
    pay_entity.update({
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Payment was cancelled or dismissed by the user.",
        "error_source": "customer",
        "error_step": "payment_authentication",
        "error_reason": "payment_cancelled"
    })
    return payload


def get_bank_decline_payload():
    payload = get_base_payload("pay_bank_decline_123", amount_paise=99900, method="netbanking")
    pay_entity = payload["payload"]["payment"]["entity"]
    pay_entity.update({
        "error_code": "GATEWAY_ERROR",
        "error_description": "The transaction was declined by the bank.",
        "error_source": "gateway",
        "error_step": "payment_initiation",
        "error_reason": "gateway_technical_error"
    })
    return payload


def get_subscription_failed_payload():
    # Mandate payment fail
    payload = get_base_payload("pay_sub_failed_123", amount_paise=150000, method="card")
    pay_entity = payload["payload"]["payment"]["entity"]
    # Add subscription details
    pay_entity["subscription_id"] = "sub_mocksubscription123"
    pay_entity.update({
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Recurring charge failed due to authentication failure on card mandate.",
        "error_source": "customer",
        "error_step": "payment_initiation",
        "error_reason": "authentication_failed"
    })
    return payload


def get_below_minimum_payload():
    # Amount ₹0.50 (50 paise)
    payload = get_base_payload("pay_low_amount_123", amount_paise=50, method="upi")
    pay_entity = payload["payload"]["payment"]["entity"]
    pay_entity.update({
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "Amount is less than minimum amount of Rs. 1.00",
        "error_source": "business",
        "error_step": "payment_initiation",
        "error_reason": "amount_less_than_minimum_amount"
    })
    return payload


SCENARIOS = {
    "upi_timeout": get_upi_timeout_payload,
    "card_expired": get_card_expired_payload,
    "insufficient_funds": get_insufficient_funds_payload,
    "user_cancelled": get_user_cancelled_payload,
    "bank_decline": get_bank_decline_payload,
    "subscription_failed": get_subscription_failed_payload,
    "below_minimum": get_below_minimum_payload
}


def get_payment_link_paid_payload(payment_link_id: str):
    """Build a Razorpay-style payment_link.paid event for demo reconciliation."""
    return {
        "entity": "event",
        "account_id": "acc_mockmerchant",
        "event": "payment_link.paid",
        "contains": ["payment_link"],
        "created_at": int(time.time()),
        "payload": {
            "payment_link": {
                "entity": {
                    "id": payment_link_id,
                    "entity": "payment_link",
                    "status": "paid",
                    "paid_at": int(time.time()),
                }
            }
        },
    }
