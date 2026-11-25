"""Business rules from a purchase request to its payment, and expense claims (RULES.md PR, SQ, PO, PI, PE, EC).

No site or database is needed, see fake_site:

	python -m unittest custom_app.tests.test_rules_purchase
	bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_purchase
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe

from custom_app.api import (
	expense_claim,
	material_request,
	payment_entry,
	purchase_invoice,
	purchase_order,
	supplier_quotation,
)
from custom_app.overrides import material_request as request_override
from custom_app.tasks import auto_cancel_material_request as auto_cancel
from custom_app.tests.fake_site import Doc, SiteTest

COMPANY = "Test College"
CUSTOM = Path(__file__).resolve().parents[1] / "custom_app" / "custom"


def customised(doctype):
	return json.loads((CUSTOM / f"{frappe.scrub(doctype)}.json").read_text(encoding="utf-8"))


def mandatory_custom_fields(doctype):
	return {f["fieldname"] for f in customised(doctype)["custom_fields"] if f.get("reqd")}


def property_of(doctype, field, prop):
	for setter in customised(doctype)["property_setters"]:
		if setter.get("field_name") == field and setter["property"] == prop:
			return setter["value"]


class PurchaseTest(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Employee", "EMP-1", department="Library - TC", user_id="raiser@example.com")
		self.site.add("Cost Center", "Library - TC", custom_department="Library - TC")
		self.site.add(
			"Fiscal Year", "2026-2027", year_start_date="2026-04-01", year_end_date="2027-03-31", disabled=0
		)
		self.site.add("Item Default", "d1", parent="Books", company=COMPANY, expense_account="Books - TC")
		self.budgeted = [{"name": "BUDGET-1"}]
		self.site.answer("from `tabBudget` b", lambda values: self.budgeted)

	def request(self, **values):
		return Doc(
			"Material Request",
			**{
				"name": "PR-1",
				"company": COMPANY,
				"custom_employee": "EMP-1",
				"custom_cost_center": "Library - TC",
				"transaction_date": "2026-10-15",
				"items": [Doc(idx=1, item_code="Books")],
				**values,
			},
		)


class TestPurchaseRequest(PurchaseTest):
	def test_a_request_must_name_employee_cost_center_approver_and_notes(self):
		self.assertLessEqual(
			{"custom_employee", "custom_cost_center", "custom_request_approver", "custom_notes"},
			mandatory_custom_fields("Material Request"),
		)
		self.assertEqual(property_of("Material Request Item", "rate", "reqd"), "1")

	def test_every_row_takes_the_requests_cost_center(self):
		doc = self.request(
			items=[Doc(idx=1, item_code="Books", cost_center="Other - TC"), Doc(idx=2, item_code="Books")]
		)
		material_request.update_item_cost_center(doc, None)
		self.assertEqual([row.cost_center for row in doc.items], ["Library - TC"] * 2)

	def test_an_employee_without_a_department_cannot_raise_a_request(self):
		self.site.add("Employee", "EMP-2")
		self.assertRefused(
			"Department not found for Employee EMP-2",
			material_request.update_item_cost_center,
			self.request(custom_employee="EMP-2"),
			None,
		)

	def test_a_department_without_a_cost_center_cannot_raise_a_request(self):
		self.site.add("Employee", "EMP-3", department="Sports - TC")
		self.assertRefused(
			"No Cost Center found for Department Sports - TC",
			material_request.update_item_cost_center,
			self.request(custom_employee="EMP-3"),
			None,
		)

	def test_a_request_needs_an_active_fiscal_year_on_its_date(self):
		self.assertRefused(
			"No active Fiscal Year",
			material_request.update_item_cost_center,
			self.request(transaction_date="2028-01-01"),
			None,
		)
		self.site.records["Fiscal Year"]["2026-2027"].disabled = 1
		self.assertRefused(
			"No active Fiscal Year", material_request.update_item_cost_center, self.request(), None
		)

	def test_an_item_needs_an_expense_account_in_the_company(self):
		self.assertRefused(
			"No Default Account found for Item",
			material_request.update_item_cost_center,
			self.request(items=[Doc(idx=4, item_code="Chairs")]),
			None,
		)

	def test_a_request_needs_a_submitted_budget_on_its_account_and_cost_center(self):
		material_request.update_item_cost_center(self.request(), None)
		query, values = self.site.queries[-1]
		self.assertEqual(values, ("Books - TC", COMPANY, "Library - TC", "2026-2027"))
		self.assertIn("b.docstatus = 1", query)
		self.budgeted = []
		self.assertRefused(
			"No submitted Budget found for Account",
			material_request.update_item_cost_center,
			self.request(),
			None,
		)

	def test_the_expense_account_follows_the_item_on_every_save(self):
		doc = self.request(
			items=[
				Doc(item_code="Books", expense_account="Old - TC"),
				Doc(item_code="Books"),
				Doc(expense_account="Typed - TC"),
			]
		)
		self.site.add("Company", COMPANY, default_expense_account="General - TC")
		with patch.object(request_override, "_expected_expense_account", return_value="Books - TC") as lookup:
			request_override.sync_expense_account(doc)
		self.assertEqual([r.expense_account for r in doc.items], ["Books - TC", "Books - TC", "Typed - TC"])
		lookup.assert_called_once_with("Books", COMPANY, "General - TC")

	def test_an_item_with_no_account_anywhere_keeps_the_rows_own(self):
		doc = self.request(items=[Doc(item_code="Books", expense_account="Old - TC")])
		with patch.object(request_override, "_expected_expense_account", return_value=None):
			request_override.sync_expense_account(doc)
		self.assertEqual(doc.items[0].expense_account, "Old - TC")

	def test_the_account_comes_from_item_then_group_then_brand_then_company(self):
		def account(item=None, group=None, brand=None):
			with (
				patch.object(request_override, "get_item_defaults", return_value=frappe._dict(expense_account=item)),
				patch.object(
					request_override, "get_item_group_defaults", return_value=frappe._dict(expense_account=group)
				),
				patch.object(
					request_override, "get_brand_defaults", return_value=frappe._dict(expense_account=brand)
				),
			):
				return request_override._expected_expense_account("Books", COMPANY, "Company - TC")

		self.assertEqual(account("Item - TC", "Group - TC", "Brand - TC"), "Item - TC")
		self.assertEqual(account(None, "Group - TC", "Brand - TC"), "Group - TC")
		self.assertEqual(account(None, None, "Brand - TC"), "Brand - TC")
		self.assertEqual(account(), "Company - TC")

	def test_rates_typed_on_a_new_request_are_kept(self):
		def refreshed(in_insert, before):
			doc = object.__new__(request_override.CustomMaterialRequest)
			doc.flags = frappe._dict(in_insert=in_insert)
			doc.get_doc_before_save = lambda: before
			with patch.object(request_override.MaterialRequest, "update_item_rates", create=True) as core:
				doc.update_item_rates()
			return core.called

		self.assertFalse(refreshed(True, None))
		self.assertFalse(refreshed(False, None))
		self.assertTrue(refreshed(False, Doc()))

	def test_a_listed_cost_center_needs_a_verifier(self):
		self.site.add(
			"Verifier PR Details",
			"v1",
			parent="Verifier PR Settings",
			parenttype="Verifier PR Settings",
			cost_center="Library - TC",
		)
		self.assertRefused(
			"Request Verifier is mandatory", material_request.validate_request_verifier, self.request()
		)
		doc = self.request(custom_request_verifier="verifier@example.com")
		material_request.validate_request_verifier(doc)
		self.assertEqual(doc.custom_request_verifier, "verifier@example.com")

	def test_a_cost_center_that_is_not_listed_has_no_verifier(self):
		doc = self.request(custom_request_verifier="verifier@example.com")
		material_request.validate_request_verifier(doc)
		self.assertIsNone(doc.custom_request_verifier)

	def test_a_new_request_emails_its_approver(self):
		self.site.add("User", "boss@example.com", email="boss@example.com")
		material_request.notify_approver_on_create(self.request(custom_request_approver="boss@example.com"))
		self.assertEqual(self.site.emails[0].recipients, ["boss@example.com"])
		self.assertIn("New Purchase Request: PR-1", self.site.emails[0].subject)

	def test_a_request_with_no_approver_emails_no_one(self):
		material_request.notify_approver_on_create(self.request())
		self.assertEqual(self.site.emails, [])

	def status_change(self, before, after):
		self.site.add("User", "raiser@example.com", email="raiser@example.com")
		material_request.notify_employee_on_status_change(
			self.request(workflow_state=after, before=Doc(workflow_state=before))
		)
		return [(email.recipients, email.subject) for email in self.site.emails]

	def test_the_employee_is_told_when_a_request_is_rejected(self):
		self.assertEqual(
			self.status_change("Draft", "Rejected"),
			[(["raiser@example.com"], "Purchase Request PR-1 — Rejected")],
		)

	def test_saving_a_rejected_request_again_sends_no_second_email(self):
		self.assertEqual(self.status_change("Rejected", "Rejected"), [])



class TestAutoCancel(SiteTest):
	def setUp(self):
		super().setUp()
		self.patch("custom_app.tasks.auto_cancel_material_request.nowdate", lambda: "2026-10-31")
		self.orders = []
		self.site.answer("from `tabPurchase Order Item` poi", lambda values: self.orders)
		self.patch(
			"custom_app.tasks.auto_cancel_material_request.get_workflow_name", lambda doctype: "PR workflow"
		)
		self.site.add(
			"Workflow",
			"PR workflow",
			workflow_state_field="workflow_state",
			states=[Doc(state="Approved by Manager", doc_status="1"), Doc(state="Cancelled", doc_status="2")],
		)
		self.site.add("Employee", "EMP-1", user_id="raiser@example.com")
		self.site.add("User", "raiser@example.com", email="raiser@example.com")

	def request(self, name="PR-1", **values):
		return self.site.add(
			"Material Request",
			name,
			**{
				"docstatus": 1,
				"material_request_type": "Purchase",
				"status": "Pending",
				"per_ordered": 0,
				"transaction_date": "2026-10-01",
				"workflow_state": "Approved by Manager",
				"custom_employee": "EMP-1",
				**values,
			},
		)

	def test_a_request_with_no_order_is_cancelled_after_thirty_days(self):
		old = self.request("PR-1", transaction_date="2026-10-01")
		young = self.request("PR-2", transaction_date="2026-10-02")
		self.assertEqual(auto_cancel.cancel_unordered_material_requests()["cancelled"], ["PR-1"])
		self.assertEqual((old.docstatus, old.workflow_state), (2, "Cancelled"))
		self.assertEqual(young.docstatus, 1)
		self.assertEqual([email.recipients for email in self.site.emails], [["raiser@example.com"]])

	def test_stopped_ordered_and_non_purchase_requests_are_left_alone(self):
		for i, values in enumerate(
			(
				{"status": "Stopped"},
				{"status": "Ordered"},
				{"status": "Partially Ordered"},
				{"material_request_type": "Material Transfer"},
				{"docstatus": 0},
				{"per_ordered": 40},
			)
		):
			self.request(f"PR-{i}", **values)
		self.assertEqual(auto_cancel.cancel_unordered_material_requests()["eligible"], 0)

	def test_a_request_with_a_submitted_order_is_left_alone(self):
		doc = self.request()
		self.orders = [{"name": "PO-1", "docstatus": 1}]
		result = auto_cancel.cancel_unordered_material_requests()
		self.assertEqual((result["cancelled"], result["skipped_has_submitted_po"]), ([], ["PR-1"]))
		self.assertEqual(doc.docstatus, 1)

	def test_a_draft_order_is_kept_with_a_comment(self):
		self.request()
		order = self.site.add("Purchase Order", "PO-1")
		self.orders = [{"name": "PO-1", "docstatus": 0}]
		auto_cancel.cancel_unordered_material_requests()
		self.assertEqual(order.docstatus, 0)
		self.assertIn("Purchase Request PR-1 was automatically cancelled", order.calls[0][1])

	def test_a_dry_run_changes_nothing(self):
		doc = self.request()
		self.assertEqual(auto_cancel.cancel_unordered_material_requests(dry_run=True)["cancelled"], ["PR-1"])
		self.assertEqual((doc.docstatus, self.site.emails), (1, []))

	def test_one_request_that_fails_does_not_stop_the_others(self):
		bad, good = self.request("PR-1"), self.request("PR-2")
		bad.cancel = MagicMock(side_effect=frappe.ValidationError("linked"))
		self.assertEqual(auto_cancel.cancel_unordered_material_requests()["cancelled"], ["PR-2"])
		self.assertEqual((good.docstatus, len(self.site.errors)), (2, 1))


class TestQuotation(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Material Request Item", "row-1", parent="PR-1", item_code="Books", amount=1000)

	def check(self, amount, **row):
		row = {"material_request": "PR-1", "material_request_item": "row-1", "item_code": "Books", **row}
		material_request.validate_quotation_against_material_request(Doc(items=[Doc(amount=amount, **row)]))

	def test_a_quotation_may_equal_the_request_but_not_exceed_it(self):
		self.check(1000)
		self.assertRefused("cannot exceed the approved Purchase", self.check, 1000.01)

	def test_a_row_without_a_row_link_is_checked_by_its_item(self):
		self.check(1000, material_request_item=None)
		self.assertRefused("cannot exceed", self.check, 1001, material_request_item=None)
		self.assertRefused("cannot exceed", self.check, 1, material_request_item=None, item_code="Chairs")

	def test_a_row_without_a_request_is_not_checked(self):
		self.check(999999, material_request=None)

	def test_the_quotations_cost_center_is_put_on_every_row(self):
		doc = Doc(cost_center="Library - TC", items=[Doc(), Doc(cost_center="Other - TC")])
		supplier_quotation.update_item_cost_center(doc, None)
		self.assertEqual([row.cost_center for row in doc.items], ["Library - TC"] * 2)

	def test_a_new_quotation_is_not_ordered(self):
		doc = Doc()
		supplier_quotation.set_default_order_status(doc, None)
		self.assertEqual(doc.custom_order_status, "Not Ordered")
		doc = Doc(custom_order_status="Partially Ordered")
		supplier_quotation.set_default_order_status(doc, None)
		self.assertEqual(doc.custom_order_status, "Partially Ordered")

	def order(self, qty, row="q1"):
		return Doc(items=[Doc(qty=qty, supplier_quotation="SQ-1", supplier_quotation_item=row), Doc(qty=5)])

	def quotation(self):
		self.site.add("Supplier Quotation Item", "q1", parent="SQ-1", qty=10)
		self.site.add("Supplier Quotation Item", "q2", parent="SQ-1", qty=4)
		return self.site.add("Supplier Quotation", "SQ-1", custom_order_status="Not Ordered")

	def test_submitting_orders_moves_the_quotation_to_completely_ordered(self):
		quotation = self.quotation()
		supplier_quotation.update_ordered_qty_on_po_submit(self.order(10), None)
		self.assertEqual(quotation.custom_order_status, "Partially Ordered")
		supplier_quotation.update_ordered_qty_on_po_submit(self.order(4, "q2"), None)
		self.assertEqual(quotation.custom_order_status, "Completely Ordered")

	def test_cancelling_an_order_takes_its_quantity_back_and_never_below_zero(self):
		quotation = self.quotation()
		supplier_quotation.update_ordered_qty_on_po_submit(self.order(6), None)
		supplier_quotation.update_ordered_qty_on_po_cancel(self.order(6), None)
		self.assertEqual(quotation.custom_order_status, "Not Ordered")
		supplier_quotation.update_ordered_qty_on_po_cancel(self.order(6), None)
		self.assertEqual(self.site.get_value("Supplier Quotation Item", "q1", "custom_qty_ordered"), 0)


class TestPurchaseOrder(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Item Default", "d1", parent="Books", company=COMPANY, default_supplier="Book House")
		self.site.add("Material Request Item", "row-1", expense_account="Books - TC")

	def check(self, supplier="Book House", **row):
		row = {"idx": 1, "item_code": "Books", "material_request": "PR-1", **row}
		doc = Doc(company=COMPANY, supplier=supplier, cost_center="Library - TC", items=[Doc(**row)])
		purchase_order.validate_po_items(doc, None)
		return doc

	def test_every_order_row_needs_a_purchase_request(self):
		self.assertRefused("Row 1: Material Request is mandatory", self.check, material_request=None)

	def test_without_a_quotation_only_the_items_default_supplier_may_be_ordered_from(self):
		self.check()
		self.assertRefused("does not match Purchase Order Supplier", self.check, supplier="Other House")
		self.assertRefused("no Default Supplier set", self.check, item_code="Chairs")

	def test_with_a_quotation_any_supplier_may_be_ordered_from(self):
		self.check(supplier="Other House", supplier_quotation="SQ-1")

	def test_an_orders_expense_account_must_match_the_request(self):
		self.check(material_request_item="row-1", expense_account="Books - TC")
		self.assertRefused(
			"does not match the Expense Account",
			self.check,
			material_request_item="row-1",
			expense_account="Travel - TC",
		)

	def test_the_orders_cost_center_is_put_on_every_row(self):
		self.assertEqual(self.check(cost_center="Other - TC").items[0].cost_center, "Library - TC")

	def test_a_receipt_row_needs_a_purchase_order(self):
		self.assertEqual(property_of("Purchase Receipt Item", "purchase_order", "reqd"), "1")

	def test_the_cost_center_is_mandatory_along_the_whole_chain(self):
		for doctype in ("Supplier Quotation", "Purchase Order", "Purchase Receipt", "Purchase Invoice"):
			self.assertEqual(property_of(doctype, "cost_center", "reqd"), "1", doctype)
		self.assertIn("custom_cost_center", mandatory_custom_fields("Request for Quotation"))


class TestPurchaseInvoice(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Purchase Order Item", "po-row", expense_account="Books - TC")
		self.site.add("Material Request Item", "pr-row", expense_account="Books - TC")

	def check(self, **row):
		row = {"idx": 2, "purchase_order": "PO-1", "expense_account": "Books - TC", **row}
		purchase_invoice.validate_pi_items(Doc(items=[Doc(**row)]), None)

	def test_every_invoice_row_needs_a_purchase_order(self):
		self.check()
		self.assertRefused("Row 2: Purchase Order is mandatory", self.check, purchase_order=None)
		self.assertEqual(property_of("Purchase Invoice Item", "purchase_order", "reqd"), "1")

	def test_an_invoices_expense_account_must_match_the_order(self):
		self.check(po_detail="po-row")
		self.assertRefused("set in Purchase Order", self.check, po_detail="po-row", expense_account="X - TC")

	def test_an_invoices_expense_account_must_match_the_request(self):
		self.check(material_request_item="pr-row")
		self.assertRefused(
			"set in Material Request", self.check, material_request_item="pr-row", expense_account="X - TC"
		)

	def test_category_and_planned_payment_date_can_change_after_submit(self):
		fields = {f["fieldname"]: f for f in customised("Purchase Invoice")["custom_fields"]}
		for field in ("custom_category", "custom_planned_payment_date"):
			self.assertEqual(fields[field].get("allow_on_submit"), 1, field)


class TestPayment(SiteTest):
	def pay(self, party_type, references, unallocated=0):
		payment_entry.validate(
			Doc(party_type=party_type, references=references, unallocated_amount=unallocated), None
		)

	def test_an_employee_payment_needs_a_reference(self):
		self.pay("Employee", [Doc()], unallocated=10)
		self.assertRefused("required for Employee Payment Entry", self.pay, "Employee", [])

	def test_a_supplier_payment_needs_a_reference_and_nothing_unallocated(self):
		self.pay("Supplier", [Doc()])
		self.assertRefused("required for Supplier Payment Entry", self.pay, "Supplier", [])
		self.assertRefused("Unallocated Amount must be zero", self.pay, "Supplier", [Doc()], 1)

	def test_a_customer_payment_needs_no_reference(self):
		self.pay("Customer", [], unallocated=10)

	def test_a_payment_keeps_who_made_it_and_who_approved_it(self):
		doc = Doc()
		self.log_in("maker@example.com")
		payment_entry.before_save(doc, None)
		self.log_in("approver@example.com")
		payment_entry.before_submit(doc, None)
		self.assertEqual((doc.custom_creator, doc.custom_approver), ("maker@example.com", "approver@example.com"))
		self.assertIsNotNone(doc.custom_creation_date_time)
		self.assertIsNotNone(doc.custom_approval_date_time)



class TestExpenseClaim(PurchaseTest):
	def setUp(self):
		super().setUp()
		self.site.add(
			"Expense Claim Account", "a1", parent="Travel", company=COMPANY, default_account="Travel - TC"
		)

	def claim(self, **values):
		return Doc(
			"Expense Claim",
			**{
				"name": "EC-1",
				"company": COMPANY,
				"employee": "EMP-1",
				"posting_date": "2026-10-15",
				"expenses": [Doc(idx=1, expense_type="Travel")],
				**values,
			},
		)

	def test_a_claim_takes_the_cost_center_of_the_employees_department(self):
		doc = self.claim(cost_center="Other - TC")
		expense_claim.update_item_cost_center(doc, None)
		self.assertEqual((doc.cost_center, doc.expenses[0].cost_center), ("Library - TC", "Library - TC"))

	def test_a_claim_needs_a_department_and_its_cost_center(self):
		self.site.add("Employee", "EMP-2")
		self.site.add("Employee", "EMP-3", department="Sports - TC")
		check = expense_claim.update_item_cost_center
		self.assertRefused("Department not found", check, self.claim(employee="EMP-2"), None)
		self.assertRefused("No Cost Center found", check, self.claim(employee="EMP-3"), None)

	def test_a_claim_needs_an_active_fiscal_year_on_its_date(self):
		self.assertRefused(
			"No active Fiscal Year",
			expense_claim.update_item_cost_center,
			self.claim(posting_date="2030-01-01"),
			None,
		)

	def test_a_claim_type_needs_an_account_in_the_company(self):
		self.assertRefused(
			"No Default Account found for Expense Claim Type",
			expense_claim.update_item_cost_center,
			self.claim(company="Other College"),
			None,
		)

	def test_a_claim_needs_a_submitted_budget_on_its_account_and_cost_center(self):
		expense_claim.update_item_cost_center(self.claim(), None)
		self.assertEqual(
			self.site.queries[-1][1], ("Travel - TC", COMPANY, "Library - TC", "2026-2027")
		)
		self.budgeted = []
		self.assertRefused(
			"No submitted Budget found", expense_claim.update_item_cost_center, self.claim(), None
		)

	def test_no_one_approves_their_own_claim(self):
		from custom_app.overrides.expense_claim import CustomExpenseClaim, ExpenseClaim

		def save(user, status):
			self.log_in(user)
			doc = object.__new__(CustomExpenseClaim)
			doc.employee, doc.approval_status = "EMP-1", status
			with patch.object(ExpenseClaim, "validate"):
				doc.validate()

		save("raiser@example.com", "Draft")
		save("boss@example.com", "Approved")
		for status in ("Approved", "Rejected"):
			self.assertRefused("cannot Approve/Reject your own", save, "raiser@example.com", status)

	def test_a_new_claim_emails_its_approver(self):
		self.site.add("User", "boss@example.com", email="boss@example.com")
		expense_claim.notify_approver_on_create(self.claim(expense_approver="boss@example.com"))
		expense_claim.notify_approver_on_create(self.claim())
		self.assertEqual([e.recipients for e in self.site.emails], [["boss@example.com"]])

	def test_the_employee_is_told_once_when_a_claim_is_approved_or_rejected(self):
		self.site.add("User", "raiser@example.com", email="raiser@example.com")

		def move(before, after):
			expense_claim.on_workflow_state_change(
				self.claim(workflow_state=after, before=Doc(workflow_state=before))
			)

		move("Draft", "Approved")
		move("Approved", "Approved")
		move("Approved", "Finance Approved")
		move("Draft", "Rejected")
		self.assertEqual(
			[e.subject for e in self.site.emails],
			["Expense Claim EC-1 — Approved", "Expense Claim EC-1 — Rejected"],
		)

	def test_the_cost_center_is_mandatory_on_a_claim_and_its_rows(self):
		self.assertEqual(property_of("Expense Claim", "cost_center", "reqd"), "1")
		self.assertEqual(property_of("Expense Claim Detail", "cost_center", "reqd"), "1")


if __name__ == "__main__":
	unittest.main()
