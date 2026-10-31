"""Secret storage: env var AL_<BOOK>_<KEY> first, then the OS keychain via keyring."""
from __future__ import annotations

import getpass
import os
from typing import Optional

SERVICE = "agentic-ledger"


def _env_name(book: str, key: str) -> str:
    return f"AL_{book}_{key}".upper().replace("-", "_")


def get(book: str, key: str, required: bool = True) -> Optional[str]:
    value = os.environ.get(_env_name(book, key))
    if value is None:
        import keyring
        value = keyring.get_password(f"{SERVICE}:{book}", key)
    if value is None and required:
        raise SystemExit(f"Missing secret '{key}' for book '{book}'. Run: python -m engine auth {book}")
    return value


def put(book: str, key: str, value: str) -> None:
    import keyring
    keyring.set_password(f"{SERVICE}:{book}", key, value)


def prompt(book: str, key: str, label: str, secret: bool = True) -> str:
    """Ask for a value (hidden if secret), keeping the stored one on empty input."""
    existing = get(book, key, required=False)
    hint = " [keep existing]" if existing else ""
    value = (getpass.getpass if secret else input)(f"{label}{hint}: ").strip()
    if not value:
        if not existing:
            raise SystemExit(f"{label} is required.")
        return existing
    put(book, key, value)
    return value
