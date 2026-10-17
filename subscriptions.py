from datetime import date, datetime, timedelta, timezone

from db import get_connection

FREE_DAILY_LIMIT = 2


def init_subscription_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_email TEXT PRIMARY KEY,
                plan TEXT NOT NULL DEFAULT 'free',
                status TEXT NOT NULL DEFAULT 'active',
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscription_details (
                user_email TEXT PRIMARY KEY,
                billing_plan TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_daily (
                user_email TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                question_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_email, usage_date)
            )
        """)


def get_subscription(email):
    init_subscription_db()
    email = email.strip().lower()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT plan, status FROM subscriptions WHERE user_email = %s",
            (email,)
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO subscriptions (user_email, plan, status) "
                "VALUES (%s, 'free', 'active') ON CONFLICT (user_email) DO NOTHING",
                (email,)
            )
            return {"plan": "free", "status": "active"}

        details = conn.execute(
            "SELECT expires_at FROM subscription_details WHERE user_email = %s",
            (email,)
        ).fetchone()

        if row[0] == "premium" and details:
            try:
                expires_at = datetime.fromisoformat(details[0])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                if expires_at <= datetime.now(timezone.utc):
                    conn.execute(
                        "UPDATE subscriptions SET plan='free', status='active', "
                        "updated_at=CURRENT_TIMESTAMP WHERE user_email=%s",
                        (email,)
                    )
                    return {"plan": "free", "status": "active"}
            except (ValueError, TypeError):
                return {"plan": "free", "status": "inactive"}

    return {"plan": row[0], "status": row[1]}


def get_daily_usage(email):
    init_subscription_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT question_count FROM usage_daily "
            "WHERE user_email = %s AND usage_date = %s",
            (email.strip().lower(), date.today().isoformat())
        ).fetchone()
    return row[0] if row else 0


def can_ask_question(email, exempt=False):
    if exempt:
        return True, "Friend access enabled."

    subscription = get_subscription(email)
    if subscription["plan"] == "premium" and subscription["status"] == "active":
        return True, "Premium access enabled."

    used = get_daily_usage(email)
    if used >= FREE_DAILY_LIMIT:
        return False, (
            f"You have used your {FREE_DAILY_LIMIT} free questions today. "
            "Upgrade to Premium for more access."
        )

    return True, f"{FREE_DAILY_LIMIT - used} free question(s) remaining today."


def record_question(email, exempt=False):
    if exempt:
        return

    init_subscription_db()
    email = email.strip().lower()

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO usage_daily (user_email, usage_date, question_count) "
            "VALUES (%s, %s, 1) "
            "ON CONFLICT (user_email, usage_date) DO UPDATE SET "
            "question_count = usage_daily.question_count + 1",
            (email, date.today().isoformat())
        )


def set_subscription(email, plan, status="active"):
    if plan not in {"free", "premium"}:
        raise ValueError("Unsupported subscription plan.")

    init_subscription_db()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO subscriptions (user_email, plan, status) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (user_email) DO UPDATE SET "
            "plan = EXCLUDED.plan, status = EXCLUDED.status, "
            "updated_at = CURRENT_TIMESTAMP",
            (email.strip().lower(), plan, status)
        )


def activate_verified_subscription(email, plan):
    durations = {"monthly": 30, "annual": 365}
    if plan not in durations:
        raise ValueError("Unsupported paid plan.")

    init_subscription_db()
    email = email.strip().lower()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=durations[plan])
    ).isoformat()

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO subscriptions (user_email, plan, status) "
            "VALUES (%s, 'premium', 'active') "
            "ON CONFLICT (user_email) DO UPDATE SET "
            "plan='premium', status='active', updated_at=CURRENT_TIMESTAMP",
            (email,)
        )
        conn.execute(
            "INSERT INTO subscription_details (user_email, billing_plan, expires_at) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (user_email) DO UPDATE SET "
            "billing_plan=EXCLUDED.billing_plan, expires_at=EXCLUDED.expires_at",
            (email, plan, expires_at)
        )
