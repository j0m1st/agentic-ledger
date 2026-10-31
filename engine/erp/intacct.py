"""Sage Intacct REST API v1 via OAuth 2.0 client credentials.

Intacct object/field names vary by release and by company configuration, so extract() asks the
model endpoint for each object's fields, and normalize() matches fields by candidate names.
Check the warnings it prints, and fix the candidates below if a field is missed.
"""
from __future__ import annotations

import json
import time

from .. import vault
from ..http import request
from ..schema import ACCOUNT_COLUMNS, GL_COLUMNS, load_json, num, write_csv
from . import Extractor

BASE = "https://api.intacct.com/ia/api/v1"
TOKEN_URL = f"{BASE}/oauth2/token"
MCP_ENV: dict = {}  # AI Gateway is remote; authenticate in the agent's MCP UI.

OBJECTS = {
    "accounts": ("general-ledger/account", None),
    "journals": ("general-ledger/journal", None),
    "gl_lines": ("general-ledger/journal-entry-line", ("entryDate", "postingDate", "glEntryDate")),
    "journal_entries": ("general-ledger/journal-entry", ("postingDate", "entryDate")),
    "customers": ("accounts-receivable/customer", None),
    "vendors": ("accounts-payable/vendor", None),
    "ar_invoices": ("accounts-receivable/invoice", ("invoiceDate", "createdDate")),
    "ar_payments": ("accounts-receivable/payment", ("receiptDate", "paymentDate")),
    "ap_bills": ("accounts-payable/bill", ("createdDate", "billDate")),
    "ap_payments": ("accounts-payable/payment", ("paymentDate",)),
    "departments": ("company-config/department", None),
    "locations": ("company-config/location", None),
    "classes": ("company-config/class", None),
    "employees": ("company-config/employee", None),
}


def auth(book) -> None:
    s = book.slug
    vault.prompt(s, "intacct_client_id", "Client ID", secret=False)
    vault.prompt(s, "intacct_client_secret", "Client Secret")
    company = input("Company ID: ").strip()
    vault.prompt(s, "intacct_user", "Web Services user ID", secret=False)
    book.set(company_id=company)
    Client(book).token()
    print("Connected.")


class Client:
    def __init__(self, book):
        self.s, self.company = book.slug, book.config["company_id"]
        self._token, self._exp = None, 0.0

    def token(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        tok = request("POST", TOKEN_URL, allow_post=True, json={
            "grant_type": "client_credentials",
            "client_id": vault.get(self.s, "intacct_client_id"),
            "client_secret": vault.get(self.s, "intacct_client_secret"),
            "username": f"{vault.get(self.s, 'intacct_user')}@{self.company}"}).json()
        self._token, self._exp = tok["access_token"], time.time() + int(tok.get("expires_in", 3600))
        return self._token

    def _h(self):
        return {"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}

    def fields(self, obj: str):
        model = request("GET", f"{BASE}/services/core/model", params={"name": obj}, headers=self._h()).json()
        f = (model.get("ia::result") or {}).get("fields") or {}
        return list(f) if f else ["key", "id"]

    def query(self, obj: str, fields, filters=None):
        out, start = [], 1
        while True:
            body = {"object": obj, "fields": fields, "start": start, "size": 1000}
            if filters:
                body["filters"] = filters
            rows = request("POST", f"{BASE}/services/core/query", allow_post=True, json=body, headers=self._h()).json()
            rows = rows.get("ia::result", [])
            out += rows
            if len(rows) < 1000:
                return out
            start += 1000


def extract(book, start, end) -> None:
    c, x = Client(book), Extractor(book, start, end)
    for name, (obj, date_fields) in OBJECTS.items():
        def fetch(obj=obj, date_fields=date_fields):
            fields = c.fields(obj)
            date_field = next((d for d in date_fields or () if d in fields), None)
            filters = [{"$gte": {date_field: start.isoformat()}}, {"$lte": {date_field: end.isoformat()}}] if date_field else None
            return c.query(obj, fields, filters)
        x.run(name, fetch)
    x.finish()


def _flat(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def _pick(d, *names):
    for n in names:
        if d.get(n) not in (None, ""):
            return d[n]
    return ""


def normalize(book) -> None:
    raw, out = book.dir("raw"), book.dir("normalized")
    accounts = [_flat(a) for a in load_json(raw / "accounts.json") or []]

    def acct_class(a):
        cat = str(_pick(a, "category", "accountCategory")).lower()
        if "equity" in cat or "retained" in cat:
            return "equity"
        income_stmt = "income" in str(_pick(a, "accountType")).lower()
        credit = str(_pick(a, "normalBalance")).lower() == "credit"
        return ("income" if credit else "expense") if income_stmt else ("liability" if credit else "asset")

    write_csv(out / "accounts.csv", ACCOUNT_COLUMNS, ({
        "account_id": _pick(a, "id", "key"), "number": _pick(a, "id"), "name": _pick(a, "name", "title"),
        "full_name": _pick(a, "name", "title"), "erp_type": _pick(a, "accountType"), "erp_subtype": _pick(a, "category"),
        "class": acct_class(a), "role": "other", "parent_id": "", "active": _pick(a, "status") != "inactive", "balance": "",
    } for a in accounts))

    warned = set()

    def rows():
        for r in load_json(raw / "gl_lines.json") or []:
            f = _flat(r)
            amount = num(_pick(f, "baseAmount", "txnAmount", "amount"))
            direction = str(_pick(f, "txnType", "debitCredit")).lower()
            sign = -1 if direction in ("credit", "-1") else 1
            line = {
                "date": str(_pick(f, "entryDate", "postingDate", "glEntryDate"))[:10],
                "txn_id": _pick(f, "journalEntry.id", "journalEntry.key", "glJournalEntry.key", "recordNumber"),
                "txn_type": _pick(f, "journalEntry.journal.id", "journal.id", "sourceModule", "module"),
                "doc_num": _pick(f, "documentId", "document", "journalEntry.documentNumber"),
                "line_no": _pick(f, "lineNumber", "key"),
                "account_id": _pick(f, "glAccount.id", "account.id", "glAccount.key"),
                "account_number": _pick(f, "glAccount.id", "account.id"),
                "account_name": _pick(f, "glAccount.name", "account.name"),
                "debit": amount if sign > 0 else 0, "credit": amount if sign < 0 else 0,
                "memo": _pick(f, "description", "memo"),
                "counterparty": _pick(f, "dimensions.vendor.name", "dimensions.customer.name", "dimensions.employee.name"),
                "counterparty_type": "vendor" if f.get("dimensions.vendor.name") else "customer" if f.get("dimensions.customer.name")
                else "employee" if f.get("dimensions.employee.name") else "",
                "dimensions": ";".join(f"{k.split('.')[1]}={v}" for k, v in f.items()
                                       if k.startswith("dimensions.") and k.endswith(".name") and v
                                       and k.split(".")[1] not in ("vendor", "customer", "employee")),
                "created_date": str(_pick(f, "audit.createdDateTime", "whenCreated"))[:10],
                "is_adjusting": "",
            }
            for key in ("date", "account_id", "txn_id"):
                if not line[key] and key not in warned:
                    warned.add(key)
                    print(f"WARNING: could not map '{key}' from Intacct fields; edit engine/erp/intacct.py candidates. "
                          f"Available: {sorted(f)[:40]}")
            yield line

    n = write_csv(out / "gl_lines.csv", GL_COLUMNS, rows())
    (out / "erp_settings.json").write_text(json.dumps({"company_id": book.config.get("company_id")}))
    print(f"Normalized {len(accounts)} accounts, {n} GL lines.")
