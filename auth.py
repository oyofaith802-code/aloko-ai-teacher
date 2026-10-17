import hashlib
import hmac
import secrets
import re

import psycopg
from db import get_connection


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        600000
    ).hex()


def register_user(email, password):
    email = email.strip().lower()

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return False, "Enter a valid email address."

    if len(password) < 8:
        return False, "Password must contain at least 8 characters."

    salt = secrets.token_hex(16)
    password_hash = hash_password(password, salt)

    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (email, password_hash, salt) VALUES (%s, %s, %s)",
                (email, password_hash, salt)
            )
        return True, "Account created. You can now sign in."
    except psycopg.errors.UniqueViolation:
        return False, "Unable to create this account. Try signing in instead."


def verify_user(email, password):
    email = email.strip().lower()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT password_hash, salt FROM users WHERE email = %s",
            (email,)
        ).fetchone()

    if not row:
        return False

    stored_hash, salt = row
    supplied_hash = hash_password(password, salt)
    return hmac.compare_digest(stored_hash, supplied_hash)


# Approved accounts exempt from subscription payments.
SUBSCRIPTION_EXEMPT_EMAILS = {
    "oshokhajahmin@gmail.com",
}


def is_subscription_exempt(email):
    return (email or "").strip().lower() in SUBSCRIPTION_EXEMPT_EMAILS
