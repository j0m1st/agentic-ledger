"""NetSuite REST (SuiteQL) via OAuth 2.0 client credentials (M2M, certificate-signed JWT)."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from .. import vault
from ..http import request
from ..schema import ACCOUNT_COLUMNS, GL_COLUMNS, load_json, num, write_csv
from . import Extractor, month_ranges

MCP_ENV: dict = {}  # AI Connector Service is remote + OAuth; no local secrets needed.

GL_SQL = """
SELECT t.id AS txn_id, TO_CHAR(t.trandate, 'YYYY-MM-DD') AS trandate, t.type, t.tranid,
       TO_CHAR(t.createddate, 'YYYY-MM-DD') AS createddate, t.memo AS tmemo,
       tal.transactionline AS line_no, tal.account, a.acctnumber, a.fullname AS acctname,
       tal.debit, tal.credit, tl.memo AS lmemo,
       BUILTIN.DF(t.entity) AS entity_name, e.type AS entity_type,
       BUILTIN.DF(tl.class) AS class_name, BUILTIN.DF(tl.department) AS dept_name,
       BUILTIN.DF(tl.location) AS loc_name, BUILTIN.DF(tl.subsidiary) AS sub_name
FROM transactionaccountingline tal
JOIN transaction t ON t.id = tal.transaction
JOIN transactionline tl ON tl.transaction = tal.transaction AND tl.id = tal.transactionline
JOIN account a ON a.id = tal.account
LEFT JOIN entity e ON e.id = t.entity
WHERE tal.posting = 'T' {book_filter}
  AND t.trandate BETWEEN TO_DATE('{start}', 'YYYY-MM-DD') AND TO_DATE('{end}', 'YYYY-MM-DD')
ORDER BY t.trandate, t.id, tal.transactionline
"""
PRIMARY_BOOK = "AND tal.accountingbook = (SELECT id FROM accountingbook WHERE isprimary = 'T')"

REFERENCE_TABLES = ["account", "accountingperiod", "subsidiary", "classification", "department", "location",
                    "term", "currency", "customer", "vendor", "employee"]


def auth(book) -> None:
    s = book.slug
    account = input("NetSuite account ID (e.g. 1234567 or 1234567_SB1): ").strip()
    vault.prompt(s, "ns_client_id", "Integration Client ID", secret=False)
    vault.prompt(s, "ns_certificate_id", "M2M Certificate ID", secret=False)
    key_path = input("Path to private key PEM: ").strip()
    vault.put(s, "ns_private_key", Path(key_path).expanduser().read_text())
    book.set(account_id=account)
    Client(book).token()
    print(f"Connected. Key stored in keychain. Now delete {key_path}.")


class Client:
    def __init__(self, book):
        self.s = book.slug
        host = book.config["account_id"].lower().replace("_", "-")
        self.base = f"https://{host}.suitetalk.api.netsuite.com/services/rest"
        self._token, self._exp = None, 0.0

    def token(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        import jwt
        url = f"{self.base}/auth/oauth2/v1/token"
        now = int(time.time())
        assertion = jwt.encode(
            {"iss": vault.get(self.s, "ns_client_id"), "scope": ["rest_webservices"], "aud": url,
             "iat": now, "exp": now + 3600, "jti": str(uuid.uuid4())},
            vault.get(self.s, "ns_private_key"), algorithm="PS256",
            headers={"kid": vault.get(self.s, "ns_certificate_id"), "typ": "JWT"})
        tok = request("POST", url, allow_post=True, data={
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion}).json()
        self._token, self._exp = tok["access_token"], time.time() + int(tok.get("expires_in", 3600))
        return self._token

    def suiteql(self, q: str):
        out, offset = [], 0
        while True:
            page = request("POST", f"{self.base}/query/v1/suiteql", allow_post=True, json={"q": q},
                           params={"limit": 1000, "offset": offset},
                           headers={"Authorization": f"Bearer {self.token()}", "Prefer": "transient"}).json()
            out += page.get("items", [])
            if not page.get("hasMore"):
                return out
            offset += 1000


def extract(book, start, end) -> None:
    c, x = Client(book), Extractor(book, start, end)
    for t in REFERENCE_TABLES:
        x.run(t, lambda t=t: c.suiteql(f"SELECT * FROM {t}"))
    x.run("txn_type_counts", lambda: c.suiteql(
        f"SELECT type, TO_CHAR(trandate,'YYYY') AS yr, COUNT(*) AS n FROM transaction "
        f"WHERE trandate >= TO_DATE('{start}','YYYY-MM-DD') GROUP BY type, TO_CHAR(trandate,'YYYY')"))

    def gl():
        rows, book_filter = [], PRIMARY_BOOK
        for a, b in month_ranges(start, end):  # monthly chunks stay under SuiteQL's 100k row cap
            try:
                rows += c.suiteql(GL_SQL.format(book_filter=book_filter, start=a, end=b))
            except RuntimeError:
                if not book_filter:
                    raise
                book_filter = ""  # account without Multi-Book: retry without the filter
                rows += c.suiteql(GL_SQL.format(book_filter="", start=a, end=b))
        return rows
    x.run("gl", gl)
    x.finish()


CLASS_MAP = {"AcctRec": "asset", "Bank": "asset", "FixedAsset": "asset", "OthAsset": "asset", "OthCurrAsset": "asset",
             "DeferExpense": "asset", "UnbilledRec": "asset", "AcctPay": "liability", "CredCard": "liability",
             "LongTermLiab": "liability", "OthCurrLiab": "liability", "DeferRevenue": "liability", "Equity": "equity",
             "Income": "income", "OthIncome": "income", "COGS": "expense", "Expense": "expense", "OthExpense": "expense"}
ROLE_MAP = {"AcctRec": "ar", "AcctPay": "ap", "Bank": "bank", "CredCard": "credit_card"}
ENTITY_TYPES = {"CustJob": "customer", "Vendor": "vendor", "Employee": "employee"}


def normalize(book) -> None:
    raw, out = book.dir("raw"), book.dir("normalized")
    accounts = load_json(raw / "account.json") or []
    write_csv(out / "accounts.csv", ACCOUNT_COLUMNS, ({
        "account_id": a.get("id"), "number": a.get("acctnumber", ""), "name": a.get("accountsearchdisplaynamecopy") or a.get("fullname"),
        "full_name": a.get("fullname"), "erp_type": a.get("accttype"), "erp_subtype": a.get("sspecacct", ""),
        "class": CLASS_MAP.get(a.get("accttype"), ""), "role": ROLE_MAP.get(a.get("accttype"), "other"),
        "parent_id": a.get("parent", ""), "active": a.get("isinactive") != "T", "balance": "",
    } for a in accounts))

    def rows():
        for r in load_json(raw / "gl.json") or []:
            dims = ";".join(f"{k}={r[f]}" for k, f in (("Subsidiary", "sub_name"), ("Class", "class_name"),
                            ("Department", "dept_name"), ("Location", "loc_name")) if r.get(f))
            yield {
                "date": r.get("trandate"), "txn_id": r.get("txn_id"), "txn_type": r.get("type"), "doc_num": r.get("tranid"),
                "line_no": r.get("line_no"), "account_id": r.get("account"), "account_number": r.get("acctnumber"),
                "account_name": r.get("acctname"), "debit": num(r.get("debit")), "credit": num(r.get("credit")),
                "memo": r.get("lmemo") or r.get("tmemo"), "counterparty": r.get("entity_name"),
                "counterparty_type": ENTITY_TYPES.get(r.get("entity_type"), "other" if r.get("entity_name") else ""),
                "dimensions": dims, "created_date": r.get("createddate"),
                "is_adjusting": "true" if r.get("type") == "Journal" else "false",
            }

    n = write_csv(out / "gl_lines.csv", GL_COLUMNS, rows())
    print(f"Normalized {len(accounts)} accounts, {n} GL lines.")
