"""HTTP with retry/backoff and a read-only guard."""
from __future__ import annotations

import time

import requests


class ReadOnlyViolation(RuntimeError):
    pass


def request(method: str, url: str, *, allow_post: bool = False, retries: int = 5, **kw) -> requests.Response:
    """GET by default. POST only when the caller marks it a read (token, query endpoints)."""
    method = method.upper()
    if method != "GET" and not (method == "POST" and allow_post):
        raise ReadOnlyViolation(f"Blocked {method} {url}: the engine is read-only.")
    kw.setdefault("timeout", 120)
    for attempt in range(retries):
        resp = requests.request(method, url, **kw)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            wait = float(resp.headers.get("Retry-After") or 2 ** attempt * 2)
            time.sleep(min(wait, 120))
            continue
        if resp.status_code >= 400:
            # Bodies can echo request data, not secrets; truncate anyway.
            raise RuntimeError(f"{method} {url.split('?')[0]} -> {resp.status_code}: {resp.text[:500]}")
        return resp
    raise RuntimeError("unreachable")
