"""Shared helpers for Bluetti discovery scripts.

Loads credentials from .env at the repo root and puts the integration's
api/ modules on the import path so scripts can reuse the real login,
crypto, TOTP, MQTT, and Modbus code.

Run from the repo root with the dev venv active (Home Assistant must be
installed, because the bluetti_cloud package __init__ imports it):

    ./venv/bin/python scripts/discovery/01_rest_recon.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "custom_components"))


def load_env() -> None:
    """Populate os.environ from repo-root .env (no external dependency)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise SystemExit(
            f".env not found at {env_path}.\n"
            "Create it with:\n"
            "  BLUETTI_EMAIL=you@example.com\n"
            "  BLUETTI_PASSWORD=your-password\n"
        )
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_credentials() -> tuple[str, str]:
    """Return (email, password) from .env, or exit with a clear message."""
    load_env()
    email = os.environ.get("BLUETTI_EMAIL")
    password = os.environ.get("BLUETTI_PASSWORD")
    if not email or not password:
        raise SystemExit("BLUETTI_EMAIL and BLUETTI_PASSWORD must be set in .env")
    return email, password


def dump(label: str, obj: Any) -> None:
    """Pretty-print a labelled JSON block for recon output."""
    print(f"\n===== {label} =====")
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
