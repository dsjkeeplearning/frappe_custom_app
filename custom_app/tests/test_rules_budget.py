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
from unittest.mock import patch

import frappe
import pandas as pd

from custom_app.api import budget_control
from custom_app.custom_app.doctype.budget_reallocation.budget_reallocation import BudgetReallocation
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
from custom_app.tests.fake_site import Doc, SiteTest

COMPANY = "Test College"
DOCTYPES = Path(__file__).resolve().parents[1] / "custom_app" / "doctype"


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
		self.doc = document(
			BudgetReallocation,
			company=COMPANY,
			cost_center="Library - TC",
			fiscal_year="2026-2027",
			account="Books - TC",
			month="October",
			new_budget=20000,
		)

	def budget(self):
		self.site.add(
			"Monthly Distribution",
			"2026-2027 - Library - TC - Books - TC",
			percentages=[Doc(month="October", percentage_allocation=25)],
		)
		return self.site.add(
			"Budget",
			"BUDGET-1",
			docstatus=1,
			company=COMPANY,
			cost_center="Library - TC",
			fiscal_year="2026-2027",
			accounts=[Doc(account="Books - TC", budget_amount=120000)],
		)

	def test_it_starts_from_the_months_present_budget(self):
		self.budget()
		self.doc.calculate_current_budget()
		self.doc.calculate_differences()
		self.assertEqual(
			(self.doc.current_budget, self.doc.difference, self.doc.new_total_annual_budget),
			(30000, -10000, 110000),
		)

	def test_it_needs_a_monthly_distribution(self):
		self.assertRefused("Monthly Distribution not found", self.doc.calculate_current_budget)

	def test_it_needs_a_submitted_budget_for_the_account(self):
		self.budget().docstatus = 0
		self.assertRefused("No Budget found for Account", self.doc.calculate_current_budget)

	def test_it_needs_a_reason_and_a_new_amount(self):
		fields = json.loads(
			(DOCTYPES / "budget_reallocation" / "budget_reallocation.json").read_text(encoding="utf-8")
		)["fields"]
		mandatory = {f["fieldname"] for f in fields if f.get("reqd")}
		self.assertLessEqual({"account", "month", "new_budget", "reason", "cost_center"}, mandatory)

	def test_an_increase_beyond_the_master_budget_is_refused(self):
		self.doc.__dict__.update(
			difference=10,
			master_budget_limit=1000,
			total_allocated_budget=1000,
			total_annual_budget=400,
			new_total_annual_budget=410,
		)
		self.assertRefused("Budget Limit Exceeded", self.doc.validate_budget_limit)
		self.doc.master_budget_limit = 1010
		self.doc.validate_budget_limit()



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
