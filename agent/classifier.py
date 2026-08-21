"""Failure Classifier: Maps Razorpay error details to high-level FailureClass."""

from openai import OpenAI
from config import settings
from models import FailureClass

# Rule-based mapping as a fallback or primary classifier
def classify_by_rules(
    error_code: str,
    error_description: str,
    error_source: str,
    error_step: str,
    error_reason: str,
    method: str
) -> tuple[FailureClass, str]:
    """Classifies error based on rules. Returns (FailureClass, rationale)."""
    
    code = (error_code or "").upper()
    desc = (error_description or "").lower()
    source = (error_source or "").lower()
    step = (error_step or "").lower()
    reason = (error_reason or "").lower()
    m = (method or "").lower()

    # UPI timeout specific check
    if m == "upi" and ("timeout" in desc or reason == "payment_timeout" or "timed out" in desc):
        return FailureClass.UPI_TIMEOUT, "UPI transaction timed out before user could complete authorization."

    # Insufficient funds
    if "insufficient" in desc or reason == "insufficient_funds" or "balance" in desc:
        return FailureClass.INSUFFICIENT_FUNDS, "Payment failed due to insufficient funds in customer's account."

    # Stale/Invalid card details
    if "expired" in desc or reason == "card_expired" or "invalid card" in desc:
        return FailureClass.CARD_EXPIRED, "Customer's card has expired or card details are invalid."

    # User cancellation
    if "cancelled" in desc or reason == "payment_cancelled" or "dismissed" in desc:
        return FailureClass.PAYMENT_CANCELLED, "Customer closed the checkout window or cancelled the payment."

    # Subscription/mandate failures need a different recovery path than a one-off OTP failure.
    if "subscription" in desc or "recurring" in desc or "mandate" in desc:
        return FailureClass.SUBSCRIPTION_FAILED, "Recurring subscription or mandate payment failed and needs a customer update."

    # Authentication failure (OTP)
    if "otp" in desc or reason in ("invalid_otp", "authentication_failed") or "auth" in step:
        return FailureClass.AUTHENTICATION_FAILED, "Authentication failed. Likely incorrect OTP entered by the customer."

    # Bank decline
    if "bank" in desc or reason == "gateway_technical_error" or source == "gateway":
        return FailureClass.BANK_DECLINE, "Payment declined by the customer's issuing bank or network provider."

    # Gateway or connection errors
    if code == "GATEWAY_ERROR":
        return FailureClass.GATEWAY_ERROR, "A transient error occurred at the payment gateway level."

    # Default fallback
    return FailureClass.UNKNOWN, f"Unknown payment failure. Code: {error_code}, Reason: {error_reason}"


def classify_failure(
    error_code: str,
    error_description: str,
    error_source: str,
    error_step: str,
    error_reason: str,
    method: str
) -> tuple[FailureClass, str]:
    """Main classification function. Uses rule-based logic and optional LLM refinement."""
    # First get rule-based classification
    f_class, rationale = classify_by_rules(
        error_code, error_description, error_source, error_step, error_reason, method
    )

    # Use LLM explanation layer only if API key is present and enabled
    if settings.USE_LLM_EXPLANATIONS and settings.OPENAI_API_KEY:
        try:
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            prompt = (
                f"A payment failed on Razorpay.\n"
                f"- Error Code: {error_code}\n"
                f"- Error Description: {error_description}\n"
                f"- Source: {error_source}\n"
                f"- Step: {error_step}\n"
                f"- Reason: {error_reason}\n"
                f"- Payment Method: {method}\n\n"
                f"We classified this as: {f_class.value}.\n"
                f"Write a short, professional, user-facing summary explaining to the merchant why "
                f"this failed and what it means (maximum 2 sentences)."
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert payment risk analyst."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=60,
                temperature=0.3
            )
            llm_rationale = response.choices[0].message.content.strip()
            if llm_rationale:
                rationale = llm_rationale
        except Exception as e:
            # Fallback to rule-based rationale if LLM fails
            print(f"[Classifier] LLM explanation failed: {e}")

    return f_class, rationale
