"""Business rules of workflows, access, vendors, emails and dashboards (RULES.md WF, AC, VN, EM, DB).

No site or database is needed, see fake_site:

	python -m unittest custom_app.tests.test_rules_access
	bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_access
"""

import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import frappe

from custom_app.api import email, letter_head, notification_utils, supplier, user_permission
from custom_app.custom_app.page.finance_dashboard import finance_dashboard
from custom_app.custom_app.page.hr_dashboard import hr_dashboard
from custom_app.custom_app.page.purchase_timeline import purchase_timeline
from custom_app.permissions import expense_claim, material_request, salary_slip, wb_task
from custom_app.tests.fake_site import Doc, SiteTest

APP = Path(__file__).resolve().parents[1]


def workflows():
	found = json.loads((APP / "fixtures" / "workflow.json").read_text(encoding="utf-8"))
	return {workflow["document_type"]: workflow for workflow in found}


def steps(doctype, **wanted):
	return [t for t in workflows()[doctype]["transitions"] if all(t.get(k) == v for k, v in wanted.items())]


class TestWorkflows(unittest.TestCase):
	APPROVERS = {
		"Material Request": {"Expense Approver"},
		"Purchase Order": {"Procurement Approver"},
		"Purchase Invoice": {"Finance Approver"},
		"Payment Entry": {"AP Manager"},
		"Expense Claim": {"Expense Approver"},
		"Budget Upload": {"Finance Approver"},
		"Budget Reallocation": {"Finance Approver"},
		"Master Budget": {"Finance Approver"},
	}

	def test_each_document_has_one_active_workflow(self):
		self.assertEqual(set(workflows()), set(self.APPROVERS))
		self.assertTrue(all(w["is_active"] for w in workflows().values()))

	def test_each_document_is_approved_by_its_own_role(self):
		for doctype, roles in self.APPROVERS.items():
			self.assertEqual({t["allowed"] for t in steps(doctype, action="Approve")}, roles, doctype)

	def test_no_one_approves_their_own_draft(self):
		for doctype in self.APPROVERS:
			for action in ("Approve", "Reject"):
				for step in steps(doctype, state="Draft", action=action):
					self.assertFalse(step["allow_self_approval"], f"{doctype} {action}")

	def allowed(self, doctype, state, **values):
		doc = frappe._dict(values)
		return [
			t["action"]
			for t in steps(doctype, state=state)
			if not t.get("condition") or eval(t["condition"], {"doc": doc})  # the app's own fixture
		]

	def test_a_request_with_a_verifier_is_verified_before_approval(self):
		self.assertEqual(
			self.allowed("Material Request", "Draft", custom_request_verifier="v@example.com"),
			["Verify", "Reject"],
		)
		self.assertEqual(self.allowed("Material Request", "Verified"), ["Approve", "Reject"])

	def test_a_request_without_a_verifier_is_approved_directly(self):
		for empty in (None, ""):
			self.assertEqual(
				self.allowed("Material Request", "Draft", custom_request_verifier=empty), ["Approve", "Reject"]
			)

	def test_a_claim_is_approved_by_the_manager_and_then_by_finance(self):
		(step,) = steps("Expense Claim", action="Finance Approve")
		self.assertEqual(
			(step["state"], step["next_state"], step["allowed"]), ("Approved", "Finance Approved", "Finance Approver")
		)
		self.assertFalse(step["allow_self_approval"])

	def test_a_claim_finance_rejects_is_cancelled(self):
		(step,) = steps("Expense Claim", action="Finance Reject")
		self.assertEqual((step["next_state"], step["allowed"]), ("Cancelled", "Finance Approver"))

	def status(self, doctype):
		return {s["state"]: str(s["doc_status"]) for s in workflows()[doctype]["states"]}

	def test_an_approved_document_is_submitted_and_a_rejected_one_stays_a_draft(self):
		for doctype in set(self.APPROVERS) - {"Expense Claim", "Material Request"}:
			self.assertEqual(
				self.status(doctype), {"Draft": "0", "Approved": "1", "Rejected": "0", "Cancelled": "2"}, doctype
			)
		self.assertEqual(self.status("Material Request")["Approved by Manager"], "1")
		self.assertEqual(self.status("Material Request")["Rejected"], "0")

	def test_a_rejected_claim_is_submitted_as_rejected(self):
		states = {s["state"]: s for s in workflows()["Expense Claim"]["states"]}
		self.assertEqual(
			(str(states["Rejected"]["doc_status"]), states["Rejected"]["update_value"]), ("1", "Rejected")
		)

	def test_a_reallocation_cannot_be_cancelled(self):
		self.assertEqual(steps("Budget Reallocation", action="Cancel"), [])


class TestLists(SiteTest):
	def shown(self, query, *roles):
		self.log_in("me@example.com", *roles)
		self.site.add("Employee", "EMP-1", user_id="me@example.com")
		return query("me@example.com")

	def test_system_managers_and_auditors_list_everything(self):
		for query in (
			material_request.material_request_permission_query,
			expense_claim.expense_claim_permission_query,
		):
			for role in ("System Manager", "Auditor"):
				self.assertEqual(self.shown(query, role), "")

	def test_a_user_with_no_role_lists_nothing(self):
		for query in (
			material_request.material_request_permission_query,
			expense_claim.expense_claim_permission_query,
			wb_task.wb_task_permission_query,
		):
			self.assertEqual(self.shown(query), "1=0")

	def test_who_lists_which_purchase_requests(self):
		query = material_request.material_request_permission_query
		self.assertEqual(
			self.shown(query, "Procurement User"),
			"(`tabMaterial Request`.`workflow_state` = 'Approved by Manager')",
		)
		self.assertEqual(
			self.shown(query, "Expense Approver"),
			"(`tabMaterial Request`.`custom_request_approver` = 'me@example.com'"
			" OR `tabMaterial Request`.`custom_request_verifier` = 'me@example.com')",
		)
		self.assertEqual(
			self.shown(query, "Employee"), "(`tabMaterial Request`.`custom_employee` = 'EMP-1')"
		)

	def test_who_lists_which_expense_claims(self):
		query = expense_claim.expense_claim_permission_query
		self.assertIn("IN ('Approved', 'Finance Approved', 'Cancelled')", self.shown(query, "Finance Approver"))
		for role in ("AP User", "AP Manager"):
			self.assertIn("IN ('Finance Approved')", self.shown(query, role))
		self.assertIn("`expense_approver` = 'me@example.com'", self.shown(query, "Expense Approver"))
		self.assertIn("`employee` = 'EMP-1'", self.shown(query, "Employee"))

	def test_two_roles_list_what_either_lists(self):
		shown = self.shown(material_request.material_request_permission_query, "Procurement User", "Employee")
		self.assertIn(" OR ", shown)

	def test_an_employee_role_without_an_employee_record_lists_nothing(self):
		self.log_in("ghost@example.com", "Employee")
		self.assertEqual(
			material_request.material_request_permission_query("ghost@example.com"), "(1=0)"
		)

	def test_salary_slips_are_listed_only_to_their_employee(self):
		self.assertEqual(
			self.shown(salary_slip.salary_slip_permission_query, "Employee", "HR User"),
			"`tabSalary Slip`.`employee` in ('EMP-1')",
		)
		for role in ("System Manager", "HR Manager"):
			self.assertEqual(self.shown(salary_slip.salary_slip_permission_query, role), "")
		self.log_in("ghost@example.com", "Employee")
		self.assertEqual(salary_slip.salary_slip_permission_query("ghost@example.com"), "1=0")

	def test_a_salary_slip_opens_only_for_its_employee(self):
		self.shown(lambda user: None, "Employee")
		opens = lambda employee: salary_slip.has_permission(Doc(employee=employee), user="me@example.com")  # noqa: E731
		self.assertTrue(opens("EMP-1"))
		self.assertFalse(opens("EMP-2"))
		self.assertFalse(opens(None))
		self.site.roles["me@example.com"] = ["HR Manager"]
		self.assertTrue(opens("EMP-2"))

	def test_a_workboard_task_is_listed_to_who_gave_it_and_who_does_it(self):
		shown = self.shown(wb_task.wb_task_permission_query, "Employee")
		self.assertIn("`assign_from` = 'me@example.com'", shown)
		self.assertIn("`assign_to` = 'me@example.com'", shown)
		self.assertEqual(self.shown(wb_task.wb_task_permission_query, "System Manager"), "")


class TestUserPermissions(SiteTest):
	def setUp(self):
		super().setUp()
		for company in ("CDE", "VU", "KL"):
			self.site.add("Company", company)
		self.site.add("Employee", "EMP-1", user_id="me@example.com", company="CDE")

	def save_user(self, profile):
		user_permission.manage_user_permissions(Doc(name="me@example.com", role_profile_name=profile), None)
		return [(doc.allow, doc.for_value, doc.applicable_for) for doc in self.site.made]

	def test_an_employee_is_limited_to_their_own_record(self):
		self.assertEqual(self.save_user("Employee"), [("Employee", "EMP-1", None)])

	def test_an_employee_keeps_only_their_own_company(self):
		for company in ("CDE", "VU"):
			self.site.add(
				"User Permission", f"up-{company}", user="me@example.com", allow="Company", for_value=company
			)
		self.save_user(None)
		self.assertEqual(self.site.deleted, [("User Permission", "up-VU")])

	def test_hr_and_admin_lose_the_employee_limit_and_get_every_other_company_mailbox(self):
		self.site.add("User Permission", "up", user="me@example.com", allow="Employee", for_value="EMP-1")
		self.assertEqual(
			self.save_user("HR"), [("Company", "VU", "Email Account"), ("Company", "KL", "Email Account")]
		)
		self.assertEqual(self.site.deleted, [("User Permission", "up")])

	def test_a_user_with_no_employee_record_is_left_alone(self):
		user_permission.manage_user_permissions(Doc(name="ghost@example.com"), None)
		self.assertEqual(self.site.made, [])


class TestVendor(SiteTest):
	def code(self, company, last=None):
		self.site.answers = [("SELECT custom_vendor_code", [{"custom_vendor_code": last}] if last else [])]
		doc = Doc(custom_company=company)
		supplier.set_vendor_code(doc, None)
		return doc.custom_vendor_code.split("-")

	def test_a_vendor_code_is_company_year_and_number(self):
		year = str(date.today().year)
		self.assertEqual(self.code("DSJ Keep Learning"), ["DSJ", year, "0001"])
		self.assertEqual(self.code("Centre for Developmental Education")[0], "CDE")
		self.assertEqual(self.code("Vijaybhoomi University")[0], "VU")
		self.assertEqual(self.code("Anyone else")[0], "GEN")

	def test_the_number_follows_the_last_vendor_of_the_company_and_year(self):
		self.assertEqual(self.code("DSJ Keep Learning", "DSJ-2026-0041")[2], "0042")
		self.assertIn(f"DSJ-{date.today().year}-%", self.site.queries[-1][1])

	def test_a_vendor_must_have_tax_contact_and_bank_details(self):
		fields = json.loads((APP / "custom_app" / "custom" / "supplier.json").read_text(encoding="utf-8"))
		mandatory = {f["fieldname"] for f in fields["custom_fields"] if f.get("reqd")}
		self.assertLessEqual(
			{
				"custom_company",
				"custom_pan_number",
				"custom_primary_contact_person",
				"custom_email",
				"custom_phone_number",
				"custom_office_address",
				"custom_bank_account_number_1",
				"custom_benificiary_name_1",
				"custom_ifsc_code_1",
				"custom_bank_name_1",
			},
			mandatory,
		)

	def test_the_vendor_form_asks_for_the_same_details(self):
		form = json.loads(
			(APP / "custom_app" / "web_form" / "vendor_details" / "vendor_details.json").read_text(encoding="utf-8")
		)
		mandatory = {f["fieldname"] for f in form["web_form_fields"] if f.get("reqd")}
		self.assertLessEqual({"custom_company", "custom_pan_number", "custom_bank_account_number_1"}, mandatory)
		self.assertEqual(form["doc_type"], "Supplier")


class TestEmails(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Email Account", "CDE mail", custom_company="CDE", email_id="cde@example.com")
		self.site.add("Purchase Order", "PO-1", company="CDE")

	def send(self, **values):
		doc = Doc(**{"sent_or_received": "Sent", "sender": "me@example.com", **values})
		email.set_company_email_account(doc, None)
		return doc.email_account, doc.sender

	def test_an_email_goes_out_from_the_documents_companys_account(self):
		self.assertEqual(
			self.send(reference_doctype="Purchase Order", reference_name="PO-1"), ("CDE mail", "cde@example.com")
		)

	def test_without_a_document_the_senders_own_company_is_used(self):
		self.site.add("Employee", "EMP-1", user_id="me@example.com", company="CDE")
		self.log_in("me@example.com")
		self.assertEqual(self.send(), ("CDE mail", "cde@example.com"))

	def test_received_emails_and_companies_with_no_account_are_left_alone(self):
		self.site.add("Purchase Order", "PO-2", company="VU")
		for values in (
			{"sent_or_received": "Received", "reference_doctype": "Purchase Order", "reference_name": "PO-1"},
			{"reference_doctype": "Purchase Order", "reference_name": "PO-2"},
		):
			self.assertEqual(self.send(**values), (None, "me@example.com"))

	def test_each_person_gets_a_notification_once(self):
		notification_utils.safe_sendmail(["A@example.com", "a@example.com ", "", None], "s", "m")
		self.assertEqual(self.site.emails[0].recipients, ["a@example.com"])
		notification_utils.safe_sendmail([None, " "], "s", "m")
		self.assertEqual(len(self.site.emails), 1)

	def test_a_failed_email_never_stops_the_document(self):
		with patch("frappe.sendmail", side_effect=RuntimeError("mail server down")):
			notification_utils.safe_sendmail(["a@example.com"], "s", "m")
		self.assertEqual(len(self.site.errors), 1)


class TestLetterHead(SiteTest):
	def after(self, **values):
		self.site.add("Company", "CDE", default_letter_head="CDE head")
		self.site.add("Company", "VU")
		doc = Doc(**{"letter_head": "Typed", **values})
		letter_head.set_letter_head(doc)
		return doc.letter_head

	def test_a_new_document_takes_its_companys_letter_head(self):
		self.assertEqual(self.after(company="CDE", new=True), "CDE head")

	def test_a_saved_document_changes_it_only_with_its_company(self):
		self.assertEqual(self.after(company="CDE", before=Doc(company="CDE")), "Typed")
		self.assertEqual(self.after(company="CDE", before=Doc(company="VU")), "CDE head")

	def test_a_company_without_one_leaves_the_letter_head_alone(self):
		self.assertEqual(self.after(company="VU", new=True), "Typed")


class TestDashboards(SiteTest):
	def setUp(self):
		super().setUp()
		self.companies = ["CDE", "VU"]
		self.site.answer("FROM `tabCompany` ORDER BY", [{"name": "CDE"}, {"name": "KL"}, {"name": "VU"}])
		self.site.answer("FROM `tabCompany` WHERE name IN", lambda names: [{"name": n} for n in sorted(names)])
		self.patch(
			"frappe.permissions.get_user_permissions",
			lambda user: {"Company": [frappe._dict(doc=c) for c in self.companies]},
		)

	def log_in_as(self, role):
		self.log_in("me@example.com", role)

	def test_a_system_manager_sees_every_company(self):
		self.log_in_as("System Manager")
		self.assertEqual(hr_dashboard._resolve_company("KL"), "KL")
		self.assertIsNone(hr_dashboard._resolve_company(None))
		self.assertEqual(finance_dashboard._enforce_company("KL"), "KL")
		self.assertEqual(purchase_timeline._get_permitted_companies(), (["CDE", "KL", "VU"], False))

	def test_an_institution_head_is_kept_to_their_companies(self):
		self.log_in_as("Institution Head")
		self.assertEqual(hr_dashboard._resolve_company("KL"), "CDE")
		self.assertIn("IN (", finance_dashboard._company_where("pi", "KL")[0])
		self.assertEqual(finance_dashboard._company_where("pi", "VU")[1], {"company": "VU"})
		self.companies = ["VU"]
		self.assertEqual(finance_dashboard._enforce_company("KL"), "VU")
		self.assertEqual(purchase_timeline._get_permitted_companies(), (["VU"], True))

	def test_with_no_company_permission_hr_and_finance_show_nothing(self):
		self.log_in_as("Institution Head")
		self.companies = []
		self.assertEqual(hr_dashboard._resolve_company("CDE"), "__NONE__")
		self.assertEqual(finance_dashboard._enforce_company("CDE"), "__NONE__")
		self.assertEqual(finance_dashboard._company_where("pi", "CDE"), (" AND 1=0", {}))

	def test_with_no_company_permission_the_purchase_timeline_shows_all(self):
		self.log_in_as("Institution Head")
		self.companies = []
		self.assertEqual(purchase_timeline._get_permitted_companies(), (["CDE", "KL", "VU"], False))

	def test_the_purchase_timeline_is_refused_to_other_roles(self):
		self.log_in_as("Employee")
		with self.assertRaises(frappe.PermissionError):
			purchase_timeline._get_permitted_companies()

	def test_a_period_is_this_month_quarter_or_year(self):
		with patch.object(hr_dashboard, "nowdate", lambda: "2026-11-25"):
			period = hr_dashboard._period_dates
			self.assertEqual(period("month"), (date(2026, 11, 1), date(2026, 11, 30)))
			self.assertEqual(period("quarter"), (date(2026, 10, 1), date(2026, 12, 31)))
			self.assertEqual(period("year"), (date(2026, 1, 1), date(2026, 12, 31)))
			self.assertEqual(
				period("custom", "2026-02-01", "2026-02-10"), (date(2026, 2, 1), date(2026, 2, 10))
			)

	def ageing(self, *rows):
		self.log_in_as("System Manager")
		self.site.answer(
			"FROM `tabPurchase Invoice` pi",
			[{"supplier": "S", "supplier_name": "S", "age_days": a, "outstanding_amount": o} for a, o in rows],
		)
		result = finance_dashboard.get_creditor_ageing(date_to="2026-11-25")
		return {row["label"]: row["amount"] for row in result["chart_data"]}

	def test_creditors_age_in_thirty_day_steps(self):
		self.assertEqual(
			self.ageing((30, 1), (31, 2), (60, 4), (61, 8), (90, 16), (120, 32), (121, 64)),
			{"0-30": 1, "31-60": 6, "61-90": 24, "91-120": 32, "120+": 64},
		)

	def risk(self, *spend):
		self.log_in_as("System Manager")
		self.site.answers = [
			("GROUP BY pi.supplier", [{"supplier": f"S{i}", "total_spend": s} for i, s in enumerate(spend)])
		]
		return finance_dashboard.get_vendor_concentration(date_from="2026-04-01", date_to="2026-11-25")["risk_level"]

	def test_vendor_risk_is_the_share_of_the_top_three(self):
		self.assertEqual(self.risk(14, 14, 13, *[1] * 59), "High")
		self.assertEqual(self.risk(14, 13, 13, *[1] * 60), "Medium")
		self.assertEqual(self.risk(9, 8, 8, *[1] * 75), "Low")


if __name__ == "__main__":
	unittest.main()
