"""Approved writes to the ERP: change set → plan/preview → explicit approval → apply → result report.

books/<slug>/changes/
  <id>.json          change set written by the agent (ops: create | update | void)
  <id>.plan.json     frozen, signed plan with before-snapshots and diffs
  <id>.preview.md    what the user reviews (shown in chat before approval)
  <id>.result.md     what was done / not done / errored
  audit.jsonl        append-only log of every attempted operation
"""
from __future__ import annotations

import getpass
import hashlib
import json
import sys
from datetime import date, datetime, timezone

from .erp import load
from .http import OutcomeUnknown, WriteGrant
from .schema import load_json

OPS = ("create", "update", "void")
ICON = {"create": "➕ CREATE", "update": "✏️ UPDATE", "void": "🚫 VOID"}
STALE_KEYS = ("SyncToken", "UpdatedDateUTC", "lastModifiedDate", "audit.modifiedDateTime")
DEFAULT_TAG = "[ag write/edit]"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _fmt(v):
    s = "" if v is None else str(v)
    return (s[:80] + "…") if len(s) > 80 else s.replace("|", "\\|")


def _lock_date(book):
    s = load_json(book.path / "normalized" / "erp_settings.json") or {}
    candidates = [book.config.get("lock_date"), (s.get("AccountingInfoPrefs") or {}).get("BookCloseDate"),
                  s.get("PeriodLockDate"), s.get("EndOfYearLockDate")]
    dates = [str(d)[:10] for d in candidates if d and str(d)[:4].isdigit()]
    return max(dates) if dates else None


class ChangeSet:
    def __init__(self, book, cid: str):
        self.book, self.id = book, cid
        self.dir = book.dir("changes")
        self.src = self.dir / f"{cid}.json"
        self.plan_path = self.dir / f"{cid}.plan.json"
        if not self.src.exists():
            raise SystemExit(f"No change set {self.src}")

    def load_plan(self):
        if not self.plan_path.exists():
            raise SystemExit(f"Not planned yet. Run: python -m engine changes-plan {self.book.slug} {self.id}")
        return json.loads(self.plan_path.read_text())

    def save_plan(self, plan):
        self.plan_path.write_text(json.dumps(plan, indent=2, default=str))

    # --- plan ------------------------------------------------------------------
    def plan(self):
        book, erp = self.book, load(self.book.erp)
        cs = json.loads(self.src.read_text())
        mode = cs.get("mode", "api")
        tag = book.config.get("sign_tag", DEFAULT_TAG)
        threshold = float(book.config.get("large_amount_threshold", 10000))
        lock = _lock_date(book)
        client = erp.write_client(book) if mode == "api" else None
        ops, blocking = [], []
        for n, raw in enumerate(cs.get("ops", []), 1):
            op = json.loads(json.dumps(raw))  # deep copy; the source file stays as the agent wrote it
            errors, warnings = [], []
            if op.get("op") not in OPS:
                errors.append(f"op must be one of {OPS} (hard delete is never allowed)")
            if not op.get("entity"):
                errors.append("entity is required")
            if op.get("op") in ("update", "void") and not op.get("id"):
                errors.append("id is required for update/void")
            if op.get("op") in ("create", "update") and not op.get("payload"):
                errors.append("payload is required")
            if not op.get("reason"):
                errors.append("reason is required (why this change, with evidence or Q-ID)")
            before = None
            if not errors and op["op"] != "create":
                if mode == "api":
                    try:
                        before = erp.fetch(client, op["entity"], op["id"])
                    except Exception as e:
                        errors.append(f"could not read current record: {str(e)[:200]}")
                else:
                    before = op.pop("before", None)
                    if before is None:
                        errors.append("MCP mode: include 'before' (the current record, read via MCP) so the diff can be shown")
            op.pop("before", None)
            if not errors:
                signed_in = erp.sign(op, before, tag)
                errors += erp.check(op)
                flat_after, flat_before = flatten(op.get("payload", {})), flatten(before or {})
                diff = [[k, flat_before.get(k), v] for k, v in flat_after.items() if flat_before.get(k) != v]
                if op["op"] == "update" and any(k.split("[")[0] in ("Line", "LineItems", "JournalLines", "lines") for k, *_ in diff):
                    warnings.append("Payload includes line items: the ERP may REPLACE ALL lines with these")
                for f in getattr(erp, "DATE_FIELDS", ()):
                    d = str(op.get("payload", {}).get(f) or (before or {}).get(f) or "")[:10]
                    if lock and d and d <= lock:
                        if op.get("allow_closed_period"):
                            warnings.append(f"🚨 Dated {d}, inside the closed period (lock {lock}); allow_closed_period=true")
                        else:
                            errors.append(f"Dated {d}, inside the closed period (lock {lock}). Set allow_closed_period only if the owner asks.")
                amounts = [abs(float(v)) for k, v in flat_after.items()
                           if isinstance(v, (int, float)) and not isinstance(v, bool) and k.split(".")[-1].lower() in
                           ("amount", "totalamt", "lineamount", "debit", "credit", "txnamount", "unitamount")]
                if amounts and max(amounts) >= threshold:
                    warnings.append(f"Large amount: {max(amounts):,.2f} (threshold {threshold:,.0f})")
                op.update(signed_in=signed_in, diff=diff, before_stamp=_stamp(before, diff))
            if errors:
                blocking.append(n)
            op.update(n=n, errors=errors, warnings=warnings)
            ops.append(op)

        core = {"book": book.slug, "erp": book.erp, "mode": mode, "id": self.id,
                "ops": [{k: o.get(k) for k in ("op", "entity", "id", "payload", "history_note")} for o in ops]}
        plan = {"id": self.id, "title": cs.get("title", ""), "book": book.slug, "erp": book.erp, "mode": mode,
                "tag": tag, "planned_at": _now(), "source_hash": _hash(cs), "approval_code": _hash(core)[:10],
                "status": "blocked" if blocking else "awaiting_approval", "ops": ops}
        self.save_plan(plan)
        preview = render_preview(plan, writes_enabled=book.config.get("writes_enabled", False))
        (self.dir / f"{self.id}.preview.md").write_text(preview)
        print(preview)
        return plan

    # --- approve / apply -------------------------------------------------------
    def _verify(self, code: str):
        plan = self.load_plan()
        if plan["status"] == "blocked":
            raise SystemExit("🚨 Plan has blocking errors. Fix the change set and re-plan.")
        if plan["status"] not in ("awaiting_approval", "approved"):
            raise SystemExit(f"🚨 Change set is already '{plan['status']}'. Create a new change set for further changes.")
        if _hash(json.loads(self.src.read_text())) != plan["source_hash"]:
            raise SystemExit("🚨 Change set was edited after the preview. Re-plan and get approval again.")
        if code != plan["approval_code"]:
            raise SystemExit("🚨 Approval code does not match the previewed plan. Nothing was written.")
        if not self.book.config.get("writes_enabled"):
            raise SystemExit(f"🚨 Writes are disabled for this book. The owner enables them: python -m engine writes {self.book.slug} on")
        return plan

    def approve(self, code: str):
        plan = self._verify(code)
        plan.update(status="approved", approved_at=_now(), approved_by=getpass.getuser())
        self.save_plan(plan)
        print(f"✅ Approved {self.id} (code {code}). Apply each op exactly as in {self.plan_path.name}, then record results.")

    def apply(self, code: str, interactive_confirm: bool = True):
        plan = self._verify(code)
        if plan["mode"] != "api":
            raise SystemExit("MCP-mode change set: approve it, apply via the connector, then use changes-record.")
        if interactive_confirm and sys.stdin.isatty():
            if input(f"Type APPLY {code} to write {len(plan['ops'])} change(s) to {plan['erp']}: ").strip() != f"APPLY {code}":
                raise SystemExit("Cancelled. Nothing was written.")
        erp = load(self.book.erp)
        client, grant = erp.write_client(self.book), WriteGrant(self.id, code)
        plan.update(status="applying", approved_at=plan.get("approved_at") or _now(), approved_by=getpass.getuser())
        self.save_plan(plan)
        halted = False
        for op in plan["ops"]:
            if halted:
                self._result(plan, op, "not_done", message="Not attempted: an earlier operation failed")
                continue
            try:
                if op["op"] != "create":
                    current = erp.fetch(client, op["entity"], op["id"])
                    if _stamp(current, op["diff"]) != op["before_stamp"]:
                        self._result(plan, op, "not_done", message="Record changed since preview; re-plan")
                        halted = True
                        continue
                ref = erp.apply(client, op, grant)
                self._result(plan, op, "done", ref=ref, message=f"Signed in {op['signed_in']}")
            except OutcomeUnknown as e:
                self._result(plan, op, "unknown", message=str(e)[:300])
                halted = True
            except Exception as e:
                self._result(plan, op, "error", message=str(e)[:300])
                halted = True
        return self.finish(plan)

    # --- MCP-mode recording ---------------------------------------------------
    def record(self, n: int, status: str, ref: str = "", message: str = ""):
        plan = self.load_plan()
        if plan["status"] not in ("approved", "applying"):
            raise SystemExit("🚨 Not approved. Approve the exact plan before applying any change via MCP.")
        plan["status"] = "applying"
        op = next((o for o in plan["ops"] if o["n"] == n), None)
        if not op:
            raise SystemExit(f"No op #{n}")
        self._result(plan, op, status, ref=ref, message=message)
        self.save_plan(plan)
        print(f"Recorded op #{n}: {status}")

    def finish(self, plan=None):
        plan = plan or self.load_plan()
        for op in plan["ops"]:
            op.setdefault("result", {"status": "not_done", "message": "No result recorded"})
        statuses = {o["result"]["status"] for o in plan["ops"]}
        plan["status"] = "applied" if statuses == {"done"} else "partial" if "done" in statuses else "failed"
        plan["finished_at"] = _now()
        self.save_plan(plan)
        report = render_result(plan)
        (self.dir / f"{self.id}.result.md").write_text(report)
        print(report)
        return plan

    def _result(self, plan, op, status, ref="", message=""):
        op["result"] = {"status": status, "ref": ref, "message": message, "at": _now()}
        with (self.dir / "audit.jsonl").open("a") as f:
            f.write(json.dumps({"ts": _now(), "book": plan["book"], "erp": plan["erp"], "changeset": plan["id"],
                                "approval_code": plan["approval_code"], "operator": getpass.getuser(), "n": op["n"],
                                "op": op["op"], "entity": op["entity"], "id": op.get("id"), "ref": ref,
                                "status": status, "message": message, "tag": plan["tag"], "reason": op.get("reason")}) + "\n")
        self.save_plan(plan)


def _stamp(record, diff):
    """Fingerprint of the fields we change plus version markers, to detect edits between preview and apply."""
    if record is None:
        return None
    flat = flatten(record)
    keys = sorted({k for k, *_ in diff} | {k for k in STALE_KEYS if k in flat})
    return _hash({k: flat.get(k) for k in keys})


def render_preview(plan, writes_enabled: bool) -> str:
    ops = plan["ops"]
    blocked = [o for o in ops if o["errors"]]
    head = "🛑 CHANGE SET BLOCKED: fix errors, nothing can be written" if blocked else \
        "🚨 PROPOSED CHANGES: NOTHING HAS BEEN WRITTEN YET"
    out = [f"# {head}", "",
           f"**Change set** `{plan['id']}` · **Book** {plan['book']} ({plan['erp']}) · **Mode** {plan['mode']} · "
           f"**Operations** {len(ops)} · **Approval code** `{plan['approval_code']}`", "",
           f"{plan['title']}", "",
           f"Every record written is signed with `{plan['tag']}` in its notes/memo.", ""]
    if not writes_enabled:
        out += ["⚠️ Writes are currently **disabled** for this book; the owner must run "
                f"`python -m engine writes {plan['book']} on` before applying.", ""]
    out += ["| # | Action | Record | Fields changed | Reason / evidence | Status |", "|---|---|---|---|---|---|"]
    for o in ops:
        state = "🛑 blocked" if o["errors"] else ("⚠️ review" if o["warnings"] else "ready")
        out.append(f"| {o['n']} | {ICON.get(o.get('op'), o.get('op'))} | {o.get('entity')} {o.get('id') or '(new)'} | "
                   f"{len(o.get('diff', []))} | {_fmt(o.get('reason'))} {_fmt(o.get('evidence', ''))} | {state} |")
    for o in ops:
        out += ["", f"## {o['n']}. {ICON.get(o.get('op'), o.get('op'))} {o.get('entity')} {o.get('id') or '(new)'}", "",
                f"Reason: {o.get('reason', '')}" + (f" · Evidence: {o['evidence']}" if o.get("evidence") else ""),
                f"Signed in: {o.get('signed_in', 'n/a')}", ""]
        for e in o["errors"]:
            out.append(f"- 🛑 {e}")
        for w in o["warnings"]:
            out.append(f"- ⚠️ {w}")
        if o.get("diff"):
            out += ["", "| Field | Before | After |", "|---|---|---|"]
            out += [f"| {_fmt(k)} | {_fmt(b)} | **{_fmt(a)}** |" for k, b, a in o["diff"]]
        if o.get("history_note"):
            out.append(f"\nHistory note added: `{_fmt(o['history_note'])}`")
    out += ["", "---", ""]
    out.append("🛑 Not approvable until errors are fixed and the change set is re-planned." if blocked else
               f"**To approve exactly these changes, reply:** `approve {plan['approval_code']}`. Anything else means no.")
    return "\n".join(out) + "\n"


def render_result(plan) -> str:
    ops = plan["ops"]
    icon = {"done": "✅ done", "error": "❌ error", "unknown": "🚨 outcome unknown", "not_done": "⏭️ not done",
            "skipped": "⏭️ not done"}
    count = lambda s: sum(1 for o in ops if o["result"]["status"] in s)
    done, bad, unknown, skipped = count({"done"}), count({"error"}), count({"unknown"}), count({"not_done", "skipped"})
    if done == len(ops):
        head = f"✅ CHANGE SET APPLIED: {done}/{len(ops)} done"
    else:
        head = (f"🚨 CHANGE SET {'PARTIALLY APPLIED' if done else 'NOT APPLIED'}: "
                f"✅ {done} done · ❌ {bad} error · 🚨 {unknown} unknown · ⏭️ {skipped} not done")
    out = [f"# {head}", "", f"Change set `{plan['id']}` · {plan['book']} ({plan['erp']}) · approval `{plan['approval_code']}` · "
           f"finished {plan.get('finished_at', '')}", "",
           "| # | Result | Action | Record | ERP ref | Message |", "|---|---|---|---|---|---|"]
    for o in ops:
        r = o["result"]
        out.append(f"| {o['n']} | {icon.get(r['status'], r['status'])} | {ICON.get(o['op'], o['op'])} | "
                   f"{o['entity']} {o.get('id') or ''} | {r.get('ref', '')} | {_fmt(r.get('message'))} |")
    if unknown:
        out += ["", "🚨 **Outcome unknown** means the ERP may or may not have saved the record. Check it in the ERP "
                "before retrying, or you may create a duplicate."]
    if bad or skipped:
        out += ["", "Nothing after the first failure was attempted. Fix the cause, then create a **new** change set for the remaining items."]
    out += ["", f"Every applied record is signed `{plan['tag']}`. Audit log: `changes/audit.jsonl`."]
    return "\n".join(out) + "\n"


def set_writes(book, on: bool):
    if on:
        if not sys.stdin.isatty():
            raise SystemExit("Enabling writes must be done by the owner in an interactive terminal.")
        print(f"🚨 This allows approved change sets to WRITE to {book.erp} for '{book.slug}'.\n"
              "Each change set still needs your explicit approval code. Use a role/scopes limited to what you need.")
        if input("Type ENABLE WRITES to continue: ").strip() != "ENABLE WRITES":
            raise SystemExit("Cancelled.")
    book.set(writes_enabled=on, writes_changed_at=date.today().isoformat())
    print(("✅ Writes enabled" if on else "✅ Writes disabled") + f" for {book.slug}.")
