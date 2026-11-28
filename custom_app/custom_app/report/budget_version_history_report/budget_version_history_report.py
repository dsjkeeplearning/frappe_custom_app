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
		# A transfer within one account changes two of its months: one row each.
		for month in reallocation.get("months") or [reallocation]:
			rows.append({
				"month": month.month or "-",
				"old_budget": "-" if month.current_budget is None else month.current_budget,
				"new_budget": "-" if month.new_budget is None else month.new_budget,
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

    reallocation = frappe.db.get_value(
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

    return (
        reallocation
        or get_transfer_by_new_link(budget_name)
        or get_mid_year_upload_by_new_link(budget_name)
    )


def get_transfer_by_new_link(budget_name):
    """
    A transfer that amended this Budget, from the side the Budget was on, in the
    shape of a reallocation. A transfer within one account changed two of its
    months, so it has a row for each.
    """
    fields = [
        "name",
        "reallocation_type",
        "from_month",
        "to_month",
        "from_month_budget",
        "from_new_month_budget",
        "to_month_budget",
        "to_new_month_budget",
        "from_year_budget",
        "from_new_year_budget",
        "to_year_budget",
        "to_new_year_budget",
        "from_old_budget",
        "from_new_budget",
        "to_old_budget",
        "to_new_budget",
        "reason",
        "approver",
        "approval_date",
    ]
    for side in ("from", "to"):
        transfer = frappe.db.get_value(
            "Budget Reallocation",
            {f"{side}_new_budget": budget_name, "docstatus": 1},
            fields,
            as_dict=True,
        )
        if transfer:
            break
    else:
        return None

    giving = frappe._dict(
        month=transfer.from_month,
        current_budget=transfer.from_month_budget,
        new_budget=transfer.from_new_month_budget,
    )
    receiving = frappe._dict(
        month=transfer.to_month,
        current_budget=transfer.to_month_budget,
        new_budget=transfer.to_new_month_budget,
    )
    if transfer.from_new_budget == transfer.to_new_budget:
        months = [giving, receiving]
    else:
        months = [giving] if side == "from" else [receiving]

    return frappe._dict(
        name=transfer.name,
        months=months,
        total_annual_budget=transfer.get(f"{side}_year_budget"),
        new_total_annual_budget=transfer.get(f"{side}_new_year_budget"),
        reason="{0}: {1}".format(_(transfer.reallocation_type), transfer.reason),
        old_budget_link=transfer.get(f"{side}_old_budget"),
        approver=transfer.approver,
        approval_date=transfer.approval_date,
    )


def get_mid_year_upload_by_new_link(budget_name):
    """
    A budget revised by a Mid Year Budget Upload, in the shape of a reallocation
    """
    revision = frappe.db.get_value(
        "Mid Year Budget Upload Item",
        {
            "new_budget": budget_name,
            "status": "Revised",
            "docstatus": 1
        },
        ["parent", "old_budget", "old_annual_budget", "new_annual_budget"],
        as_dict=True
    )
    if not revision:
        return None

    upload = frappe.db.get_value(
        "Mid Year Budget Upload", revision.parent, ["owner", "modified"], as_dict=True
    )

    return frappe._dict(
        name=revision.parent,
        month=_("All (Mid Year)"),
        current_budget=None,
        new_budget=None,
        total_annual_budget=revision.old_annual_budget,
        new_total_annual_budget=revision.new_annual_budget,
        reason=_("Mid Year Budget Upload {0}").format(revision.parent),
        old_budget_link=revision.old_budget,
        approver=upload.owner,
        approval_date=upload.modified,
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