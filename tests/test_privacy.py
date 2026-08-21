from agent.executor import redact_for_audit


def test_audit_redaction_removes_email_and_phone_number():
    text = "customer@example.com called from +91 98765 43210"
    redacted = redact_for_audit(text)

    assert "customer@example.com" not in redacted
    assert "98765" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
