# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, formatdate

from custom_app.api.budget_control import (
	get_budget_settings,
	get_fiscal_year_months,
	get_monthly_consumption,
	get_pr_date_basis,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not (filters.company and filters.cost_center and filters.fiscal_year):
		return [], []

	settings = get_budget_settings()

	# Same switch the Material Request validation uses: when ticked a month can
	# only use its own budget, otherwise unused budget of earlier months rolls on.
	month_wise = bool(settings.get("restrict_pr_to_current_month_budget"))
	pr_dates = get_pr_date_basis(settings)

	months = get_fiscal_year_months(filters.fiscal_year)
	columns = get_columns(months, month_wise)
	data = get_data(filters, months, month_wise, pr_dates)

	return columns, data, get_message(month_wise, pr_dates)


def get_columns(months, month_wise):
	columns = [
		{
			"label": _("Account"),
			"fieldname": "account",
			"fieldtype": "Link",
			"options": "Account",
			"width": 260,
		},
		{
			"label": _("Annual Budget"),
			"fieldname": "annual_budget",
			"fieldtype": "Currency",
			"width": 140,
		},
	]

	if month_wise:
		labels = (_("{0} Budget"), _("{0} Consumed"), _("{0} Left"))
	else:
		labels = (_("Budget upto {0}"), _("Consumed upto {0}"), _("Left upto {0}"))

	for month in months:
		for label, suffix in zip(labels, ("budget", "consumed", "left"), strict=True):
			columns.append(
				{
					"label": label.format(_(month.label)),
					"fieldname": f"{month.fieldname}_{suffix}",
					"fieldtype": "Currency",
					"width": 140,
				}
			)

	return columns


def get_message(month_wise, pr_dates):
	if month_wise:
		mode = _(
			"<b>Restrict PR to Current Month Budget</b> is enabled in Budget Settings: every month"
			" shows only its own budget and consumption. <b>Left</b> is the lower of the month's own"
			" balance and the cumulative balance from the start of the fiscal year up to that month"
			" (shown in orange where the cumulative balance is the limit)."
		)
	else:
		mode = _(
			"<b>Restrict PR to Current Month Budget</b> is disabled in Budget Settings: every month"
			" shows the cumulative budget, consumption and balance from the start of the fiscal year"
			" up to that month."
		)

	if not pr_dates.use_transaction_date:
		dates = _("PRs are counted in the month of their Required By date.")
	elif pr_dates.effective_from:
		dates = _(
			"PRs raised before {0} are counted in the month of their Required By date, later PRs in"
			" the month they were raised."
		).format(formatdate(pr_dates.effective_from))
	else:
		dates = _(
			"PRs are counted in the month they were raised. Set <b>Transaction Date Check Effective"
			" From</b> in Budget Settings to count older PRs in their Required By month."
		)

	stopped = _("A stopped PR counts only for the part already ordered.")

	return f"{mode}<br>{dates} {stopped}"


def get_data(filters, months, month_wise, pr_dates):
	budgets = get_budgets(filters)
	if not budgets:
		return []

	distributions = get_distribution_percentages(budgets)
	consumption = get_monthly_consumption(filters.company, filters.cost_center, filters.fiscal_year, pr_dates)

	# account -> month name -> budget of that month
	monthly_budget = {}
	annual_budget = {}
	for budget in budgets:
		account_budget = monthly_budget.setdefault(budget.account, {})
		annual_budget[budget.account] = annual_budget.get(budget.account, 0) + flt(budget.budget_amount)

		for month in months:
			if budget.monthly_distribution:
				percentage = distributions.get((budget.monthly_distribution, month.name), 0)
			else:
				percentage = 100.0 / 12

			account_budget[month.name] = (
				account_budget.get(month.name, 0) + flt(budget.budget_amount) * flt(percentage) / 100
			)

	data = []
	for account in sorted(monthly_budget):
		row = {"account": account, "annual_budget": flt(annual_budget[account], 2)}
		running_budget = running_consumed = 0

		for month in months:
			budget = monthly_budget[account].get(month.name, 0)
			consumed = consumption.get((account, month.key), 0)

			running_budget += budget
			running_consumed += consumed
			cumulative_left = flt(running_budget - running_consumed, 2)

			if month_wise:
				# A PR has to pass two checks: the month's own budget, and
				# ERPNext's accumulated budget up to that month. Earlier months
				# may have used more than their own budget (PRs approved before
				# the monthly restriction, or counted in a later Required By
				# month), which leaves less than the month's own balance.
				left = flt(budget - consumed, 2)
				if cumulative_left < left:
					left = cumulative_left
					row[f"{month.fieldname}_capped"] = 1
			else:
				budget, consumed, left = running_budget, running_consumed, cumulative_left

			row[f"{month.fieldname}_budget"] = flt(budget, 2)
			row[f"{month.fieldname}_consumed"] = flt(consumed, 2)
			row[f"{month.fieldname}_left"] = left

		data.append(row)

	return data


def get_budgets(filters):
	return frappe.db.sql(
		"""
		select ba.account, ba.budget_amount, b.monthly_distribution
		from `tabBudget` b
		inner join `tabBudget Account` ba on ba.parent = b.name
		where b.docstatus = 1
			and b.company = %(company)s
			and b.fiscal_year = %(fiscal_year)s
			and b.budget_against = 'Cost Center'
			and b.cost_center = %(cost_center)s
		""",
		filters,
		as_dict=True,
	)


def get_distribution_percentages(budgets):
	"""(monthly distribution, month name) -> percentage allocation."""
	names = list({budget.monthly_distribution for budget in budgets if budget.monthly_distribution})
	if not names:
		return {}

	rows = frappe.get_all(
		"Monthly Distribution Percentage",
		filters={"parent": ["in", names], "parenttype": "Monthly Distribution"},
		fields=["parent", "month", "percentage_allocation"],
	)

	return {(row.parent, row.month): flt(row.percentage_allocation) for row in rows}
