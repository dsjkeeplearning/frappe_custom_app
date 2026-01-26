# Copyright (c) 2026
# License: See license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}

	validate_filters(filters)

	budget, base_annual_budget = get_budget(filters)
	rows = []

	# Initial new budget link = selected budget
	current_new_budget_link = budget.name

	reallocation = get_reallocation_by_new_link(current_new_budget_link)

	# CASE: No Budget Reallocation
	if not reallocation:
		rows.append(make_empty_row(base_annual_budget, current_new_budget_link))
		return get_columns(), rows

	last_new_annual_budget = None
    
	while reallocation:
		rows.append({
			"month": reallocation.month or "-",
			"old_budget": reallocation.current_budget or "-",
			"new_budget": reallocation.new_budget or "-",
			"old_annual_budget": reallocation.total_annual_budget or "-",
			"new_annual_budget": reallocation.new_total_annual_budget or "-",
			"reason": reallocation.reason or "-",
			"old_budget_link": reallocation.old_budget_link or "-",
			"new_budget_link": current_new_budget_link,
            "approver": reallocation.approver or "-",
            "approval_date": reallocation.approval_date or "-",
		})

		last_new_annual_budget = reallocation.total_annual_budget

		# Move backward
		current_new_budget_link = reallocation.old_budget_link
		reallocation = get_reallocation_by_new_link(current_new_budget_link)

	# Terminal row
	rows.append(make_empty_row(last_new_annual_budget, current_new_budget_link))

	return get_columns(), rows

# ========================================================
# Helper Functions
# ========================================================

def validate_filters(filters):
    required_filters = ["company", "cost_center", "fiscal_year", "account"]

    for field in required_filters:
        if not filters.get(field):
            frappe.throw(_("Missing required filter: {0}").format(field))


def get_budget(filters):
	"""
	Validate budget existence and return it
	"""
	budgets = frappe.get_all(
		"Budget",
		{
			"company": filters.get("company"),
			"cost_center": filters.get("cost_center"),
			"fiscal_year": filters.get("fiscal_year"),
			"docstatus": 1
		},
		["name"],
	)
	print(budgets)
	for budget in budgets:
		budget_amount = frappe.db.get_value("Budget Account",
			{
				"parent": budget.name,
				"account": filters.get("account")
			},
			["budget_amount"]
		)
		if budget_amount:
			budget_doc = frappe.get_doc("Budget", budget)
			return budget_doc, budget_amount
	frappe.throw(
				_("No Budget exists for selected Company, Cost Center, Fiscal Year and Account")
			)

def get_reallocation_by_new_link(budget_name):
    """
    Fetch Budget Reallocation using new_budget_link
    """
    if not budget_name:
        return None

    return frappe.db.get_value(
        "Budget Reallocation",
        {
            "new_budget_link": budget_name,
            "docstatus": 1
        },
        [
            "name",
            "month",
            "current_budget",
            "new_budget",
            "total_annual_budget",
            "new_total_annual_budget",
            "reason",
            "old_budget_link",
            "approver",
            "approval_date"
        ],
        as_dict=True
    )


def make_empty_row(annual_budget, new_budget_link):
    """
    Terminal / No-reallocation row
    """
    return {
        "month": "-",
        "old_budget": "-",
        "new_budget": "-",
        "old_annual_budget": "-",
        "new_annual_budget": annual_budget,
        "reason": "-",
        "old_budget_link": "-",
		"new_budget_link": new_budget_link,
        "approver": "-",
        "approval_date": "-"
    }


def get_columns():
    return [
        {
            "label": _("Month"),
            "fieldname": "month",
            "fieldtype": "Data",
            "width": 100
        },
        {
            "label": _("Old Budget"),
            "fieldname": "old_budget",
            "fieldtype": "Currency",
            "width": 120
        },
        {
            "label": _("New Budget"),
            "fieldname": "new_budget",
            "fieldtype": "Currency",
            "width": 120
        },
        {
            "label": _("Old Annual Budget"),
            "fieldname": "old_annual_budget",
            "fieldtype": "Currency",
            "width": 150
        },
        {
            "label": _("New Annual Budget"),
            "fieldname": "new_annual_budget",
            "fieldtype": "Currency",
            "width": 150
        },
        {
            "label": _("Reason"),
            "fieldname": "reason",
            "fieldtype": "Data",
            "width": 200
        },
        {
            "label": _("Old Budget Link"),
            "fieldname": "old_budget_link",
            "fieldtype": "Link",
            "options": "Budget",
            "width": 180
        },
        {
			"label": _("New Budget Link"),
			"fieldname": "new_budget_link",
			"fieldtype": "Link",
			"options": "Budget",
			"width": 180
		},
        {
              "label": _("Approver"),
              "fieldname": "approver",
              "fieldtype": "Link",
              "options": "User",
              "width": 150
        },
        {
              "label": _("Approval Date"),
              "fieldname": "approval_date",
              "fieldtype": "Datetime",
              "width": 150
        }
    ]