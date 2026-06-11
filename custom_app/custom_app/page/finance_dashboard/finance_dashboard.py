import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate, add_months, get_first_day, get_last_day
from datetime import date


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _period_dates(period="month", date_from=None, date_to=None):
    if period == "custom" and date_from and date_to:
        return getdate(date_from), getdate(date_to)
    today = getdate(nowdate())
    if period == "month":
        return get_first_day(today), get_last_day(today)
    elif period == "quarter":
        qm = ((today.month - 1) // 3) * 3 + 1
        start = date(today.year, qm, 1)
        return start, get_last_day(add_months(start, 2))
    else:  # year
        return date(today.year, 1, 1), date(today.year, 12, 31)


# ─────────────────────────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_filter_options():
    companies = frappe.db.sql("SELECT name FROM `tabCompany` ORDER BY name", as_dict=True)
    cost_centers = frappe.db.sql(
        "SELECT name FROM `tabCost Center` WHERE is_group = 0 ORDER BY name", as_dict=True
    )
    fiscal_years = frappe.db.sql(
        "SELECT name FROM `tabFiscal Year` WHERE disabled = 0 ORDER BY year_start_date DESC",
        as_dict=True,
    )
    suppliers = frappe.db.sql("SELECT name FROM `tabSupplier` ORDER BY name", as_dict=True)
    return {
        "companies": [r.name for r in companies],
        "cost_centers": [r.name for r in cost_centers],
        "fiscal_years": [r.name for r in fiscal_years],
        "suppliers": [r.name for r in suppliers],
    }


# ─────────────────────────────────────────────────────────────────
# 1. CREDITOR (SUPPLIER) AGEING DISTRIBUTION
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_creditor_ageing(company=None, date_from=None, date_to=None, ageing_based_on="posting_date"):
    today = getdate(date_to) if date_to else getdate(nowdate())

    ew, args = [], {"today": today}
    if company:
        ew.append("pi.company = %(company)s")
        args["company"] = company
    if date_from:
        ew.append(f"pi.{ageing_based_on} >= %(date_from)s")
        args["date_from"] = date_from
    if date_to:
        ew.append(f"pi.{ageing_based_on} <= %(date_to)s")
        args["date_to"] = date_to

    where = (" AND " + " AND ".join(ew)) if ew else ""

    rows = frappe.db.sql(f"""
        SELECT
            pi.name,
            pi.supplier,
            pi.supplier_name,
            pi.{ageing_based_on} AS base_date,
            pi.grand_total,
            pi.outstanding_amount,
            DATEDIFF(%(today)s, pi.{ageing_based_on}) AS age_days
        FROM `tabPurchase Invoice` pi
        WHERE pi.docstatus = 1
          AND pi.outstanding_amount > 0
          {where}
        ORDER BY age_days DESC
    """, args, as_dict=True)

    buckets = {"0-30": 0, "31-60": 0, "61-90": 0, "91-120": 0, "120+": 0}
    suppliers_in_bucket = {"0-30": [], "31-60": [], "61-90": [], "91-120": [], "120+": []}
    total_outstanding = 0
    supplier_totals = {}

    for r in rows:
        age = r.age_days or 0
        amt = flt(r.outstanding_amount)
        total_outstanding += amt

        if age <= 30:
            key = "0-30"
        elif age <= 60:
            key = "31-60"
        elif age <= 90:
            key = "61-90"
        elif age <= 120:
            key = "91-120"
        else:
            key = "120+"

        buckets[key] += amt
        suppliers_in_bucket[key].append(r.supplier_name or r.supplier)

        supplier_totals.setdefault(r.supplier, {"name": r.supplier_name or r.supplier, "amount": 0, "count": 0})
        supplier_totals[r.supplier]["amount"] += amt
        supplier_totals[r.supplier]["count"] += 1

    chart_data = [
        {"label": k, "amount": round(v, 2), "suppliers": len(set(suppliers_in_bucket[k]))}
        for k, v in buckets.items()
    ]

    top_suppliers = sorted(supplier_totals.values(), key=lambda x: x["amount"], reverse=True)[:5]

    return {
        "chart_data": chart_data,
        "total_outstanding": round(total_outstanding, 2),
        "invoice_count": len(rows),
        "top_suppliers": top_suppliers,
        "ageing_based_on": ageing_based_on,
        "as_on_date": str(today),
    }


# ─────────────────────────────────────────────────────────────────
# 2. EXPENSE VS BUDGET  (from Budget Committed Actual Report)
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_expense_vs_budget(company=None, fiscal_year=None, cost_center=None):
    """
    Delegates to the Budget Committed Actual Report's execute() and
    aggregates month-columns into per-account totals.

    Report columns pattern (per month in FY):
        {mon}_budget   – allocated budget
        {mon}_mr       – PR / EC raised (committed)
        {mon}_actual   – Finance-Approved EC + submitted PI actual
    """
    if not fiscal_year:
        fiscal_year = frappe.db.get_value(
            "Fiscal Year",
            {"year_start_date": ["<=", nowdate()], "year_end_date": [">=", nowdate()], "disabled": 0},
            "name",
        )
    if not fiscal_year:
        return {"rows": [], "total_budget": 0, "total_actual": 0, "total_committed": 0,
                "fiscal_year": None}

    filters = frappe._dict(
        company=company or frappe.defaults.get_user_default("Company"),
        fiscal_year=fiscal_year,
        cost_center=cost_center or None,
    )

    # Import and run the report directly
    from custom_app.custom_app.report.budget_committed_actual_report.budget_committed_actual_report import execute
    columns, data = execute(filters)

    # Determine which fieldnames belong to budget / mr / actual
    budget_fields, mr_fields, actual_fields = [], [], []
    for col in columns:
        fn = col.get("fieldname", "")
        if fn.endswith("_budget"):
            budget_fields.append(fn)
        elif fn.endswith("_mr"):
            mr_fields.append(fn)
        elif fn.endswith("_actual"):
            actual_fields.append(fn)

    rows = []
    total_budget = total_actual = total_committed = 0

    for row in data:
        account = row.get("account") or row.get("Account") or ""
        if not account:
            continue

        budget  = sum(flt(row.get(f, 0)) for f in budget_fields)
        committed = sum(flt(row.get(f, 0)) for f in mr_fields)
        actual  = sum(flt(row.get(f, 0)) for f in actual_fields)
        variance = budget - actual
        utilisation = round((actual / budget) * 100, 1) if budget > 0 else 0

        rows.append({
            "account": account,
            "budget": round(budget, 2),
            "committed": round(committed, 2),
            "actual": round(actual, 2),
            "variance": round(variance, 2),
            "utilisation_pct": utilisation,
        })
        total_budget    += budget
        total_actual    += actual
        total_committed += committed

    rows.sort(key=lambda x: x["utilisation_pct"], reverse=True)

    return {
        "rows": rows,
        "total_budget": round(total_budget, 2),
        "total_actual": round(total_actual, 2),
        "total_committed": round(total_committed, 2),
        "total_variance": round(total_budget - total_actual, 2),
        "total_utilisation": round((total_actual / total_budget) * 100, 1) if total_budget > 0 else 0,
        "fiscal_year": fiscal_year,
    }


# ─────────────────────────────────────────────────────────────────
# 3. NON-BUDGETED PAYMENTS
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_non_budgeted_payments(company=None, fiscal_year=None, cost_center=None):
    if not fiscal_year:
        fiscal_year = frappe.db.get_value(
            "Fiscal Year",
            {"year_start_date": ["<=", nowdate()], "year_end_date": [">=", nowdate()], "disabled": 0},
            "name",
        )
    if not fiscal_year:
        return {"rows": [], "total_amount": 0}

    fy_doc = frappe.get_doc("Fiscal Year", fiscal_year)
    fy_start = fy_doc.year_start_date
    fy_end = fy_doc.year_end_date

    b_ew, b_args = ["b.fiscal_year = %(fiscal_year)s", "b.docstatus = 1"], {"fiscal_year": fiscal_year}
    if company:
        b_ew.append("b.company = %(company)s")
        b_args["company"] = company
    if cost_center:
        b_ew.append("b.cost_center = %(cost_center)s")
        b_args["cost_center"] = cost_center

    budgeted_accounts = frappe.db.sql(f"""
        SELECT DISTINCT ba.account
        FROM `tabBudget Account` ba
        JOIN `tabBudget` b ON ba.parent = b.name
        WHERE {" AND ".join(b_ew)}
    """, b_args, as_dict=True)

    budgeted_set = {r.account for r in budgeted_accounts}

    rows = []

    # Purchase Invoices
    pi_ew = ["pi.docstatus = 1", "pi.posting_date BETWEEN %(fy_start)s AND %(fy_end)s"]
    pi_args = {"fy_start": fy_start, "fy_end": fy_end}
    if company:
        pi_ew.append("pi.company = %(company)s")
        pi_args["company"] = company
    if cost_center:
        pi_ew.append("pii.cost_center = %(cost_center)s")
        pi_args["cost_center"] = cost_center

    pi_rows = frappe.db.sql(f"""
        SELECT
            pi.name AS document,
            'Purchase Invoice' AS doctype,
            pi.supplier_name AS party,
            pi.posting_date,
            pii.expense_account AS account,
            pii.cost_center,
            SUM(pii.base_net_amount) AS amount
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE {" AND ".join(pi_ew)}
        GROUP BY pi.name, pii.expense_account
    """, pi_args, as_dict=True)

    for r in pi_rows:
        if r.account not in budgeted_set:
            rows.append(r)

    # Expense Claims (Finance Approved)
    ec_ew = [
        "ec.docstatus = 1",
        "ec.workflow_state = 'Finance Approved'",
        "ec.posting_date BETWEEN %(fy_start)s AND %(fy_end)s",
    ]
    ec_args = {"fy_start": fy_start, "fy_end": fy_end}
    if company:
        ec_ew.append("ec.company = %(company)s")
        ec_args["company"] = company
    if cost_center:
        ec_ew.append("ecd.cost_center = %(cost_center)s")
        ec_args["cost_center"] = cost_center

    ec_rows = frappe.db.sql(f"""
        SELECT
            ec.name AS document,
            'Expense Claim' AS doctype,
            ec.employee_name AS party,
            ec.posting_date,
            ecd.default_account AS account,
            ecd.cost_center,
            SUM(ecd.amount) AS amount
        FROM `tabExpense Claim Detail` ecd
        JOIN `tabExpense Claim` ec ON ec.name = ecd.parent
        WHERE {" AND ".join(ec_ew)}
        GROUP BY ec.name, ecd.default_account
    """, ec_args, as_dict=True)

    for r in ec_rows:
        if r.account not in budgeted_set:
            rows.append(r)

    rows.sort(key=lambda x: flt(x.amount), reverse=True)

    total_amount = sum(flt(r.amount) for r in rows)

    account_summary = {}
    for r in rows:
        a = r.account or "Unknown"
        account_summary.setdefault(a, {"account": a, "amount": 0, "count": 0})
        account_summary[a]["amount"] += flt(r.amount)
        account_summary[a]["count"] += 1

    account_summary_list = sorted(account_summary.values(), key=lambda x: x["amount"], reverse=True)

    return {
        "rows": rows[:50],
        "total_amount": round(total_amount, 2),
        "total_count": len(rows),
        "account_summary": account_summary_list,
        "fiscal_year": fiscal_year,
    }


# ─────────────────────────────────────────────────────────────────
# 4. VENDOR CONCENTRATION RISK
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_vendor_concentration(company=None, fiscal_year=None, date_from=None, date_to=None, top_n=10):
    if fiscal_year and not (date_from and date_to):
        fy_doc = frappe.get_doc("Fiscal Year", fiscal_year)
        date_from = str(fy_doc.year_start_date)
        date_to = str(fy_doc.year_end_date)

    if not date_from:
        today = getdate(nowdate())
        date_from = str(date(today.year, 1, 1))
        date_to = str(today)

    ew, args = ["pi.docstatus = 1", "pi.posting_date BETWEEN %(date_from)s AND %(date_to)s"], {
        "date_from": date_from,
        "date_to": date_to,
    }
    if company:
        ew.append("pi.company = %(company)s")
        args["company"] = company

    where = " AND ".join(ew)

    supplier_spend = frappe.db.sql(f"""
        SELECT
            pi.supplier,
            pi.supplier_name,
            SUM(pi.grand_total) AS total_spend,
            COUNT(pi.name) AS invoice_count
        FROM `tabPurchase Invoice` pi
        WHERE {where}
        GROUP BY pi.supplier
        ORDER BY total_spend DESC
    """, args, as_dict=True)

    total_spend = sum(flt(r.total_spend) for r in supplier_spend)
    top_n = int(top_n)

    rows = []
    cumulative = 0
    for i, r in enumerate(supplier_spend):
        pct = round((flt(r.total_spend) / total_spend) * 100, 2) if total_spend > 0 else 0
        cumulative += pct
        rows.append({
            "rank": i + 1,
            "supplier": r.supplier,
            "supplier_name": r.supplier_name or r.supplier,
            "total_spend": round(flt(r.total_spend), 2),
            "invoice_count": r.invoice_count,
            "pct_of_total": pct,
            "cumulative_pct": round(cumulative, 2),
        })

    top3_spend = sum(flt(r.total_spend) for r in supplier_spend[:3])
    top3_pct = round((top3_spend / total_spend) * 100, 2) if total_spend > 0 else 0
    top_n_spend = sum(flt(r.total_spend) for r in supplier_spend[:top_n])
    top_n_pct = round((top_n_spend / total_spend) * 100, 2) if total_spend > 0 else 0

    risk_level = "High" if top3_pct > 40 else ("Medium" if top3_pct > 25 else "Low")

    chart_labels, chart_values = [], []
    for r in rows[:top_n]:
        chart_labels.append(r["supplier_name"])
        chart_values.append(r["total_spend"])
    if len(rows) > top_n:
        others = sum(r["total_spend"] for r in rows[top_n:])
        chart_labels.append("Others")
        chart_values.append(round(others, 2))

    return {
        "rows": rows,
        "total_spend": round(total_spend, 2),
        "top3_pct": top3_pct,
        "top_n_pct": top_n_pct,
        "top_n": top_n,
        "supplier_count": len(rows),
        "risk_level": risk_level,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "date_from": date_from,
        "date_to": date_to,
    }