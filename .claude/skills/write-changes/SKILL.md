---
name: write-changes
description: Make changes in the connected ERP (create, update or void transactions, recode, journal entries) through the approved change-set protocol. Use whenever the user asks to fix, post, recode or edit anything in their books.
---

Book slug and request: $ARGUMENTS.

Follow `playbooks/write-changes.md` exactly: draft the change set, run `changes-plan` and paste the full preview, wait for the user's `approve <code>`, apply, then paste the ✅/❌/🚨/⏭️ result report. Never call an MCP write tool or write endpoint outside this flow.
