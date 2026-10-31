# Context you provide (optional, recommended)

Drop files here. CSV, XLSX or pasted text all work; the agent maps them to the columns below. This folder is git-ignored with the rest of `books/`, but it still holds personal data, so share only what's needed.

| File | Used for |
|---|---|
| `employees.csv` | Who does what: approvers, cardholders, who books AR/AP, payroll owner. Helps tell employee reimbursements from vendor spend and identifies who to ask. |
| `contacts.csv` | **Email allowlist** for information requests. The agent may only draft emails to rows with `can_email = yes`. |
| `notes.md` | Anything you know: business model, policies (capitalization threshold, revenue recognition), known messes, prior accountant's notes. |
| Any policy docs, prior-year tax return summary, audit/review letters | Ground truth for the conventions. |

## Columns

**employees.csv**: `name,email,title,department,manager,responsibilities,approval_limit,cards_held,start_date,end_date`

**contacts.csv**: `name,email,organization,relationship,topics,can_email,notes`
- `relationship`: owner | employee | accountant | bookkeeper | vendor | customer | lender | other
- `topics`: what to ask them about (e.g. "receipts for AmEx 1004; vendor W-9s")
- `can_email`: yes | no
