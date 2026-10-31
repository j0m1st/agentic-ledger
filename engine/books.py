"""Per-company book folders under books/<slug>/."""
from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = ROOT / "books"
TEMPLATE_DIR = ROOT / "templates" / "book"
ERPS = ("qbo", "xero", "intacct", "netsuite")
DATA_DIRS = ("raw", "normalized", "analysis", "work", "outbox")


class Book:
    def __init__(self, slug: str):
        self.slug = slug
        self.path = BOOKS_DIR / slug
        if not (self.path / "book.json").exists():
            raise SystemExit(f"No book '{slug}'. Create it: python -m engine new {slug} --erp <{'|'.join(ERPS)}>")
        self.config = json.loads((self.path / "book.json").read_text())

    @property
    def erp(self) -> str:
        return self.config["erp"]

    def dir(self, name: str) -> Path:
        d = self.path / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def set(self, **values) -> None:
        self.config.update(values)
        (self.path / "book.json").write_text(json.dumps(self.config, indent=2) + "\n")


def create(slug: str, erp: str) -> Book:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise SystemExit("Slug must be lowercase letters, digits and dashes.")
    if erp not in ERPS:
        raise SystemExit(f"erp must be one of {ERPS}")
    path = BOOKS_DIR / slug
    if path.exists():
        raise SystemExit(f"{path} already exists.")
    shutil.copytree(TEMPLATE_DIR, path)
    for d in DATA_DIRS:
        (path / d).mkdir(exist_ok=True)
    (path / "book.json").write_text(json.dumps(
        {"slug": slug, "erp": erp, "created": date.today().isoformat()}, indent=2) + "\n")
    return Book(slug)
