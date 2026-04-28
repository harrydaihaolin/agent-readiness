"""Main application module."""
import os

DB_URL = os.environ["DATABASE_URL"]
SECRET = os.environ.get("SECRET_KEY", "")


def run() -> None:
    print(f"Connecting to {DB_URL}")
