---
name: reverse-engineer
description: Reverse-engineer the accounting conventions of a connected book (QBO, Xero, Sage Intacct, NetSuite) into books/<slug>/ACCOUNTING_CONVENTIONS.md, BOOK.md and OPEN_QUESTIONS.md. Use when the user asks to analyse, document or reverse-engineer their books, chart of accounts, AR/AP conventions.
---

Book slug: $ARGUMENTS (if empty, list `books/*/book.json` and ask which one).

Follow `playbooks/reverse-engineer.md` end to end, under the rules in `AGENTS.md` (read-only ERP access, no secrets, evidence for every claim, ask rather than assume). If the book is not connected yet, walk the user through `setup/CONNECT.md` for its ERP first.
