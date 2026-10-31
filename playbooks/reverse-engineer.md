# Playbook: reverse-engineer the accounting conventions

**Goal:** a complete, evidence-backed `books/<slug>/ACCOUNTING_CONVENTIONS.md`, a filled `BOOK.md`, and an `OPEN_QUESTIONS.md` the owner can answer, with no writes to the ERP.

**Inputs:** a connected book (see `setup/CONNECT.md`) and optional context in `books/<slug>/context/`.

**Rules:** follow `AGENTS.md` (read-only, no secrets, evidence for every claim, ask instead of assuming). Keep scratch scripts in `books/<slug>/work/`, never in `engine/`.

---

## Phase 0: Scope (ask the user, in one message)

Ask only what you can't get from the data. Skip any question already answered in `context/notes.md`.

1. Which legal entity/entities are in scope, if the ERP holds more than one?
2. Period: default is the current fiscal year plus the 2 prior years, or since inception if shorter. For micro businesses one full year plus YTD is usually enough.
3. Who relies on these financials: owner/tax only, a lender (covenants?), investors, an audit or review, a regulator?
4. Any context files to add (employees, contacts, policies, prior accountant notes)? If the user uploads files in another format, map them to the templates in `context/README.md`.

Then start. Don't wait on answers that only affect Phase 9.

## Phase 1: Load the data

**API path:** `python -m engine run <slug> --start YYYY-MM-DD --end YYYY-MM-DD`. Review `raw/_manifest.json`. For each failed dataset, decide whether it matters (e.g. a missing TaxCode endpoint for a non-US QBO company doesn't) and note it in the Appendix.

**MCP path:** use the connector's read tools to pull the chart of accounts, the GL (or every transaction type plus journals), customers, vendors, aging reports, trial balance and P&L by month (cash and accrual if the tool supports both), and company settings. Write them in the normalized schema (`engine/schema.py`) to `normalized/accounts.csv`, `normalized/gl_lines.csv` and `normalized/erp_settings.json`, then run `python -m engine profile <slug>`. Page through results fully. If a tool caps rows, chunk by month and record it. If the GL can't be pulled completely through MCP, say so and offer the API path.

**Sanity checks before analysing anything:**
- The sum of GL debits equals the sum of credits for the period.
- Trial balance from the GL ≈ the ERP's trial balance report at period end (compare the top 10 accounts by balance). Explain any difference.
- Line counts per month look plausible (no missing months).

Note any failure at the top of the conventions doc and proceed with caution.

## Phase 2: Entity profile, basis and size tier → `BOOK.md`

Use `analysis/signals.json` plus raw settings.

**Books basis.** Decide from evidence, never by default:

| Signal | Points to accrual | Points to cash |
|---|---|---|
| ERP report basis setting (QBO `ReportPrefs.ReportBasis`) | Accrual | Cash |
| `income_txns_via_ar` | high (> 60%) | low; income posts direct to bank |
| `expense_txns_via_ap` and bill date vs payment date | bills entered at invoice date | no AP, or bills entered on the payment date |
| Accrual-type accounts active (accrued, prepaid, deferred, allowance) | regular monthly activity | absent or year-end only |
| Depreciation | monthly | annual/tax-only or none |
| Month-end adjusting JEs with reversals | yes | no |

Many small businesses are **hybrid**: AR/AP used for convenience, reported on cash for tax. Say so explicitly, and say which basis the *tax return* and *users* need. Also check the P&L under both bases: a large difference tells you AR/AP are actually used.

**Size tier** (use judgement; these are guides, not rules):

| Tier | Typical signals |
|---|---|
| Micro | < ~$1M revenue, owner-operated, few/no employees, < ~300 txns/month, no dimensions |
| Small | ~$1–10M, payroll, some AR/AP, maybe classes, outside CPA does year-end |
| Mid-market | ~$10–250M, multi-entity or dimensions, monthly close, controller, possible review/audit |
| Enterprise | multi-subsidiary, consolidation, intercompany, audit, SOX or lender reporting |

**Framework:** pick the one users need. Tax basis / cash or modified cash for owner-only micro and small businesses. US GAAP accrual when there's audit, investors or GAAP covenants. IFRS or a local GAAP (FRS 102/105 in the UK, ASPE in Canada, AASB in Australia/NZ) based on the organisation country. Write the reasoning in BOOK.md. If you're unsure, ask the user (P1 question).

## Phase 3: Chart of accounts → §2

Start from `analysis/account_usage.csv`. For **every account with activity**:
1. Inferred purpose: what actually posts there (txn types, counterparties, offset accounts, memo themes). Sample 5–10 transactions for anything ambiguous.
2. Compare against the name and ERP type. Record mismatches in §2.3. Examples: owner loan typed as income, "Equipment" holding expensed repairs, a credit card set up as a bank account, a loan typed as equity.
3. Structure: numbering ranges, depth, duplicates and near-duplicates (`duplicate_account_names`), unused active accounts, inactive accounts with activity.
4. Suspense-style accounts (§2.4): the balance, what's inside (list the items), and how old it is. Always ask the owner about anything material.

## Phase 4: Dimensions → §3

From `dimension_coverage_on_pl_lines`, determine for each dimension: whether it's required in practice, which accounts/txn types skip it, and whether values are duplicated (e.g. "NY" vs "New York").

## Phase 5: Revenue and AR → §4

Answer every bullet in §4 of the template. Specific tests:
- Revenue split by recording method (invoice / sales receipt / deposit / JE): % of revenue each, per year. A change over time is **drift** (§11).
- Deposits coded straight to income that also match an invoice amount from the same customer → possible double-counted revenue (🛑 if material).
- Payments not applied to invoices; open credits; invoices > 90 days old.
- Processor fees: are deposits recorded net (fees netted out of revenue)? That understates revenue and expense, which is a finding under any framework.
- Deferred revenue: annual prepaid contracts recognised upfront (only a finding under accrual GAAP/IFRS).
- Sales tax: collected and posted to a liability, versus recorded as income.

## Phase 6: Expenses and AP → §5

- Spend split by recording method (bill / check / expense / card / JE), per year.
- Bill date vs payment date: if most bills are dated on the payment date, AP is a cash-basis shadow.
- Vendor coding consistency: `analysis/counterparty_coding.csv` (`inconsistent = True`) and `coding_drift.csv`. For each material case, look at sample transactions. Is it legitimate (e.g. Amazon buying both supplies and equipment) or an error? Legitimate multi-coding becomes a memo-based rule in §10. Errors and unclear cases go to OPEN_QUESTIONS.
- Capitalisation threshold: the smallest item capitalised to fixed assets vs the largest equipment-like purchase expensed. Note US tax de minimis safe harbour context ($2,500 / $5,000 with an AFS) only when US tax-basis books apply.
- Prepaids and accruals: present? cadence? reversed?
- Duplicates (`possible_duplicate`): review each one. Duplicate bills are the most common real money leak.
- Personal or owner expenses in business accounts (meals, personal-looking vendors, Venmo/Zelle to individuals): note them, don't accuse; ask.

## Phase 7: Payroll, fixed assets, inventory, cash, financing, equity → §6–§8

- Payroll: gross-to-net completeness (wages, employer taxes, benefits, liabilities cleared to zero after each payment). Liability accounts that keep growing are a finding.
- Loans: payments booked entirely to expense, or entirely to principal (no interest), are both findings. Compare balances to any statements the user provides.
- Transfers between own accounts booked as income/expense.
- Opening Balance Equity ≠ 0, retained earnings not rolling, distributions vs draws vs salary for the entity type (e.g. S-corp reasonable comp is a tax issue: flag it for the CPA, don't opine).
- Undeposited Funds / payments clearing with an old balance.

## Phase 8: Close and controls → §9

- Lock/closing date set? Entries dated inside closed periods, using `created_date` vs `date` (`backdated_entry`).
- Adjusting entries: who, when, round amounts, reversal habit.
- Reconciliation evidence where the ERP exposes it (QBO/Xero `is_cleared`/reconciled flags; if not available, say so).
- Scale expectations to size: a micro business without a monthly close is normal; flag it as "Low / recommendation", not a failure.

## Phase 9: Conflicts, findings, recommendations → §10–§13 and OPEN_QUESTIONS

**Conflicts and inconsistencies (§11):** the same economic event treated two ways, the same vendor coded inconsistently, a mid-period change in method, a name/use mismatch. Every one gets a Q-ID in OPEN_QUESTIONS with evidence and options. Put your recommendation first and explain why it fits *this* business.

**Compliance findings (§12):** judge against the framework chosen in Phase 2, and say which principle applies. Calibrate:
- *Cash/tax-basis micro or small business.* Focus on items that misstate cash income, deductible expenses or the balance sheet: owner draws as expenses, loan principal as expense, transfers as income, sales tax as revenue, missing depreciation for tax, personal expenses, unreconciled cash, suspense balances. Don't cite ASC 606/842/accrual cut-off as failures; mention them in §13 as "if you grow / take outside capital".
- *Accrual small or mid-market.* Add revenue cut-off and deferred revenue, expense accruals, prepaids, AR allowance, fixed asset register and depreciation, inventory costing, consistent dimensions, monthly close.
- *Enterprise / audited.* Add ASC 606 contracts, ASC 842 leases, consolidation and intercompany elimination, multi-book, FX remeasurement, segregation of duties, SOX-relevant controls.
- *Non-US.* Use the local framework and VAT/GST rules. Don't cite US GAAP or IRS rules.

Never claim tax or legal conclusions. Phrase them as "flag for your CPA/tax advisor".

**Rulebook (§10):** consolidate H/M-confidence vendor/customer/memo → account rules. This is the main asset for future agentic bookkeeping.

**Missing information:** for items only a person can answer (missing receipts, unknown deposits, unexplained transfers), see Phase 11.

## Phase 10: Write and present

1. Fill `BOOK.md`, `ACCOUNTING_CONVENTIONS.md` (every section; write "n/a: <reason>" rather than deleting one) and `OPEN_QUESTIONS.md`.
2. Self-review: every convention has evidence and confidence; every ⚠️ has a Q-ID; every 🛑 says which framework principle it breaks and why that applies to this business; numbers tie to `analysis/` files.
3. Reply to the user with: basis/tier/framework (one line each), the top 5 findings, and the **P1 questions** (max ~7) to answer now. Link the files. Don't paste the whole document.
4. As answers arrive: update the conventions, move questions to "Resolved", and add a decision log entry (§14).

## Phase 11 (optional): Request missing information by email

Only if `context/contacts.csv` exists and email is configured (`python -m engine email-setup <slug>`). Follow `playbooks/request-info.md`. **Never send without the user's explicit approval of the exact draft.**
