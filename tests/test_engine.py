"""Offline tests with synthetic data (no ERP access). Run: python -m unittest"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import books, mail
from engine.erp import qbo, xero
from engine.http import ReadOnlyViolation, request
from engine.profile import profile
from engine.schema import read_csv


class BookCase(unittest.TestCase):
    erp = "qbo"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(books, "BOOKS_DIR", Path(self.tmp.name))
        self.patch.start()
        self.book = books.create("acme", self.erp)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def write_raw(self, name, data):
        (self.book.dir("raw") / f"{name}.json").write_text(json.dumps(data))


def col(v, id=None):
    return {"value": v, **({"id": id} if id else {})}


class TestQbo(BookCase):
    def test_normalize_and_profile(self):
        self.write_raw("account", [
            {"Id": "1", "Name": "Checking", "FullyQualifiedName": "Checking", "AccountType": "Bank", "Classification": "Asset", "Active": True},
            {"Id": "2", "Name": "Sales", "FullyQualifiedName": "Sales", "AccountType": "Income", "Classification": "Revenue", "Active": True},
            {"Id": "3", "Name": "Software", "FullyQualifiedName": "Software", "AccountType": "Expense", "Classification": "Expense", "Active": True},
            {"Id": "4", "Name": "Office Supplies", "FullyQualifiedName": "Office Supplies", "AccountType": "Expense", "Classification": "Expense", "Active": True},
            {"Id": "5", "Name": "Ask My Accountant", "FullyQualifiedName": "Ask My Accountant", "AccountType": "Expense", "Classification": "Expense", "Active": True},
            {"Id": "6", "Name": "Owner Loan", "FullyQualifiedName": "Owner Loan", "AccountType": "Income", "Classification": "Revenue", "Active": True},
        ])
        self.write_raw("vendor", [{"DisplayName": "Adobe"}])
        self.write_raw("customer", [{"DisplayName": "Client Co"}])
        keys = ["tx_date", "txn_type", "doc_num", "name", "memo", "account_name", "klass_name", "dept_name", "debt_amt", "credt_amt", "create_date", "is_adj"]
        columns = {"Column": [{"ColTitle": k, "MetaData": [{"Name": "ColKey", "Value": k}]} for k in keys]}

        def row(d, t, tid, name, debit, credit):
            return {"type": "Data", "ColData": [col(d), col(t, tid), col(""), col(name), col(""), col(""), col(""), col(""),
                                                 col(debit), col(credit), col(d + "T10:00:00"), col("No")]}

        def section(aid, aname, rows):
            return {"type": "Section", "Header": {"ColData": [col(aname, aid)]}, "Rows": {"Row": rows}}

        lines = {"1": [], "2": [], "3": [], "4": [], "5": []}
        for m in range(1, 5):  # Adobe coded to Software 3x, Office Supplies 1x -> inconsistent
            acct = "3" if m < 4 else "4"
            d = f"2025-0{m}-15"
            lines[acct].append(row(d, "Expense", f"e{m}", "Adobe", "54.99", ""))
            lines["1"].append(row(d, "Expense", f"e{m}", "Adobe", "", "54.99"))
            lines["2"].append(row(d, "Deposit", f"d{m}", "Client Co", "", "1000.00"))
            lines["1"].append(row(d, "Deposit", f"d{m}", "Client Co", "1000.00", ""))
        lines["5"].append(row("2025-02-01", "Expense", "x1", "", "250.00", ""))
        lines["1"].append(row("2025-02-01", "Expense", "x1", "", "", "250.00"))
        names = {"1": "Checking", "2": "Sales", "3": "Software", "4": "Office Supplies", "5": "Ask My Accountant"}
        report = {"Columns": columns, "Rows": {"Row": [section(a, names[a], r) for a, r in lines.items()]}}
        self.write_raw("gl", [report])
        self.write_raw("preferences", {"Preferences": {"ReportPrefs": {"ReportBasis": "Cash"}}})

        qbo.normalize(self.book)
        gl = read_csv(self.book.path / "normalized" / "gl_lines.csv")
        self.assertEqual(len(gl), 18)
        self.assertEqual({r["counterparty_type"] for r in gl if r["counterparty"] == "Adobe"}, {"vendor"})

        sig = profile(self.book)
        self.assertEqual(sig["erp_settings_excerpt"]["ReportPrefs.ReportBasis"], "Cash")
        self.assertEqual(sig["basis"]["income_txns_direct_to_bank"], 1.0)
        self.assertEqual(sig["inconsistent_counterparties"], 1)
        kinds = sig["anomaly_counts"]
        self.assertIn("suspense_or_clearing_balance", kinds)
        self.assertIn("name_type_mismatch", kinds)       # Owner Loan typed as income
        self.assertNotIn("unbalanced_transaction", kinds)
        self.assertTrue((self.book.path / "analysis" / "summary.md").exists())


class TestXero(BookCase):
    erp = "xero"

    def test_journals(self):
        (self.book.dir("raw") / "_manifest.json").write_text(json.dumps({"start": "2025-01-01", "end": "2025-12-31"}))
        self.write_raw("accounts", [{"AccountID": "a", "Code": "200", "Name": "Sales", "Type": "REVENUE", "Class": "REVENUE", "Status": "ACTIVE"},
                                    {"AccountID": "b", "Code": "610", "Name": "Accounts Receivable", "Type": "CURRENT", "Class": "ASSET",
                                     "Status": "ACTIVE", "SystemAccount": "DEBTORS"}])
        self.write_raw("invoices", [{"InvoiceID": "inv1", "Type": "ACCREC", "InvoiceNumber": "INV-1", "Contact": {"Name": "Client Co"}}])
        self.write_raw("journals", [{"JournalID": "j1", "JournalNumber": 1, "JournalDate": "/Date(1736899200000+0000)/",
                                     "CreatedDateUTC": "/Date(1736899200000)/", "SourceID": "inv1", "SourceType": "ACCREC",
                                     "JournalLines": [{"AccountID": "b", "AccountCode": "610", "AccountName": "AR", "NetAmount": 500},
                                                      {"AccountID": "a", "AccountCode": "200", "AccountName": "Sales", "NetAmount": -500,
                                                       "TrackingCategories": [{"Name": "Region", "Option": "North"}]}]}])
        xero.normalize(self.book)
        gl = read_csv(self.book.path / "normalized" / "gl_lines.csv")
        self.assertEqual([r["date"] for r in gl], ["2025-01-15"] * 2)
        self.assertEqual(gl[1]["dimensions"], "Region=North")
        self.assertEqual(gl[0]["counterparty_type"], "customer")
        self.assertEqual(profile(self.book)["basis"]["income_txns_via_ar"], 1.0)


class TestGuards(BookCase):
    def test_http_is_read_only(self):
        with self.assertRaises(ReadOnlyViolation):
            request("POST", "https://example.com/v3/company/1/invoice")
        with self.assertRaises(ReadOnlyViolation):
            request("DELETE", "https://example.com/x")

    def test_email_allowlist_and_content(self):
        (self.book.path / "context" / "contacts.csv").write_text(
            "name,email,organization,relationship,topics,can_email,notes\nPat,pat@acme.test,Acme,employee,receipts,yes,\n"
            "Lee,lee@acme.test,Acme,employee,,no,\n")
        ok = {"to": ["pat@acme.test"], "subject": "s", "body": "Receipt for 03/04 Delta $612.40 please", "reason": "Q-1"}
        self.assertEqual(mail.validate(self.book, ok), [])
        self.assertTrue(mail.validate(self.book, {**ok, "to": ["lee@acme.test"]}))
        self.assertTrue(mail.validate(self.book, {**ok, "body": "send your password"}))

    def test_send_requires_approval(self):
        (self.book.path / "context" / "contacts.csv").write_text("name,email,can_email\nPat,pat@acme.test,yes\n")
        self.book.set(email_from="Books <b@acme.test>")
        (self.book.dir("outbox") / "d1.json").write_text(json.dumps(
            {"to": ["pat@acme.test"], "subject": "s", "body": "b", "reason": "r"}))
        with mock.patch("sys.stdin.isatty", return_value=False), mock.patch.object(mail, "request") as req:
            with self.assertRaises(SystemExit):
                mail.send(self.book, "d1")
            req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
