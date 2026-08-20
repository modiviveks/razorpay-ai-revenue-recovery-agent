"""Constrained AI advisor for recovery explanations and next-best-action context.

The advisor receives no contact details and is deliberately non-authoritative:
the policy engine has already selected the strategy and enforced all bounds.
"""

import json
from dataclasses import dataclass

from openai import OpenAI

from config import settings
from models import ActionStatus, FailureClass, RecoveryStrategy


@dataclass(frozen=True)
class AdvisorResult:
    summary: str
    source: str


def _fallback(failure_class: FailureClass, strategy: RecoveryStrategy, status: ActionStatus) -> AdvisorResult:
    if status not in (ActionStatus.PENDING, ActionStatus.SUCCESS):
        return AdvisorResult(
            "Safety policy has paused automatic action. A merchant can inspect the audit trail before any follow-up.",
            "policy_fallback",
        )
    return AdvisorResult(
        f"AI advisor context: {failure_class.value} is being handled with {strategy.value}. "
        "The customer-facing explanation should be concise, avoid sensitive failure details, and offer only the approved recovery path.",
        "policy_fallback",
    )


def generate_advice(
    failure_class: FailureClass,
    strategy: RecoveryStrategy,
    status: ActionStatus,
    confidence: float,
    previous_retries: int,
) -> AdvisorResult:
    """Generate a bounded merchant explanation; never return executable instructions."""
    fallback = _fallback(failure_class, strategy, status)
    if not (settings.USE_AI_ADVISOR and settings.OPENAI_API_KEY):
        return fallback
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        prompt = {
            "failure_class": failure_class.value,
            "approved_strategy": strategy.value,
            "policy_status": status.value,
            "recovery_confidence": confidence,
            "prior_attempts": previous_retries,
        }
        response = client.chat.completions.create(
            model=settings.AI_ADVISOR_MODEL,
            temperature=0.2,
            max_tokens=100,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an advisory payment-recovery analyst. The approved strategy and policy status are immutable. "
                        "Do not recommend a different strategy, extra retries, charging a saved instrument, contacting a customer, "
                        "or bypassing a safety rule. Return JSON only: {\"summary\": \"one or two concise sentences for a merchant\"}."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        summary = json.loads(content).get("summary", "").strip()
        if summary:
            return AdvisorResult(summary[:500], "openai_advisor")
    except Exception as exc:
        print(f"[Advisor] AI advisor unavailable: {exc}")
    return fallback
