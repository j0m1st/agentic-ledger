"""HTTP with retry/backoff, a read-only guard, and an explicit grant for approved writes."""
from __future__ import annotations

import time

import requests


class ReadOnlyViolation(RuntimeError):
    pass


class OutcomeUnknown(RuntimeError):
    """A write got a 5xx/timeout: it may or may not have been applied. Never auto-retry."""


class WriteGrant:
    """Issued only by engine.changes after the user approved the exact change set (by its approval code)."""

    def __init__(self, changeset_id: str, approval_code: str):
        self.changeset_id, self.approval_code = changeset_id, approval_code


def request(method: str, url: str, *, allow_post: bool = False, grant: WriteGrant = None,
            retries: int = 5, **kw) -> requests.Response:
    """GET by default. POST only for reads (token, query endpoints). Any other write needs a WriteGrant."""
    method = method.upper()
    is_read = method == "GET" or (method == "POST" and allow_post)
    if not is_read and not isinstance(grant, WriteGrant):
        raise ReadOnlyViolation(f"Blocked {method} {url}: writes require an approved change set (engine.changes).")
    kw.setdefault("timeout", 120)
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, **kw)
        except requests.RequestException as e:
            if is_read and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise (RuntimeError if is_read else OutcomeUnknown)(f"{method} {url.split('?')[0]}: {e}")
        # Writes only retry on 429 (request rejected, not processed); a retried 5xx could duplicate a record.
        retryable = (429,) if not is_read else (429, 500, 502, 503, 504)
        if resp.status_code in retryable and attempt < retries - 1:
            wait = float(resp.headers.get("Retry-After") or 2 ** attempt * 2)
            time.sleep(min(wait, 120))
            continue
        if resp.status_code >= 500 and not is_read:
            raise OutcomeUnknown(f"{method} {url.split('?')[0]} -> {resp.status_code}: outcome unknown, check the ERP before retrying")
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {url.split('?')[0]} -> {resp.status_code}: {resp.text[:500]}")
        return resp
    raise RuntimeError("unreachable")
