# Playbook: write changes to the books (approved change sets only)

Every write, whether through the API or an MCP connector, follows **show → clear approval → apply → report**. There are no exceptions, no "small" changes, and no batching approvals across change sets.

## One-time owner setup

1. Give the integration write access, limited to what's needed (see `setup/CONNECT.md` › *Enabling writes*).
2. The owner runs this in an interactive terminal (an agent can't do it): `python -m engine writes <slug> on`. Turn it `off` when you're done.

## 1. Draft the change set (agent)

Write `books/<slug>/changes/<id>.json`, where `<id>` is `cs-YYYYMMDD-NN`:

```json
{
  "title": "Recode Adobe to Software; accrue June rent",
  "mode": "api",
  "ops": [
    {"op": "update", "entity": "Purchase", "id": "123",
     "payload": {"AccountRef": {"value": "61"}},
     "reason": "Adobe is coded to Software in 92% of cases (Q-004, owner confirmed)", "evidence": "txn 123"},
    {"op": "create", "entity": "JournalEntry",
     "payload": {"TxnDate": "2026-06-30", "Line": ["..."]},
     "reason": "June rent accrual per conventions §5"}
  ]
}
```

- `op`: `create`, `update` or `void`. **Hard deletes are never allowed**; use void or a reversing entry instead.
- `entity`/`id`/`payload`: the ERP's own record names and fields (QBO entity names, Xero endpoint names like `Invoices`, NetSuite record types like `journalentry`, Intacct objects like `general-ledger/journal-entry`). For updates, send only the fields that change.
- `reason` is required. Link it to an OPEN_QUESTIONS ID or a conventions section.
- **MCP mode** (`"mode": "mcp"`): add `"before": {...}` to every update/void, holding the current record as read through the connector.
- Don't add the signature yourself: the engine stamps `[ag write/edit]` (book.json `sign_tag`) into each record's memo/notes:

| ERP | Where the tag goes |
|---|---|
| QBO | `PrivateNote` (transactions), `Notes` (customers/vendors), `Description` (accounts/items), plus each JE line's `Description` |
| Xero | a *History & Notes* entry on the record, plus `Narration` on manual journals |
| NetSuite | `memo` (transactions), `comments` (entities) |
| Intacct | `description` or `notes` (verify per object) |

## 2. Plan and SHOW (agent)

`python -m engine changes-plan <slug> <id>` writes nothing. It:
- reads the current records and builds a **before → after** diff for every field
- signs each payload with the tag
- blocks: unbalanced journals, dates inside the closed/locked period (unless `allow_closed_period` is set *at the owner's request*), unsupported ops, missing reasons
- warns on large amounts (book.json `large_amount_threshold`) and on line-replacing updates
- prints `changes/<id>.preview.md`, headed **🚨 PROPOSED CHANGES: NOTHING HAS BEEN WRITTEN YET**, with an **approval code**

**Paste the full preview into the chat.** Don't summarise it away. If something is blocked (🛑), fix it and re-plan.

## 3. CLEAR approval (user)

Ask exactly: **"Approve change set `<id>`? Reply `approve <code>` to apply these N changes."**
- Only a reply containing `approve <code>` counts. "ok", "sure" or "looks good" are not approval: ask again.
- Editing the change set after the preview invalidates the code (the engine refuses). Re-plan and re-ask.
- One approval = one change set, applied once.

## 4. Apply

- **API mode:** `python -m engine changes-apply <slug> <id> --approve <code>`. In Claude Code this command also prompts for permission.
- **MCP mode:**
  1. Run `python -m engine changes-approve <slug> <id> --approve <code>`.
  2. Call the connector's write tool for each op **in order, with the exact signed payload from `changes/<id>.plan.json`**.
  3. After each op, record it with `python -m engine changes-record <slug> <id> <n> --status done|error|unknown --ref <erp id> --message "..."`. Stop at the first error, leaving the rest unrecorded so they report as not done.
  4. Finish with `python -m engine changes-report <slug> <id>`. If a connector can't set the memo field, record `done` with a message saying so.

Safeguards in apply: it re-reads each record and skips it as ⏭️ if it changed since the preview, it stops at the first failure, and it never retries a write that got a 5xx (🚨 outcome unknown).

## 5. Report AFTER (agent)

Paste `changes/<id>.result.md` into the chat. It's headed ✅ (all done) or 🚨 (partial or none), with one row per operation:
- ✅ done (with the ERP reference)
- ❌ error (with the message)
- 🚨 outcome unknown (check the ERP before retrying)
- ⏭️ not done

Then update `ACCOUNTING_CONVENTIONS.md` (decision log) and `OPEN_QUESTIONS.md` where relevant. The full trail is in `changes/audit.jsonl`.
