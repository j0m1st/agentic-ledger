"""Write protocol tests with a mocked ERP (no network)."""
import json
from unittest import mock

from engine import changes
from engine.erp import qbo, xero
from engine.http import OutcomeUnknown, ReadOnlyViolation, WriteGrant, request

from .test_engine import BookCase

BEFORE = {"Id": "123", "SyncToken": "4", "PrivateNote": "Adobe sub", "AccountRef": {"value": "4"}, "TxnDate": "2025-03-15"}


class TestChanges(BookCase):
    def setUp(self):
        super().setUp()
        self.book.set(writes_enabled=True)
        self.patches = [mock.patch.object(qbo, "write_client", return_value=object()),
                        mock.patch.object(qbo, "fetch", side_effect=lambda c, e, i: json.loads(json.dumps(BEFORE)))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def changeset(self, ops, cid="cs-1", mode="api"):
        (self.book.dir("changes") / f"{cid}.json").write_text(json.dumps({"title": "t", "mode": mode, "ops": ops}))
        return changes.ChangeSet(self.book, cid)

    def recode(self):
        return {"op": "update", "entity": "Purchase", "id": "123", "reason": "Q-004 recode to Software",
                "payload": {"AccountRef": {"value": "3"}}}

    def je(self, dr=100, cr=100):
        line = lambda t, a: {"Amount": a, "DetailType": "JournalEntryLineDetail",
                             "JournalEntryLineDetail": {"PostingType": t, "AccountRef": {"value": "1"}}}
        return {"op": "create", "entity": "JournalEntry", "reason": "accrue rent", "payload": {"TxnDate": "2025-06-30", "Line": [line("Debit", dr), line("Credit", cr)]}}

    def test_plan_signs_and_previews(self):
        plan = self.changeset([self.recode(), self.je()]).plan()
        self.assertEqual(plan["status"], "awaiting_approval")
        up, je = plan["ops"]
        self.assertEqual(up["payload"]["PrivateNote"], "Adobe sub [ag write/edit]")
        self.assertIn(["AccountRef.value", "4", "3"], up["diff"])
        self.assertTrue(all("[ag write/edit]" in l["Description"] for l in je["payload"]["Line"]))
        preview = (self.book.path / "changes" / "cs-1.preview.md").read_text()
        self.assertIn("🚨 PROPOSED CHANGES: NOTHING HAS BEEN WRITTEN YET", preview)
        self.assertIn(f"approve {plan['approval_code']}", preview)

    def test_blocks_unbalanced_delete_and_closed_period(self):
        self.book.set(lock_date="2025-12-31")
        plan = self.changeset([self.je(100, 90), {"op": "delete", "entity": "Bill", "id": "9", "reason": "x"}]).plan()
        self.assertEqual(plan["status"], "blocked")
        errs = " ".join(plan["ops"][0]["errors"])
        self.assertIn("unbalanced", errs)
        self.assertIn("closed period", errs)
        self.assertIn("hard delete", " ".join(plan["ops"][1]["errors"]))

    def test_approval_guards(self):
        cs = self.changeset([self.recode()])
        code = cs.plan()["approval_code"]
        with mock.patch.object(qbo, "apply") as ap:
            with self.assertRaises(SystemExit):
                cs.apply("wrongcode00")
            self.book.set(writes_enabled=False)
            with self.assertRaises(SystemExit):
                cs.apply(code)
            self.book.set(writes_enabled=True)
            src = json.loads(cs.src.read_text())
            src["ops"][0]["payload"]["AccountRef"]["value"] = "5"
            cs.src.write_text(json.dumps(src))
            with self.assertRaises(SystemExit):
                cs.apply(code)
            ap.assert_not_called()

    def test_apply_stops_on_error_and_reports(self):
        cs = self.changeset([self.recode(), self.je(), self.je()])
        code = cs.plan()["approval_code"]
        with mock.patch.object(qbo, "apply", side_effect=["123", RuntimeError("400 bad account"), "999"]) as ap:
            plan = cs.apply(code, interactive_confirm=False)
        self.assertEqual(ap.call_count, 2)
        self.assertEqual([o["result"]["status"] for o in plan["ops"]], ["done", "error", "not_done"])
        self.assertEqual(plan["status"], "partial")
        report = (self.book.path / "changes" / "cs-1.result.md").read_text()
        for s in ("🚨 CHANGE SET PARTIALLY APPLIED", "✅ done", "❌ error", "⏭️ not done"):
            self.assertIn(s, report)
        audit = (self.book.path / "changes" / "audit.jsonl").read_text().splitlines()
        self.assertEqual(len(audit), 3)
        with self.assertRaises(SystemExit):  # cannot re-apply a finished change set
            cs.apply(code, interactive_confirm=False)

    def test_stale_record_not_written(self):
        cs = self.changeset([self.recode()])
        code = cs.plan()["approval_code"]
        BEFORE["SyncToken"] = "5"
        try:
            with mock.patch.object(qbo, "apply") as ap:
                plan = cs.apply(code, interactive_confirm=False)
            ap.assert_not_called()
            self.assertEqual(plan["ops"][0]["result"]["status"], "not_done")
        finally:
            BEFORE["SyncToken"] = "4"

    def test_mcp_mode_requires_before_and_approval(self):
        op = self.recode()
        self.assertEqual(self.changeset([op], "cs-m", mode="mcp").plan()["status"], "blocked")
        cs = self.changeset([{**op, "before": BEFORE}], "cs-m2", mode="mcp")
        code = cs.plan()["approval_code"]
        with self.assertRaises(SystemExit):
            cs.record(1, "done", "123")
        cs.approve(code)
        cs.record(1, "done", "123")
        self.assertEqual(cs.finish()["status"], "applied")


class TestXeroSign(BookCase):
    erp = "xero"

    def test_history_note_and_narration(self):
        op = {"op": "create", "entity": "ManualJournals", "reason": "accrual",
              "payload": {"Narration": "June accrual", "JournalLines": [{"LineAmount": 50}, {"LineAmount": -50}]}}
        where = xero.sign(op, None, "[ag write/edit]")
        self.assertEqual(op["payload"]["Narration"], "June accrual [ag write/edit]")
        self.assertIn("History", where)
        self.assertEqual(xero.check(op), [])


class TestWriteGuard(BookCase):
    def test_grant_required_and_no_5xx_retry(self):
        with self.assertRaises(ReadOnlyViolation):
            request("PATCH", "https://example.com/x")
        resp = mock.Mock(status_code=503, headers={}, text="")
        with mock.patch("requests.request", return_value=resp) as rq:
            with self.assertRaises(OutcomeUnknown):
                request("POST", "https://example.com/x", grant=WriteGrant("cs", "code"))
            self.assertEqual(rq.call_count, 1)
