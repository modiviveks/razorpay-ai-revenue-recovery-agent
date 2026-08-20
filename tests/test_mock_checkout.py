from fastapi.testclient import TestClient

from main import app
from simulator.scenarios import get_checkout_abandoned_payload


def test_mock_link_is_clickable_and_marks_recovery():
    with TestClient(app) as client:
        payload = get_checkout_abandoned_payload()
        payload["payload"]["checkout"]["entity"]["id"] = "checkout_clickable_test"
        payload["payload"]["checkout"]["entity"]["order_id"] = "order_clickable_test"
        created = client.post(
            "/webhook/razorpay",
            json=payload,
            headers={"X-Test-Simulator": "true", "X-Razorpay-Event-Id": "evt_clickable_mock_link"},
        ).json()
        link = created["new_payment_link"]
        assert client.get(link).status_code == 200
        paid = client.post(f"{link}/pay")
        assert paid.status_code == 200
        assert paid.json()["status"] == "recovered"


def test_mock_demo_reset_is_available_only_for_mock_mode():
    with TestClient(app) as client:
        response = client.post("/demo/reset")
        assert response.status_code == 200
        assert response.json()["status"] == "reset"
