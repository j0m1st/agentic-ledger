# Agentic Ledger

Point a coding agent at your accounting system and have it reverse-engineer the bookkeeping conventions already in use: chart of accounts, AR/AP practices, coding rules, close habits. It reports conflicts and anything that isn't GAAP or sound bookkeeping, measured against the framework that fits *your* business (cash vs accrual, small business vs mid-market vs enterprise).

Supported: **QuickBooks Online, Xero, Sage Intacct, NetSuite**.

Agent-agnostic: instructions live in [AGENTS.md](AGENTS.md), which Codex, Cursor, Copilot, Gemini CLI and others read. [CLAUDE.md](CLAUDE.md) imports the same file. **Full end-to-end testing is done on Claude Code**; other agents should work but are not tested as thoroughly.

> ⚠️ **Use at your own risk.** This is an analysis aid, not accounting, tax, audit or legal advice. Output can be wrong. Have a qualified accountant review findings before acting on them. The authors accept no liability (see [LICENSE](LICENSE)).

## Quick start

```bash
git clone https://github.com/j0m1st/agentic-ledger.git && cd agentic-ledger
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
git config core.hooksPath .githooks              # blocks accidental commits of books/ data
python -m engine new acme --erp qbo               # creates books/acme/ (qbo | xero | intacct | netsuite)
```

**Connect** using [setup/CONNECT.md](setup/CONNECT.md). The default path depends on the system:

| System | Default | Alternative |
|---|---|---|
| QuickBooks Online, Xero | **MCP connector** (simplest) | Direct API |
| Sage Intacct, NetSuite | **Direct API** (complete, bulk GL) | MCP connector |

On the API path, also run `python -m engine auth acme && python -m engine run acme --start 2024-01-01`.

**Optional context:** drop an employee list, a contact list, or policy notes into `books/acme/context/`. See [its README](templates/book/context/README.md).

**Run it:** tell your agent *"Run the reverse-engineering playbook on books/acme."* In Claude Code: `/reverse-engineer acme`.

## Layout

```
AGENTS.md / CLAUDE.md     agent rules (read-only ERP access, workflow)
setup/CONNECT.md          connecting each ERP: MCP connector or direct API, securely
playbooks/
  reverse-engineer.md     step 1: derive conventions from the live books
  request-info.md         email people for missing info (Resend, approval per email)
  write-changes.md        write to the ERP: preview → approve → apply → report
engine/                   source: Python ERP clients, extract → normalize → profile, email
templates/book/           copied into each new book folder
books/<slug>/             YOUR data and notes (git-ignored, never pushed)
```

`engine/`, `playbooks/` and `templates/` are the shared source. Everything specific to your books lives in `books/<slug>/`:

| File | Purpose |
|---|---|
| `BOOK.md` | Entity profile: ERP, basis (cash/accrual), size tier, framework, who relies on the financials |
| `ACCOUNTING_CONVENTIONS.md` | Master conventions: every account's use, AR/AP process, coding rulebook, findings, all with evidence |
| `OPEN_QUESTIONS.md` | Conflicts and inconsistencies for you to resolve; answers flow back into the conventions |
| `context/` | Your uploads: employees, contacts (email allowlist), notes |
| `raw/ normalized/ analysis/ work/ outbox/` | Extracted data, profiler output, agent scratch, email drafts |

## Keeping your books private

- **Never commit company or ERP data to this public repository.** `books/*` is git-ignored, the pre-commit hook rejects anything under `books/`, and the Claude Code settings deny `git add -f`.
- For history of your own notes, make `books/` a separate **private** repo (see [books/README.md](books/README.md)), or keep it local.
- If you fork to contribute, contribute only to `engine/`, `playbooks/`, `templates/` and docs.

## Safety

- **Read-only by default.** The engine's HTTP layer refuses any write unless it comes from an approved change set.
- **Writes (opt-in)** via API or MCP follow [playbooks/write-changes.md](playbooks/write-changes.md):
  1. 🚨 a full before → after preview of every change, with nothing written yet
  2. ✅ clear approval: you reply `approve <code>`, bound to that exact preview
  3. 📋 an after-report: ✅ done / ❌ error / 🚨 outcome unknown / ⏭️ not done

  Every written record is signed `[ag write/edit]` in its memo/notes, and every attempt is logged to `changes/audit.jsonl`. Hard deletes are never allowed. Writes stay off until the owner runs `python -m engine writes <slug> on` in a terminal.
- **Secrets** live in the OS keychain (or env vars injected by 1Password, Doppler, or similar), never in files or chat.
- **Email** goes out only via `engine email-send`, only to `context/contacts.csv` rows with `can_email = yes`, and only after you approve each draft (Claude Code also asks for permission on every send).

## License

[PolyForm Noncommercial 1.0.0](LICENSE): free for personal, research, educational, nonprofit and other noncommercial use, with attribution (keep the `Required Notice`). Commercial use needs a separate license from the authors. Provided as-is, with no warranty or liability.
