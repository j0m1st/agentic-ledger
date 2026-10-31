# Playbook: request missing information by email (Resend)

Use this to close out transactions or a period when only a person can answer (missing receipts, unidentified deposits, unknown transfers, a vendor W-9, the purpose of a large payment).

## Setup (once per book; the user runs it)

1. Create a [Resend](https://resend.com) account, verify a sending domain, and create an API key with **Sending access** only, restricted to that domain.
2. `python -m engine email-setup <slug>` stores the key in the OS keychain and sets the From and Reply-To addresses in `book.json`.
3. Fill `context/contacts.csv`. Only rows with `can_email = yes` can receive email. The engine enforces this allowlist.

(Resend also publishes an MCP server for sending. Don't use it here: the engine's allowlist, credential-content check, idempotency and sent log are the safeguards.)

## Drafting (agent)

1. Group open items **per recipient**: one email per person, not one per transaction. Match items to people using `contacts.csv` `topics` and `employees.csv` responsibilities.
2. Write `books/<slug>/outbox/<YYYYMMDD>-<recipient-short>-<n>.json`:
   ```json
   {
     "to": ["pat@example.com"],
     "cc": [],
     "subject": "Acme books: 4 items needed to close March",
     "reason": "Q-012, Q-015; missing receipts for AmEx 1004",
     "related": ["txn 1832", "txn 1840"],
     "body": "Hi Pat,\n\nTo close March we need:\n\n1. 03/04  Delta Air Lines  $612.40  (AmEx 1004): receipt and business purpose\n2. ...\n\nA reply to this email is fine.\n\nThanks,\nAcme Books"
   }
   ```
   - Plain, polite and specific: date, payee, amount, and what's needed. Keep it short.
   - **Never** include or request passwords, full account/card numbers, SSNs or other IDs. Use the last 4 digits only. Don't attach ledger exports.
   - Include only the data that recipient needs (no other employees' items, no salary data).
3. `python -m engine email-check <slug> <draft_id>` validates the allowlist and content.

## Approval and sending

1. Show the user the full draft (to, cc, subject, body) in chat and ask: **"Send this email? (yes/no)"**.
2. Only after an explicit "yes" for *that* draft, run `python -m engine email-send <slug> <draft_id> --yes`. In Claude Code the repo's settings also make this command ask for permission every time. Approval covers one draft only. Ask again for every email, and again if you edit a draft after approval.
3. Sent mail is logged in `outbox/sent/` with the Resend ID. Link answers back: update `OPEN_QUESTIONS.md` and the conventions when replies arrive (the user pastes or forwards them; the agent doesn't read inboxes).
