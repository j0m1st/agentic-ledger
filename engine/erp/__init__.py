"""ERP adapters. Each module exposes auth(book), extract(book, start, end), normalize(book), MCP_ENV."""
from __future__ import annotations

import importlib
import json
from datetime import date, timedelta
from typing import Callable, Iterator, Tuple


def load(erp: str):
    return importlib.import_module(f"engine.erp.{erp}")


def month_ranges(start: date, end: date) -> Iterator[Tuple[date, date]]:
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield cur, min(nxt - timedelta(days=1), end)
        cur = nxt


class Extractor:
    """Saves each dataset to raw/<name>.json and records success/failure in raw/_manifest.json."""

    def __init__(self, book, start: date, end: date):
        self.book, self.start, self.end = book, start, end
        self.raw = book.dir("raw")
        self.manifest = {"erp": book.erp, "start": start.isoformat(), "end": end.isoformat(), "datasets": {}}

    def run(self, name: str, fn: Callable[[], object]) -> None:
        try:
            data = fn()
            (self.raw / f"{name}.json").write_text(json.dumps(data, indent=1, default=str))
            count = len(data) if isinstance(data, list) else 1
            self.manifest["datasets"][name] = {"ok": True, "records": count}
            print(f"  ok   {name} ({count})")
        except Exception as e:  # keep going; the agent reviews failures in the manifest
            self.manifest["datasets"][name] = {"ok": False, "error": str(e)[:300]}
            print(f"  FAIL {name}: {str(e)[:150]}")

    def finish(self) -> None:
        (self.raw / "_manifest.json").write_text(json.dumps(self.manifest, indent=2))
