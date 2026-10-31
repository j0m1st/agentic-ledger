"""Xero Accounting API via a Custom Connection (client_credentials)."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from .. import vault
from ..http import request
from ..schema import ACCOUNT_COLUMNS, GL_COLUMNS, load_json, num, write_csv
from . import Extractor

TOKEN_URL = "https://identity.xero.com/connect/token"
API = "https://api.xero.com/api.xro/2.0"

MCP_ENV = {"XERO_CLIENT_ID": "xero_client_id", "XERO_CLIENT_SECRET": "xero_client_secret"}


def auth(book) -> None:
    vault.prompt(book.slug, "xero_client_id", "Custom Connection Client ID", secret=False)
    vault.prompt(book.slug, "xero_client_secret", "Custom Connection Client Secret")
    org = Client(book).get("Organisation")["Organisations"][0]
    book.set(organisation=org.get("Name"), country=org.get("CountryCode"), base_currency=org.get("BaseCurrency"))
    print(f"Connected to {org.get('Name')}.")


class Client:
    def __init__(self, book):
        self.s = book.slug
        self._token, self._exp = None, 0.0

    def token(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        # Scopes come from the connection itself; omit `scope` to receive all granted (read-only) scopes.
        tok = request("POST", TOKEN_URL, allow_post=True, data={"grant_type": "client_credentials"},
                      auth=(vault.get(self.s, "xero_client_id"), vault.get(self.s, "xero_client_secret"))).json()
        self._token, self._exp = tok["access_token"], time.time() + tok["expires_in"]
        return self._token

    def get(self, path: str, **params):
        return request("GET", f"{API}/{path}", params=params,
                       headers={"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}).json()

    def paged(self, path: str, key: str, **params):
        out, page = [], 1
        while True:
            rows = self.get(path, page=page, pageSize=1000, **params).get(key, [])
            if not rows:
                return out
            out += rows
            page += 1

    def journals(self):
        out, offset = [], 0
        while True:
            rows = self.get("Journals", offset=offset).get("Journals", [])
            if not rows:
                return out
            out += rows
            offset = rows[-1]["JournalNumber"]


def extract(book, start, end) -> None:
    c, x = Client(book), Extractor(book, start, end)
    where = f"Date>=DateTime({start:%Y,%m,%d}) AND Date<=DateTime({end:%Y,%m,%d})"
    s, e = start.isoformat(), end.isoformat()
    x.run("organisation", lambda: c.get("Organisation"))
    x.run("accounts", lambda: c.get("Accounts")["Accounts"])
    x.run("tracking_categories", lambda: c.get("TrackingCategories", includeArchived="true")["TrackingCategories"])
    x.run("tax_rates", lambda: c.get("TaxRates")["TaxRates"])
    x.run("contacts", lambda: c.paged("Contacts", "Contacts", includeArchived="true"))
    x.run("items", lambda: c.get("Items")["Items"])
    for path in ("Invoices", "CreditNotes", "BankTransactions", "ManualJournals", "Payments", "Prepayments", "Overpayments"):
        x.run(path.lower(), lambda p=path: c.paged(p, p, where=where))
    x.run("journals", c.journals)  # full GL; needs accounting.journals.read
    x.run("report_trial_balance", lambda: c.get("Reports/TrialBalance", date=e))
    x.run("report_pnl_monthly", lambda: c.get("Reports/ProfitAndLoss", fromDate=s, toDate=e, timeframe="MONTH"))
    x.run("report_balance_sheet", lambda: c.get("Reports/BalanceSheet", date=e))
    x.run("report_bank_summary", lambda: c.get("Reports/BankSummary", fromDate=s, toDate=e))
    x.finish()


def xdate(value: str) -> str:
    """'/Date(1704067200000+0000)/' or ISO -> YYYY-MM-DD."""
    m = re.search(r"/Date\((-?\d+)", value or "")
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).date().isoformat()
    return (value or "")[:10]


CLASS_MAP = {"ASSET": "asset", "LIABILITY": "liability", "EQUITY": "equity", "REVENUE": "income", "EXPENSE": "expense"}
ROLE_MAP = {"DEBTORS": "ar", "CREDITORS": "ap"}


def normalize(book) -> None:
    raw, out = book.dir("raw"), book.dir("normalized")
    manifest = load_json(raw / "_manifest.json") or {}
    start, end = manifest.get("start", "0000"), manifest.get("end", "9999")
    accounts = load_json(raw / "accounts.json") or []
    write_csv(out / "accounts.csv", ACCOUNT_COLUMNS, ({
        "account_id": a["AccountID"], "number": a.get("Code", ""), "name": a.get("Name"), "full_name": a.get("Name"),
        "erp_type": a.get("Type"), "erp_subtype": a.get("SystemAccount", ""), "class": CLASS_MAP.get(a.get("Class"), ""),
        "role": "bank" if a.get("Type") == "BANK" and a.get("BankAccountType") != "CREDITCARD"
        else "credit_card" if a.get("BankAccountType") == "CREDITCARD" else ROLE_MAP.get(a.get("SystemAccount"), "other"),
        "parent_id": "", "active": a.get("Status") == "ACTIVE", "balance": "",
    } for a in accounts))

    # Journals carry no contact; resolve it through the source document.
    source = {}
    for name, id_key in (("invoices", "InvoiceID"), ("creditnotes", "CreditNoteID"), ("banktransactions", "BankTransactionID")):
        for d in load_json(raw / f"{name}.json") or []:
            kind = "customer" if d.get("Type", "").startswith(("ACCREC", "RECEIVE")) else "vendor"
            source[d[id_key]] = ((d.get("Contact") or {}).get("Name", ""), kind, d.get("InvoiceNumber") or d.get("Reference", ""))
    for p in load_json(raw / "payments.json") or []:
        inv = p.get("Invoice") or {}
        kind = "customer" if inv.get("Type") == "ACCREC" else "vendor"
        source[p["PaymentID"]] = ((inv.get("Contact") or {}).get("Name", ""), kind, p.get("Reference", ""))

    def rows():
        for j in load_json(raw / "journals.json") or []:
            d = xdate(j.get("JournalDate"))
            if not (start <= d <= end):
                continue
            who, kind, doc = source.get(j.get("SourceID"), ("", "", ""))
            for i, ln in enumerate(j.get("JournalLines", [])):
                amt = num(ln.get("NetAmount"))
                yield {
                    "date": d, "txn_id": j.get("SourceID") or j["JournalID"], "txn_type": j.get("SourceType"),
                    "doc_num": doc or j.get("Reference", ""), "line_no": i, "account_id": ln.get("AccountID"),
                    "account_number": ln.get("AccountCode"), "account_name": ln.get("AccountName"),
                    "debit": max(amt, 0), "credit": max(-amt, 0), "memo": ln.get("Description", ""),
                    "counterparty": who, "counterparty_type": kind if who else "",
                    "dimensions": ";".join(f"{t.get('Name')}={t.get('Option')}" for t in ln.get("TrackingCategories", [])),
                    "created_date": xdate(j.get("CreatedDateUTC")),
                    "is_adjusting": "true" if j.get("SourceType") == "MANJOURNAL" else "false",
                }

    n = write_csv(out / "gl_lines.csv", GL_COLUMNS, rows())
    org = (load_json(raw / "organisation.json") or {}).get("Organisations", [{}])[0]
    (out / "erp_settings.json").write_text(json.dumps(org, indent=1))
    print(f"Normalized {len(accounts)} accounts, {n} GL lines.")
