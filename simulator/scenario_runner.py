"""CLI Tool to simulate Razorpay payment failures and post webhooks to the local FastAPI server."""

import argparse
import sys
import json
import time
import httpx
from scenarios import SCENARIOS, get_payment_link_paid_payload

DEFAULT_URL = "http://127.0.0.1:8000/webhook/razorpay"

def post_webhook(url: str, payload: dict):
    """Sends webhook payload using HTTP POST with custom simulator bypass headers."""
    headers = {
        "Content-Type": "application/json",
        "X-Test-Simulator": "true"
    }
    
    event_type = payload.get("event", "unknown")
    entities = payload.get("payload", {})
    entity_id = next(
        (
            value.get("entity", {}).get("id")
            for value in entities.values()
            if isinstance(value, dict) and isinstance(value.get("entity"), dict)
        ),
        "unknown",
    )
    print(f"\n[Simulator] Posting {event_type} webhook for: {entity_id} ...")
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=5.0)
        if response.status_code == 200:
            res_data = response.json()
            print(f"[Simulator] SUCCESS (200 OK)")
            print(f"            - Classification : {res_data.get('failure_class')}")
            print(f"            - Strategy       : {res_data.get('strategy')}")
            print(f"            - Action Status  : {res_data.get('action_status')}")
            if res_data.get('new_payment_link'):
                print(f"            - Recovery Link  : {res_data.get('new_payment_link')}")
            if res_data.get("status") == "recovered":
                print(f"            - Recovery      : VERIFIED AND ATTRIBUTED")
            return res_data
        else:
            print(f"[Simulator] FAILED: Status code {response.status_code}")
            print(f"            Response: {response.text}")
    except httpx.RequestError as e:
        print(f"[Simulator] HTTP Connection Error: {e}")
        print("            Is the FastAPI server running on http://127.0.0.1:8000?")
    return None


def main():
    parser = argparse.ArgumentParser(description="Razorpay Failure Webhook Simulator")
    parser.add_argument(
        "--scenario",
        type=str,
        choices=list(SCENARIOS.keys()) + ["all"],
        default="all",
        help="The failure scenario to trigger (default: all)"
    )
    parser.add_argument(
        "--mark-recovered",
        action="store_true",
        help="After each generated recovery link, simulate a verified payment_link.paid webhook.",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=DEFAULT_URL,
        help=f"Target webhook URL (default: {DEFAULT_URL})"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between scenarios when running 'all' (default: 1.0)"
    )

    args = parser.parse_args()
    
    if args.scenario == "all":
        print(f"--- Running ALL {len(SCENARIOS)} simulated failure scenarios against {args.url} ---")
        for idx, (name, builder_fn) in enumerate(SCENARIOS.items(), 1):
            print(f"\n({idx}/{len(SCENARIOS)}) Triggering Scenario: {name.upper()}")
            payload = builder_fn()
            result = post_webhook(args.url, payload)
            if args.mark_recovered and result and result.get("new_payment_link"):
                payment_link_id = result["new_payment_link"].rstrip("/").split("/")[-1]
                print("[Simulator] Simulating successful payment for the recovery link...")
                post_webhook(args.url, get_payment_link_paid_payload(payment_link_id))
            if idx < len(SCENARIOS):
                time.sleep(args.delay)
    else:
        print(f"--- Running scenario: {args.scenario.upper()} against {args.url} ---")
        builder_fn = SCENARIOS[args.scenario]
        payload = builder_fn()
        result = post_webhook(args.url, payload)
        if args.mark_recovered and result and result.get("new_payment_link"):
            payment_link_id = result["new_payment_link"].rstrip("/").split("/")[-1]
            print("[Simulator] Simulating successful payment for the recovery link...")
            post_webhook(args.url, get_payment_link_paid_payload(payment_link_id))

if __name__ == "__main__":
    main()
