# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, get_first_day, get_last_day, add_months, nowdate

# Reuse the budget / actual maths from the Committed vs Actual report so both
# reports always agree on what a month's budget and spend are.
from custom_app.custom_app.report.budget_committed_actual_report.budget_committed_actual_report import (
    get_accounts_with_budget,
    get_actual_amount,
    get_budget_amount,
)


def execute(filters=None):
    fiscal_year = frappe.get_doc("Fiscal Year", filters.get("fiscal_year"))
    months = get_months_in_fiscal_year(fiscal_year)

    columns = get_columns(months)
    data = get_data(filters, months)

    return columns, data


def get_months_in_fiscal_year(fiscal_year):
    """
    Months of the fiscal year, stopping at the current month.

    Carry forward is only meaningful up to today — future months have no spend
    yet, so showing them would carry the full budget forward into empty columns.
    A past fiscal year is shown in full.
    """
    months = []
    start_date = getdate(fiscal_year.year_start_date)
    end_date = getdate(fiscal_year.year_end_date)

    today = getdate(nowdate())
    if start_date <= today <= end_date:
        end_date = get_last_day(today)

    current_date = get_first_day(start_date)

    while current_date <= end_date:
        months.append({
            "month_name": current_date.strftime("%B")[:3],
            "month_start": get_first_day(current_date),
            "month_end": get_last_day(current_date),
        })
        current_date = add_months(current_date, 1)

    return months


def get_columns(months):
    """
    One column per past month showing what was spent that month, and two
    columns for the current month: what has been spent, and the budget
    available to spend — this month's allocation plus everything unspent
    that rolled in from earlier months.
    """
    columns = [
        {
            "label": _("Account"),
            "fieldname": "account",
            "fieldtype": "Link",
            "options": "Account",
            "width": 260,
        }
    ]

    for month in months[:-1]:
        columns.append({
            "label": _(f"{month['month_name']} Budget / Utilised"),
            "fieldname": f"{month['month_name'].lower()}_utilised",
            "fieldtype": "Currency",
            "width": 160,
        })

    if months:
        current = months[-1]["month_name"]
        columns.append({
            "label": _(f"{current} Cumulative Budget"),
            "fieldname": f"{current.lower()}_available",
            "fieldtype": "Currency",
            "width": 175,
        })
        columns.append({
            "label": _(f"{current} Utilised"),
            "fieldname": f"{current.lower()}_utilised",
            "fieldtype": "Currency",
            "width": 140,
        })

    return columns


def get_data(filters, months):
    company = filters.get("company")
    cost_center = filters.get("cost_center")

    data = []

    for account in get_accounts_with_budget(filters):
        row = {"account": account}

        # unspent budget rolled in from the previous month
        carry_forward = 0

        for month in months:
            key = month["month_name"].lower()

            budget = flt(get_budget_amount(
                account, cost_center, month["month_start"], month["month_end"], company
            ), 2)

            utilised = flt(get_actual_amount(
                account, cost_center, month["month_start"], month["month_end"], company
            ), 2)

            # this month's allocation plus whatever rolled in
            available = flt(carry_forward + budget, 2)

            row[f"{key}_utilised"] = utilised
            row[f"{key}_available"] = available

            # whatever is left becomes next month's opening; a negative value is
            # kept on purpose so an overspend eats into the next month
            carry_forward = flt(available - utilised, 2)

        data.append(row)

    return data
