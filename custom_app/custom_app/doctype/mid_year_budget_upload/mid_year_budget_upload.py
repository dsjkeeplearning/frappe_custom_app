# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

import numbers

import frappe
import pandas as pd
from frappe import _
from frappe.model.document import Document
from frappe.utils import escape_html, flt, fmt_money
from frappe.utils.file_manager import get_file_path

from custom_app.api.budget_control import get_fiscal_year_months, get_monthly_consumption

# Column order of the "Download Budget Excel Format" file.
MONTHS = [
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
	"January",
	"February",
	"March",
]

# A month counts as changed only when it moves by a rupee or more. Budgets hold
# an annual amount and a percentage per month, so a month read back from them
# can differ from the figure originally typed in Excel by a few paise.
TOLERANCE = 1.0

# Controls put on a Budget created for an account that had none, same as
# Budget Upload. A revised Budget keeps the controls of the one it replaces.
NEW_BUDGET_CONTROLS = {
	"applicable_on_material_request": 1,
	"action_if_annual_budget_exceeded_on_mr": "Stop",
	"action_if_accumulated_monthly_budget_exceeded_on_mr": "Stop",
	"applicable_on_purchase_order": 1,
	"action_if_annual_budget_exceeded_on_po": "Stop",
	"action_if_accumulated_monthly_budget_exceeded_on_po": "Stop",
	"applicable_on_booking_actual_expenses": 1,
	"action_if_annual_budget_exceeded": "Stop",
	"action_if_accumulated_monthly_budget_exceeded": "Stop",
}


class MidYearBudgetUpload(Document):
	"""Revise the budgets of one cost center from a mid-year Excel file.

	Every account in the file is compared month by month with its submitted
	Budget:
		same figures       -> left alone
		different figures  -> Budget cancelled and re-created with the new figures
		no Budget yet      -> Budget created
	A month whose new budget is below what is already consumed is reported as
	a warning and still applied.
	"""

	def validate(self):
		if self.cost_center and self.company:
			cost_center_company = frappe.get_cached_value("Cost Center", self.cost_center, "company")
			if cost_center_company != self.company:
				frappe.throw(
					_("Cost Center {0} does not belong to Company {1}").format(
						frappe.bold(self.cost_center), frappe.bold(self.company)
					)
				)

	def before_submit(self):
		# Runs inside the submit transaction: if any Budget fails, nothing is changed.
		comparison = self.compare()
		if comparison.errors:
			frappe.throw(
				"<br>".join(comparison.errors), title=_("Budget File Cannot Be Applied"), as_list=False
			)

		if not (comparison.revised or comparison.new):
			frappe.throw(_("Nothing to apply: every budget in the file is unchanged."))

		self.apply(comparison)

	def on_submit(self):
		result = self.flags.result
		if not result:
			return

		message = _("Budgets revised: {0}<br>Budgets created: {1}<br>Unchanged, left as they are: {2}").format(
			frappe.bold(result.revised), frappe.bold(result.created), frappe.bold(result.unchanged)
		)
		if result.warnings:
			message += "<br><br><b>{0}</b><ul><li>{1}</li></ul>".format(
				_("Applied with warnings (budget is below what is already consumed):"),
				"</li><li>".join(result.warnings),
			)

		frappe.msgprint(
			message,
			title=_("Mid Year Budget Applied"),
			indicator="orange" if result.warnings else "green",
		)

	def before_cancel(self):
		frappe.throw(
			_(
				"A Mid Year Budget Upload cannot be cancelled: cancelling it would not restore the"
				" earlier budgets. Upload a corrected file instead."
			)
		)

	# ------------------------------------------------------------------
	# Comparison
	# ------------------------------------------------------------------

	@frappe.whitelist()
	def get_preview(self):
		"""Comparison shown on the form before submitting. Changes nothing."""
		if not (self.company and self.cost_center and self.fiscal_year and self.budget_file):
			return {}

		comparison = self.compare()
		return {
			"html": self.render_preview(comparison),
			"errors": comparison.errors,
			"warnings": comparison.warnings,
			"has_changes": bool(comparison.revised or comparison.new),
		}

	def compare(self):
		"""Compare the file with the submitted budgets of the cost center."""
		currency = frappe.get_cached_value("Company", self.company, "default_currency")
		comparison = frappe._dict(
			currency=currency,
			errors=[],
			warnings=[],
			revised=[],
			new=[],
			unchanged=[],
			blank=[],
			not_in_file=0,
		)

		file_rows = self.read_file(comparison.errors)
		if comparison.errors:
			return comparison

		existing = self.get_existing_budgets(comparison.errors)
		self.validate_accounts(file_rows, comparison.errors)

		consumption = get_monthly_consumption(self.company, self.cost_center, self.fiscal_year)
		month_keys = {month.name: month.key for month in get_fiscal_year_months(self.fiscal_year)}

		for row in file_rows:
			budget = existing.get(row.account)
			row.new_total = sum(row.months)

			if not row.new_total:
				# The format lists every expense account, so an empty row only
				# means "not filled in". It never removes a budget.
				if budget:
					comparison.blank.append(row.account)
				continue

			if not budget:
				row.update(status="New", old_total=0, old_months=[0] * 12, changes=[], warnings=[])
				comparison.new.append(row)
				continue

			row.update(
				old_budget=budget.name,
				old_total=budget.total,
				old_months=budget.months,
				changes=[],
				warnings=[],
			)

			for month, old, new in zip(MONTHS, budget.months, row.months, strict=True):
				if abs(new - old) < TOLERANCE:
					continue

				row.changes.append((month, old, new))

				consumed = flt(consumption.get((row.account, month_keys.get(month)), 0))
				if new < old and consumed > new + 0.005:
					warning = _("{0}, {1}: budget {2} reduced to {3}, already consumed {4}").format(
						escape_html(row.account),
						_(month),
						fmt_money(old, currency=currency),
						fmt_money(new, currency=currency),
						fmt_money(consumed, currency=currency),
					)
					row.warnings.append(warning)
					comparison.warnings.append(warning)

			if not row.changes:
				row.status = "Unchanged"
				comparison.unchanged.append(row)
				continue

			row.status = "Revised"
			if budget.account_count > 1:
				comparison.errors.append(
					_(
						"{0}: Budget {1} holds several accounts and cannot be revised from a file."
						" Revise it manually."
					).format(escape_html(row.account), budget.name)
				)
			comparison.revised.append(row)

		file_accounts = {row.account for row in file_rows}
		comparison.not_in_file = len([account for account in existing if account not in file_accounts])

		if comparison.revised or comparison.new:
			self.validate_master_budget(comparison, existing)

		return comparison

	def read_file(self, errors):
		"""Rows of the Excel file as dicts {account, row_no, months[12]}."""
		try:
			sheet = pd.read_excel(get_file_path(self.budget_file), header=None)
		except Exception:
			errors.append(_("Unable to read the Excel file. Please upload a valid .xlsx file."))
			return []

		if sheet.empty or sheet.shape[1] < 13:
			errors.append(
				_("Invalid budget format. The file must have the account followed by 12 months of data.")
			)
			return []

		# The amounts are read by position, so the months have to be in order.
		header = [str(value).strip().lower()[:3] for value in sheet.iloc[0, 1:13].tolist()]
		expected = [month.lower()[:3] for month in MONTHS]
		if header != expected:
			errors.append(
				_(
					"The first row must have the months April to March in columns B to M, as in the"
					" Download Budget Excel Format file."
				)
			)
			return []

		rows = []
		seen = {}
		for row_no, values in enumerate(sheet.iloc[1:].itertuples(index=False), start=2):
			account = values[0]
			if pd.isna(account) or not str(account).strip():
				continue
			account = str(account).strip()

			months = []
			for column, cell in enumerate(values[1:13], start=2):
				if pd.isna(cell):
					months.append(0.0)
				elif isinstance(cell, numbers.Real) and not isinstance(cell, bool) and cell >= 0:
					months.append(float(cell))
				else:
					months.append(0.0)
					errors.append(
						_("Row {0}, {1} for account {2}: '{3}' is not a valid amount").format(
							row_no, MONTHS[column - 2], escape_html(account), escape_html(str(cell))
						)
					)

			if account in seen:
				errors.append(
					_("Account {0} is repeated in rows {1} and {2}").format(
						escape_html(account), seen[account], row_no
					)
				)
				continue

			seen[account] = row_no
			rows.append(frappe._dict(account=account, row_no=row_no, months=months))

		if not rows and not errors:
			errors.append(_("The file has no account rows."))

		return rows

	def validate_accounts(self, file_rows, errors):
		budgeted = [row for row in file_rows if sum(row.months)]
		if not budgeted:
			return

		accounts = {
			account.name: account
			for account in frappe.get_all(
				"Account",
				filters={"name": ["in", [row.account for row in budgeted]]},
				fields=["name", "company", "is_group"],
			)
		}

		for row in budgeted:
			account = accounts.get(row.account)
			if not account:
				errors.append(
					_("Row {0}: account {1} not found in the Chart of Accounts").format(
						row.row_no, escape_html(row.account)
					)
				)
			elif account.company != self.company:
				errors.append(
					_("Row {0}: account {1} belongs to company {2}").format(
						row.row_no, escape_html(row.account), escape_html(account.company)
					)
				)
			elif account.is_group:
				errors.append(
					_("Row {0}: {1} is a group account and cannot have a budget").format(
						row.row_no, escape_html(row.account)
					)
				)

	def get_existing_budgets(self, errors):
		"""account -> submitted Budget of the cost center with its 12 monthly figures."""
		rows = frappe.db.sql(
			"""
			select b.name, b.monthly_distribution, ba.account, ba.budget_amount,
				(select count(*) from `tabBudget Account` x where x.parent = b.name) as account_count
			from `tabBudget` b
			inner join `tabBudget Account` ba on ba.parent = b.name
			where b.docstatus = 1
				and b.company = %(company)s
				and b.fiscal_year = %(fiscal_year)s
				and b.budget_against = 'Cost Center'
				and b.cost_center = %(cost_center)s
			""",
			{"company": self.company, "fiscal_year": self.fiscal_year, "cost_center": self.cost_center},
			as_dict=True,
		)

		distributions = {row.monthly_distribution for row in rows if row.monthly_distribution}
		percentages = {}
		if distributions:
			for row in frappe.get_all(
				"Monthly Distribution Percentage",
				filters={"parent": ["in", list(distributions)], "parenttype": "Monthly Distribution"},
				fields=["parent", "month", "percentage_allocation"],
			):
				percentages[(row.parent, row.month)] = flt(row.percentage_allocation)

		existing = {}
		for row in rows:
			if row.account in existing:
				errors.append(
					_("Account {0} has more than one submitted Budget ({1}, {2})").format(
						escape_html(row.account), existing[row.account].name, row.name
					)
				)
				continue

			row.total = flt(row.budget_amount)
			row.months = [
				row.total
				* (
					percentages.get((row.monthly_distribution, month), 0)
					if row.monthly_distribution
					else 100.0 / 12
				)
				/ 100
				for month in MONTHS
			]
			existing[row.account] = row

		return existing

	def validate_master_budget(self, comparison, existing):
		"""The cost center's budgets must still fit its Master Budget, as in Budget Upload."""
		limit = self.get_master_budget_limit()
		if limit is None:
			comparison.errors.append(
				_("No submitted Master Budget found for Cost Center {0}, Company {1}, Fiscal Year {2}").format(
					escape_html(self.cost_center), escape_html(self.company), self.fiscal_year
				)
			)
			return

		allocated = sum(budget.total for budget in existing.values())
		after = allocated + sum(row.new_total - row.old_total for row in comparison.revised + comparison.new)
		comparison.update(master_budget_limit=limit, allocated=allocated, allocated_after=after)

		if after > allocated and after > flt(limit) + 0.005:
			currency = comparison.currency
			comparison.errors.append(
				_(
					"Master Budget limit exceeded. Limit: {0}, allocated now: {1}, allocated after this"
					" file: {2}, excess: {3}. Reduce the amounts or revise the Master Budget first."
				).format(
					fmt_money(limit, currency=currency),
					fmt_money(allocated, currency=currency),
					fmt_money(after, currency=currency),
					fmt_money(after - flt(limit), currency=currency),
				)
			)

	def get_master_budget_limit(self):
		master_budget = frappe.db.get_value(
			"Master Budget", {"company": self.company, "fiscal_year": self.fiscal_year, "docstatus": 1}
		)
		if not master_budget:
			return None

		return frappe.db.get_value(
			"Master Budget Department",
			{"parent": master_budget, "parenttype": "Master Budget", "cost_center": self.cost_center},
			"budget",
		)

	# ------------------------------------------------------------------
	# Apply
	# ------------------------------------------------------------------

	def apply(self, comparison):
		self.set("changes", [])

		# Reductions first: each Budget is checked against the Master Budget
		# as it is submitted, so a file that moves budget from one account to
		# another must free the room before it is used.
		for row in sorted(comparison.revised, key=lambda row: row.new_total - row.old_total):
			new_budget = self.revise_budget(row)
			self.add_change(row, new_budget)

		for row in comparison.new:
			new_budget = self.create_budget(row)
			self.add_change(row, new_budget)

		self.flags.result = frappe._dict(
			revised=len(comparison.revised),
			created=len(comparison.new),
			unchanged=len(comparison.unchanged),
			warnings=comparison.warnings,
		)

	def revise_budget(self, row):
		"""Cancel the account's Budget and submit an amended copy with the new figures."""
		distribution = self.set_monthly_distribution(row)

		old_budget = frappe.get_doc("Budget", row.old_budget)
		# Budget Reallocation and earlier uploads keep links to the Budget.
		old_budget.flags.ignore_links = True
		old_budget.cancel()

		new_budget = frappe.copy_doc(old_budget)
		new_budget.docstatus = 0
		new_budget.amended_from = old_budget.name
		new_budget.monthly_distribution = distribution
		for account in new_budget.accounts:
			if account.account == row.account:
				account.budget_amount = row.new_total

		new_budget.insert()
		new_budget.submit()
		return new_budget.name

	def create_budget(self, row):
		budget = frappe.new_doc("Budget")
		budget.update(NEW_BUDGET_CONTROLS)
		budget.budget_against = "Cost Center"
		budget.company = self.company
		budget.cost_center = self.cost_center
		budget.fiscal_year = self.fiscal_year
		budget.monthly_distribution = self.set_monthly_distribution(row)
		budget.append("accounts", {"account": row.account, "budget_amount": row.new_total})

		budget.insert()
		budget.submit()
		return budget.name

	def set_monthly_distribution(self, row):
		"""Write the file's month split to the account's Monthly Distribution.

		Percentages are kept at full precision: rounding them shifts the monthly
		figures on large budgets.
		"""
		distribution_id = f"{self.fiscal_year} - {self.cost_center} - {row.account}"[:140]

		if frappe.db.exists("Monthly Distribution", distribution_id):
			distribution = frappe.get_doc("Monthly Distribution", distribution_id)
			distribution.set("percentages", [])
		else:
			distribution = frappe.new_doc("Monthly Distribution")
			distribution.distribution_id = distribution_id

		distribution.fiscal_year = self.fiscal_year
		for month, amount in zip(MONTHS, row.months, strict=True):
			distribution.append(
				"percentages", {"month": month, "percentage_allocation": amount / row.new_total * 100}
			)

		distribution.save()
		return distribution.name

	def add_change(self, row, new_budget):
		currency = frappe.get_cached_value("Company", self.company, "default_currency")
		remarks = [
			"{0}: {1} -> {2}".format(month, fmt_money(old, currency=currency), fmt_money(new, currency=currency))
			for month, old, new in row.changes
		]
		remarks += [_("Warning: {0}").format(warning) for warning in row.warnings]

		self.append(
			"changes",
			{
				"account": row.account,
				"status": row.status,
				"old_annual_budget": row.old_total,
				"new_annual_budget": row.new_total,
				"difference": row.new_total - row.old_total,
				"old_budget": row.get("old_budget"),
				"new_budget": new_budget,
				"remarks": "\n".join(remarks),
			},
		)

	# ------------------------------------------------------------------
	# Preview
	# ------------------------------------------------------------------

	def render_preview(self, comparison):
		def money(value):
			return fmt_money(value, currency=comparison.currency)

		html = []

		if comparison.errors:
			html.append(
				'<div class="alert alert-danger"><b>{0}</b><ul class="mb-0"><li>{1}</li></ul></div>'.format(
					_("This file cannot be applied. Fix these and upload it again:"),
					"</li><li>".join(comparison.errors),
				)
			)

		if comparison.warnings:
			html.append(
				'<div class="alert alert-warning"><b>{0}</b><ul class="mb-0"><li>{1}</li></ul></div>'.format(
					_(
						"Warning: these months are reduced below what is already consumed."
						" You can still submit."
					),
					"</li><li>".join(comparison.warnings),
				)
			)

		summary = [
			_("{0} budgets will be revised").format(frappe.bold(len(comparison.revised))),
			_("{0} will be created").format(frappe.bold(len(comparison.new))),
			_("{0} are unchanged").format(frappe.bold(len(comparison.unchanged))),
		]
		if comparison.blank:
			summary.append(
				_("{0} budgeted accounts are blank in the file and stay as they are").format(
					frappe.bold(len(comparison.blank))
				)
			)
		if comparison.not_in_file:
			summary.append(
				_("{0} budgeted accounts are not in the file and stay as they are").format(
					frappe.bold(comparison.not_in_file)
				)
			)
		html.append('<p>{0}.</p>'.format("; ".join(summary)))

		if comparison.get("allocated_after") is not None:
			html.append(
				'<p class="text-muted">{0}</p>'.format(
					_("Cost center total: {0} now, {1} after this file. Master Budget limit: {2}.").format(
						money(comparison.allocated),
						money(comparison.allocated_after),
						money(comparison.master_budget_limit),
					)
				)
			)

		rows = comparison.revised + comparison.new + comparison.unchanged
		if not rows:
			return "".join(html)

		colours = {"Revised": "orange", "New": "blue", "Unchanged": "gray"}
		html.append(
			'<table class="table table-bordered table-sm"><thead><tr>'
			"<th>{0}</th><th>{1}</th><th class='text-right'>{2}</th><th class='text-right'>{3}</th>"
			"<th class='text-right'>{4}</th><th>{5}</th></tr></thead><tbody>".format(
				_("Account"),
				_("Status"),
				_("Current Annual Budget"),
				_("New Annual Budget"),
				_("Difference"),
				_("Months Changed"),
			)
		)
		for row in rows:
			details = [
				"{0}: {1} &rarr; {2}".format(_(month), money(old), money(new))
				for month, old, new in row.get("changes") or []
			]
			if row.status == "New":
				details = [
					"{0}: {1}".format(_(month), money(amount))
					for month, amount in zip(MONTHS, row.months, strict=True)
					if amount
				]

			html.append(
				"<tr><td>{account}</td>"
				'<td><span class="indicator-pill {colour}">{status}</span></td>'
				"<td class='text-right'>{old}</td><td class='text-right'>{new}</td>"
				"<td class='text-right'>{difference}</td><td class='small'>{details}</td></tr>".format(
					account=escape_html(row.account),
					colour=colours[row.status],
					status=_(row.status),
					old=money(row.old_total) if row.status != "New" else "-",
					new=money(row.new_total),
					difference=money(row.new_total - row.old_total) if row.status == "Revised" else "-",
					details="<br>".join(details),
				)
			)
		html.append("</tbody></table>")

		return "".join(html)
