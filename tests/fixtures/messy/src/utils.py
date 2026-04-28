"""Utility functions."""
import os

API_KEY = os.environ["API_KEY"]


def fetch(url: str) -> str:
    return f"GET {url} with key={API_KEY}"
