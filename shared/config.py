"""Settings shared across the project: credentials, folders."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"


def api_key() -> str:
    key = os.getenv("MASSIVE_API_KEY")
    if not key:
        raise SystemExit("MASSIVE_API_KEY is missing. Copy .env.example to .env and add your key.")
    return key


def finra_credentials() -> tuple[str, str]:
    client_id = os.getenv("FINRA_CLIENT_ID")
    client_secret = os.getenv("FINRA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit(
            "FINRA_CLIENT_ID / FINRA_CLIENT_SECRET missing. Register a free account at "
            "developer.finra.org, create a Public app, and copy .env.example to .env with those values."
        )
    return client_id, client_secret
