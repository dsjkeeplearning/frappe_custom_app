# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, get_first_day, get_last_day, add_months

def execute(filters=None):
	employee = frappe.get_value(
		"Employee",
		{"user_id": frappe.session.user},
		["department", "company"],
		as_dict=True
	)
	if not employee or not employee.department:
		frappe.throw(_("Please set Department for the current user in Employee record"))
	dept = employee.department
	cost_center = frappe.get_value("Cost Center", {"custom_department": dept})
	if not cost_center:
		frappe.throw(_("Please set Cost Center for the Department: {0}".format(dept)))
	columns = get_columns(filters)
	data = get_data(filters, cost_center)
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

def get_data(filters, cost_center):
    """Fetch data for the report"""
    fiscal_year = frappe.get_doc("Fiscal Year", filters.get("fiscal_year"))
    months = get_months_in_fiscal_year(fiscal_year)
    
    # Get all accounts with budgets
    accounts = get_accounts_with_budget(filters, cost_center)
    
    data = []
    
    for account in accounts:
        row = {"account": account}
        
        for month in months:
            month_name = month["month_name"].lower()
            
            # Get budget amount
            budget_amount = get_budget_amount(
                account, 
                cost_center,
                month["month_start"],
                month["month_end"],
                filters.get("company")
            )
            row[f"{month_name}_budget"] = budget_amount
        
        data.append(row)
    
    return data

def get_accounts_with_budget(filters, cost_center):
    conditions = [
        "b.fiscal_year = %(fiscal_year)s",
        "b.docstatus = 1",
        "b.cost_center = %(cost_center)s"
    ]

    if filters.get("company"):
        conditions.append("b.company = %(company)s")

    return frappe.db.sql_list(f"""
        SELECT DISTINCT ba.account
        FROM `tabBudget Account` ba
        INNER JOIN `tabBudget` b ON ba.parent = b.name
        WHERE {" AND ".join(conditions)}
        ORDER BY ba.account
    """, {
        "fiscal_year": filters.get("fiscal_year"),
        "cost_center": cost_center,
        "company": filters.get("company")
    })

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