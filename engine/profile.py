"""Deterministic profiling of normalized books. Produces evidence for the reverse-engineering playbook.

Input:  books/<slug>/normalized/{accounts.csv, gl_lines.csv, erp_settings.json?}
Output: books/<slug>/analysis/{summary.md, account_usage.csv, counterparty_coding.csv,
        coding_drift.csv, anomalies.csv, signals.json}
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Dict, List

from .schema import load_json, num, read_csv, write_csv

SUSPENSE = re.compile(r"suspense|uncategori[sz]ed|ask my accountant|undeposited|opening balance|clearing|temporary|\btemp\b|\bmisc", re.I)
ACCRUAL_NAMES = re.compile(r"accrued|accrual|prepaid|prepayment|deferred|unearned|unbilled|accumulated depreciation|allowance", re.I)
DEPRECIATION = re.compile(r"depreciation|amorti[sz]ation", re.I)
PAYROLL = re.compile(r"payroll|wages|salar", re.I)
NAME_CLASS_HINTS = [
    (re.compile(r"\bloan\b|payable|due to|accrued|deferred revenue|unearned|line of credit", re.I), {"liability"}),
    (re.compile(r"owner'?s? (draw|contribution|equity|capital)|distribution|retained earnings|member|partner capital|shareholder", re.I), {"equity", "liability"}),
    (re.compile(r"accumulated depreciation|receivable|prepaid|inventory|equipment|vehicle", re.I), {"asset"}),
    (re.compile(r"^(sales|revenue)\b|service income|consulting income", re.I), {"income"}),
]
MATERIAL = 1000.0


def _d(s: str):
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def profile(book) -> Dict:
    src, out = book.dir("normalized"), book.dir("analysis")
    accounts = read_csv(src / "accounts.csv")
    gl = read_csv(src / "gl_lines.csv")
    settings = load_json(src / "erp_settings.json") or {}
    acct = {a["account_id"]: a for a in accounts}

    for ln in gl:
        ln["amt"] = num(ln["debit"]) - num(ln["credit"])
        ln["d"] = _d(ln["date"])
        a = acct.get(ln["account_id"], {})
        ln["class"], ln["role"] = a.get("class", ""), a.get("role", "other")
    gl = [ln for ln in gl if ln["d"]]
    txns = defaultdict(list)
    for ln in gl:
        txns[ln["txn_id"] or f"{ln['date']}|{ln['doc_num']}"].append(ln)

    anomalies: List[Dict] = []

    def flag(kind, severity, detail, ln=None, account=None, amount=None):
        anomalies.append({"type": kind, "severity": severity, "detail": detail,
                          "date": ln["date"] if ln else "", "txn_id": ln["txn_id"] if ln else "",
                          "doc_num": ln["doc_num"] if ln else "", "txn_type": ln["txn_type"] if ln else "",
                          "account": account or (ln["account_name"] if ln else ""),
                          "amount": round(amount if amount is not None else (ln["amt"] if ln else 0), 2)})

    # --- account usage -----------------------------------------------------
    use = defaultdict(lambda: {"lines": 0, "txns": set(), "debits": 0.0, "credits": 0.0, "first": None, "last": None,
                               "types": Counter(), "parties": Counter(), "counter": Counter(), "months": set(), "manual": 0})
    for tid, lines in txns.items():
        names = Counter(ln["account_name"] for ln in lines)
        for ln in lines:
            u = use[ln["account_id"]]
            u["lines"] += 1
            u["txns"].add(tid)
            u["debits"] += num(ln["debit"])
            u["credits"] += num(ln["credit"])
            u["first"] = min(filter(None, [u["first"], ln["d"]]))
            u["last"] = max(filter(None, [u["last"], ln["d"]]))
            u["types"][ln["txn_type"]] += 1
            if ln["counterparty"]:
                u["parties"][ln["counterparty"]] += 1
            u["months"].add(ln["date"][:7])
            u["manual"] += ln["is_adjusting"] == "true"
            for other in names:
                if other != ln["account_name"]:
                    u["counter"][other] += 1

    def top(c: Counter, n=3):
        return "; ".join(f"{k} ({v})" for k, v in c.most_common(n))

    usage_rows = []
    for a in accounts:
        u = use.get(a["account_id"])
        net = (u["debits"] - u["credits"]) if u else 0.0
        usage_rows.append({
            "account_id": a["account_id"], "number": a["number"], "name": a["full_name"] or a["name"],
            "class": a["class"], "role": a["role"], "erp_type": a["erp_type"], "active": a["active"],
            "lines": u["lines"] if u else 0, "txns": len(u["txns"]) if u else 0,
            "debits": round(u["debits"], 2) if u else 0, "credits": round(u["credits"], 2) if u else 0,
            "net": round(net, 2), "months_active": len(u["months"]) if u else 0,
            "first": u["first"] or "" if u else "", "last": u["last"] or "" if u else "",
            "manual_je_lines": u["manual"] if u else 0, "txn_types": top(u["types"]) if u else "",
            "top_counterparties": top(u["parties"]) if u else "", "top_counter_accounts": top(u["counter"]) if u else "",
        })
        name = a["full_name"] or a["name"]
        is_active = str(a["active"]).lower() in ("true", "1", "t", "yes")
        if not u and is_active:
            flag("unused_account", "info", "Active account with no activity in period", account=name, amount=0)
        if u and not is_active:
            flag("inactive_account_activity", "medium", f"{u['lines']} lines posted to an inactive account", account=name, amount=net)
        if u and SUSPENSE.search(name) and abs(net) >= 0.01:
            flag("suspense_or_clearing_balance", "high", "Suspense/clearing/opening-balance style account carries net activity", account=name, amount=net)
        if u and a["class"] == "income" and net > MATERIAL:
            flag("income_account_net_debit", "medium", "Income account has a net debit for the period", account=name, amount=net)
        if u and a["class"] == "expense" and net < -MATERIAL:
            flag("expense_account_net_credit", "medium", "Expense account has a net credit for the period", account=name, amount=net)
        for pattern, ok in NAME_CLASS_HINTS:
            if pattern.search(name) and a["class"] and a["class"] not in ok and not re.search(r"income tax|interest", name, re.I):
                flag("name_type_mismatch", "medium", f"Name suggests {'/'.join(sorted(ok))} but account class is {a['class']} ({a['erp_type']})", account=name, amount=net)
                break

    seen = {}
    for a in accounts:
        key = _norm(a["name"])
        for other_key, other in seen.items():
            if key and (key == other_key or difflib.SequenceMatcher(None, key, other_key).ratio() > 0.9):
                flag("duplicate_account_names", "medium", f"Near-duplicate of '{other['name']}' ({other['number']})", account=a["name"], amount=0)
                break
        seen[key] = a

    # --- transaction-level tests ------------------------------------------
    for tid, lines in txns.items():
        bal = sum(ln["amt"] for ln in lines)
        if abs(bal) > 0.01:
            flag("unbalanced_transaction", "high", f"Lines net to {bal:.2f}", lines[0], amount=bal)
        first = lines[0]
        size = sum(num(ln["debit"]) for ln in lines)
        if first["is_adjusting"] == "true":
            if size >= MATERIAL and size % 100 == 0:
                flag("round_manual_journal", "low", "Round-number manual journal (estimate or plug?)", first, amount=size)
            if first["d"].weekday() >= 5:
                flag("weekend_manual_journal", "low", "Manual journal dated on a weekend", first, amount=size)
        created = _d(first["created_date"])
        if created and (created - first["d"]).days > 45:
            flag("backdated_entry", "medium", f"Entered {(created - first['d']).days} days after transaction date", first, amount=size)

    by_key = defaultdict(list)
    for ln in gl:
        if ln["counterparty"] and ln["role"] in ("ap", "ar") and ln["is_adjusting"] != "true":
            by_key[(ln["counterparty"], ln["account_id"], round(abs(ln["amt"]), 2), ln["amt"] > 0)].append(ln)
    for key, lines in by_key.items():
        lines.sort(key=lambda x: x["d"])
        for a, b in zip(lines, lines[1:]):
            if a["txn_id"] != b["txn_id"] and (b["d"] - a["d"]).days <= 3 and key[2] >= 50:
                flag("possible_duplicate", "medium", f"Same party/amount/account as txn {a['txn_id']} ({a['date']})", b)

    # --- coding consistency -------------------------------------------------
    coding = defaultdict(Counter)
    coding_by_year = defaultdict(lambda: defaultdict(Counter))
    for ln in gl:
        if ln["counterparty"] and ln["class"] in ("income", "expense", "asset") and ln["role"] == "other":
            coding[ln["counterparty"]][ln["account_name"]] += 1
            coding_by_year[ln["counterparty"]][ln["date"][:4]][ln["account_name"]] += 1
    coding_rows, drift_rows = [], []
    for party, c in coding.items():
        total = sum(c.values())
        acct_name, n = c.most_common(1)[0]
        share = n / total
        coding_rows.append({"counterparty": party, "lines": total, "accounts_used": len(c), "dominant_account": acct_name,
                            "dominant_share": round(share, 2), "inconsistent": total >= 3 and share < 0.8,
                            "distribution": top(c, 5)})
        years = sorted(coding_by_year[party])
        doms = [(y, coding_by_year[party][y].most_common(1)[0][0]) for y in years]
        for (y1, a1), (y2, a2) in zip(doms, doms[1:]):
            if a1 != a2:
                drift_rows.append({"counterparty": party, "from_year": y1, "from_account": a1, "to_year": y2, "to_account": a2})
    coding_rows.sort(key=lambda r: (not r["inconsistent"], -r["lines"]))

    # --- basis, size and dimension signals ---------------------------------
    def share(pred_lines, role):
        hits = [t for t in pred_lines if any(ln["role"] == role for ln in txns[t])]
        return round(len(hits) / len(pred_lines), 2) if pred_lines else None

    income_txns = [t for t, ls in txns.items() if any(ln["class"] == "income" for ln in ls)]
    expense_txns = [t for t, ls in txns.items() if any(ln["class"] == "expense" for ln in ls)]
    month_end_adj = [ls[0] for ls in txns.values() if ls[0]["is_adjusting"] == "true"
                     and (ls[0]["d"] + timedelta(days=1)).day == 1]
    reversals = 0
    by_acct_amt = defaultdict(list)
    for ln in gl:
        by_acct_amt[(ln["account_id"], round(ln["amt"], 2))].append(ln["d"])
    for first in month_end_adj:
        for ln in txns[first["txn_id"]]:
            if any(0 < (d - ln["d"]).days <= 5 for d in by_acct_amt.get((ln["account_id"], round(-ln["amt"], 2)), [])):
                reversals += 1
                break

    years = defaultdict(lambda: {"income": 0.0, "expense": 0.0, "txns": set()})
    for ln in gl:
        y = years[ln["date"][:4]]
        y["txns"].add(ln["txn_id"])
        if ln["class"] == "income":
            y["income"] -= ln["amt"]
        elif ln["class"] == "expense":
            y["expense"] += ln["amt"]
    pl_lines = [ln for ln in gl if ln["class"] in ("income", "expense")]
    dim_cov = Counter(k.split("=")[0] for ln in pl_lines for k in ln["dimensions"].split(";") if "=" in k)

    signals = {
        "erp": book.erp,
        "period": {"first": min((ln["date"] for ln in gl), default=""), "last": max((ln["date"] for ln in gl), default="")},
        "erp_settings_excerpt": _settings_excerpt(settings),
        "basis": {
            "income_txns_via_ar": share(income_txns, "ar"),
            "income_txns_direct_to_bank": share(income_txns, "bank"),
            "expense_txns_via_ap": share(expense_txns, "ap"),
            "expense_txns_direct_bank_or_card": round(((share(expense_txns, "bank") or 0) + (share(expense_txns, "credit_card") or 0)), 2),
            "accrual_type_accounts_active": sorted({r["name"] for r in usage_rows if r["lines"] and ACCRUAL_NAMES.search(r["name"])}),
            "depreciation_months": len({ln["date"][:7] for ln in gl if DEPRECIATION.search(ln["account_name"] or "")}),
            "month_end_manual_journals": len(month_end_adj),
            "month_end_journals_reversed_next_month": reversals,
        },
        "size": {
            "by_year": {y: {"income": round(v["income"], 2), "expense": round(v["expense"], 2), "txns": len(v["txns"])}
                        for y, v in sorted(years.items())},
            "accounts_total": len(accounts),
            "accounts_active_with_activity": sum(1 for r in usage_rows if r["lines"]),
            "distinct_customers": len({ln["counterparty"] for ln in gl if ln["counterparty_type"] == "customer"}),
            "distinct_vendors": len({ln["counterparty"] for ln in gl if ln["counterparty_type"] == "vendor"}),
            "payroll_activity": any(PAYROLL.search(ln["account_name"] or "") for ln in gl),
        },
        "dimension_coverage_on_pl_lines": {k: round(v / len(pl_lines), 2) for k, v in dim_cov.items()} if pl_lines else {},
        "anomaly_counts": dict(Counter(a["type"] for a in anomalies)),
        "inconsistent_counterparties": sum(1 for r in coding_rows if r["inconsistent"]),
        "coding_drift_events": len(drift_rows),
    }

    write_csv(out / "account_usage.csv", list(usage_rows[0]) if usage_rows else ["account_id"], usage_rows)
    write_csv(out / "counterparty_coding.csv", ["counterparty", "lines", "accounts_used", "dominant_account",
                                                "dominant_share", "inconsistent", "distribution"], coding_rows)
    write_csv(out / "coding_drift.csv", ["counterparty", "from_year", "from_account", "to_year", "to_account"], drift_rows)
    sev = {"high": 0, "medium": 1, "low": 2, "info": 3}
    anomalies.sort(key=lambda a: (sev[a["severity"]], -abs(a["amount"])))
    write_csv(out / "anomalies.csv", ["severity", "type", "detail", "account", "date", "txn_id", "doc_num", "txn_type", "amount"], anomalies)
    (out / "signals.json").write_text(json.dumps(signals, indent=2, default=str))
    (out / "summary.md").write_text(_summary(book, signals, usage_rows, coding_rows, anomalies))
    print(f"Profiled {len(gl)} lines / {len(txns)} txns -> {out}")
    return signals


def _settings_excerpt(s: Dict) -> Dict:
    """Pull basis- and control-relevant settings (QBO Preferences, Xero Organisation)."""
    keep = {}
    for path in (("ReportPrefs", "ReportBasis"), ("AccountingInfoPrefs", "BookCloseDate"), ("AccountingInfoPrefs", "ClassTrackingPerTxnLine"),
                 ("AccountingInfoPrefs", "TrackDepartments"), ("AccountingInfoPrefs", "FirstMonthOfFiscalYear"),
                 ("AccountingInfoPrefs", "TaxYearMonth"), ("CurrencyPrefs", "MultiCurrencyEnabled"),
                 ("SalesFormsPrefs", "DefaultTerms"), ("VendorAndPurchasesPrefs", "BillableExpenseTracking")):
        v = s
        for p in path:
            v = v.get(p) if isinstance(v, dict) else None
        if v is not None:
            keep[".".join(path)] = v
    for k in ("OrganisationType", "CountryCode", "BaseCurrency", "FinancialYearEndDay", "FinancialYearEndMonth",
              "PeriodLockDate", "EndOfYearLockDate", "SalesTaxBasis", "TaxNumber", "Class", "Edition"):
        if k in s:
            keep[k] = "set" if k == "TaxNumber" else s[k]
    return keep


def _summary(book, sig, usage, coding, anomalies) -> str:
    b, z = sig["basis"], sig["size"]
    lines = [f"# Profile summary: {book.slug} ({book.erp})", "",
             f"Period analysed: {sig['period']['first']} → {sig['period']['last']}. Generated by `python -m engine profile`.", "",
             "## Basis signals", "", "| Signal | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sig["erp_settings_excerpt"].items()]
    lines += [f"| {k} | {v} |" for k, v in b.items()]
    lines += ["", "## Size", "", "| Year | Income | Expense | Txns |", "|---|---|---|---|"]
    lines += [f"| {y} | {v['income']:,.0f} | {v['expense']:,.0f} | {v['txns']} |" for y, v in z["by_year"].items()]
    lines += ["", f"Accounts: {z['accounts_total']} ({z['accounts_active_with_activity']} with activity). "
              f"Customers: {z['distinct_customers']}. Vendors: {z['distinct_vendors']}. Payroll activity: {z['payroll_activity']}.",
              f"Dimension coverage on P&L lines: {sig['dimension_coverage_on_pl_lines'] or 'none'}.", "",
              "## Anomalies by type", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(sig["anomaly_counts"].items(), key=lambda kv: -kv[1])] or ["- none"]
    lines += ["", "## Top 15 anomalies", "", "| Sev | Type | Account | Date | Doc/Txn | Amount | Detail |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {a['severity']} | {a['type']} | {a['account']} | {a['date']} | {a['doc_num'] or a['txn_id']} | {a['amount']:,.2f} | {a['detail']} |"
              for a in anomalies[:15]]
    lines += ["", f"## Inconsistent counterparty coding ({sig['inconsistent_counterparties']})", "",
              "| Counterparty | Lines | Dominant (share) | Distribution |", "|---|---|---|---|"]
    lines += [f"| {r['counterparty']} | {r['lines']} | {r['dominant_account']} ({r['dominant_share']:.0%}) | {r['distribution']} |"
              for r in coding if r["inconsistent"]][:20]
    lines += ["", "Details: account_usage.csv, counterparty_coding.csv, coding_drift.csv, anomalies.csv, signals.json.", ""]
    return "\n".join(lines)
