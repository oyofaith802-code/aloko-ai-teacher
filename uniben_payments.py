import os
import secrets
from datetime import timedelta

from db import get_connection
from paystack_payments import initialize_checkout, verify_transaction

UNIBEN_PLAN = {
    "amount": 50000,  # ₦250 in kobo
    "label": "UNIBEN Verified Past Questions - 5 Hours",
    "access_seconds": 5 * 60 * 60,
}


def init_uniben_payment_tables():
    """Create separate payment records; do not modify Aloko payment tables."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS uniben_pending_payments (
                reference TEXT PRIMARY KEY,
                user_email TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


def create_uniben_checkout(email, callback_url=None):
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("A valid signed-in email is required.")

    reference = "uniben_" + secrets.token_hex(16)

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO uniben_pending_payments
                (reference, user_email, amount)
            VALUES (%s, %s, %s)
        """, (reference, email, UNIBEN_PLAN["amount"]))

    try:
        checkout_url = initialize_checkout(
            email=email,
            plan="uniben_quiz",
            reference=reference,
            callback_url=callback_url,
        )
    except Exception:
        with get_connection() as conn:
            conn.execute("""
                DELETE FROM uniben_pending_payments
                WHERE reference = %s AND status = 'pending'
            """, (reference,))
        raise

    return {"reference": reference, "checkout_url": checkout_url}


def verify_uniben_checkout(reference, signed_in_email):
    """
    Verify against the saved account and expected amount.
    Returns True only after Paystack confirms the transaction.
    """
    reference = (reference or "").strip()
    email = (signed_in_email or "").strip().lower()
    if not reference or not email:
        return False

    with get_connection() as conn:
        pending = conn.execute("""
            SELECT user_email, amount, status
            FROM uniben_pending_payments
            WHERE reference = %s
            FOR UPDATE
        """, (reference,)).fetchone()

        if not pending:
            return False

        pending_email, amount, status = pending
        if pending_email.strip().lower() != email:
            return False
        if status != "pending" or amount != UNIBEN_PLAN["amount"]:
            return False

        verified = verify_transaction(
            reference=reference,
            expected_amount=UNIBEN_PLAN["amount"],
            expected_email=email,
        )
        if not verified:
            return False

        # Grant access using the existing quiz engine's dedicated table.
        conn.execute("""
            INSERT INTO uniben_quiz_premium_access
                (student_id, payment_reference, expires_at)
            VALUES (%s, %s, NOW() + (%s * INTERVAL '1 second'))
            ON CONFLICT (payment_reference) DO NOTHING
        """, (email, reference, UNIBEN_PLAN["access_seconds"]))

        conn.execute("""
            UPDATE uniben_pending_payments
            SET status = 'verified'
            WHERE reference = %s AND status = 'pending'
        """, (reference,))

    return True
