import os
from pathlib import Path

import psycopg
import streamlit as st
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")

def get_database_url():
    url = os.environ.get("DATABASE_URL", "").strip()

    if not url:
        try:
            url = str(st.secrets.get("DATABASE_URL", "")).strip()
        except Exception:
            url = ""

    if not url:
        raise RuntimeError(
            "DATABASE_URL is missing. Configure it in Streamlit secrets "
            "or your local .env file."
        )

    return url

def get_connection():
    return psycopg.connect(
        get_database_url(),
        connect_timeout=15
    )
