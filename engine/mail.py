"""Information-request emails via Resend, gated by a contact allowlist and explicit human approval.

Drafts live in books/<slug>/outbox/<id>.json; sent ones move to outbox/sent/.
Recipients must appear in context/contacts.csv with can_email = yes.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import vault
from .http import request
from .schema import read_csv

RESEND_URL = "https://api.resend.com/emails"
DRAFT_FIELDS = ("to", "subject", "body", "reason")


def setup(book) -> None:
    vault.prompt(book.slug, "resend_api_key", "Resend API key (sending-only scope recommended)")
    sender = input("From address on a Resend-verified domain (e.g. Books <books@yourco.com>): ").strip()
    reply_to = input("Reply-to address (blank = same as from): ").strip()
    book.set(email_from=sender, email_reply_to=reply_to or sender)
    print("Email configured. Add recipients to context/contacts.csv (can_email = yes).")


def allowlist(book) -> dict:
    path = book.path / "context" / "contacts.csv"
    if not path.exists():
        return {}
    return {r["email"].strip().lower(): r for r in read_csv(path)
            if r.get("email") and r.get("can_email", "").strip().lower() in ("yes", "y", "true")}


def validate(book, draft: dict) -> list:
    problems = [f"missing '{f}'" for f in DRAFT_FIELDS if not draft.get(f)]
    allowed = allowlist(book)
    for addr in draft.get("to", []) + draft.get("cc", []):
        if addr.strip().lower() not in allowed:
            problems.append(f"{addr} is not in context/contacts.csv with can_email=yes")
    if re.search(r"\b\d{9,}\b|password|passcode|ssn", draft.get("body", ""), re.I):
        problems.append("body looks like it contains an account number or credential request; remove it")
    return problems


def show(book, draft_id: str) -> dict:
    path = book.dir("outbox") / f"{draft_id}.json"
    if not path.exists():
        raise SystemExit(f"No draft {path}")
    draft = json.loads(path.read_text())
    print(f"From:    {book.config.get('email_from')}\nTo:      {', '.join(draft['to'])}")
    if draft.get("cc"):
        print(f"Cc:      {', '.join(draft['cc'])}")
    print(f"Subject: {draft['subject']}\nReason:  {draft['reason']}\n\n{draft['body']}\n")
    return draft


def send(book, draft_id: str, yes: bool = False) -> None:
    draft = show(book, draft_id)
    problems = validate(book, draft)
    if problems:
        raise SystemExit("Not sent:\n- " + "\n- ".join(problems))
    if not book.config.get("email_from"):
        raise SystemExit(f"Email not configured. Run: python -m engine email-setup {book.slug}")
    if not yes:
        if not sys.stdin.isatty():
            raise SystemExit("Refusing to send without approval: run interactively or pass --yes after the user approves.")
        if input("Type SEND to send this email: ").strip() != "SEND":
            raise SystemExit("Cancelled.")
    payload = {"from": book.config["email_from"], "to": draft["to"], "subject": draft["subject"],
               "text": draft["body"], "reply_to": book.config.get("email_reply_to")}
    if draft.get("cc"):
        payload["cc"] = draft["cc"]
    # Not an ERP call; allow_post is the deliberate, approved exception.
    resp = request("POST", RESEND_URL, allow_post=True, json=payload, retries=2, headers={
        "Authorization": f"Bearer {vault.get(book.slug, 'resend_api_key')}",
        "Idempotency-Key": f"{book.slug}-{draft_id}"}).json()
    draft.update(status="sent", resend_id=resp.get("id"), sent_at=datetime.now(timezone.utc).isoformat())
    sent_dir = book.dir("outbox/sent")
    (sent_dir / f"{draft_id}.json").write_text(json.dumps(draft, indent=2))
    (book.dir("outbox") / f"{draft_id}.json").unlink()
    print(f"Sent ({resp.get('id')}). Logged to {Path('outbox/sent') / (draft_id + '.json')}.")
