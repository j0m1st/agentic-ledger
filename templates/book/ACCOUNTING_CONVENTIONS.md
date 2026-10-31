# Accounting conventions: master reference

> **What this is:** the conventions this company's books *actually follow*, reverse-engineered from the ledger, plus the decisions the owner made on open questions. Future bookkeeping (human or agent) should follow it.
>
> **Evidence standard:** every convention cites counts, percentages, a date range, and 1–3 example doc numbers or txn IDs. Confidence is **H** (≥90% consistent, ≥20 instances), **M** (≥70% or fewer instances), or **L** (inferred or thin).
>
> **Markers:** ⚠️ inconsistency (linked to an OPEN_QUESTIONS ID) · 🛑 not compliant with the chosen framework / sound bookkeeping · ✅ owner-confirmed.

- Book: `<slug>` · ERP: · Period analysed: · Last updated: · Prepared by: agent (reviewed by: )

## 0. Executive summary
- Basis and framework (one line each, with confidence):
- Overall health (1–2 sentences):
- Top 5 issues to fix (link to §12 / OPEN_QUESTIONS):
- Top 5 conventions anyone touching these books must know:

## 1. Entity profile and framework
Summary of BOOK.md: basis, size tier, framework, users of financials. **State what that means for this review:** which standards apply and which are deliberately out of scope (e.g. "cash basis, tax-only users: ASC 606/842 not applied; findings limited to tax-accurate cash income and clean balance sheet").

## 2. Chart of accounts
### 2.1 Structure
- Numbering scheme (ranges per class, sub-account depth, gaps), or "unnumbered":
- Naming conventions (prefixes, abbreviations, "Other"/"Misc" usage):
- Accounts: total / active / with activity in period / unused-active / inactive-with-activity:
- Industry template origin, if recognisable (e.g. QBO default for "services"):

### 2.2 Account register
One row per account with activity, plus active accounts without activity in a collapsed list.

| # | Account | Type (ERP) | Class | Inferred purpose / what actually posts here | Typical sources (txn types) | Typical counterparties | Typical offset accounts | Lines / net | Conf | Flags |
|---|---|---|---|---|---|---|---|---|---|---|

### 2.3 Accounts whose use differs from their name or type
| Account | Name/type implies | Actually used for | Evidence | Flag / Q-ID |
|---|---|---|---|---|

### 2.4 Suspense, clearing, opening-balance, "Ask my accountant", Undeposited Funds
| Account | Balance at end | Aging / oldest item | What's in it | Q-ID |
|---|---|---|---|---|

## 3. Dimensions and tracking
| Dimension | Values in use | Coverage on P&L lines | Rule observed (when it is/isn't set) | Gaps / conflicts |
|---|---|---|---|---|

## 4. Revenue and accounts receivable
- **Recording method:** invoices → AR → payment, versus sales receipts / deposits straight to income, versus summary JEs from POS or payments platform (with % of revenue each):
- **Revenue recognition timing:** at invoice date / service period / cash receipt / milestone; deferred revenue usage:
- **Revenue accounts and split logic** (by product, service, channel, class):
- **Terms and due dates** (default and exceptions):
- **Customer deposits / retainers / gift cards:**
- **Payment application:** applied to specific invoices versus unapplied payments/credits; how processor fees are recorded (gross versus net deposits):
- **Credit memos, refunds, discounts:**
- **Bad debt:** direct write-off versus allowance; who/when; account used:
- **Sales tax / VAT / GST:** collected via items/tax codes versus manual; liability account; filing frequency evidence:
- **AR aging snapshot** (end of period), and items > 90 days:
- **Customer master hygiene** (duplicates, inactive with balances, missing terms):
- Conventions table:

| Rule | Evidence | Conf |
|---|---|---|

## 5. Expenses and accounts payable
- **Recording method:** bills → AP → bill payment, versus checks/expenses/card charges direct (% of spend each). Are bills entered at bill date or when paid (bill date ≈ payment date in X%)?
- **Approval evidence** (approvers from employees.csv, bill-pay tool):
- **Coding rules by vendor** (see §10 rulebook):
- **Credit cards:** liability account per card; statement reconciliation cadence; how payments to card are recorded:
- **Employee reimbursements and expense reports:**
- **Prepaids:** threshold, amortisation schedule and cadence, or expensed immediately:
- **Accrued expenses:** month-end accruals? reversed next month?
- **Vendor credits / refunds:**
- **1099 / contractor tracking** (US): vendors flagged, account mapping:
- **AP aging snapshot** and items > 60 days:
- **Vendor master hygiene:**
- Conventions table:

| Rule | Evidence | Conf |
|---|---|---|

## 6. Payroll and people costs
- Source (payroll provider integration versus summary JE versus manual), gross versus net recording, liabilities clearing, employer taxes, benefits, owner/officer comp, contractor versus employee split:

## 7. Fixed assets, inventory, leases
- **Capitalisation threshold** (stated, or inferred from the smallest capitalised item / largest expensed equipment purchase):
- **Depreciation:** method, frequency (monthly / annual / tax-only at year end), source (fixed asset register versus manual JE):
- **Inventory:** perpetual (items) versus periodic (COGS adjusted at period end); costing method; count adjustments:
- **Leases:** expensed as paid versus ASC 842 / IFRS 16 ROU assets (only relevant where the framework requires it):

## 8. Cash, bank, financing and equity
- Bank and card accounts and reconciliation evidence (last reconciled, uncleared aged items):
- Transfers between accounts (how recorded; any transfers booked as income/expense):
- **Loans:** principal versus interest split, statement true-ups, current/long-term split:
- **Owner / shareholder transactions:** draws, contributions, distributions, personal expenses, due to/from shareholder:
- Retained earnings rollover / opening balance equity:

## 9. Period close and controls
- Close cadence (monthly / quarterly / annual only) and evidence:
- Lock / closing date setting and whether entries post into closed periods:
- Recurring and adjusting journal patterns (who, when, round amounts, reversals):
- Back-dated entries (entered > 45 days after transaction date):
- Segregation of duties signals (same user creating and paying, where visible):

## 10. Coding rulebook (machine-usable)
Rules a bookkeeping agent can apply going forward. Only include **H/M** confidence or owner-confirmed rules.

| Match (vendor / customer / memo pattern / bank description) | Account | Dimensions | Tax code | Treatment notes | Evidence | Conf |
|---|---|---|---|---|---|---|

## 11. Inconsistencies and convention drift
| Area | What's inconsistent | Pattern A (count, period) | Pattern B (count, period) | Impact | Q-ID |
|---|---|---|---|---|---|

## 12. Compliance findings (vs the framework in §1)
Severity: **Critical** (misstates profit/tax/balance-sheet materially, or a control failure), **High**, **Medium**, **Low** (best practice).

| ID | Severity | Finding | Standard / principle | Evidence | Impact (est.) | Recommended fix (for a human to make) | Applies because… |
|---|---|---|---|---|---|---|---|

## 13. Recommendations, sized to the business
- Now (this month):
- Next close:
- When the business grows / if it takes on a lender or investors (e.g. switch to accrual, adopt ASC 606 policy, fixed asset register):

## 14. Decision log
| Date | Q-ID | Decision | Section changed | By |
|---|---|---|---|---|

## Appendix: method
Data sources (API datasets / MCP tools), period, row counts, profiler version, anything not covered and why.
