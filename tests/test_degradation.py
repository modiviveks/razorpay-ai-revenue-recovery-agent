"""Unit tests for payment-network degradation detection."""

from models import FailureClass, RecoveryStrategy
from agent.degradation import PaymentDegradationDetector, BASELINE_SUCCESS_RATES


def test_degradation_detector_healthy_window():
    detector = PaymentDegradationDetector()
    report = detector.evaluate_method(
        method="upi",
        recent_total_count=100,
        recent_success_count=96,
    )
    assert not report.is_degraded
    assert report.severity == "HEALTHY"
    assert report.degradation_magnitude == 0.0
    assert not report.suppress_immediate_retry


def test_degradation_detector_triggers_on_drop():
    detector = PaymentDegradationDetector()
    # Baseline UPI is 96%; if recent success drops to 80%, degradation is 16% (CRITICAL)
    report = detector.evaluate_method(
        method="upi",
        recent_total_count=100,
        recent_success_count=80,
        dominant_failure_class=FailureClass.UPI_TIMEOUT,
    )
    assert report.is_degraded
    assert report.severity == "CRITICAL"
    assert report.degradation_magnitude >= 0.15
    assert report.suppress_immediate_retry
    assert report.recommended_action == RecoveryStrategy.ALTERNATE_METHOD_LINK
    assert "NPCI" in report.root_cause_hypothesis or "switch" in report.root_cause_hypothesis


def test_degradation_detector_event_stream():
    detector = PaymentDegradationDetector()
    events = [
        {"method": "card", "status": "failed", "failure_class": "BANK_DECLINE"} for _ in range(30)
    ] + [
        {"method": "card", "status": "captured"} for _ in range(70)
    ]
    reports = detector.evaluate_event_stream(events)
    assert "card" in reports
    card_report = reports["card"]
    assert card_report.is_degraded
    assert card_report.current_success_rate == 0.70
