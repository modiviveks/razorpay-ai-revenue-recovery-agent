"""Lightweight, deterministic payment-network degradation detector.

Compares recent payment method failure/success rates against established baselines
to prevent blindly firing retries during widespread bank or network outages.
"""

from dataclasses import dataclass
from typing import Sequence
from models import FailureClass, RecoveryStrategy


BASELINE_SUCCESS_RATES = {
    "upi": 0.96,           # 96% standard UPI success baseline
    "card": 0.94,          # 94% standard 3DS card baseline
    "netbanking": 0.91,    # 91% standard NB redirect baseline
    "wallet": 0.95,        # 95% wallet direct baseline
    "unknown": 0.90,
}

DEGRADATION_THRESHOLD = 0.07  # 7% drop from baseline triggers degradation state
CRITICAL_THRESHOLD = 0.15     # 15% drop from baseline indicates widespread bank downtime


@dataclass(frozen=True)
class DegradationReport:
    method: str
    baseline_success_rate: float
    current_success_rate: float
    degradation_magnitude: float
    is_degraded: bool
    severity: str                         # HEALTHY | MODERATE | CRITICAL
    affected_failure_classes: list[str]
    root_cause_hypothesis: str
    recommended_action: RecoveryStrategy
    suppress_immediate_retry: bool
    explanation: str


class PaymentDegradationDetector:
    """Evaluates sliding windows of payment events to identify real-time network degradation."""

    def __init__(self, baselines: dict[str, float] | None = None):
        self.baselines = baselines or BASELINE_SUCCESS_RATES

    def evaluate_method(
        self,
        method: str,
        recent_total_count: int,
        recent_success_count: int,
        dominant_failure_class: FailureClass | None = None,
    ) -> DegradationReport:
        norm_method = (method or "unknown").lower()
        baseline = self.baselines.get(norm_method, 0.92)

        if recent_total_count < 5:
            # Insufficient sample volume in recent window
            return DegradationReport(
                method=norm_method,
                baseline_success_rate=baseline,
                current_success_rate=baseline,
                degradation_magnitude=0.0,
                is_degraded=False,
                severity="HEALTHY",
                affected_failure_classes=[],
                root_cause_hypothesis="Insufficient window sample size to detect network degradation.",
                recommended_action=RecoveryStrategy.RETRY_PAYMENT_LINK,
                suppress_immediate_retry=False,
                explanation=f"{norm_method.upper()} network is operating normally within sample tolerance.",
            )

        current_rate = round(recent_success_count / recent_total_count, 4)
        degradation_mag = round(max(0.0, baseline - current_rate), 4)
        is_degraded = degradation_mag >= DEGRADATION_THRESHOLD

        if not is_degraded:
            return DegradationReport(
                method=norm_method,
                baseline_success_rate=baseline,
                current_success_rate=current_rate,
                degradation_magnitude=degradation_mag,
                is_degraded=False,
                severity="HEALTHY",
                affected_failure_classes=[],
                root_cause_hypothesis=f"{norm_method.upper()} gateway and NPCI/issuer switch latencies are within SLA limits.",
                recommended_action=RecoveryStrategy.RETRY_PAYMENT_LINK,
                suppress_immediate_retry=False,
                explanation=f"{norm_method.upper()} success rate ({current_rate:.1%}) is stable relative to baseline ({baseline:.1%}).",
            )

        # Degraded state logic
        is_critical = degradation_mag >= CRITICAL_THRESHOLD
        severity = "CRITICAL" if is_critical else "MODERATE"
        failure_name = dominant_failure_class.value if dominant_failure_class else "UPI_TIMEOUT"

        if norm_method == "upi":
            hypothesis = (
                "Severe NPCI / major bank switch timeout spike detected. Multi-issuer PSP latencies exceeding 15s."
                if is_critical
                else "Moderate UPI issuer response latency elevation detected across top bank PSPs."
            )
            rec_action = RecoveryStrategy.ALTERNATE_METHOD_LINK if is_critical else RecoveryStrategy.RETRY_PAYMENT_LINK
        elif norm_method == "card":
            hypothesis = (
                "Major 3DS ACS (Access Control Server) OTP delivery failures detected across Visa/Mastercard networks."
                if is_critical
                else "Elevated bank decline rates observed for credit/debit card 3DS verification."
            )
            rec_action = RecoveryStrategy.ALTERNATE_METHOD_LINK
        else:
            hypothesis = f"Elevated technical decline rate on {norm_method.upper()} aggregator channel."
            rec_action = RecoveryStrategy.ALTERNATE_METHOD_LINK

        explanation = (
            f"NETWORK DEGRADATION DETECTED: {norm_method.upper()} success rate dropped from baseline {baseline:.1%} "
            f"to {current_rate:.1%} (magnitude -{degradation_mag:.1%}). {hypothesis} "
            f"{'Immediate retries suppressed in favor of alternate method link.' if is_critical else 'Monitoring network recoverability.'}"
        )

        return DegradationReport(
            method=norm_method,
            baseline_success_rate=baseline,
            current_success_rate=current_rate,
            degradation_magnitude=degradation_mag,
            is_degraded=True,
            severity=severity,
            affected_failure_classes=[failure_name],
            root_cause_hypothesis=hypothesis,
            recommended_action=rec_action,
            suppress_immediate_retry=is_critical,
            explanation=explanation,
        )

    def evaluate_event_stream(
        self,
        events: Sequence[dict],
    ) -> dict[str, DegradationReport]:
        """Aggregates a stream of recent transaction records into per-method degradation reports."""
        method_counts: dict[str, dict[str, int]] = {}
        failure_counts: dict[str, dict[str, int]] = {}

        for evt in events:
            method = (evt.get("method") or "unknown").lower()
            status = (evt.get("status") or "failed").lower()
            fc = evt.get("failure_class")

            if method not in method_counts:
                method_counts[method] = {"total": 0, "success": 0}
                failure_counts[method] = {}

            method_counts[method]["total"] += 1
            if status in {"captured", "success", "recovered"}:
                method_counts[method]["success"] += 1
            elif fc:
                failure_counts[method][fc] = failure_counts[method].get(fc, 0) + 1

        reports: dict[str, DegradationReport] = {}
        for method, counts in method_counts.items():
            top_fc = None
            if failure_counts.get(method):
                top_fc_name = max(failure_counts[method].items(), key=lambda x: x[1])[0]
                try:
                    top_fc = FailureClass(top_fc_name)
                except ValueError:
                    top_fc = FailureClass.UPI_TIMEOUT

            reports[method] = self.evaluate_method(
                method=method,
                recent_total_count=counts["total"],
                recent_success_count=counts["success"],
                dominant_failure_class=top_fc,
            )

        return reports


# Singleton instance for system usage
global_degradation_detector = PaymentDegradationDetector()
