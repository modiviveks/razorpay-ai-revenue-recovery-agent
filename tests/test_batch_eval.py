"""Tests for Batch Evaluation and Benchmarking Engine."""

import os
from pathlib import Path
from simulator.batch_eval import run_batch_evaluation, generate_synthetic_batch


def test_generate_synthetic_batch_determinism():
    """Verify synthetic batch generation is deterministic given a fixed seed."""
    batch_a = generate_synthetic_batch(size=20, seed=42)
    batch_b = generate_synthetic_batch(size=20, seed=42)
    assert len(batch_a) == 20
    assert len(batch_b) == 20
    assert [x["payment_id"] for x in batch_a] == [x["payment_id"] for x in batch_b]
    assert [x["amount"] for x in batch_a] == [x["amount"] for x in batch_b]


def test_run_batch_evaluation_metrics_and_stopping_rules(tmp_path):
    """Test batch evaluation computes accurate totals, stopping rules, and produces markdown."""
    report_file = tmp_path / "TEST_BATCH_REPORT.md"
    results = run_batch_evaluation(
        batch_size=30,
        seed=123,
        auto_pay=True,
        auto_pay_rate=0.7,
        output_report=True,
        report_path=str(report_file),
    )

    assert results["batch_size"] == 30
    assert results["seed"] == 123
    assert results["total_at_risk_rupees"] > 0
    assert results["total_interventions"] > 0
    assert results["total_settled_recoveries"] > 0
    assert 0 <= results["value_recovery_rate_pct"] <= 100
    assert 0 <= results["intervention_rate_pct"] <= 100

    # Policy blocks sanity check
    pb = results["policy_blocks"]
    assert "NEGATIVE_EV_SKIPPED" in pb
    assert "HIGH_VALUE_PENDING_APPROVAL" in pb
    assert "BOUNDS_EXCEEDED" in pb
    assert "PROMISE_ACTIVE" in pb

    # Verify report was generated and contains critical sections
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "RazorRevive — Batch Evaluation & Measured Recovery Report" in content
    assert "Executive Summary & Measured Recovery Metrics" in content
    assert "Policy Enforcement & Stopping Rules Accounting" in content
    assert "Breakdown by Failure Classification" in content
