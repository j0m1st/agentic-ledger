"""QuickBooks Online (Accounting API v3)."""
from __future__ import annotations

import json
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse

from .. import vault
from ..http import request
from ..schema import ACCOUNT_COLUMNS, GL_COLUMNS, load_json, num, write_csv
from . import Extractor, month_ranges

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API_BASE = {"production": "https://quickbooks.api.intuit.com", "sandbox": "https://sandbox-quickbooks.api.intuit.com"}
SCOPE = "com.intuit.quickbooks.accounting"
MINOR_VERSION = "75"

# Env names for intuit/quickbooks-online-mcp-server (check its README).
MCP_ENV = {
    "QUICKBOOKS_CLIENT_ID": "qbo_client_id",
    "QUICKBOOKS_CLIENT_SECRET": "qbo_client_secret",
    "QUICKBOOKS_REFRESH_TOKEN": "qbo_refresh_token",
    "QUICKBOOKS_REALM_ID": "qbo_realm_id",
    "QUICKBOOKS_ENVIRONMENT": "qbo_environment",
}

TXN_ENTITIES = ["Invoice", "SalesReceipt", "Payment", "CreditMemo", "RefundReceipt", "Deposit",
                "Bill", "BillPayment", "VendorCredit", "Purchase", "JournalEntry", "Transfer"]
LIST_ENTITIES = ["Account", "Class", "Department", "Term", "Customer", "Vendor", "Employee", "Item", "TaxCode"]
GL_COLUMN_KEYS = "tx_date,txn_type,doc_num,name,memo,account_name,klass_name,dept_name,debt_amt,credt_amt,create_date,is_adj"


def auth(book) -> None:
    s = book.slug
    cid = vault.prompt(s, "qbo_client_id", "Intuit app Client ID", secret=False)
    csec = vault.prompt(s, "qbo_client_secret", "Intuit app Client Secret")
    env = (input("Environment [production/sandbox] (production): ").strip() or "production").lower()
    redirect = input("Redirect URI registered on the app: ").strip()
    state = secrets.token_urlsafe(16)
    print("\nOpen this URL, approve access, then paste the full URL you land on:\n")
    print(AUTH_URL + "?" + urlencode({"client_id": cid, "response_type": "code", "scope": SCOPE,
                                      "redirect_uri": redirect, "state": state}))
    q = parse_qs(urlparse(input("\nRedirected URL: ").strip()).query)
    if q.get("state", [""])[0] != state:
        raise SystemExit("State mismatch: aborting (possible CSRF or wrong URL).")
    tok = request("POST", TOKEN_URL, allow_post=True, auth=(cid, csec), headers={"Accept": "application/json"},
                  data={"grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": redirect}).json()
    vault.put(s, "qbo_refresh_token", tok["refresh_token"])
    vault.put(s, "qbo_realm_id", q["realmId"][0])
    vault.put(s, "qbo_environment", env)
    book.set(environment=env)
    print("Connected. Refresh token stored in keychain.")


class Client:
    def __init__(self, book):
        self.s = book.slug
        self.realm = vault.get(self.s, "qbo_realm_id")
        self.base = API_BASE[vault.get(self.s, "qbo_environment", required=False) or "production"]
        self._token, self._exp = None, 0.0

    def token(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        tok = request("POST", TOKEN_URL, allow_post=True, headers={"Accept": "application/json"},
                      auth=(vault.get(self.s, "qbo_client_id"), vault.get(self.s, "qbo_client_secret")),
                      data={"grant_type": "refresh_token", "refresh_token": vault.get(self.s, "qbo_refresh_token")}).json()
        vault.put(self.s, "qbo_refresh_token", tok["refresh_token"])  # rotates on every refresh
        self._token, self._exp = tok["access_token"], time.time() + tok["expires_in"]
        return self._token

    def get(self, path: str, **params):
        params.setdefault("minorversion", MINOR_VERSION)
        return request("GET", f"{self.base}/v3/company/{self.realm}/{path}", params=params,
                       headers={"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}).json()

    def query(self, entity: str, where: str = ""):
        out, pos = [], 1
        while True:
            q = f"select * from {entity}{where} startposition {pos} maxresults 1000"
            rows = self.get("query", query=q)["QueryResponse"].get(entity, [])
            out += rows
            if len(rows) < 1000:
                return out
            pos += 1000


def extract(book, start, end) -> None:
    c, x = Client(book), Extractor(book, start, end)
    s, e = start.isoformat(), end.isoformat()
    x.run("preferences", lambda: c.get("preferences"))   # ReportBasis, closing date, class/location tracking
    x.run("company_info", lambda: c.get(f"companyinfo/{c.realm}"))
    for ent in LIST_ENTITIES:
        x.run(ent.lower(), lambda ent=ent: c.query(ent))
    for ent in TXN_ENTITIES:
        x.run(ent.lower(), lambda ent=ent: c.query(ent, f" where TxnDate >= '{s}' and TxnDate <= '{e}'"))
    for basis in ("Accrual", "Cash"):
        x.run(f"report_trial_balance_{basis.lower()}", lambda b=basis: c.get("reports/TrialBalance", start_date=s, end_date=e, accounting_method=b))
        x.run(f"report_pnl_monthly_{basis.lower()}", lambda b=basis: c.get("reports/ProfitAndLoss", start_date=s, end_date=e, accounting_method=b, summarize_column_by="Month"))
    x.run("report_balance_sheet", lambda: c.get("reports/BalanceSheet", start_date=s, end_date=e, summarize_column_by="Year"))
    x.run("report_aged_receivables", lambda: c.get("reports/AgedReceivableDetail", report_date=e))
    x.run("report_aged_payables", lambda: c.get("reports/AgedPayableDetail", report_date=e))
    x.run("gl", lambda: [c.get("reports/GeneralLedger", start_date=a.isoformat(), end_date=b.isoformat(),
                                 accounting_method="Accrual", columns=GL_COLUMN_KEYS)
                           for a, b in month_ranges(start, end)])
    x.finish()


CLASS_MAP = {"Asset": "asset", "Liability": "liability", "Equity": "equity", "Revenue": "income", "Expense": "expense"}
ROLE_MAP = {"Accounts Receivable": "ar", "Accounts Payable": "ap", "Bank": "bank", "Credit Card": "credit_card"}


def _walk(rows, acct):
    for r in (rows or {}).get("Row", []):
        if "Header" in r or r.get("type") == "Section":
            h = (r.get("Header", {}).get("ColData") or [{}])[0]
            yield from _walk(r.get("Rows"), {"id": h.get("id"), "name": h.get("value")} if h.get("id") else acct)
        elif "ColData" in r:
            yield acct, r["ColData"]


def normalize(book) -> None:
    raw, out = book.dir("raw"), book.dir("normalized")
    accounts = load_json(raw / "account.json") or []
    by_id = {a["Id"]: a for a in accounts}
    write_csv(out / "accounts.csv", ACCOUNT_COLUMNS, ({
        "account_id": a["Id"], "number": a.get("AcctNum", ""), "name": a.get("Name"),
        "full_name": a.get("FullyQualifiedName"), "erp_type": a.get("AccountType"),
        "erp_subtype": a.get("AccountSubType"), "class": CLASS_MAP.get(a.get("Classification"), ""),
        "role": ROLE_MAP.get(a.get("AccountType"), "other"), "parent_id": (a.get("ParentRef") or {}).get("value", ""),
        "active": a.get("Active"), "balance": a.get("CurrentBalance"),
    } for a in accounts))

    vendors = {v["DisplayName"] for v in load_json(raw / "vendor.json") or []}
    customers = {v["DisplayName"] for v in load_json(raw / "customer.json") or []}
    employees = {v["DisplayName"] for v in load_json(raw / "employee.json") or []}

    def rows():
        for report in load_json(raw / "gl.json") or []:
            keys = [next((m["Value"] for m in col.get("MetaData", []) if m["Name"] == "ColKey"), col.get("ColTitle"))
                    for col in report.get("Columns", {}).get("Column", [])]
            for i, (acct, cols) in enumerate(_walk(report.get("Rows"), None)):
                d = {k: (cd.get("value") or "") for k, cd in zip(keys, cols)}
                ids = {k: cd.get("id") for k, cd in zip(keys, cols)}
                if not acct or not d.get("tx_date") or not d["tx_date"][:4].isdigit():
                    continue  # beginning balance / totals
                a = by_id.get(acct["id"], {})
                name = d.get("name", "")
                dims = ";".join(f"{k}={d[f]}" for k, f in (("Class", "klass_name"), ("Department", "dept_name")) if d.get(f))
                yield {
                    "date": d["tx_date"], "txn_id": ids.get("txn_type") or "", "txn_type": d.get("txn_type"),
                    "doc_num": d.get("doc_num"), "line_no": i, "account_id": acct["id"],
                    "account_number": a.get("AcctNum", ""), "account_name": a.get("FullyQualifiedName", acct["name"]),
                    "debit": num(d.get("debt_amt")), "credit": num(d.get("credt_amt")), "memo": d.get("memo"),
                    "counterparty": name, "counterparty_type": "vendor" if name in vendors else "customer" if name in customers
                    else "employee" if name in employees else ("other" if name else ""),
                    "dimensions": dims, "created_date": (d.get("create_date") or "")[:10],
                    "is_adjusting": {"Yes": "true", "No": "false"}.get(d.get("is_adj", ""), ""),
                }

    n = write_csv(out / "gl_lines.csv", GL_COLUMNS, rows())
    prefs = load_json(raw / "preferences.json") or {}
    (out / "erp_settings.json").write_text(json.dumps(prefs.get("Preferences", prefs), indent=1))
    print(f"Normalized {len(accounts)} accounts, {n} GL lines.")


# --- writes (only via engine.changes, after approval) ------------------------
VOIDABLE = {"Invoice", "Payment", "SalesReceipt", "BillPayment"}
NOTE_FIELD = {"Customer": "Notes", "Vendor": "Notes", "Employee": "Notes", "Account": "Description", "Item": "Description"}
UNSIGNABLE = {"Class", "Department", "Term", "TaxCode"}
DATE_FIELDS = ("TxnDate",)


def write_client(book):
    return Client(book)


def fetch(c, entity, rid):
    return c.get(f"{entity.lower()}/{rid}")[entity]


def _append(text, tag):
    text = text or ""
    return text if tag in text else f"{text} {tag}".strip()


def sign(op, before, tag) -> str:
    entity, payload = op["entity"], op.setdefault("payload", {})
    if entity in UNSIGNABLE:
        return "audit log only (no memo field)"
    field = NOTE_FIELD.get(entity, "PrivateNote")
    payload[field] = _append(payload.get(field, (before or {}).get(field)), tag)
    if entity == "JournalEntry" and op["op"] == "create":
        for line in payload.get("Line", []):  # line Description is the GL "memo" column
            line["Description"] = _append(line.get("Description"), tag)
        return f"{field} + every line Description"
    return field


def check(op) -> list:
    errors = []
    if op["op"] == "void" and op["entity"] not in VOIDABLE:
        errors.append(f"QBO cannot void {op['entity']}; propose a reversing JournalEntry or credit instead")
    if op["entity"] == "JournalEntry" and op.get("payload", {}).get("Line"):
        side = {"Debit": 0.0, "Credit": 0.0}
        for line in op["payload"]["Line"]:
            d = line.get("JournalEntryLineDetail", {})
            side[d.get("PostingType", "Debit")] += num(line.get("Amount"))
        if abs(side["Debit"] - side["Credit"]) > 0.005:
            errors.append(f"Journal entry unbalanced: debits {side['Debit']:.2f} vs credits {side['Credit']:.2f}")
    return errors


def apply(c, op, grant) -> str:
    entity, path = op["entity"], op["entity"].lower()
    url = f"{c.base}/v3/company/{c.realm}/{path}"
    h = lambda: {"Authorization": f"Bearer {c.token()}", "Accept": "application/json"}
    p = {"minorversion": MINOR_VERSION}
    if op["op"] == "create":
        return request("POST", url, grant=grant, params=p, headers=h(), json=op["payload"]).json()[entity]["Id"]
    current = fetch(c, entity, op["id"])
    body = {"Id": op["id"], "SyncToken": current["SyncToken"], "sparse": True, **op.get("payload", {})}
    updated = request("POST", url, grant=grant, params=p, headers=h(), json=body).json()[entity]
    if op["op"] == "void":  # memo signed by the sparse update above, then void
        request("POST", url, grant=grant, params={**p, "operation": "void"}, headers=h(),
                json={"Id": op["id"], "SyncToken": updated["SyncToken"]})
    return op["id"]
