import os
from urllib.parse import quote

import requests

PAYSTACK_BASE_URL = "https://api.paystack.co"

PLANS = {
    "monthly": {"amount": 150000, "label": "Aloko Premium Monthly"},
    "annual": {"amount": 1500000, "label": "Aloko Premium Annual"},
}


def _headers():
    secret = os.getenv("PAYSTACK_SECRET_KEY", "").strip()

    if not secret:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not configured.")

    if not (secret.startswith("sk_test_") or secret.startswith("sk_live_")):
        raise RuntimeError("Configure a valid Paystack test or live secret key.")

    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


def initialize_checkout(email, plan, reference, callback_url=None):
    if plan not in PLANS:
        raise ValueError("Invalid subscription plan.")

    payload = {
        "email": email.strip().lower(),
        "amount": PLANS[plan]["amount"],
        "currency": "NGN",
        "reference": reference,
        "metadata": {"product": "Aloko AI Teacher", "plan": plan},
    }

    if callback_url:
        payload["callback_url"] = callback_url

    response = requests.post(
        f"{PAYSTACK_BASE_URL}/transaction/initialize",
        json=payload,
        headers=_headers(),
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("status") or not result.get("data", {}).get("authorization_url"):
        raise RuntimeError("Paystack did not return a checkout URL.")

    return result["data"]["authorization_url"]


def verify_transaction(reference, expected_amount, expected_email=None):
    safe_reference = quote(str(reference), safe="")
    response = requests.get(
        f"{PAYSTACK_BASE_URL}/transaction/verify/{safe_reference}",
        headers=_headers(),
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("status"):
        raise RuntimeError("Paystack transaction verification failed.")

    data = result.get("data", {})

    if data.get("status") != "success":
        return False
    if data.get("currency") != "NGN":
        return False
    if data.get("amount") != expected_amount:
        return False
    if data.get("reference") != reference:
        return False

    if expected_email:
        customer_email = str(
            (data.get("customer") or {}).get("email") or ""
        ).strip().lower()
        if customer_email != expected_email.strip().lower():
            return False

    return True
