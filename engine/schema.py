"""ERP-agnostic normalized schema consumed by engine/profile.py.

Agents using an MCP connector (instead of the API extractors) should write these two
CSVs directly into books/<slug>/normalized/ and then run `python -m engine profile`.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

ACCOUNT_COLUMNS = [
    "account_id", "number", "name", "full_name",
    "erp_type", "erp_subtype",
    "class",      # asset | liability | equity | income | expense
    "role",       # ar | ap | bank | credit_card | other
    "parent_id", "active", "balance",
]

GL_COLUMNS = [
    "date",            # YYYY-MM-DD transaction/posting date
    "txn_id", "txn_type", "doc_num", "line_no",
    "account_id", "account_number", "account_name",
    "debit", "credit",  # positive numbers, one of them zero
    "memo",
    "counterparty", "counterparty_type",  # customer | vendor | employee | other | ""
    "dimensions",      # "Class=Retail;Location=NY"
    "created_date",    # YYYY-MM-DD entry date, if the ERP exposes it
    "is_adjusting",    # true/false/""
]

CLASS_VALUES = {"asset", "liability", "equity", "income", "expense"}


def write_csv(path: Path, columns: List[str], rows: Iterable[Dict[str, Any]]) -> int:
    n = 0
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in columns})
            n += 1
    return n


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "")) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0
