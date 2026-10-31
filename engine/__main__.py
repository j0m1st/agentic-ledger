"""CLI: python -m engine <command> <book> [...]"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date

from . import books, mail, vault
from .erp import load


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m engine", description="Agentic Ledger engine (read-only ERP access).")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="create books/<slug>/ from templates")
    n.add_argument("book")
    n.add_argument("--erp", required=True, choices=books.ERPS)

    for name, desc in (("auth", "store ERP credentials in the OS keychain and test them"),
                       ("normalize", "raw/ -> normalized/{accounts,gl_lines}.csv"),
                       ("profile", "normalized/ -> analysis/ (works for MCP-written CSVs too)"),
                       ("email-setup", "store Resend API key and sender for information requests")):
        sub.add_parser(name, help=desc).add_argument("book")

    for name, desc in (("extract", "pull ERP data into raw/"), ("run", "extract + normalize + profile")):
        x = sub.add_parser(name, help=desc)
        x.add_argument("book")
        x.add_argument("--start", type=date.fromisoformat, default=date(date.today().year - 2, 1, 1))
        x.add_argument("--end", type=date.fromisoformat, default=date.today())

    for name, desc in (("email-check", "validate a draft in outbox/ (no send)"), ("email-send", "send an approved draft via Resend")):
        m = sub.add_parser(name, help=desc)
        m.add_argument("book")
        m.add_argument("draft_id")
        if name == "email-send":
            m.add_argument("--yes", action="store_true", help="user already approved this exact draft")

    e = sub.add_parser("exec", help="run a command (e.g. a local MCP server) with this book's secrets as env vars")
    e.add_argument("book")
    e.add_argument("command", nargs=argparse.REMAINDER)

    a = p.parse_args(argv)
    if a.cmd == "new":
        b = books.create(a.book, a.erp)
        print(f"Created {b.path}. Next: python -m engine auth {a.book}  (or connect via MCP: setup/CONNECT.md)")
        return

    b = books.Book(a.book)
    erp = load(b.erp)
    if a.cmd == "auth":
        erp.auth(b)
    elif a.cmd == "extract":
        erp.extract(b, a.start, a.end)
    elif a.cmd == "normalize":
        erp.normalize(b)
    elif a.cmd == "profile":
        from .profile import profile
        profile(b)
    elif a.cmd == "run":
        from .profile import profile
        print(f"Extracting {a.start} → {a.end} from {b.erp}…")
        erp.extract(b, a.start, a.end)
        erp.normalize(b)
        profile(b)
    elif a.cmd == "email-setup":
        mail.setup(b)
    elif a.cmd == "email-check":
        draft = mail.show(b, a.draft_id)
        problems = mail.validate(b, draft)
        print("OK: ready for user approval." if not problems else "Problems:\n- " + "\n- ".join(problems))
    elif a.cmd == "email-send":
        mail.send(b, a.draft_id, yes=a.yes)
    elif a.cmd == "exec":
        cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
        if not cmd:
            raise SystemExit("Usage: python -m engine exec <book> -- <command...>")
        env = dict(os.environ)
        for var, key in getattr(erp, "MCP_ENV", {}).items():
            value = vault.get(b.slug, key, required=False)
            if value:
                env[var] = value
        sys.exit(subprocess.call(cmd, env=env))


if __name__ == "__main__":
    main()
