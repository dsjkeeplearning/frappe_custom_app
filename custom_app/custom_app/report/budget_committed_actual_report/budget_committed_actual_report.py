# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, get_first_day, get_last_day, add_months

def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data

def get_columns(filters):
    """Generate columns for each month in the fiscal year"""
    columns = [
        {
            "label": _("Account"),
            "fieldname": "account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 250
        }
    ]
    
    # Get fiscal year start and end dates
    fiscal_year = frappe.get_doc("Fiscal Year", filters.get("fiscal_year"))
    
    # Generate columns for each month
    months = get_months_in_fiscal_year(fiscal_year)
    
    for month in months:
        month_name = month["month_name"]
        
        # Budget column
        columns.append({
            "label": _(f"{month_name} Budget"),
            "fieldname": f"{month_name.lower()}_budget",
            "fieldtype": "Currency",
            "width": 120
        })
        
        # Material Request column
        columns.append({
            "label": _(f"{month_name} PR/EC Raised"),
            "fieldname": f"{month_name.lower()}_mr",
            "fieldtype": "Currency",
            "width": 120
        })
        
        # Actual Spent column
        columns.append({
            "label": _(f"{month_name} Actual"),
            "fieldname": f"{month_name.lower()}_actual",
            "fieldtype": "Currency",
            "width": 120
        })
    
    return columns

def get_months_in_fiscal_year(fiscal_year):
    """Get list of months in the fiscal year"""
    months = []
    start_date = getdate(fiscal_year.year_start_date)
    end_date = getdate(fiscal_year.year_end_date)
    
    current_date = get_first_day(start_date)
    
    while current_date <= end_date:
        months.append({
            "month_name": current_date.strftime("%B")[:3],  # Apr, May, Jun, etc.
            "month_start": get_first_day(current_date),
            "month_end": get_last_day(current_date)
        })
        current_date = add_months(current_date, 1)
    
    return months

def get_data(filters):
    """Fetch data for the report"""
    fiscal_year = frappe.get_doc("Fiscal Year", filters.get("fiscal_year"))
    months = get_months_in_fiscal_year(fiscal_year)
    
    # Get all accounts with budgets
    accounts = get_accounts_with_budget(filters)
    
    data = []
    
    for account in accounts:
        row = {"account": account}
        
        for month in months:
            month_name = month["month_name"].lower()
            
            # Get budget amount
            budget_amount = get_budget_amount(
                account, 
                filters.get("cost_center"),
                month["month_start"],
                month["month_end"],
                filters.get("company")
            )
            row[f"{month_name}_budget"] = budget_amount
            
            # Get material request amount
            mr_amount = get_material_request_amount(
                account,
                filters.get("cost_center"),
                month["month_start"],
                month["month_end"],
                filters.get("company")
            )
            row[f"{month_name}_mr"] = mr_amount
            
            # Get actual spent amount
            actual_amount = get_actual_amount(
                account,
                filters.get("cost_center"),
                month["month_start"],
                month["month_end"],
                filters.get("company")
            )
            row[f"{month_name}_actual"] = actual_amount
        
        data.append(row)
    
    return data

def get_accounts_with_budget(filters):
    """Get all accounts that have budgets"""
    conditions = ["b.fiscal_year = %(fiscal_year)s", "b.docstatus = 1"]
    
    if filters.get("cost_center"):
        conditions.append("b.cost_center = %(cost_center)s")
    
    if filters.get("company"):
        conditions.append("b.company = %(company)s")
    
    condition_str = " AND ".join(conditions)
    
    accounts = frappe.db.sql(f"""
        SELECT DISTINCT ba.account
        FROM `tabBudget Account` ba
        INNER JOIN `tabBudget` b ON ba.parent = b.name
        WHERE {condition_str}
        ORDER BY ba.account
    """, filters, as_dict=False)
    
    return [acc[0] for acc in accounts]

def get_budget_amount(account, cost_center, start_date, end_date, company):
    """Get budget amount for a specific account and month"""
    # Build conditions
    conditions = ["ba.account = %(account)s", "b.fiscal_year = %(fiscal_year)s", "b.docstatus = 1"]
    params = {"account": account}
    
    # Get fiscal year from the date range
    fiscal_year = frappe.db.get_value("Fiscal Year", 
        {"year_start_date": ["<=", start_date], "year_end_date": [">=", end_date]})
    params["fiscal_year"] = fiscal_year
    
    if cost_center:
        conditions.append("b.cost_center = %(cost_center)s")
        params["cost_center"] = cost_center
    
    if company:
        conditions.append("b.company = %(company)s")
        params["company"] = company
    
    condition_str = " AND ".join(conditions)
    
    # Get budget details including monthly distribution
    budget_data = frappe.db.sql(f"""
        SELECT ba.budget_amount, b.monthly_distribution
        FROM `tabBudget Account` ba
        INNER JOIN `tabBudget` b ON ba.parent = b.name
        WHERE {condition_str}
    """, params, as_dict=True)
    
    if not budget_data:
        return 0
    
    total_budget = 0
    for row in budget_data:
        budget_amount = flt(row.budget_amount)
        monthly_distribution = row.monthly_distribution
        
        if monthly_distribution:
            # Get the percentage for this specific month
            month_percentage = get_monthly_distribution_percentage(
                monthly_distribution, start_date
            )
            total_budget += budget_amount * month_percentage / 100
        else:
            # If no monthly distribution, divide equally by 12
            total_budget += budget_amount / 12
    
    return total_budget

def get_monthly_distribution_percentage(distribution_name, date):
    """Get percentage for a specific month from Monthly Distribution"""
    month_name = getdate(date).strftime("%B")
    
    percentage = frappe.db.get_value(
        "Monthly Distribution Percentage",
        {
            "parent": distribution_name,
            "month": month_name
        },
        "percentage_allocation"
    )
    
    return flt(percentage) if percentage else 0

def get_material_request_amount(account, cost_center, start_date, end_date, company):
    """Get material request amount for a specific account and month"""
    total_amount = 0
    
    # Get Material Request amount
    mr_conditions = ["mr.docstatus = 1", "mr.transaction_date BETWEEN %(start_date)s AND %(end_date)s"]
    
    if cost_center:
        mr_conditions.append("mri.cost_center = %(cost_center)s")
    
    if company:
        mr_conditions.append("mr.company = %(company)s")
    
    # Add account condition - linking through expense account
    mr_conditions.append("mri.expense_account = %(account)s")
    
    mr_condition_str = " AND ".join(mr_conditions)
    
    mr_amount = frappe.db.sql(f"""
        SELECT SUM(mri.amount) as total_amount
        FROM `tabMaterial Request Item` mri
        INNER JOIN `tabMaterial Request` mr ON mri.parent = mr.name
        WHERE {mr_condition_str}
    """, {
        "account": account,
        "cost_center": cost_center,
        "start_date": start_date,
        "end_date": end_date,
        "company": company
    }, as_dict=True)
    
    total_amount += flt(mr_amount[0].total_amount) if mr_amount and mr_amount[0].total_amount else 0
    
    # Get Expense Claim amount
    ec_conditions = ["ec.docstatus = 1", "ec.posting_date BETWEEN %(start_date)s AND %(end_date)s"]
    
    if cost_center:
        ec_conditions.append("ecd.cost_center = %(cost_center)s")
    
    if company:
        ec_conditions.append("ec.company = %(company)s")
    
    # Add account condition - linking through default account
    ec_conditions.append("ecd.default_account = %(account)s")
    
    ec_condition_str = " AND ".join(ec_conditions)
    
    ec_amount = frappe.db.sql(f"""
        SELECT SUM(ecd.amount) as total_amount
        FROM `tabExpense Claim Detail` ecd
        INNER JOIN `tabExpense Claim` ec ON ecd.parent = ec.name
        WHERE {ec_condition_str}
    """, {
        "account": account,
        "cost_center": cost_center,
        "start_date": start_date,
        "end_date": end_date,
        "company": company
    }, as_dict=True)
    
    total_amount += flt(ec_amount[0].total_amount) if ec_amount and ec_amount[0].total_amount else 0
    
    return total_amount

def get_actual_amount(account, cost_center, start_date, end_date, company):
    """
    Total Actual =
    Finance Approved Expense Claims
    + Submitted Purchase Invoices
    """
    total_actual = 0

    # -----------------------------
    # Expense Claim (Finance Approved)
    # -----------------------------
    ec_conditions = [
        "ec.docstatus = 1",
        "ec.workflow_state = 'Finance Approved'",
        "ec.posting_date BETWEEN %(start_date)s AND %(end_date)s",
        "ecd.default_account = %(account)s"
    ]

    if cost_center:
        ec_conditions.append("ecd.cost_center = %(cost_center)s")

    if company:
        ec_conditions.append("ec.company = %(company)s")

    ec_actual = frappe.db.sql(f"""
        SELECT SUM(ecd.amount) AS total_amount
        FROM `tabExpense Claim Detail` ecd
        INNER JOIN `tabExpense Claim` ec ON ec.name = ecd.parent
        WHERE {" AND ".join(ec_conditions)}
    """, {
        "account": account,
        "cost_center": cost_center,
        "start_date": start_date,
        "end_date": end_date,
        "company": company
    }, as_dict=True)

    total_actual += flt(ec_actual[0].total_amount) if ec_actual and ec_actual[0].total_amount else 0

    # -----------------------------
    # Purchase Invoice (Submitted)
    # -----------------------------
    pi_conditions = [
        "pi.docstatus = 1",
        "pi.posting_date BETWEEN %(start_date)s AND %(end_date)s",
        "pii.expense_account = %(account)s"
    ]

    if cost_center:
        pi_conditions.append("pii.cost_center = %(cost_center)s")

    if company:
        pi_conditions.append("pi.company = %(company)s")

    pi_actual = frappe.db.sql(f"""
        SELECT SUM(pii.base_net_amount) AS total_amount
        FROM `tabPurchase Invoice Item` pii
        INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE {" AND ".join(pi_conditions)}
    """, {
        "account": account,
        "cost_center": cost_center,
        "start_date": start_date,
        "end_date": end_date,
        "company": company
    }, as_dict=True)

    total_actual += flt(pi_actual[0].total_amount) if pi_actual and pi_actual[0].total_amount else 0

    return total_actual
