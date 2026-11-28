"""Business rules of budgets and budget reports (RULES.md BC, BU, BR, RP).

These add to test_budget_integration, which checks the same rules end to end on
a site with data. No site or database is needed here, see fake_site:

	python -m unittest custom_app.tests.test_rules_budget
	bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_budget
"""

import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
import pandas as pd

from custom_app.api import budget_control
from custom_app.custom_app.doctype.budget_reallocation.budget_reallocation import BudgetReallocation
from custom_app.custom_app.doctype.budget_reallocation import budget_reallocation as reallocation
from custom_app.custom_app.doctype.budget_settings.budget_settings import BudgetSettings
from custom_app.custom_app.doctype.budget_upload import budget_upload
from custom_app.custom_app.doctype.master_budget.master_budget import MasterBudget
from custom_app.custom_app.doctype.mid_year_budget_upload import mid_year_budget_upload as mid_year
from custom_app.custom_app.report.budget_carry_forward_report import budget_carry_forward_report as carry
from custom_app.custom_app.report.budget_version_history_report import (
	budget_version_history_report as history,
)
from custom_app.custom_app.report.institution_budget_report import institution_budget_report as institution
from custom_app.custom_app.report.user_role_report import user_role_report
from custom_app.overrides import budget as budget_override
from custom_app.patches import mark_old_budget_reallocations
from custom_app.tests.fake_site import Doc, SiteTest

COMPANY = "Test College"
DOCTYPES = Path(__file__).resolve().parents[1] / "custom_app" / "doctype"
REALLOCATION_FIELDS = {
	field["fieldname"]: field
	for field in json.loads(
		(DOCTYPES / "budget_reallocation" / "budget_reallocation.json").read_text(encoding="utf-8")
	)["fields"]
}
MONTHS = [
	"April", "May", "June", "July", "August", "September",
	"October", "November", "December", "January", "February", "March",
]
SAME_MONTH, CARRY_FORWARD, INTER_DEPARTMENT = reallocation.TRANSFER_TYPES


def document(controller, **values):
	"""A document of an app doctype, without asking the site for its fields."""
	doc = object.__new__(controller)
	doc.__dict__.update({"flags": frappe._dict(), **values})
	return doc


class TestMonthBudget(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Company", COMPANY)
		self.budgets = [{"budget_amount": 120000, "monthly_distribution": "split"}]
		self.site.answer("select ba.budget_amount, b.monthly_distribution", lambda values: self.budgets)
		self.site.add(
			"Monthly Distribution Percentage", "p", parent="split", month="October", percentage_allocation=25
		)
		self.patch("custom_app.api.budget_control.get_fiscal_year", lambda *a, **k: ("2026-2027",))
		self.used = 0
		self.patch("custom_app.api.budget_control.get_month_consumption", lambda *a: self.used)

	def month(self, name="October"):
		return budget_control.get_month_budget(COMPANY, "2026-2027", "Books - TC", "Library - TC", name)

	def test_a_months_budget_is_its_share_of_the_year(self):
		self.assertEqual(self.month(), 30000)
		self.assertEqual(self.month("November"), 0)

	def test_without_a_distribution_a_month_gets_one_twelfth(self):
		self.budgets = [{"budget_amount": 120000, "monthly_distribution": None}]
		self.assertEqual(round(self.month(), 2), 10000)

	def check(self, *amounts, **values):
		budget_control.validate_current_month_budget(
			Doc(
				**{
					"name": "PR-1",
					"company": COMPANY,
					"material_request_type": "Purchase",
					"transaction_date": "2026-10-15",
					"custom_cost_center": "Library - TC",
					"items": [Doc(expense_account="Books - TC", amount=amount) for amount in amounts],
					**values,
				}
			)
		)

	def test_rows_on_one_account_and_cost_center_are_checked_together(self):
		self.check(10000, 20000)
		self.assertRefused("Insufficient budget for October 2026", self.check, 10000, 20000, 0.01)

	def test_what_the_month_already_used_is_taken_off_first(self):
		self.used = 25000
		self.check(5000)
		self.assertRefused("Insufficient budget", self.check, 5000.01)

	def test_an_account_with_no_budget_for_requests_is_not_checked(self):
		self.budgets = []
		self.check(999999)

	def test_only_purchase_requests_use_the_months_budget(self):
		self.check(999999, material_request_type="Material Transfer")


class TestBackdatedRequest(SiteTest):
	def check(self, when, before=None, new=False):
		with patch.object(budget_control, "today", lambda: "2026-10-15"):
			budget_control.validate_backdated_pr(Doc(transaction_date=when, before=before, new=new))

	def test_a_draft_raised_earlier_can_still_be_approved(self):
		self.check("2026-10-01", before=Doc(transaction_date="2026-10-01"))

	def test_a_date_moved_into_the_past_is_refused(self):
		self.assertRefused("Backdated", self.check, "2026-10-14", before=Doc(transaction_date="2026-10-15"))
		self.assertRefused("Backdated", self.check, "2026-10-14", new=True)

	def test_each_check_runs_only_when_its_setting_is_on(self):
		def ran(**settings):
			with (
				patch.object(budget_control, "get_budget_settings", lambda: frappe._dict(settings)),
				patch.object(budget_control, "validate_backdated_pr") as backdated,
				patch.object(budget_control, "validate_current_month_budget") as month,
			):
				budget_control.validate_material_request(Doc())
			return backdated.called, month.called

		self.assertEqual(ran(), (False, False))
		self.assertEqual(ran(restrict_backdated_pr=1), (True, False))
		self.assertEqual(ran(restrict_pr_to_current_month_budget=1), (False, True))


class TestDateBasis(SiteTest):
	def test_requests_before_the_effective_date_keep_their_required_by_month(self):
		basis = budget_control.get_pr_date_basis(
			frappe._dict(
				use_transaction_date_for_pr_budget=1, pr_transaction_date_effective_from="2026-11-01"
			)
		)
		self.assertEqual((basis.use_transaction_date, basis.effective_from), (True, date(2026, 11, 1)))

	def test_the_effective_date_counts_only_while_the_setting_is_on(self):
		basis = budget_control.get_pr_date_basis(
			frappe._dict(pr_transaction_date_effective_from="2026-11-01")
		)
		self.assertEqual((basis.use_transaction_date, basis.effective_from), (False, None))

	def test_a_years_months_run_from_april_to_march(self):
		self.site.add(
			"Fiscal Year", "2026-2027", year_start_date=date(2026, 4, 1), year_end_date=date(2027, 3, 31)
		)
		months = budget_control.get_fiscal_year_months("2026-2027")
		self.assertEqual((len(months), months[0].key, months[-1].key), (12, "2026-04", "2027-03"))

	def test_the_requested_amount_fix_is_only_for_older_erpnext(self):
		from erpnext.accounts.doctype.budget import budget as core

		def installed(new_erpnext):
			with (
				patch.object(core, "get_requested_amount", "core", create=True),
				patch.object(budget_control, "core_uses_query_builder_conditions", lambda: new_erpnext),
			):
				budget_override.apply_budget_patch()
				return core.get_requested_amount

		self.assertIs(installed(False), budget_override.get_requested_amount_fixed)
		self.assertEqual(installed(True), "core")

	def test_the_requested_amount_is_summed_row_by_row(self):
		self.site.answer("(child.stock_qty - child.ordered_qty) * child.rate", [[1500]])
		self.patch(
			"erpnext.accounts.doctype.budget.budget.get_other_condition", lambda args, for_doc: "1=1"
		)
		self.assertEqual(budget_override.get_requested_amount_fixed({"item_code": "Books"}), 1500)


class TestMasterBudget(SiteTest):
	def master(self, *rows, total=100):
		return document(
			MasterBudget,
			total_budget=total,
			department_budget=[Doc(idx=i + 1, department=d, budget=b) for i, (d, b) in enumerate(rows)],
		)

	def test_a_department_is_listed_once(self):
		self.master(("Library", 1), ("Sports", 1)).validate_duplicate_departments()
		self.assertRefused(
			"is repeated in row 2", self.master(("Library", 1), ("Library", 2)).validate_duplicate_departments
		)

	def test_departments_together_stay_within_the_total(self):
		self.patch("frappe.format_value", lambda value, *a, **k: str(value))
		self.master(("Library", 60), ("Sports", 40)).validate_budget_total()
		self.assertRefused(
			"cannot be greater than Total Budget",
			self.master(("Library", 60), ("Sports", 41)).validate_budget_total,
		)


class TestReallocation(SiteTest):
	def setUp(self):
		super().setUp()
		# A reallocation made with the earlier form: one account's month set to a new amount.
		self.doc = document(
			BudgetReallocation,
			reallocation_type=reallocation.SINGLE_ACCOUNT,
			company=COMPANY,
			cost_center="Library - TC",
			fiscal_year="2026-2027",
			account="Books - TC",
			month="October",
			new_budget=20000,
		)

	def test_it_needs_a_type_a_reason_and_both_sides(self):
		fields = REALLOCATION_FIELDS
		mandatory = {name for name, field in fields.items() if field.get("reqd")}
		self.assertEqual(mandatory, {"naming_series", "reallocation_type", "company", "fiscal_year", "reason"})
		for name, label in reallocation.TRANSFER_FIELDS.items():
			self.assertEqual(fields[name]["label"], label)
			if name not in ("company", "fiscal_year"):
				self.assertIn(
					"'Within Same Month','Carry Forward','Inter Department Transfer'", fields[name]["mandatory_depends_on"]
				)
		self.assertEqual(
			fields["reallocation_type"]["options"].splitlines(), [*reallocation.TRANSFER_TYPES, reallocation.SINGLE_ACCOUNT]
		)

	def test_a_new_reallocation_takes_a_transfer_type(self):
		self.doc.__dict__["__islocal"] = 1
		self.assertRefused("A new reallocation is one of", self.doc.validate)

	def test_an_earlier_form_reallocation_is_kept_as_a_record(self):
		# Saving, approving and rejecting all check the reallocation first.
		self.assertRefused("kept as a record and can no longer be changed, approved or rejected", self.doc.validate)

		# Nor can it be turned into a transfer.
		self.doc._doc_before_save = Doc(reallocation_type=reallocation.SINGLE_ACCOUNT)
		self.doc.reallocation_type = reallocation.SAME_MONTH
		self.assertRefused("kept as a record", self.doc.validate)

		# Its own fields are shown, not filled in, and nothing is left to approve it with.
		for name in ("cost_center", "account", "month", "new_budget"):
			self.assertEqual(REALLOCATION_FIELDS[name].get("read_only"), 1, name)
			self.assertNotIn("mandatory_depends_on", REALLOCATION_FIELDS[name], name)
		for method in ("validate_single_account", "reallocate_budget", "cancel_and_amend_budget"):
			self.assertFalse(hasattr(BudgetReallocation, method), method)


class TestTransfer(SiteTest):
	"""Budget moved from one month of an account to another in one step."""

	def setUp(self):
		super().setUp()
		self.site.add("Company", COMPANY, default_currency="INR")
		self.site.add("Fiscal Year", "2026-2027", year_start_date="2026-04-01", year_end_date="2027-03-31")
		self.site.add("Cost Center", "Library - TC", company=COMPANY)
		self.site.add("Cost Center", "Sports - TC", company=COMPANY)
		self.site.add("Cost Center", "Office - OC", company="Other College")
		self.settings = self.site.add(
			"Budget Settings",
			"Budget Settings",
			restrict_pr_to_current_month_budget=1,
			allow_inter_department_transfer=0,
		)
		self.lines = {}
		self.site.answer(
			"select b.name, b.monthly_distribution, ba.budget_amount",
			lambda values: self.lines.get((values["cost_center"], values["account"]), []),
		)
		self.budget("Library - TC", "Books - TC", [10_000] * 12)
		self.budget("Library - TC", "Journals - TC", [5_000] * 12)
		self.budget("Sports - TC", "Kits - TC", [10_000] * 12)

		self.used = {}
		self.patch(
			"custom_app.api.budget_control.get_monthly_consumption",
			lambda company, cost_center, fiscal_year: {
				(account, month): amount
				for (place, account, month), amount in self.used.items()
				if place == cost_center
			},
		)
		self.patch(
			"custom_app.custom_app.doctype.budget_reallocation.budget_reallocation.fmt_money",
			lambda amount, currency=None: f"{currency} {amount:,.2f}",
		)
		self.workflows = {}
		self.patch(
			"custom_app.custom_app.doctype.budget_reallocation.budget_reallocation.get_workflow_name",
			self.workflows.get,
		)

	def budget(self, cost_center, account, amounts):
		name = f"BUDGET {cost_center} {account}"
		split = f"2026-2027 - {cost_center} - {account}"
		annual = sum(amounts)
		self.site.add(
			"Monthly Distribution",
			split,
			percentages=[
				Doc(month=month, percentage_allocation=amount * 100 / annual)
				for month, amount in zip(MONTHS, amounts, strict=True)
			],
		)
		self.lines[(cost_center, account)] = [
			{"name": name, "monthly_distribution": split, "budget_amount": annual}
		]
		return self.site.add(
			"Budget",
			name,
			docstatus=1,
			company=COMPANY,
			cost_center=cost_center,
			accounts=[Doc(account=account, budget_amount=annual)],
		)

	def use(self, cost_center, account, month, amount):
		year = 2027 if MONTHS.index(month) > 8 else 2026
		key = f"{year}-{(MONTHS.index(month) + 3) % 12 + 1:02d}"
		self.used[(cost_center, account, key)] = amount

	def transfer(self, **values):
		return document(
			reallocation.BudgetReallocation,
			**{
				**dict.fromkeys(REALLOCATION_FIELDS),
				"doctype": "Budget Reallocation",
				"name": "BR-1",
				"company": COMPANY,
				"fiscal_year": "2026-2027",
				"reallocation_type": SAME_MONTH,
				"from_cost_center": "Library - TC",
				"from_account": "Books - TC",
				"from_month": "October",
				"to_account": "Journals - TC",
				"amount": 4_000,
				"reason": "Exam papers",
				**values,
			},
		)

	def inter_department(self, **values):
		self.settings.allow_inter_department_transfer = 1
		return self.transfer(
			reallocation_type=INTER_DEPARTMENT,
			to_cost_center="Sports - TC",
			to_account="Kits - TC",
			to_month="January",
			**values,
		)

	def master_budget(self, limits, total=1_000_000, **values):
		return self.site.add(
			"Master Budget",
			"MB-1",
			docstatus=1,
			company=COMPANY,
			fiscal_year="2026-2027",
			total_budget=total,
			department_budget=[Doc(cost_center=place, budget=limit) for place, limit in limits.items()],
			**values,
		)

	def approve(self, doc):
		copy_doc = self.site.copy_doc

		def amended(old, **kwargs):
			copy = copy_doc(old)
			copy.name = f"{old.name}-1"
			return copy

		self.patch("frappe.copy_doc", amended)
		doc.validate()
		doc.db_set = doc.__dict__.update
		doc.on_submit()
		return doc

	def split(self, cost_center, account, annual):
		distribution = self.site.get_doc("Monthly Distribution", f"2026-2027 - {cost_center} - {account}")
		return {row.month: round(row.percentage_allocation * annual / 100, 2) for row in distribution.percentages}

	# Types --------------------------------------------------------------------

	def test_within_a_month_budget_moves_from_one_account_to_another(self):
		doc = self.transfer()
		doc.validate()
		self.assertEqual((doc.to_cost_center, doc.to_month), ("Library - TC", "October"))
		self.assertEqual(figures(doc, "from"), (10_000, 6_000, 120_000, 116_000))
		self.assertEqual(figures(doc, "to"), (5_000, 9_000, 60_000, 64_000))

	def test_carry_forward_moves_an_accounts_budget_from_any_month_to_another(self):
		doc = self.transfer(reallocation_type=CARRY_FORWARD, to_month="December")
		doc.validate()
		self.assertEqual((doc.to_cost_center, doc.to_account), ("Library - TC", "Books - TC"))
		self.assertEqual(figures(doc, "from"), (10_000, 6_000, 120_000, 120_000))
		self.assertEqual(figures(doc, "to"), (10_000, 14_000, 120_000, 120_000))
		self.transfer(reallocation_type=CARRY_FORWARD, to_month="May").validate()

	def test_an_inter_department_transfer_moves_budget_between_cost_centers(self):
		doc = self.inter_department()
		doc.validate()
		self.assertEqual(figures(doc, "from"), (10_000, 6_000, 120_000, 116_000))
		self.assertEqual(figures(doc, "to"), (10_000, 14_000, 120_000, 124_000))

	def test_each_type_keeps_its_two_sides_apart(self):
		self.settings.allow_inter_department_transfer = 1
		for values, words in (
			({"to_account": "Books - TC"}, "Choose two different accounts"),
			({"reallocation_type": CARRY_FORWARD, "to_month": "October"}, "Choose two different months"),
			(
				{"reallocation_type": INTER_DEPARTMENT, "to_cost_center": "Library - TC", "to_month": "May"},
				"Choose two different cost centers",
			),
			(
				{"reallocation_type": INTER_DEPARTMENT, "to_cost_center": "Office - OC", "to_month": "May"},
				'Cost Center "Office - OC" does not belong to Test College',
			),
			({"amount": -5}, "Amount to Move must be more than zero"),
			({"amount": None, "from_month": None}, "Fill in: From Month, To Month, Amount to Move"),
		):
			with self.subTest(words):
				self.assertRefused(words, self.transfer(**values).validate)

	def test_inter_department_transfer_is_offered_only_while_allowed(self):
		self.patch("frappe.has_permission", lambda *args, **kwargs: True)
		self.assertEqual(reallocation.get_transfer_types(), [SAME_MONTH, CARRY_FORWARD])
		doc = self.transfer(
			reallocation_type=INTER_DEPARTMENT, to_cost_center="Sports - TC", to_account="Kits - TC", to_month="May"
		)
		self.assertRefused("Inter Department Transfer is turned off", doc.validate)

		self.settings.allow_inter_department_transfer = 1
		self.assertEqual(reallocation.get_transfer_types(), [SAME_MONTH, CARRY_FORWARD, INTER_DEPARTMENT])
		doc.validate()

	# What may move ------------------------------------------------------------

	def test_only_what_the_month_has_left_can_move(self):
		self.use("Library - TC", "Books - TC", "October", 7_000)
		self.use("Library - TC", "Books - TC", "September", 9_000)
		self.use("Sports - TC", "Books - TC", "October", 10_000)

		self.assertRefused("3,000.00 is left to move from October", self.transfer().validate)
		doc = self.transfer(amount=3_000)
		doc.validate()
		self.assertEqual((doc.from_month_used, doc.left_to_move), (7_000, 3_000))

		# A correcting entry can take a month's use below nothing. It still gives no more than its budget.
		self.use("Library - TC", "Books - TC", "October", -2_000)
		self.assertRefused("10,000.00 is left to move from October", self.transfer(amount=12_000).validate)

	def test_without_the_month_restriction_later_months_keep_their_use_covered(self):
		# Unused budget rolls forward: up to October 70,000 budget and 60,000 used,
		# up to November 80,000 and 78,000. So 2,000 can leave October.
		self.settings.restrict_pr_to_current_month_budget = 0
		for month in MONTHS[:6]:
			self.use("Library - TC", "Books - TC", month, 10_000)
		self.use("Library - TC", "Books - TC", "November", 18_000)

		with self.assertRaises(frappe.ValidationError) as refused:
			self.transfer(amount=2_500).validate()
		self.assertIn("2,000.00 is left to move from October", str(refused.exception))
		self.assertIn("Unused budget rolls forward", str(refused.exception))
		self.transfer(amount=2_000).validate()

		# Moved to November of the same account, it is back by November.
		doc = self.transfer(reallocation_type=CARRY_FORWARD, to_month="November", amount=10_000)
		doc.validate()
		self.assertEqual(doc.left_to_move, 10_000)
		# Moved to an earlier month, every later month keeps what it had.
		self.transfer(reallocation_type=CARRY_FORWARD, to_month="May", amount=10_000).validate()

	def test_a_transfer_never_leaves_an_account_without_budget_for_the_year(self):
		self.budget("Library - TC", "Prizes - TC", [0] * 6 + [5_000] + [0] * 5)
		doc = self.transfer(from_account="Prizes - TC", to_account="Books - TC", amount=5_000)
		self.assertRefused('leave Account "Prizes - TC" in Cost Center "Library - TC" with no budget', doc.validate)
		self.transfer(from_account="Prizes - TC", to_account="Books - TC", amount=4_000).validate()

	def test_both_accounts_need_a_budget_of_their_own_with_a_monthly_split(self):
		self.assertRefused(
			'Account "Stamps - TC" has no approved budget in Cost Center "Library - TC" for 2026-2027',
			self.transfer(to_account="Stamps - TC").validate,
		)
		self.budget("Library - TC", "Stamps - TC", [1_000] * 12)
		self.lines[("Library - TC", "Stamps - TC")][0]["monthly_distribution"] = None
		self.assertRefused("has no Monthly Distribution", self.transfer(to_account="Stamps - TC").validate)

		journals = self.site.get_doc("Budget", "BUDGET Library - TC Journals - TC")
		journals.accounts.append(Doc(account="Stamps - TC", budget_amount=1_000))
		self.assertRefused("holds more than one account", self.transfer().validate)

	def test_the_lists_offer_only_cost_centers_and_accounts_with_an_approved_budget(self):
		self.patch("frappe.has_permission", lambda *args, **kwargs: True)
		self.site.add("DocType", "Cost Center")
		self.site.add("DocType", "Account")
		self.site.answer("select distinct b.cost_center", [("Library - TC",)])
		self.site.answer("select distinct ba.account", [("Books - TC",)])
		search = {"txt": "Lib", "searchfield": "name", "start": 0, "page_len": 20}
		year = {"company": COMPANY, "fiscal_year": "2026-2027"}

		self.assertEqual(reallocation.budgeted_cost_centers(doctype="Cost Center", filters={}, **search), [])
		found = reallocation.budgeted_cost_centers(
			doctype="Cost Center", filters={**year, "leave_out": "Sports - TC"}, **search
		)
		self.assertEqual(found, [("Library - TC",)])
		query, values = self.site.queries[-1]
		self.assertIn("b.docstatus = 1", query)
		self.assertEqual((values["txt"], values["leave_out"]), ("%Lib%", "Sports - TC"))

		self.assertEqual(reallocation.budgeted_accounts(doctype="Account", filters=year, **search), [])
		found = reallocation.budgeted_accounts(
			doctype="Account", filters={**year, "cost_center": "Library - TC"}, **search
		)
		self.assertEqual(found, [("Books - TC",)])
		query, values = self.site.queries[-1]
		self.assertIn("b.docstatus = 1", query)
		self.assertEqual(values["cost_center"], "Library - TC")

	def test_the_form_gets_the_figures_once_both_sides_are_chosen(self):
		self.assertEqual(self.transfer(to_account=None).get_figures(), {})
		shown = self.transfer(amount=None).get_figures()
		self.assertEqual(set(shown), set(reallocation.FIGURES))
		self.assertEqual((round(shown["from_month_budget"]), round(shown["left_to_move"])), (10_000, 10_000))

	# The Master Budget ----------------------------------------------------------

	def test_an_inter_department_transfer_moves_the_master_budget_limits_too(self):
		self.master_budget({"Library - TC": 200_000, "Sports - TC": 150_000})
		doc = self.inter_department()
		doc.validate()
		limits = (doc.from_master_limit, doc.from_new_master_limit, doc.to_master_limit, doc.to_new_master_limit)
		self.assertEqual(limits, (200_000, 196_000, 150_000, 154_000))

		within = self.transfer()
		within.validate()
		self.assertIsNone(within.from_master_limit)

	def test_the_master_budget_must_allow_the_move(self):
		self.master_budget({"Library - TC": 3_000, "Sports - TC": 150_000})
		self.assertRefused("so its limit cannot go down by", self.inter_department().validate)

		# Only the receiving cost center has a row: it can rise while the rows fit the total.
		master = self.master_budget({"Sports - TC": 150_000}, total=152_000)
		self.assertRefused("over the Total Budget", self.inter_department().validate)
		master.total_budget = 154_000
		self.inter_department().validate()

		# Neither has a row: no limit moves.
		master.department_budget = []
		doc = self.inter_department()
		doc.validate()
		self.assertIsNone(doc.flags.master_budget)

	# Approval -------------------------------------------------------------------

	def test_approval_amends_both_budgets_and_keeps_the_other_months(self):
		doc = self.approve(self.transfer())

		books = self.site.get_doc("Budget", "BUDGET Library - TC Books - TC")
		self.assertEqual((books.docstatus, books.calls), (2, ["cancel"]))
		new_books, new_journals = self.site.made
		self.assertEqual((new_books.amended_from, new_books.docstatus), (books.name, 1))
		self.assertEqual(round(new_books.accounts[0].budget_amount), 116_000)
		self.assertEqual(round(new_journals.accounts[0].budget_amount), 64_000)

		books_split = self.split("Library - TC", "Books - TC", 116_000)
		self.assertEqual((books_split["October"], books_split["November"]), (6_000, 10_000))
		journals_split = self.split("Library - TC", "Journals - TC", 64_000)
		self.assertEqual((journals_split["October"], journals_split["March"]), (9_000, 5_000))

		links = (doc.from_old_budget, doc.from_new_budget, doc.to_old_budget, doc.to_new_budget)
		self.assertEqual(links, (books.name, f"{books.name}-1", new_journals.amended_from, new_journals.name))
		self.assertEqual(doc.approver, self.user)
		self.assertIsNotNone(doc.approval_date)

	def test_carry_forward_amends_the_one_budget_once(self):
		doc = self.approve(self.transfer(reallocation_type=CARRY_FORWARD, to_month="December"))

		(new_books,) = self.site.made
		self.assertEqual(round(new_books.accounts[0].budget_amount), 120_000)
		split = self.split("Library - TC", "Books - TC", 120_000)
		self.assertEqual((split["October"], split["December"], split["April"]), (6_000, 14_000, 10_000))
		self.assertEqual((doc.to_old_budget, doc.to_new_budget), (doc.from_old_budget, doc.from_new_budget))

	def test_an_inter_department_approval_amends_the_master_budget_first(self):
		master = self.master_budget({"Library - TC": 200_000, "Sports - TC": 150_000}, workflow_state="Approved")
		self.site.add(
			"Workflow",
			"Master Budget Approval",
			workflow_state_field="workflow_state",
			states=[
				Doc(state="Draft", doc_status="0"),
				Doc(state="Approved", doc_status="1"),
				Doc(state="Cancelled", doc_status="2"),
			],
		)
		self.workflows["Master Budget"] = "Master Budget Approval"
		self.patch("frappe.get_meta", lambda doctype: MagicMock(has_field=lambda field: True))

		doc = self.approve(self.inter_department())

		new_master, new_books, new_kits = self.site.made
		self.assertEqual((master.docstatus, master.workflow_state), (2, "Cancelled"))
		self.assertEqual((new_master.amended_from, new_master.workflow_state), ("MB-1", None))
		self.assertEqual([row.budget for row in new_master.department_budget], [196_000, 154_000])
		self.assertEqual((doc.old_master_budget, doc.new_master_budget), ("MB-1", "MB-1-1"))
		self.assertEqual(round(new_books.accounts[0].budget_amount), 116_000)
		self.assertEqual(round(new_kits.accounts[0].budget_amount), 124_000)

	# Earlier reallocations and the report -----------------------------------------

	def test_reallocations_from_the_earlier_form_are_marked_single_account(self):
		self.site.answer("update `tabBudget Reallocation`", [])
		mark_old_budget_reallocations.execute()
		query = " ".join(self.site.queries[-1][0].split())
		self.assertIn("set reallocation_type = 'Single Account' where ifnull(reallocation_type, '') = ''", query)

	def test_version_history_shows_a_transfer_from_the_budgets_side(self):
		moved = {
			"docstatus": 1,
			"reallocation_type": SAME_MONTH,
			"reason": "Exam papers",
			"approver": "approver@example.com",
			"approval_date": "2026-10-15 10:00:00",
			"from_month": "October",
			"to_month": "October",
			"from_month_budget": 10_000,
			"from_new_month_budget": 6_000,
			"to_month_budget": 0,
			"to_new_month_budget": 4_000,
			"from_year_budget": 120_000,
			"from_new_year_budget": 116_000,
			"to_year_budget": 60_000,
			"to_new_year_budget": 64_000,
			"from_old_budget": "BOOKS-1",
			"from_new_budget": "BOOKS-2",
			"to_old_budget": "JOURNALS-1",
			"to_new_budget": "JOURNALS-2",
		}
		self.site.add("Budget Reallocation", "BR-1", **moved)
		self.site.add(
			"Budget Reallocation",
			"BR-2",
			**{
				**moved,
				"reallocation_type": CARRY_FORWARD,
				"to_month": "December",
				"to_month_budget": 10_000,
				"to_new_month_budget": 14_000,
				"to_year_budget": 120_000,
				"to_new_year_budget": 120_000,
				"from_old_budget": "BOOKS-2",
				"from_new_budget": "BOOKS-3",
				"to_old_budget": "BOOKS-2",
				"to_new_budget": "BOOKS-3",
			},
		)

		receiving = history.get_reallocation_by_new_link("JOURNALS-2")
		self.assertEqual([(m.month, m.current_budget, m.new_budget) for m in receiving.months], [("October", 0, 4_000)])
		self.assertEqual((receiving.old_budget_link, receiving.new_total_annual_budget), ("JOURNALS-1", 64_000))
		self.assertEqual(receiving.reason, "Within Same Month: Exam papers")

		with (
			patch.object(history, "validate_filters"),
			patch.object(history, "get_budget", lambda filters: (Doc(name="BOOKS-3"), 120_000)),
		):
			_columns, rows = history.execute({})
		self.assertEqual(
			[(r["month"], r["old_budget"], r["new_budget"], r["new_budget_link"]) for r in rows],
			[
				("October", 10_000, 6_000, "BOOKS-3"),
				("December", 10_000, 14_000, "BOOKS-3"),
				("October", 10_000, 6_000, "BOOKS-2"),
				("-", "-", "-", "BOOKS-1"),
			],
		)


def figures(doc, side):
	"""A side's month budget now and after, and its year's budget now and after."""
	return tuple(
		round(doc.get(f"{side}_{name}"), 2)
		for name in ("month_budget", "new_month_budget", "year_budget", "new_year_budget")
	)


class TestBudgetSettings(SiteTest):
	def settings(self, allowed, was_allowed):
		return document(
			BudgetSettings,
			allow_inter_department_transfer=allowed,
			_doc_before_save=Doc(allow_inter_department_transfer=was_allowed),
		)

	def test_only_a_system_manager_turns_inter_department_transfer_on_or_off(self):
		self.log_in("approver@example.com", "Finance Approver")
		for allowed, was_allowed in ((1, 0), (0, 1)):
			with self.assertRaises(frappe.PermissionError):
				self.settings(allowed, was_allowed).validate()
		self.settings(1, 1).validate()

		self.log_in("admin@example.com", "System Manager")
		self.settings(1, 0).validate()
		self.settings(0, 1).validate()



class TestBudgetUpload(SiteTest):
	def preview(self, *rows):
		sheet = pd.DataFrame([["Acc Name", *mid_year.MONTHS], *rows])
		doc = document(budget_upload.BudgetUpload, budget_file="/files/budget.xlsx")
		with (
			patch.object(budget_upload, "get_file_path", lambda f: f),
			patch.object(budget_upload.pd, "read_excel", lambda *a, **k: sheet),
		):
			return doc.get_excel_preview()

	def test_the_preview_marks_cells_that_are_not_numbers(self):
		result = self.preview(["Books - TC", "ten", *[1] * 11])
		self.assertTrue(result["has_error"])
		self.assertIn("Row 2, Column 2 (April) for Account 'Books - TC'", result["errors"][0])
		self.assertFalse(self.preview(["Books - TC", *[1] * 12])["has_error"])


class TestMidYearUpload(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Company", COMPANY)
		self.site.add("Account", "Books - TC", company=COMPANY, is_group=0)
		self.site.add("Account", "Fees - TC", company=COMPANY, is_group=0)
		self.site.add("Account", "All - TC", company=COMPANY, is_group=1)
		self.site.add("Account", "Books - OC", company="Other College", is_group=0)
		self.existing = {}
		self.doc = document(
			mid_year.MidYearBudgetUpload,
			company=COMPANY,
			cost_center="Library - TC",
			fiscal_year="2026-2027",
			budget_file="/files/budget.xlsx",
		)
		self.patch(f"{mid_year.__name__}.get_monthly_consumption", lambda *a: {})
		self.patch(f"{mid_year.__name__}.get_fiscal_year_months", lambda *a: [])
		self.patch(f"{mid_year.__name__}.get_file_path", lambda f: f)
		self.patch(
			f"{mid_year.__name__}.MidYearBudgetUpload.get_existing_budgets", lambda doc, errors: self.existing
		)
		self.patch(
			f"{mid_year.__name__}.MidYearBudgetUpload.get_master_budget_limit", lambda doc: 10_000_000
		)

	def budget(self, account, monthly, accounts=1):
		self.existing[account] = frappe._dict(
			name=f"BUDGET {account}", total=monthly * 12, months=[monthly] * 12, account_count=accounts
		)

	def compare(self, *rows):
		sheet = pd.DataFrame([["Acc Name", *mid_year.MONTHS], *rows])
		with patch.object(mid_year.pd, "read_excel", lambda *a, **k: sheet):
			return self.doc.compare()

	def test_a_month_moved_by_less_than_a_rupee_is_unchanged(self):
		self.budget("Books - TC", 1000)
		self.assertEqual(len(self.compare(["Books - TC", 1000.99, *[1000] * 11]).unchanged), 1)
		self.assertEqual(len(self.compare(["Books - TC", 1001, *[1000] * 11]).revised), 1)

	def test_a_blank_row_never_removes_a_budget(self):
		self.budget("Books - TC", 1000)
		result = self.compare(["Books - TC", *[None] * 12], ["Fees - TC", *[10] * 12])
		self.assertEqual((result.blank, result.revised, result.errors), (["Books - TC"], [], []))

	def test_repeated_accounts_and_bad_amounts_are_refused(self):
		self.assertIn("is repeated in rows 2 and 3", self.compare(*[["Books - TC", *[1] * 12]] * 2).errors[0])
		for bad in (-5, "ten", True):
			self.assertIn("is not a valid amount", self.compare(["Books - TC", bad, *[1] * 11]).errors[0])

	def test_accounts_must_be_in_the_company_and_not_groups(self):
		for account, reason in (
			("Nowhere - TC", "not found in the Chart of Accounts"),
			("Books - OC", "belongs to company"),
			("All - TC", "is a group account"),
		):
			self.assertIn(reason, self.compare([account, *[1] * 12]).errors[0])

	def test_a_budget_of_several_accounts_is_not_revised_from_a_file(self):
		self.budget("Books - TC", 1000, accounts=2)
		self.assertIn("holds several accounts", self.compare(["Books - TC", *[2000] * 12]).errors[0])

	def test_the_cost_center_must_belong_to_the_company(self):
		self.site.add("Cost Center", "Library - TC", company="Other College")
		self.assertRefused("does not belong to Company", self.doc.validate)

	def test_new_budgets_stop_on_requests_orders_and_actuals(self):
		controls = mid_year.NEW_BUDGET_CONTROLS
		self.assertEqual([v for k, v in controls.items() if k.startswith("applicable")], [1, 1, 1])
		self.assertEqual({v for k, v in controls.items() if k.startswith("action")}, {"Stop"})

	def test_the_spreadsheets_months_are_april_to_march(self):
		self.assertEqual((mid_year.MONTHS[0], mid_year.MONTHS[-1], len(mid_year.MONTHS)), ("April", "March", 12))


class TestReports(SiteTest):
	def test_carry_forward_rolls_on_what_is_left_and_what_is_overspent(self):
		months = [
			{"month_name": name, "month_start": name, "month_end": name} for name in ("Apr", "May", "Jun")
		]
		spent = {"Apr": 40, "May": 190, "Jun": 0}
		with (
			patch.object(carry, "get_accounts_with_budget", lambda filters: ["Books - TC"]),
			patch.object(carry, "get_budget_amount", lambda *a: 100),
			patch.object(carry, "get_actual_amount", lambda account, cc, start, end, company: spent[start]),
		):
			row = carry.get_data(frappe._dict(), months)[0]
		self.assertEqual((row["may_available"], row["jun_available"]), (160, 70))

	def test_carry_forward_stops_at_the_present_month(self):
		year = Doc(year_start_date="2026-04-01", year_end_date="2027-03-31")
		with patch.object(carry, "nowdate", lambda: "2026-06-10"):
			self.assertEqual([m["month_name"] for m in carry.get_months_in_fiscal_year(year)], ["Apr", "May", "Jun"])
		with patch.object(carry, "nowdate", lambda: "2027-06-10"):
			self.assertEqual(len(carry.get_months_in_fiscal_year(year)), 12)

	def test_version_history_walks_back_to_the_first_budget(self):
		steps = {
			"B-3": frappe._dict(old_budget_link="B-2", total_annual_budget=200, new_total_annual_budget=300),
			"B-2": frappe._dict(old_budget_link="B-1", total_annual_budget=100, new_total_annual_budget=200),
		}
		with (
			patch.object(history, "validate_filters"),
			patch.object(history, "get_budget", lambda filters: (Doc(name="B-3"), 300)),
			patch.object(history, "get_reallocation_by_new_link", steps.get),
		):
			_columns, rows = history.execute({})
		self.assertEqual([r["new_budget_link"] for r in rows], ["B-3", "B-2", "B-1"])
		self.assertEqual([r["new_annual_budget"] for r in rows], [300, 200, 100])

	def test_institution_budget_shows_only_the_users_own_department(self):
		self.log_in("head@example.com")
		self.assertRefused("set Department", institution.execute, {})
		self.site.add("Employee", "EMP-9", user_id="head@example.com", department="Sports - TC")
		self.assertRefused("set Cost Center", institution.execute, {})
		self.site.add("Cost Center", "Sports - TC", custom_department="Sports - TC")
		with (
			patch.object(institution, "get_columns"),
			patch.object(institution, "get_data") as get_data,
		):
			institution.execute({"cost_center": "Library - TC"})
		self.assertEqual(get_data.call_args.args[1], "Sports - TC")

	def test_the_user_role_report_shows_who_holds_which_role(self):
		self.site.add("Role", "Finance Approver", disabled=0)
		self.site.add("Role", "System Manager", disabled=0)
		self.site.add("User", "a@example.com", user_type="System User", full_name="A", enabled=1)
		self.site.add("Has Role", "h", parent="a@example.com", parenttype="User", role="Finance Approver")
		columns, rows = user_role_report.execute({})
		self.assertEqual([c["label"] for c in columns[3:]], ["Finance Approver"])
		self.assertEqual((rows[0]["role_finance_approver"], rows[0]["status"]), ("✔", "Active"))


if __name__ == "__main__":
	unittest.main()
