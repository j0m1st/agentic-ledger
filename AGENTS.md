# Agent instructions

This repo reverse-engineers the accounting conventions of a live ledger (QBO, Xero, Sage Intacct, NetSuite) and documents them per company in `books/<slug>/`.

## Hard rules

1. **Read-only ERP.** Never create, update, void, delete, approve or post anything in the ERP, whether through the API, an MCP tool or a browser. If an MCP connector exposes write tools, don't call them. Recommended fixes go in the notes for a human to make.
2. **Secrets.** Never print, log, commit or echo credentials. Don't open `.env*`, `*.pem` or keychain contents. Use `python -m engine auth`, `exec` and `email-setup` to handle secrets.
3. **Company data never leaves `books/` and never gets committed.** `books/*` is git-ignored. Never force-add it, and never paste ledger data into third-party services. The public repo holds only `engine/`, `playbooks/`, `templates/` and docs.
4. **Evidence or it didn't happen.** Every stated convention cites evidence: counts, percentages, date ranges, example transaction IDs/doc numbers. Label each one with a confidence of High, Medium or Low.
5. **Ask, don't assume.** When the books are inconsistent or intent is unclear, log it in `OPEN_QUESTIONS.md` and ask the user. Don't choose a "correct" answer silently.
6. **Fit the framework to the business.** Find out cash vs accrual, size tier, country, and who relies on the financials *before* judging compliance. Don't apply enterprise or US GAAP standards to a cash-basis sole proprietor by default.
7. **Email only with approval.** Draft information requests to `books/<slug>/outbox/`, and send only via `python -m engine email-send` after the user explicitly approves *that exact draft* in chat. Recipients come from `context/contacts.csv` (`can_email = yes`) only. Never request credentials or full account/ID numbers.

## Connecting

Prefer an **MCP connector** for QuickBooks Online and Xero, and the **direct API** for Sage Intacct and NetSuite (complete bulk GL). Either works for any system. See `setup/CONNECT.md`.

## Layout

- `engine/` is shared source (no company data). CLI: `python -m engine {new,auth,extract,normalize,profile,run,exec,email-setup,email-check,email-send}`.
- `playbooks/`: `reverse-engineer.md` (start here) and `request-info.md`.
- `templates/book/` is copied into `books/<slug>/` by `python -m engine new`.
- `books/<slug>/` is per-company: `BOOK.md`, `ACCOUNTING_CONVENTIONS.md`, `OPEN_QUESTIONS.md`, `context/` (user uploads: employees, contacts, notes), plus `raw/`, `normalized/`, `analysis/`, `work/` (your scratch scripts) and `outbox/`.

## Workflow

1. Connect (`setup/CONNECT.md`).
2. Reverse-engineer (`playbooks/reverse-engineer.md`), end to end.
3. Present a short summary plus the P1 open questions. Fold the answers back into `ACCOUNTING_CONVENTIONS.md`.
4. Optionally request missing information from people (`playbooks/request-info.md`).

## Code conventions

Python 3.9+, stdlib plus `requests`, `keyring`, `PyJWT[crypto]`. ERP-specific logic goes in `engine/erp/<erp>.py`, and ERP-agnostic analysis in `engine/profile.py` using the schema in `engine/schema.py`. Run `python -m unittest` before committing.
