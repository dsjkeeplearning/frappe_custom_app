"""Integration tests for keep learning budget controls, PR raising to final payment.

Run:
    bench --site keep.localhost run-tests --module custom_app.tests.test_budget_integration

Every test builds its own data in a throwaway cost center ("TEST BI - CDE")
inside the existing CDE company and is rolled back afterwards: each test runs
inside a savepoint, and the class-level data is rolled back when the class
ends (FrappeTestCase). frappe.db.commit is disabled for the whole run, because
Budget Reallocation commits mid-transaction, which would otherwise leave test
data on the site.

Dates are frozen to 15 Oct 2026 unless a test says otherwise, because the
backdated and current-month checks depend on today's date.
"""

import os
import unittest
from contextlib import contextmanager

import frappe

# Import pandas (used by the upload doctypes) before any date is frozen:
# importing it under freezegun takes many minutes.
import pandas  # noqa: F401
import custom_app.custom_app.doctype.budget_upload.budget_upload  # noqa: F401
import custom_app.custom_app.doctype.mid_year_budget_upload.mid_year_budget_upload  # noqa: F401
from frappe.model.workflow import apply_workflow
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

COMPANY = "Centre for Developmental Education"
ABBR = "CDE"
FISCAL_YEAR = "2026-2027"
TODAY = "2026-10-15"

PREFIX = "TEST BI"
DEPARTMENT = f"{PREFIX} - {ABBR}"
COST_CENTER = f"{PREFIX} - {ABBR}"
OTHER_COST_CENTER = f"{PREFIX} Other - {ABBR}"
ACCOUNT_PARENT = "SO - Student Operations - CDE"

MONTHS = [
    "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "January", "February", "March",
]

# Account A: annual 10,00,000. October is tight (50,000), September has
# 1,00,000 and December 2,00,000. Accumulated budget to the end of October is
# 4,00,000, to the end of December 7,00,000.
PLAN_A = dict(zip(MONTHS, [
    50_000, 50_000, 50_000, 50_000, 50_000, 100_000,
    50_000, 100_000, 200_000, 100_000, 100_000, 100_000,
], strict=True))

# Account B: same total, but nothing in October.
PLAN_B = dict(zip(MONTHS, [
    50_000, 50_000, 50_000, 50_000, 50_000, 100_000,
    0, 100_000, 250_000, 100_000, 100_000, 100_000,
], strict=True))

ACCOUNT_A = f"TBI-A Test Supplies - {ABBR}"
ACCOUNT_B = f"TBI-B Test Services - {ABBR}"
ITEM_A = "TBI-ITEM-A"
ITEM_B = "TBI-ITEM-B"
SUPPLIER = "TBI Test Supplier"
CLAIM_TYPE = "TBI Test Claim"

ALL_TOGGLES_ON = {
    "restrict_backdated_pr": 1,
    "restrict_pr_to_current_month_budget": 1,
    "use_transaction_date_for_pr_budget": 1,
    "pr_transaction_date_effective_from": None,
}


def known_bug(reason):
    """Mark a test that fails because of a bug found during this work.

    The test asserts the correct behaviour. It shows as "expected failure"
    until the bug is fixed, then as "unexpected success": remove the marker
    at that point. `reason` names the bug in the test report. Run with
    SHOW_KNOWN_BUGS=1 to see the actual error of each one.
    """

    def decorate(fn):
        fn.known_bug = reason
        if os.environ.get("SHOW_KNOWN_BUGS"):
            return fn  # run as a normal test to see each bug's actual error
        return unittest.expectedFailure(fn)

    return decorate


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


def _get_or_insert(doctype, name, values):
    if frappe.db.exists(doctype, name):
        return frappe.get_doc(doctype, name)
    doc = frappe.get_doc({"doctype": doctype, **values})
    doc.insert(ignore_permissions=True)
    return doc


def make_distribution(cost_center, account, plan):
    annual = sum(plan.values())
    name = f"{FISCAL_YEAR} - {cost_center} - {account}"
    return _get_or_insert(
        "Monthly Distribution",
        name,
        {
            "distribution_id": name,
            "fiscal_year": FISCAL_YEAR,
            "percentages": [
                {"month": month, "percentage_allocation": amount * 100.0 / annual}
                for month, amount in plan.items()
            ],
        },
    )


def make_budget(cost_center, account, plan):
    distribution = make_distribution(cost_center, account, plan)
    budget = frappe.get_doc(
        {
            "doctype": "Budget",
            "budget_against": "Cost Center",
            "company": COMPANY,
            "cost_center": cost_center,
            "fiscal_year": FISCAL_YEAR,
            "monthly_distribution": distribution.name,
            "applicable_on_material_request": 1,
            "action_if_annual_budget_exceeded_on_mr": "Stop",
            "action_if_accumulated_monthly_budget_exceeded_on_mr": "Stop",
            "applicable_on_purchase_order": 1,
            "action_if_annual_budget_exceeded_on_po": "Stop",
            "action_if_accumulated_monthly_budget_exceeded_on_po": "Stop",
            "applicable_on_booking_actual_expenses": 1,
            "action_if_annual_budget_exceeded": "Stop",
            "action_if_accumulated_monthly_budget_exceeded": "Stop",
            "accounts": [{"account": account, "budget_amount": sum(plan.values())}],
        }
    )
    budget.insert(ignore_permissions=True)
    budget.submit()
    return budget


def make_test_data():
    """Cost center, department, employee, accounts, items, supplier, budgets."""
    for name in (PREFIX, f"{PREFIX} Other"):
        _get_or_insert(
            "Department",
            f"{name} - {ABBR}",
            {
                "department_name": name,
                "company": COMPANY,
                "parent_department": "CDE departments - CDE",
            },
        )
        _get_or_insert(
            "Cost Center",
            f"{name} - {ABBR}",
            {
                "cost_center_name": name,
                "company": COMPANY,
                "parent_cost_center": "Centre for Developmental Education - CDE",
                "custom_department": f"{name} - {ABBR}",
            },
        )

    for account in (ACCOUNT_A, ACCOUNT_B):
        _get_or_insert(
            "Account",
            account,
            {
                "account_name": account.removesuffix(f" - {ABBR}"),
                "company": COMPANY,
                "parent_account": ACCOUNT_PARENT,
                "root_type": "Expense",
                "report_type": "Profit and Loss",
            },
        )

    supplier = frappe.db.get_value("Supplier", {"supplier_name": SUPPLIER})
    if not supplier:
        supplier = (
            frappe.get_doc(
                {
                    "doctype": "Supplier",
                    "supplier_name": SUPPLIER,
                    "supplier_type": "Company",
                    "custom_company": COMPANY,
                    "gst_category": "Unregistered",
                    "custom_pan_number": "AAACT1234B",
                    "custom_primary_contact_person": "Test Person",
                    "custom_email": "tbi-supplier@example.com",
                    "custom_phone_number": "9999999999",
                    "custom_office_address": "Test address",
                    "custom_bank_account_number_1": "000000000000",
                    "custom_benificiary_name_1": "TBI Test Supplier",
                    "custom_ifsc_code_1": "TEST0000000",
                    "custom_bank_name_1": "Test Bank",
                }
            )
            .insert(ignore_permissions=True)
            .name
        )

    for item_code, account in ((ITEM_A, ACCOUNT_A), (ITEM_B, ACCOUNT_B)):
        _get_or_insert(
            "Item",
            item_code,
            {
                "item_code": item_code,
                "item_name": item_code,
                "item_group": "Student Operations",
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "is_purchase_item": 1,
                "item_defaults": [
                    {
                        "company": COMPANY,
                        "default_warehouse": "Stores - CDE",
                        "expense_account": account,
                        "default_supplier": supplier,
                    }
                ],
            },
        )

    _get_or_insert(
        "Expense Claim Type",
        CLAIM_TYPE,
        {
            "expense_type": CLAIM_TYPE,
            "accounts": [{"company": COMPANY, "default_account": ACCOUNT_A}],
        },
    )

    employee = frappe.db.get_value("Employee", {"first_name": "TBI Test Employee"})
    if not employee:
        employee = (
            frappe.get_doc(
                {
                    "doctype": "Employee",
                    "first_name": "TBI Test Employee",
                    "company": COMPANY,
                    "department": DEPARTMENT,
                    "gender": "Female",
                    "date_of_birth": "1990-01-01",
                    "date_of_joining": "2020-01-01",
                    "status": "Active",
                    # Mandatory on this site (property setters).
                    "bank_name": "Test Bank",
                    "bank_ac_no": "000000000000",
                    "ifsc_code": "TEST0000000",
                }
            )
            .insert(ignore_permissions=True)
            .name
        )

    budgets = {
        ACCOUNT_A: make_budget(COST_CENTER, ACCOUNT_A, PLAN_A),
        ACCOUNT_B: make_budget(COST_CENTER, ACCOUNT_B, PLAN_B),
        # Same account in another cost center: must never leak into ours.
        "other": make_budget(OTHER_COST_CENTER, ACCOUNT_A, PLAN_A),
    }

    return frappe._dict(employee=employee, supplier=supplier, budgets=budgets)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class BudgetTestCase(FrappeTestCase):
    """Shared data, frozen date, savepoint per test, settings restored."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()  # commits once, then rolls back at class end

        cls._real_commit = frappe.db.commit
        frappe.db.commit = lambda *args, **kwargs: None
        cls.addClassCleanup(cls._restore_commit)

        cls.enterClassContext(cls._frozen(TODAY))
        frappe.set_user("Administrator")

        # A worker that has already loaded the Material Request controller,
        # which is what swaps in the custom get_other_condition. A fresh
        # worker is covered by test_h3_first_budget_check_in_fresh_worker.
        import custom_app.overrides.material_request  # noqa: F401
        cls.data = make_test_data()

    @classmethod
    def _restore_commit(cls):
        frappe.db.commit = cls._real_commit

    @staticmethod
    @contextmanager
    def _frozen(when):
        from freezegun import freeze_time

        from frappe.tests.utils import get_datetime, get_system_timezone, pytz

        tz = pytz.timezone(get_system_timezone())
        with freeze_time(tz.localize(get_datetime(when)).astimezone(pytz.utc)):
            yield

    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.savepoint("budget_test")
        self.addCleanup(self._rollback_test)
        self.set_settings(**ALL_TOGGLES_ON)

    def _rollback_test(self):
        frappe.db.rollback(save_point="budget_test")
        frappe.set_user("Administrator")
        frappe.clear_document_cache("Budget Settings", "Budget Settings")
        frappe.local.flags.pop("budget_settings", None)

    # -- helpers ------------------------------------------------------------

    def set_settings(self, **values):
        settings = frappe.get_single("Budget Settings")
        settings.update(values)
        settings.flags.ignore_permissions = True
        settings.save()
        frappe.clear_document_cache("Budget Settings", "Budget Settings")

    def make_pr(
        self, rate, transaction_date=TODAY, schedule_date=None, item=ITEM_A, cost_center=COST_CENTER, qty=1, verifier=None
    ):
        """Draft Purchase Request (Material Request of type Purchase)."""
        doc = frappe.get_doc(
            {
                "doctype": "Material Request",
                "material_request_type": "Purchase",
                "company": COMPANY,
                "transaction_date": transaction_date,
                "schedule_date": schedule_date or transaction_date,
                "custom_cost_center": cost_center,
                "custom_employee": self.data.employee,
                "custom_request_approver": "Administrator",
                "custom_request_verifier": verifier,
                "custom_notes": "Integration test",
                "items": [
                    {
                        "item_code": item,
                        "qty": qty,
                        "uom": "Nos",
                        "stock_uom": "Nos",
                        "conversion_factor": 1,
                        "rate": rate,
                        "amount": rate * qty,
                        "schedule_date": schedule_date or transaction_date,
                        "warehouse": "Stores - CDE",
                    }
                ],
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def raise_and_approve_pr(self, amount, **kwargs):
        doc = self.make_pr(amount, **kwargs)
        return apply_workflow(doc, "Approve")

    def assertBlocked(self, fn, *args, contains, **kwargs):
        with self.assertRaises(frappe.ValidationError) as ctx:
            fn(*args, **kwargs)
        self.assertIn(contains, str(ctx.exception))
        return ctx.exception

    def report_row(self, account=ACCOUNT_A, cost_center=COST_CENTER):
        """The account's row in the Budget Availability Report."""
        from custom_app.custom_app.report.budget_availability_report.budget_availability_report import (
            execute,
        )

        result = execute({"company": COMPANY, "cost_center": cost_center, "fiscal_year": FISCAL_YEAR})
        rows = [row for row in result[1] if row["account"] == account]
        self.assertEqual(len(rows), 1, f"expected one report row for {account}")
        return rows[0]

    def assertPrCheckAllowsExactly(self, left, item=ITEM_A):
        """A draft PR for exactly `left` saves, one for ₹1 more is blocked.

        Drafts never count as consumption, so this does not change the state.
        """
        self.make_pr(left, item=item)
        self.assertBlocked(self.make_pr, left + 1, item=item, contains="Insufficient budget for October 2026")

    def assertConsumed(self, amount, account=ACCOUNT_A):
        """The report and the PR check agree that October has used `amount`."""
        row = self.report_row(account)
        self.assertEqual(row["oct_consumed"], amount)
        self.assertEqual(row["oct_left"], PLAN_A["October"] - amount)
        self.assertPrCheckAllowsExactly(PLAN_A["October"] - amount)


# ---------------------------------------------------------------------------
# A. Which month a PR uses
# ---------------------------------------------------------------------------


class TestPrBudgetMonth(BudgetTestCase):
    def test_a1_custom_check_uses_transaction_month_not_required_by(self):
        # October has 50,000; December (the Required By month) has 2,00,000.
        self.assertBlocked(
            self.make_pr, 60_000, schedule_date="2026-12-01", contains="Insufficient budget for October 2026"
        )

    def test_a1_core_check_uses_transaction_month_when_toggle_on(self):
        # Only the core check: accumulated budget is 4,00,000 to October and
        # 7,00,000 to December, so 5,00,000 is blocked only if October is used.
        self.set_settings(restrict_pr_to_current_month_budget=0)
        pr = self.make_pr(500_000, schedule_date="2026-12-01")

        self.assertBlocked(
            apply_workflow,
            pr,
            "Approve",
            contains="is <strong>₹ 4,00,000.00</strong>. It will be exceed by <strong>₹ 1,00,000.00</strong>",
        )

    def test_a2_core_check_uses_required_by_month_when_toggle_off(self):
        # Standard ERPNext: the Required By month (December, 7,00,000
        # accumulated) decides, so 5,00,000 is allowed.
        self.set_settings(restrict_pr_to_current_month_budget=0, use_transaction_date_for_pr_budget=0)
        pr = self.make_pr(500_000, schedule_date="2026-12-01")

        pr = apply_workflow(pr, "Approve")

        self.assertEqual(pr.docstatus, 1)

    def test_a3_march_pr_required_in_april_counts_in_current_fiscal_year(self):
        from erpnext.accounts.doctype.budget import budget as core_budget

        with self._frozen("2027-03-20"):
            self.set_settings(restrict_pr_to_current_month_budget=0)
            self.raise_and_approve_pr(40_000, transaction_date="2027-03-20", schedule_date="2027-04-10")

            args = frappe._dict(
                expense_account=ACCOUNT_A,
                item_code=ITEM_A,
                budget_against_field="cost_center",
                cost_center=COST_CENTER,
                fiscal_year=FISCAL_YEAR,
            )
            self.assertEqual(core_budget.get_requested_amount(args), 40_000)

    def test_a4_print_format_shows_transaction_month(self):
        pr = self.raise_and_approve_pr(10_000, schedule_date="2026-12-01")

        html = frappe.get_print("Material Request", pr.name, print_format="Material Request Print Format")

        self.assertIn("October 2026", html)
        self.assertNotIn("December 2026", html)


# ---------------------------------------------------------------------------
# B. Monthly limit, no carry-forward
# ---------------------------------------------------------------------------


class TestMonthlyLimit(BudgetTestCase):
    def test_b1_pr_below_month_left_is_allowed(self):
        pr = self.raise_and_approve_pr(30_000)

        self.assertEqual(pr.docstatus, 1)
        self.assertEqual(pr.workflow_state, "Approved by Manager")

    def test_b2_pr_equal_to_left_allowed_then_one_rupee_more_blocked(self):
        pr = self.raise_and_approve_pr(50_000)
        self.assertEqual(pr.docstatus, 1)

        self.assertBlocked(self.make_pr, 1, contains="Insufficient budget for October 2026")

    def test_b3_unused_september_budget_does_not_help_october(self):
        # September (1,00,000) is untouched; October has 50,000.
        self.assertBlocked(self.make_pr, 80_000, contains="Insufficient budget for October 2026")

    def test_b4_without_month_restriction_accumulated_budget_applies(self):
        self.set_settings(restrict_pr_to_current_month_budget=0)

        pr = self.raise_and_approve_pr(80_000)

        self.assertEqual(pr.docstatus, 1)

    def test_b5_month_with_zero_allocation_blocks_any_pr(self):
        self.assertBlocked(self.make_pr, 1, item=ITEM_B, contains="Insufficient budget for October 2026")


# ---------------------------------------------------------------------------
# C. Backdated PRs
# ---------------------------------------------------------------------------


class TestBackdatedPr(BudgetTestCase):
    def test_c1_pr_dated_previous_month_is_blocked(self):
        self.assertBlocked(self.make_pr, 10_000, transaction_date="2026-09-30", contains="Backdated Material Request is not allowed")

    def test_c1b_pr_dated_yesterday_is_blocked_rule_is_before_today(self):
        self.assertBlocked(self.make_pr, 10_000, transaction_date="2026-10-14", contains="Backdated Material Request is not allowed")

    def test_c2_pr_dated_today_is_allowed(self):
        pr = self.raise_and_approve_pr(10_000, transaction_date=TODAY)

        self.assertEqual(pr.docstatus, 1)

    def test_c3_toggle_off_allows_previous_month(self):
        self.set_settings(restrict_backdated_pr=0)

        pr = self.raise_and_approve_pr(10_000, transaction_date="2026-09-30")

        self.assertEqual(pr.docstatus, 1)
        self.assertEqual(self.report_row()["sep_consumed"], 10_000)


# ---------------------------------------------------------------------------
# E. Budget Availability Report
# ---------------------------------------------------------------------------


class TestAvailabilityReport(BudgetTestCase):
    def test_e1_month_budgets_follow_distribution_and_add_up(self):
        row = self.report_row()

        for month, amount in PLAN_A.items():
            self.assertAlmostEqual(row[f"{month[:3].lower()}_budget"], amount, places=2, msg=month)
        self.assertEqual(row["annual_budget"], 1_000_000)

    def test_e4_report_left_is_exactly_what_a_pr_can_use(self):
        self.raise_and_approve_pr(20_000)

        left = self.report_row()["oct_left"]

        self.assertEqual(left, 30_000)
        self.assertPrCheckAllowsExactly(left)

    def test_e5_other_cost_center_does_not_leak(self):
        self.raise_and_approve_pr(20_000, cost_center=OTHER_COST_CENTER)

        self.assertEqual(self.report_row()["oct_consumed"], 0)
        self.assertEqual(self.report_row(cost_center=OTHER_COST_CENTER)["oct_consumed"], 20_000)


# ---------------------------------------------------------------------------
# D. What counts as consumed, PR raising to final payment
# ---------------------------------------------------------------------------


class ProcureToPayMixin:
    """Each step goes through the same mapping and workflow a user would use."""

    def make_po(self, pr, qty=None):
        from custom_app.overrides.material_request import make_purchase_order

        po = make_purchase_order(pr.name)
        po.supplier = self.data.supplier
        po.transaction_date = TODAY
        po.schedule_date = TODAY
        po.custom_notes = "Integration test"
        for row in po.items:
            row.schedule_date = TODAY
            if qty is not None:
                row.qty = qty
        po.insert(ignore_permissions=True)
        return apply_workflow(po, "Approve")

    def make_receipt(self, po):
        from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

        receipt = make_purchase_receipt(po.name)
        receipt.posting_date = TODAY
        receipt.set_posting_time = 1
        receipt.insert(ignore_permissions=True)
        receipt.submit()
        return receipt

    def make_invoice(self, po):
        from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

        invoice = make_purchase_invoice(po.name)
        invoice.posting_date = TODAY
        invoice.set_posting_time = 1
        invoice.bill_no = f"TBI-{frappe.generate_hash(length=6)}"
        invoice.custom_attachment = "/files/tbi-test-invoice.pdf"
        invoice.custom_category = "Academic Expenses"
        invoice.insert(ignore_permissions=True)
        return apply_workflow(invoice, "Approve")

    def make_payment(self, invoice, **overrides):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        payment = get_payment_entry("Purchase Invoice", invoice.name, bank_account="Bank Account - CDE")
        payment.posting_date = TODAY
        payment.reference_no = "TBI-UTR-001"
        payment.reference_date = TODAY
        payment.custom_transaction_reference_number = "TBI-UTR-001"
        payment.update(overrides)
        payment.insert(ignore_permissions=True)
        return apply_workflow(payment, "Approve")

    def make_journal_entry(self, lines, posting_date=TODAY):
        """Submitted Journal Entry. lines = [(account, amount)], debit > 0, credit < 0."""
        je = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "company": COMPANY,
                "posting_date": posting_date,
                "accounts": [
                    {
                        "account": account,
                        "cost_center": COST_CENTER,
                        "debit_in_account_currency": max(amount, 0),
                        "credit_in_account_currency": max(-amount, 0),
                    }
                    for account, amount in lines
                ],
            }
        )
        je.insert(ignore_permissions=True)
        je.submit()
        return je

    def make_expense_claim(self, amount, sanctioned=None):
        claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": self.data.employee,
                "company": COMPANY,
                "posting_date": TODAY,
                "payable_account": "Creditors - CDE",
                "expense_approver": "Administrator",
                "expenses": [
                    {
                        "expense_date": TODAY,
                        "expense_type": CLAIM_TYPE,
                        "amount": amount,
                        "sanctioned_amount": amount if sanctioned is None else sanctioned,
                    }
                ],
            }
        )
        claim.insert(ignore_permissions=True)
        return claim


class TestProcureToPay(ProcureToPayMixin, BudgetTestCase):
    def test_d1_submitted_pr_nothing_ordered_counts_in_full(self):
        self.raise_and_approve_pr(20_000)

        self.assertConsumed(20_000)

    def test_d2_d3_pr_po_receipt_invoice_payment_counts_once(self):
        pr = self.raise_and_approve_pr(20_000)
        self.assertConsumed(20_000)

        po = self.make_po(pr)
        self.assertEqual(po.docstatus, 1)
        self.assertEqual(frappe.db.get_value("Material Request", pr.name, "per_ordered"), 100)
        self.assertConsumed(20_000)

        receipt = self.make_receipt(po)
        self.assertEqual(receipt.docstatus, 1)
        self.assertConsumed(20_000)

        invoice = self.make_invoice(po)
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.workflow_state, "Approved")
        self.assertConsumed(20_000)

        payment = self.make_payment(invoice)
        self.assertEqual(payment.docstatus, 1)
        self.assertEqual(payment.custom_approver, "Administrator")
        self.assertEqual(frappe.db.get_value("Purchase Invoice", invoice.name, "outstanding_amount"), 0)
        self.assertConsumed(20_000)

    def test_d2_invoice_books_expense_to_pr_account_and_cost_center(self):
        pr = self.raise_and_approve_pr(20_000)
        invoice = self.make_invoice(self.make_po(pr))

        debit = frappe.db.sql(
            """select sum(debit) from `tabGL Entry`
            where voucher_no = %s and account = %s and cost_center = %s and is_cancelled = 0""",
            (invoice.name, ACCOUNT_A, COST_CENTER),
        )[0][0]
        self.assertEqual(debit, 20_000)

    def test_d4_stopped_pr_nothing_ordered_counts_zero(self):
        pr = self.raise_and_approve_pr(20_000)

        pr.update_status("Stopped")

        self.assertEqual(frappe.db.get_value("Material Request", pr.name, "status"), "Stopped")
        self.assertConsumed(0)

    def test_d5_stopped_pr_half_ordered_counts_half(self):
        pr = self.raise_and_approve_pr(10_000, qty=2)  # 20,000
        self.make_po(pr, qty=1)

        frappe.get_doc("Material Request", pr.name).update_status("Stopped")

        self.assertConsumed(10_000)

    def test_d7_cancelled_pr_counts_zero(self):
        pr = self.raise_and_approve_pr(20_000)

        apply_workflow(pr, "Cancel")

        self.assertEqual(frappe.db.get_value("Material Request", pr.name, "docstatus"), 2)
        self.assertConsumed(0)

    def test_d8_journal_entry_counts_as_used(self):
        self.make_journal_entry([(ACCOUNT_A, 15_000), ("Cash - CDE", -15_000)])

        self.assertConsumed(15_000)

    def test_d8_correcting_journal_entry_is_not_counted_twice(self):
        # 20,000 raised on account A; a Journal Entry then moves 5,000 of it
        # to account B. A has used 15,000, B 5,000: 20,000 in all, not 25,000.
        self.raise_and_approve_pr(20_000)

        self.make_journal_entry([(ACCOUNT_B, 5_000), (ACCOUNT_A, -5_000)])

        self.assertConsumed(15_000)
        self.assertEqual(self.report_row(ACCOUNT_B)["oct_consumed"], 5_000)

    def test_d8_cancelled_journal_entry_counts_zero(self):
        je = self.make_journal_entry([(ACCOUNT_A, 15_000), ("Cash - CDE", -15_000)])

        je.cancel()

        self.assertConsumed(0)

    def test_d8_journal_entry_counts_in_its_posting_month(self):
        self.make_journal_entry([(ACCOUNT_A, 15_000), ("Cash - CDE", -15_000)], posting_date="2026-09-10")

        self.assertEqual(self.report_row()["sep_consumed"], 15_000)
        self.assertConsumed(0)

    def test_supplier_payment_without_reference_is_blocked(self):
        pr = self.raise_and_approve_pr(20_000)
        invoice = self.make_invoice(self.make_po(pr))

        self.assertBlocked(
            self.make_payment,
            invoice,
            references=[],
            contains="At least one Payment Reference is required for Supplier Payment Entry",
        )

    def test_supplier_payment_with_unallocated_amount_is_blocked(self):
        pr = self.raise_and_approve_pr(20_000)
        invoice = self.make_invoice(self.make_po(pr))

        self.assertBlocked(
            self.make_payment,
            invoice,
            paid_amount=25_000,
            received_amount=25_000,
            contains="Unallocated Amount must be zero",
        )

    def test_po_with_wrong_supplier_and_no_quotation_is_blocked(self):
        from custom_app.overrides.material_request import make_purchase_order

        pr = self.raise_and_approve_pr(20_000)
        po = make_purchase_order(pr.name)
        po.supplier = frappe.db.get_value("Supplier", {"name": ["!=", self.data.supplier], "disabled": 0})
        po.custom_notes = "Integration test"
        for row in po.items:
            row.schedule_date = TODAY

        self.assertBlocked(po.insert, contains="does not match Purchase Order Supplier")


class TestExpenseClaims(ProcureToPayMixin, BudgetTestCase):
    def test_d6_approved_claim_counts_at_sanctioned_amount(self):
        claim = self.make_expense_claim(12_000, sanctioned=9_000)

        claim = apply_workflow(claim, "Approve")

        self.assertEqual((claim.docstatus, claim.approval_status), (1, "Approved"))
        self.assertConsumed(9_000)

    def test_d6_rejected_claim_counts_zero(self):
        claim = apply_workflow(self.make_expense_claim(12_000), "Reject")

        self.assertEqual((claim.docstatus, claim.approval_status), (1, "Rejected"))
        self.assertConsumed(0)

    def test_d6_draft_claim_counts_zero(self):
        self.make_expense_claim(12_000)

        self.assertConsumed(0)

    def test_d6_finance_rejected_claim_counts_zero(self):
        claim = apply_workflow(self.make_expense_claim(12_000), "Approve")

        claim = apply_workflow(claim, "Finance Reject")

        self.assertEqual(claim.docstatus, 2)
        self.assertConsumed(0)


# ---------------------------------------------------------------------------
# F. Budget Reallocation
# ---------------------------------------------------------------------------


class ReallocationMixin:
    def make_reallocation(self, new_budget, month="October", account=ACCOUNT_A):
        doc = frappe.get_doc(
            {
                "doctype": "Budget Reallocation",
                "company": COMPANY,
                "cost_center": COST_CENTER,
                "fiscal_year": FISCAL_YEAR,
                "account": account,
                "month": month,
                "new_budget": new_budget,
                "reason": "Integration test",
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def active_budget(self, account=ACCOUNT_A):
        name = frappe.db.sql(
            """select b.name from `tabBudget` b join `tabBudget Account` ba on ba.parent = b.name
            where b.docstatus = 1 and b.cost_center = %s and ba.account = %s""",
            (COST_CENTER, account),
        )[0][0]
        return frappe.get_doc("Budget", name)

    def set_master_budget_row(self, amount):
        """Give TEST BI a row in the company's submitted Master Budget."""
        name = frappe.db.get_value("Master Budget", {"company": COMPANY, "fiscal_year": FISCAL_YEAR, "docstatus": 1})
        existing = frappe.db.get_value("Master Budget Department", {"parent": name, "cost_center": COST_CENTER})
        if existing:
            frappe.db.set_value("Master Budget Department", existing, "budget", amount)
            return name
        row = frappe.get_doc(
            {
                "doctype": "Master Budget Department",
                "parent": name,
                "parenttype": "Master Budget",
                "parentfield": "department_budget",
                "department": DEPARTMENT,
                "cost_center": COST_CENTER,
                "budget": amount,
                "idx": 999,
                "docstatus": 1,
            }
        )
        row.db_insert()
        frappe.db.set_value("Master Budget Department", row.name, "docstatus", 1)
        return name


class TestBudgetReallocation(ReallocationMixin, ProcureToPayMixin, BudgetTestCase):
    def test_f1_draft_changes_no_budget(self):
        before = self.active_budget()

        draft = self.make_reallocation(80_000)

        self.assertEqual(draft.current_budget, 50_000)
        self.assertEqual(draft.new_total_annual_budget, 1_030_000)
        self.assertEqual(self.active_budget().name, before.name)
        self.assertEqual(self.report_row()["oct_budget"], 50_000)

    def test_f2_approve_amends_budget_and_keeps_other_months(self):
        old = self.active_budget()

        doc = apply_workflow(self.make_reallocation(80_000), "Approve")
        doc.reload()

        new = self.active_budget()
        self.assertEqual(frappe.db.get_value("Budget", old.name, "docstatus"), 2)
        self.assertEqual(new.amended_from, old.name)
        self.assertEqual(new.accounts[0].budget_amount, 1_030_000)
        self.assertEqual((doc.old_budget_link, doc.new_budget_link), (old.name, new.name))

        row = self.report_row()
        for month, amount in PLAN_A.items():
            expected = 80_000 if month == "October" else amount
            self.assertAlmostEqual(row[f"{month[:3].lower()}_budget"], expected, delta=0.01, msg=month)

    def test_f3_cannot_reduce_month_below_what_it_already_used(self):
        self.raise_and_approve_pr(40_000)

        self.assertBlocked(self.make_reallocation, 30_000, contains="Cannot reduce the October budget to ₹ 30,000.00")
        self.assertEqual(self.make_reallocation(40_000).new_budget, 40_000)

    def test_f3_expense_claims_count_as_used(self):
        apply_workflow(self.make_expense_claim(45_000), "Approve")

        self.assertBlocked(self.make_reallocation, 44_999, contains="₹ 45,000.00 is already used in October")

    def test_f3_journal_entries_count_as_used(self):
        self.make_journal_entry([(ACCOUNT_A, 45_000), ("Cash - CDE", -45_000)])

        self.assertBlocked(self.make_reallocation, 44_999, contains="₹ 45,000.00 is already used in October")

    def test_f3_without_month_restriction_budget_to_date_is_checked(self):
        # Unused budget rolls forward, so October may use earlier months'
        # budget: 4,00,000 up to October, 3,90,000 used in October.
        self.set_settings(restrict_pr_to_current_month_budget=0)
        self.raise_and_approve_pr(390_000)

        self.assertBlocked(self.make_reallocation, 39_999, contains="would be ₹ 3,89,999.00")
        self.assertEqual(self.make_reallocation(40_000).new_budget, 40_000)

    def test_f3_stopped_pr_does_not_block_a_reduction(self):
        # Budget to the end of October is 4,00,000. A 3,90,000 PR, stopped
        # with nothing ordered, uses nothing, so October can go down from
        # 50,000 to 10,000. The current check counts the 3,90,000 and blocks.
        self.set_settings(restrict_pr_to_current_month_budget=0)
        pr = self.raise_and_approve_pr(390_000)
        pr.update_status("Stopped")
        self.set_settings(restrict_pr_to_current_month_budget=1)

        doc = self.make_reallocation(10_000)

        self.assertEqual(doc.new_total_annual_budget, 960_000)

    def test_f4_increase_needs_master_budget_headroom(self):
        # TEST BI has 20,00,000 allocated across two accounts.
        self.set_master_budget_row(2_000_000)
        self.assertBlocked(self.make_reallocation, 80_000, contains="Budget Limit Exceeded")

        self.set_master_budget_row(2_030_000)
        self.assertEqual(self.make_reallocation(80_000).new_total_annual_budget, 1_030_000)

    def test_f5_pr_check_and_report_use_new_month_amount_at_once(self):
        apply_workflow(self.make_reallocation(80_000), "Approve")

        self.assertEqual(self.report_row()["oct_left"], 80_000)
        self.make_pr(80_000)
        self.assertBlocked(self.make_pr, 80_001, contains="Insufficient budget for October 2026")

    def test_f6_named_approver_is_recorded(self):
        user = self.make_user("tbi-finance-approver@example.com", ["Finance Approver"])
        doc = self.make_reallocation(80_000)

        frappe.set_user(user)
        apply_workflow(frappe.get_doc("Budget Reallocation", doc.name), "Approve")
        frappe.set_user("Administrator")

        self.assertEqual(frappe.db.get_value("Budget Reallocation", doc.name, "approver"), user)

    def make_user(self, email, roles):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {"doctype": "User", "email": email, "first_name": "TBI", "send_welcome_email": 0}
            ).insert(ignore_permissions=True)
            user.add_roles(*roles)
        return email


# ---------------------------------------------------------------------------
# G. Master Budget
# ---------------------------------------------------------------------------


def march_only(amount):
    """A whole year's budget placed in March."""
    return {month: (amount if month == "March" else 0) for month in MONTHS}


class TestMasterBudget(ReallocationMixin, BudgetTestCase):
    def test_g1_cost_center_rows_cannot_exceed_master_total(self):
        doc = frappe.get_doc(
            {
                "doctype": "Master Budget",
                "company": "DSJ Keep Learning",
                "fiscal_year": "2025-2026",
                "total_budget": 100,
                "department_budget": [{"cost_center": "001 - keeplearning OS - DSJKL", "budget": 101}],
            }
        )

        self.assertBlocked(doc.insert, contains="cannot be greater than Total Budget")

    def make_account(self, name):
        return _get_or_insert(
            "Account",
            f"{name} - {ABBR}",
            {
                "account_name": name,
                "company": COMPANY,
                "parent_account": ACCOUNT_PARENT,
                "root_type": "Expense",
                "report_type": "Profit and Loss",
            },
        ).name

    def test_g1_budget_saved_directly_over_master_is_blocked(self):
        # TEST BI already has 20,00,000 allocated; the row allows 25,00,000.
        self.set_master_budget_row(2_500_000)
        account = self.make_account("TBI-C Test Extra")

        self.assertBlocked(
            make_budget, COST_CENTER, account, march_only(500_001), contains="Master Budget limit exceeded"
        )
        self.assertEqual(frappe.db.count("Budget", {"cost_center": COST_CENTER, "docstatus": 1}), 2)

    def test_g1_budget_saved_directly_within_master_is_allowed(self):
        self.set_master_budget_row(2_500_000)
        account = self.make_account("TBI-C Test Extra")

        budget = make_budget(COST_CENTER, account, march_only(500_000))  # exactly the 5,00,000 left

        self.assertEqual(budget.docstatus, 1)

    def test_g1_cost_center_without_master_row_is_not_checked(self):
        # TEST BI has no row in the Master Budget (as in setUpClass).
        account = self.make_account("TBI-C Test Extra")

        budget = make_budget(COST_CENTER, account, march_only(50_000_000))

        self.assertEqual(budget.docstatus, 1)

    def test_g1_amending_a_budget_does_not_count_it_twice(self):
        # Exactly full: amending a budget for the same amount must still pass.
        self.set_master_budget_row(2_000_000)
        old = frappe.get_doc("Budget", self.data.budgets[ACCOUNT_A].name)
        old.cancel()
        amended = frappe.copy_doc(old)
        amended.docstatus = 0
        amended.amended_from = old.name
        amended.insert(ignore_permissions=True)

        amended.submit()

        self.assertEqual(amended.docstatus, 1)

    def test_g2_amended_master_budget_with_higher_total_applies(self):
        name = self.set_master_budget_row(2_000_000)
        self.assertBlocked(self.make_reallocation, 80_000, contains="Budget Limit Exceeded")

        master = frappe.get_doc("Master Budget", name)
        master = apply_workflow(master, "Cancel")
        amended = frappe.copy_doc(master)  # what the form's Amend does
        amended.docstatus = 0
        amended.workflow_state = "Draft"
        amended.amended_from = master.name
        # The TEST BI row was added outside the total; cover it plus 30,000.
        amended.total_budget = master.total_budget + 2_030_000
        for row in amended.department_budget:
            if row.cost_center == COST_CENTER:
                row.budget = 2_030_000
        amended.insert(ignore_permissions=True)
        amended = apply_workflow(amended, "Approve")

        self.assertEqual(amended.docstatus, 1)
        self.assertEqual(self.make_reallocation(80_000).master_budget_limit, 2_030_000)


# ---------------------------------------------------------------------------
# H. Regression and housekeeping
# ---------------------------------------------------------------------------


class TestRegression(ProcureToPayMixin, BudgetTestCase):
    def test_h1_journal_entry_over_accumulated_budget_is_blocked(self):
        je = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "company": COMPANY,
                "posting_date": TODAY,
                "accounts": [
                    {"account": ACCOUNT_A, "cost_center": COST_CENTER, "debit_in_account_currency": 400_001},
                    {"account": "Cash - CDE", "cost_center": COST_CENTER, "credit_in_account_currency": 400_001},
                ],
            }
        )
        je.insert(ignore_permissions=True)

        self.assertBlocked(je.submit, contains="Accumulated Monthly Budget for Account")

    def test_h2_all_toggles_off_pr_behaves_like_standard_erpnext(self):
        self.set_settings(
            restrict_backdated_pr=0,
            restrict_pr_to_current_month_budget=0,
            use_transaction_date_for_pr_budget=0,
        )

        pr = self.raise_and_approve_pr(80_000, transaction_date="2026-09-30")

        self.assertEqual(pr.docstatus, 1)

    def test_auto_cancel_releases_budget_after_30_days(self):
        from custom_app.tasks.auto_cancel_material_request import cancel_unordered_material_requests

        pr = self.raise_and_approve_pr(20_000)
        self.assertConsumed(20_000)

        with self._frozen("2026-11-15"):
            result = cancel_unordered_material_requests(only=[pr.name])

        self.assertEqual(result["cancelled"], [pr.name])
        self.assertEqual(frappe.db.get_value("Material Request", pr.name, "docstatus"), 2)
        self.assertConsumed(0)

    def test_auto_cancel_leaves_ordered_pr_alone(self):
        from custom_app.tasks.auto_cancel_material_request import cancel_unordered_material_requests

        pr = self.raise_and_approve_pr(20_000)
        self.make_po(pr)

        with self._frozen("2026-11-15"):
            result = cancel_unordered_material_requests(only=[pr.name])

        self.assertEqual(result["cancelled"], [])
        self.assertEqual(frappe.db.get_value("Material Request", pr.name, "docstatus"), 1)


class TestReportCarriesOverspend(ProcureToPayMixin, BudgetTestCase):
    def test_e3_overspent_earlier_month_caps_left_and_pr_check_agrees(self):
        # Simulates history: before the monthly restriction, Expense Claims
        # could overspend. Let actual expenses only warn, then claim 3,80,000
        # in September against 3,50,000 budget to the end of September.
        frappe.db.set_value("Budget", self.data.budgets[ACCOUNT_A].name, "action_if_accumulated_monthly_budget_exceeded", "Warn")
        with self._frozen("2026-09-15"):
            claim = self.make_expense_claim(380_000)
            claim.posting_date = "2026-09-15"
            claim.save()
            apply_workflow(claim, "Approve")

        row = self.report_row()
        self.assertEqual(row["sep_consumed"], 380_000)
        self.assertEqual(row["sep_left"], -280_000)  # month: 1,00,000 - 3,80,000
        # October's own balance is 50,000, but only 4,00,000 - 3,80,000 is
        # left from April, so Left is capped at 20,000.
        self.assertEqual(row["oct_left"], 20_000)
        self.assertEqual(row.get("oct_capped"), 1)

        # The PR check must allow exactly 20,000. The custom monthly check
        # alone would allow 50,000; ERPNext's accumulated check stops it.
        apply_workflow(self.make_pr(20_000), "Approve")
        self.assertBlocked(apply_workflow, self.make_pr(1), "Approve", contains="Accumulated Monthly Budget")


class TestOldErpnextSignature(BudgetTestCase):
    """Live runs ERPNext 15.121, whose get_other_condition(args, for_doc)
    returns SQL text. This bench runs 15.125; stand the 15.121 function in to
    check the custom replacement still takes and returns the old form there."""

    @staticmethod
    def old_core(args, for_doc):  # ERPNext v15.121.0, budget.get_other_condition
        condition = f"expense_account = {frappe.db.escape(args.expense_account)}"
        budget_against_field = args.get("budget_against_field")
        if budget_against_field and args.get(budget_against_field):
            condition += f" and child.{budget_against_field} = {frappe.db.escape(args.get(budget_against_field))}"
        if args.get("fiscal_year"):
            date_field = "schedule_date" if for_doc == "Material Request" else "transaction_date"
            start_date, end_date = frappe.get_cached_value(
                "Fiscal Year", args.get("fiscal_year"), ["year_start_date", "year_end_date"]
            )
        condition += f" and parent.{date_field} between {frappe.db.escape(str(start_date))} and {frappe.db.escape(str(end_date))}"
        return condition

    def test_old_signature_uses_transaction_date_when_toggle_on(self):
        from unittest.mock import patch

        from custom_app.api import budget_control

        args = frappe._dict(expense_account=ACCOUNT_A, budget_against_field="cost_center", cost_center=COST_CENTER, fiscal_year=FISCAL_YEAR)
        with patch.object(budget_control, "_core_get_other_condition", self.old_core):
            self.assertIn("parent.transaction_date between '2026-04-01' and '2027-03-31'",
                          budget_control.get_other_condition(args, "Material Request"))

            self.set_settings(use_transaction_date_for_pr_budget=0)
            self.assertIn("parent.schedule_date between", budget_control.get_other_condition(args, "Material Request"))
            self.assertIn("parent.transaction_date between", budget_control.get_other_condition(args, "Purchase Order"))
            self.assertFalse(budget_control.core_uses_query_builder_conditions())


class TestFreshWorker(BudgetTestCase):
    def test_h3_first_budget_check_in_fresh_worker(self):
        # In a fresh worker the core function is still in place, but
        # custom_app.overrides.budget (applied at import of custom_app) already
        # calls it with the old 2-argument signature.
        from unittest.mock import patch

        from erpnext.accounts.doctype.budget import budget as core_budget

        from custom_app.api.budget_control import _core_get_other_condition

        je = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "company": COMPANY,
                "posting_date": TODAY,
                "accounts": [
                    {"account": ACCOUNT_A, "cost_center": COST_CENTER, "debit_in_account_currency": 1_000},
                    {"account": "Cash - CDE", "cost_center": COST_CENTER, "credit_in_account_currency": 1_000},
                ],
            }
        )
        je.insert(ignore_permissions=True)

        with patch.object(core_budget, "get_other_condition", _core_get_other_condition):
            je.submit()

        self.assertEqual(je.docstatus, 1)


# ---------------------------------------------------------------------------
# I. Budget Upload and J. Mid Year Budget Upload (Excel files)
# ---------------------------------------------------------------------------

ACCOUNT_C = f"TBI-C Test Extra - {ABBR}"
PLAN_C = dict(zip(MONTHS, [50_000] * 12, strict=True))  # 6,00,000


class UploadMixin(ReallocationMixin):
    def make_account_c(self):
        return _get_or_insert(
            "Account",
            ACCOUNT_C,
            {
                "account_name": "TBI-C Test Extra",
                "company": COMPANY,
                "parent_account": ACCOUNT_PARENT,
                "root_type": "Expense",
                "report_type": "Profit and Loss",
            },
        ).name

    def write_excel(self, rows, header=None):
        """Budget file in the "Download Budget Excel Format" layout.

        Written under the site's private files and deleted after the test
        (files on disk are not rolled back).
        """
        import os

        import pandas as pd

        name = f"tbi-budget-{frappe.generate_hash(length=8)}.xlsx"
        path = frappe.get_site_path("private", "files", name)
        header = header or ["Account", *MONTHS]
        data = [[account, *plan.values()] for account, plan in rows]
        pd.DataFrame([header, *data]).to_excel(path, header=False, index=False)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return f"/private/files/{name}"

    def make_budget_upload(self, rows):
        doc = frappe.get_doc(
            {
                "doctype": "Budget Upload",
                "company": COMPANY,
                "cost_center": COST_CENTER,
                "fiscal_year": FISCAL_YEAR,
                "budget_file": self.write_excel(rows),
            }
        )
        doc.insert(ignore_permissions=True)
        return doc

    def make_mid_year_upload(self, rows, header=None):
        doc = frappe.get_doc(
            {
                "doctype": "Mid Year Budget Upload",
                "company": COMPANY,
                "cost_center": COST_CENTER,
                "fiscal_year": FISCAL_YEAR,
                "budget_file": self.write_excel(rows, header),
            }
        )
        doc.insert(ignore_permissions=True)
        return doc


class TestBudgetUpload(UploadMixin, BudgetTestCase):
    def test_i1_upload_creates_budget_with_exact_months(self):
        self.make_account_c()
        self.set_master_budget_row(2_600_000)  # 20,00,000 allocated + 6,00,000

        upload = apply_workflow(self.make_budget_upload([(ACCOUNT_C, PLAN_C)]), "Approve")

        self.assertEqual(upload.docstatus, 1)
        row = self.report_row(ACCOUNT_C)
        self.assertEqual(row["annual_budget"], 600_000)
        for month in MONTHS:
            self.assertAlmostEqual(row[f"{month[:3].lower()}_budget"], 50_000, delta=0.01, msg=month)

    def test_i2_upload_over_master_budget_is_blocked(self):
        self.make_account_c()
        self.set_master_budget_row(2_599_999)

        self.assertBlocked(
            apply_workflow, self.make_budget_upload([(ACCOUNT_C, PLAN_C)]), "Approve", contains="Budget Limit Exceeded"
        )

    def test_i3_upload_for_cost_center_missing_from_master_is_blocked(self):
        self.make_account_c()

        self.assertBlocked(
            apply_workflow,
            self.make_budget_upload([(ACCOUNT_C, PLAN_C)]),
            "Approve",
            contains=f'No Budget found for Cost Center "{COST_CENTER}"',
        )

    def test_i4_reupload_with_existing_account_counts_only_new_rows(self):
        # Account A already has a budget and is skipped, so only C (6,00,000)
        # is new. The Master Budget has room for exactly that.
        self.make_account_c()
        self.set_master_budget_row(2_600_000)

        upload = apply_workflow(self.make_budget_upload([(ACCOUNT_A, PLAN_A), (ACCOUNT_C, PLAN_C)]), "Approve")

        self.assertEqual(upload.docstatus, 1)
        self.assertEqual(self.report_row(ACCOUNT_A)["annual_budget"], 1_000_000)


    def test_i4_unknown_account_row_adds_nothing_to_master_check(self):
        self.make_account_c()
        self.set_master_budget_row(2_600_000)

        upload = apply_workflow(
            self.make_budget_upload([(ACCOUNT_C, PLAN_C), ("TBI-Z No Such Account - CDE", PLAN_C)]), "Approve"
        )

        self.assertEqual(upload.docstatus, 1)
        self.assertEqual(self.report_row(ACCOUNT_C)["annual_budget"], 600_000)


class TestMidYearUpload(UploadMixin, BudgetTestCase):
    def test_j1_revised_month_amends_budget_others_unchanged(self):
        self.set_master_budget_row(2_030_000)
        old = self.active_budget().name
        plan = {**PLAN_A, "November": 130_000}

        upload = self.make_mid_year_upload([(ACCOUNT_A, plan), (ACCOUNT_B, PLAN_B)])
        upload.submit()

        self.assertEqual(frappe.db.get_value("Budget", old, "docstatus"), 2)
        self.assertEqual(self.active_budget().amended_from, old)
        self.assertEqual([(c.account, c.status) for c in upload.changes], [(ACCOUNT_A, "Revised")])
        row = self.report_row()
        for month, amount in plan.items():
            self.assertAlmostEqual(row[f"{month[:3].lower()}_budget"], amount, delta=0.01, msg=month)
        self.assertEqual(self.report_row(ACCOUNT_B)["annual_budget"], 1_000_000)

    def test_j1_moving_budget_between_accounts_with_no_headroom(self):
        # The Master Budget is exactly full. A's November goes up 30,000 and
        # B's down 30,000: the total is unchanged, so the file must apply.
        self.set_master_budget_row(2_000_000)

        upload = self.make_mid_year_upload(
            [(ACCOUNT_A, {**PLAN_A, "November": 130_000}), (ACCOUNT_B, {**PLAN_B, "November": 70_000})]
        )
        upload.submit()

        self.assertEqual(self.report_row()["nov_budget"], 130_000)
        self.assertEqual(self.report_row(ACCOUNT_B)["nov_budget"], 70_000)

    def test_j2_unchanged_file_is_refused(self):
        self.set_master_budget_row(2_000_000)
        upload = self.make_mid_year_upload([(ACCOUNT_A, PLAN_A)])

        self.assertBlocked(upload.submit, contains="Nothing to apply")

    def test_j3_cut_below_consumed_applies_with_warning_and_left_goes_negative(self):
        # Records behaviour: the upload warns but still applies.
        self.set_master_budget_row(2_000_000)
        self.raise_and_approve_pr(40_000)

        upload = self.make_mid_year_upload([(ACCOUNT_A, {**PLAN_A, "October": 30_000})])
        upload.submit()

        self.assertIn("already consumed", upload.changes[0].remarks)
        self.assertEqual(self.report_row()["oct_left"], -10_000)
        self.assertBlocked(self.make_pr, 1, contains="Insufficient budget for October 2026")

    def test_j4_over_master_budget_is_refused(self):
        self.set_master_budget_row(2_000_000)
        upload = self.make_mid_year_upload([(ACCOUNT_A, {**PLAN_A, "November": 100_001})])

        self.assertBlocked(upload.submit, contains="Master Budget limit exceeded")

    def test_j5_months_out_of_order_are_refused(self):
        self.set_master_budget_row(2_000_000)
        header = ["Account", "January", *[m for m in MONTHS if m != "January"]]
        upload = self.make_mid_year_upload([(ACCOUNT_A, {**PLAN_A, "November": 99_000})], header=header)

        self.assertBlocked(upload.submit, contains="The first row must have the months April to March")

    def test_j6_new_account_gets_a_budget(self):
        self.make_account_c()
        self.set_master_budget_row(2_600_000)

        upload = self.make_mid_year_upload([(ACCOUNT_C, PLAN_C)])
        upload.submit()

        self.assertEqual([(c.account, c.status) for c in upload.changes], [(ACCOUNT_C, "New")])
        self.assertEqual(self.report_row(ACCOUNT_C)["oct_budget"], 50_000)

    def test_j7_upload_cannot_be_cancelled(self):
        self.set_master_budget_row(2_030_000)
        upload = self.make_mid_year_upload([(ACCOUNT_A, {**PLAN_A, "November": 130_000})])
        upload.submit()

        self.assertBlocked(upload.cancel, contains="cannot be cancelled")


# ---------------------------------------------------------------------------
# K. Other routes and rules from PR to payment
# ---------------------------------------------------------------------------


class TestQuotationRouteAndRules(ProcureToPayMixin, BudgetTestCase):
    def make_rfq(self, pr):
        from custom_app.overrides.material_request import make_request_for_quotation

        rfq = make_request_for_quotation(pr.name)
        rfq.transaction_date = TODAY
        rfq.subject = "Integration test"
        rfq.message_for_supplier = "Integration test"
        rfq.append("suppliers", {"supplier": self.data.supplier, "send_email": 0})
        for row in rfq.items:
            row.schedule_date = TODAY
        rfq.insert(ignore_permissions=True)
        rfq.submit()
        return rfq

    def make_quotation(self, rfq, rate):
        from custom_app.overrides.rfq import make_supplier_quotation_from_rfq

        quotation = make_supplier_quotation_from_rfq(rfq.name, for_supplier=self.data.supplier)
        quotation.transaction_date = TODAY
        for row in quotation.items:
            row.rate = rate
        quotation.insert(ignore_permissions=True)
        return quotation

    def make_quotation_from_pr(self, pr, rate):
        from custom_app.overrides.material_request import make_supplier_quotation

        quotation = make_supplier_quotation(pr.name)
        quotation.supplier = self.data.supplier
        quotation.transaction_date = TODAY
        for row in quotation.items:
            row.rate = rate
        quotation.insert(ignore_permissions=True)
        return quotation

    def make_po_from_quotation(self, quotation):
        from erpnext.buying.doctype.supplier_quotation.supplier_quotation import make_purchase_order

        po = make_purchase_order(quotation.name)
        po.transaction_date = TODAY
        po.schedule_date = TODAY
        po.custom_notes = "Integration test"
        for row in po.items:
            row.schedule_date = TODAY
        po.insert(ignore_permissions=True)
        return apply_workflow(po, "Approve")

    def test_k1_pr_quotation_po_invoice_payment_counts_once(self):
        # The route used on live: every Supplier Quotation there was made
        # straight from a PR (no RFQs exist).
        pr = self.raise_and_approve_pr(20_000)
        quotation = self.make_quotation_from_pr(pr, 19_000)
        quotation.submit()
        self.assertEqual(quotation.cost_center, COST_CENTER)
        self.assertConsumed(20_000)

        po = self.make_po_from_quotation(quotation)
        self.assertEqual(
            frappe.db.get_value("Supplier Quotation", quotation.name, "custom_order_status"), "Completely Ordered"
        )
        self.assertConsumed(20_000)  # the PR amount, not the lower quoted amount

        payment = self.make_payment(self.make_invoice(po))
        self.assertEqual(payment.paid_amount, 19_000)
        self.assertConsumed(20_000)

    def test_k1_rfq_route_makes_quotation_for_supplier(self):
        rfq = self.make_rfq(self.raise_and_approve_pr(20_000))
        self.assertEqual(rfq.custom_cost_center, COST_CENTER)

        quotation = self.make_quotation(rfq, 19_000)

        self.assertEqual((quotation.supplier, quotation.cost_center), (self.data.supplier, COST_CENTER))
        row = quotation.items[0]
        self.assertEqual((row.request_for_quotation, row.material_request), (rfq.name, rfq.items[0].material_request))
        self.assertEqual(row.cost_center, COST_CENTER)

    def test_k2_quotation_above_pr_amount_is_blocked(self):
        pr = self.raise_and_approve_pr(20_000)

        self.assertBlocked(
            self.make_quotation_from_pr,
            pr,
            20_001,
            contains="Supplier quotation amount cannot exceed the approved Purchase",
        )

    def test_k3_po_expense_account_must_match_pr(self):
        from custom_app.overrides.material_request import make_purchase_order

        po = make_purchase_order(self.raise_and_approve_pr(20_000).name)
        po.supplier = self.data.supplier
        po.custom_notes = "Integration test"
        for row in po.items:
            row.schedule_date = TODAY
            row.expense_account = ACCOUNT_B

        self.assertBlocked(po.insert, contains="does not match the Expense Account")

    def test_k4_invoice_without_po_is_blocked(self):
        invoice = frappe.get_doc(
            {
                "doctype": "Purchase Invoice",
                "company": COMPANY,
                "supplier": self.data.supplier,
                "posting_date": TODAY,
                "set_posting_time": 1,
                "cost_center": COST_CENTER,
                "custom_attachment": "/files/tbi-test-invoice.pdf",
                "items": [{"item_code": ITEM_A, "qty": 1, "rate": 5_000, "cost_center": COST_CENTER}],
            }
        )

        # ERPNext's own "Purchase Order Required" (Buying Settings) stops it
        # first; the custom "Purchase Order is mandatory" check is a backstop.
        self.assertBlocked(invoice.insert, contains="Purchase Order Required for item")

    def test_k5_cancelled_po_reopens_pr_and_pr_still_counts(self):
        pr = self.raise_and_approve_pr(20_000)
        po = self.make_po(pr)

        apply_workflow(po, "Cancel")

        self.assertEqual(frappe.db.get_value("Material Request", pr.name, "per_ordered"), 0)
        self.assertConsumed(20_000)

    def test_k6_verifier_cost_center_needs_verify_then_approve(self):
        settings = frappe.get_single("Verifier PR Settings")
        settings.append(settings.meta.get_table_fields()[0].fieldname, {"cost_center": COST_CENTER})
        settings.save(ignore_permissions=True)

        self.assertBlocked(self.make_pr, 10_000, contains="Request Verifier is mandatory")

        pr = self.make_pr(10_000, verifier="Administrator")
        self.assertRaises(frappe.ValidationError, apply_workflow, pr, "Approve")

        pr = apply_workflow(pr, "Verify")
        self.assertEqual((pr.workflow_state, pr.docstatus), ("Verified", 0))
        pr = apply_workflow(pr, "Approve")
        self.assertEqual((pr.workflow_state, pr.docstatus), ("Approved by Manager", 1))
        self.assertEqual(self.report_row()["oct_consumed"], 10_000)

    def test_k7_rejected_pr_counts_zero(self):
        pr = apply_workflow(self.make_pr(20_000), "Reject")

        self.assertEqual((pr.workflow_state, pr.docstatus), ("Rejected", 0))
        self.assertConsumed(0)

    def test_k8_expense_claim_paid_through_payment_entry(self):
        from hrms.overrides.employee_payment_entry import get_payment_entry_for_employee

        claim = apply_workflow(self.make_expense_claim(12_000), "Approve")
        payment = get_payment_entry_for_employee("Expense Claim", claim.name, bank_account="Bank Account - CDE")
        payment.posting_date = TODAY
        payment.reference_no = payment.custom_transaction_reference_number = "TBI-UTR-002"
        payment.reference_date = TODAY
        payment.insert(ignore_permissions=True)
        apply_workflow(payment, "Approve")

        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "status"), "Paid")
        self.assertConsumed(12_000)

    def test_k8_employee_payment_without_reference_is_blocked(self):
        from hrms.overrides.employee_payment_entry import get_payment_entry_for_employee

        claim = apply_workflow(self.make_expense_claim(12_000), "Approve")
        payment = get_payment_entry_for_employee("Expense Claim", claim.name, bank_account="Bank Account - CDE")
        payment.reference_no = payment.custom_transaction_reference_number = "TBI-UTR-003"
        payment.reference_date = TODAY
        payment.references = []

        self.assertBlocked(payment.insert, contains="At least one Payment Reference is required for Employee")

    def test_k9_employee_cannot_approve_own_claim(self):
        # An approver who is also the claimant, set as approver of their own
        # claim. The Employee link comes first: HRMS strips the Employee role
        # from a user with no Employee record.
        user = TestBudgetReallocation.make_user(self, "tbi-employee@example.com", ["Expense Approver"])
        frappe.db.set_value("Employee", self.data.employee, "user_id", user)
        frappe.get_doc("User", user).add_roles("Employee")
        claim = self.make_expense_claim(12_000)
        claim.db_set("expense_approver", user)

        frappe.set_user(user)
        self.assertBlocked(apply_workflow, frappe.get_doc("Expense Claim", claim.name), "Approve",
                           contains="You cannot Approve/Reject your own Expense Claim")

    def test_k10_new_pr_notifies_its_approver(self):
        from unittest.mock import patch

        with patch.object(frappe, "sendmail") as sendmail:
            pr = self.make_pr(10_000)

        self.assertEqual(sendmail.call_count, 1)
        kwargs = sendmail.call_args.kwargs
        self.assertEqual(kwargs["recipients"], [frappe.db.get_value("User", "Administrator", "email")])
        self.assertEqual(kwargs["subject"], f"New Purchase Request: {pr.name}")


# ---------------------------------------------------------------------------
# L. Who can see and approve what
# ---------------------------------------------------------------------------


class TestPermissions(ProcureToPayMixin, BudgetTestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.make_employee_user("tbi-alice@example.com", "TBI Alice")
        self.bob = self.make_employee_user("tbi-bob@example.com", "TBI Bob")
        # Same roles as a real PR approver on the site (pradeep@ifim.edu.in).
        self.approver = self.make_user(
            "tbi-approver@example.com",
            ["Asset Manager", "Employee", "Employee CDE/VU", "Expense Approver", "Leave Approver"],
        )

        self.alice_pr = self.make_pr_for(self.alice.employee, approver=self.approver)
        self.bob_pr = self.make_pr_for(self.bob.employee, approver="Administrator")

    def make_user(self, email, roles):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
            ).insert(ignore_permissions=True)
            user.add_roles(*roles)
        return email

    def make_employee_user(self, email, name):
        user = self.make_user(email, ["Employee"])
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": name,
                "company": COMPANY,
                "department": DEPARTMENT,
                "gender": "Female",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "bank_name": "Test Bank",
                "bank_ac_no": "000000000000",
                "ifsc_code": "TEST0000000",
                "user_id": user,
            }
        ).insert(ignore_permissions=True)
        return frappe._dict(user=user, employee=employee.name)

    def make_pr_for(self, employee, approver):
        pr = self.make_pr(5_000)
        pr.db_set({"custom_employee": employee, "custom_request_approver": approver})
        return pr

    def visible_prs(self, user):
        frappe.set_user(user)
        try:
            return set(
                frappe.get_list("Material Request", {"custom_cost_center": COST_CENTER}, pluck="name")
            )
        finally:
            frappe.set_user("Administrator")

    def test_l1_employee_lists_only_own_prs(self):
        self.assertEqual(self.visible_prs(self.alice.user), {self.alice_pr.name})

    def test_l2_approver_lists_prs_assigned_to_them(self):
        self.assertEqual(self.visible_prs(self.approver), {self.alice_pr.name})

    def test_l3_procurement_user_lists_only_approved_prs(self):
        # Real procurement users are employees: the Employee role (which HRMS
        # removes from users with no Employee record) gives read access.
        procurement = self.make_employee_user("tbi-procurement@example.com", "TBI Procurement").user
        frappe.get_doc("User", procurement).add_roles("Procurement User", "Purchase User")
        approved = apply_workflow(self.make_pr(6_000), "Approve")

        self.assertEqual(self.visible_prs(procurement), {approved.name})

    def can_read(self, user, doctype, name):
        frappe.set_user(user)
        try:
            return frappe.has_permission(doctype, "read", name)
        finally:
            frappe.set_user("Administrator")

    def test_l4_access_rules_filter_lists_only(self):
        # Records behaviour, confirmed as intended (16 Nov 2026): the custom
        # rules filter lists; opening a PR or claim by its ID follows the
        # standard role permissions.
        claim = self.make_expense_claim(1_000)  # belongs to the shared test employee

        self.assertTrue(self.can_read(self.alice.user, "Material Request", self.bob_pr.name))
        self.assertTrue(self.can_read(self.alice.user, "Expense Claim", claim.name))

    def test_l4_right_people_can_open_a_pr(self):
        procurement = self.make_employee_user("tbi-procurement2@example.com", "TBI Procurement 2").user
        frappe.get_doc("User", procurement).add_roles("Procurement User", "Purchase User")
        approved = apply_workflow(frappe.get_doc("Material Request", self.alice_pr.name), "Approve")

        self.assertTrue(self.can_read(self.alice.user, "Material Request", self.alice_pr.name))  # own
        self.assertTrue(self.can_read(self.approver, "Material Request", self.alice_pr.name))  # assigned
        self.assertTrue(self.can_read(procurement, "Material Request", approved.name))  # approved

    def test_l4_procurement_user_can_raise_po_from_approved_pr(self):
        from custom_app.overrides.material_request import make_purchase_order

        procurement = self.make_employee_user("tbi-procurement3@example.com", "TBI Procurement 3").user
        frappe.get_doc("User", procurement).add_roles("Procurement User", "Purchase User")
        approved = apply_workflow(self.make_pr(6_000), "Approve")

        frappe.set_user(procurement)
        po = make_purchase_order(approved.name)
        frappe.set_user("Administrator")

        self.assertEqual(po.items[0].material_request, approved.name)

    def test_l5_right_people_can_open_a_claim(self):
        alice_claim = self.make_expense_claim(1_000)
        alice_claim.db_set({"employee": self.alice.employee, "expense_approver": self.approver})
        # Role sets copied from real users on the site; both are employees.
        finance = self.make_employee_user("tbi-finance-approver2@example.com", "TBI Finance").user
        frappe.get_doc("User", finance).add_roles("Finance Approver", "Finance User", "Employee CDE/VU")
        ap_user = self.make_employee_user("tbi-ap-user2@example.com", "TBI AP").user
        frappe.get_doc("User", ap_user).add_roles(
            "AP User", "Employee CDE/VU", "Finance User", "Procurement User", "Purchase User", "Vendor Manager"
        )
        alice_claim = apply_workflow(frappe.get_doc("Expense Claim", alice_claim.name), "Approve")
        apply_workflow(alice_claim, "Finance Approve")

        for user in (self.alice.user, self.approver, finance, ap_user):
            self.assertTrue(self.can_read(user, "Expense Claim", alice_claim.name), user)

    def test_l6_employee_cannot_approve_a_pr(self):
        frappe.set_user(self.alice.user)

        with self.assertRaisesRegex(frappe.ValidationError, "Not a valid Workflow Action"):
            apply_workflow(frappe.get_doc("Material Request", self.alice_pr.name), "Approve")

    def test_l7_assigned_approver_can_approve(self):
        frappe.set_user(self.approver)

        pr = apply_workflow(frappe.get_doc("Material Request", self.alice_pr.name), "Approve")

        self.assertEqual(pr.docstatus, 1)

    def test_l8_finance_user_cannot_approve_reallocation(self):
        finance_user = self.make_user("tbi-finance-user@example.com", ["Finance User"])
        doc = ReallocationMixin.make_reallocation(self, 60_000)

        frappe.set_user(finance_user)
        with self.assertRaisesRegex(frappe.ValidationError, "Not a valid Workflow Action"):
            apply_workflow(frappe.get_doc("Budget Reallocation", doc.name), "Approve")

    def test_l9_ap_user_cannot_approve_payment(self):
        ap_user = self.make_user("tbi-ap-user@example.com", ["AP User", "Accounts User"])
        invoice = self.make_invoice(self.make_po(apply_workflow(self.make_pr(7_000), "Approve")))
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        payment = get_payment_entry("Purchase Invoice", invoice.name, bank_account="Bank Account - CDE")
        payment.reference_no = payment.custom_transaction_reference_number = "TBI-UTR-004"
        payment.reference_date = TODAY
        payment.insert(ignore_permissions=True)

        frappe.set_user(ap_user)
        with self.assertRaisesRegex(frappe.ValidationError, "Not a valid Workflow Action"):
            apply_workflow(frappe.get_doc("Payment Entry", payment.name), "Approve")


# ---------------------------------------------------------------------------
# M. Spot-check against a copy of live data (read-only)
# ---------------------------------------------------------------------------

LIB_002 = "LIB-002 - Jourals/Periodicals - CDE"  # "Jourals" is the real spelling


class TestLiveDataSpotCheck(FrappeTestCase):
    """Reads real figures; creates nothing. Skipped on a site without live data.

    Expected figures are the ones worked out by hand on 16 Nov 2026, after the
    Stopped-PR and rejected-claim fixes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("Account", LIB_002):
            raise unittest.SkipTest("No live data on this site")

    def test_m1_lib_002_left_matches_hand_worked_figures(self):
        from custom_app.custom_app.report.budget_availability_report.budget_availability_report import execute

        settings = frappe.get_cached_doc("Budget Settings")
        self.assertTrue(settings.restrict_pr_to_current_month_budget and settings.use_transaction_date_for_pr_budget)

        _, data, _ = execute({"company": COMPANY, "cost_center": "Corporate - CDE", "fiscal_year": FISCAL_YEAR})
        row = next(r for r in data if r["account"] == LIB_002)
        months = ("apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "jan", "feb", "mar")

        self.assertEqual(row["annual_budget"], 5_600_000)
        self.assertEqual(round(row["annual_budget"] - sum(row[f"{m}_consumed"] for m in months)), 1_649_324)
        for month, expected in zip(("dec", "jan", "feb", "mar"), (431_906, 312_412, 310_882, 190_971), strict=True):
            self.assertAlmostEqual(row[f"{month}_left"], expected, delta=0.5, msg=month)

    def test_m2_stopped_lib_002_prs_count_nothing(self):
        from custom_app.api.budget_control import get_monthly_consumption

        stopped = {"MAT-MR-2026-01099": "2026-07", "MAT-MR-2026-00326": "2026-05", "MAT-MR-2026-00828": "2026-07", "MAT-MR-2026-01098": "2026-07"}
        for name in stopped:
            self.assertEqual(frappe.db.get_value("Material Request", name, "status"), "Stopped", name)

        with_stopped = frappe.db.sql(
            """select sum(mri.amount) from `tabMaterial Request Item` mri
            join `tabMaterial Request` mr on mr.name = mri.parent
            where mr.name in %s and mri.expense_account = %s""",
            (tuple(stopped), LIB_002),
        )[0][0]
        self.assertEqual(round(with_stopped), 1_882_078)

        consumption = get_monthly_consumption(COMPANY, "Corporate - CDE", FISCAL_YEAR)
        # July holds three of them (18,77,578); it must count only live PRs.
        july_without_stopped = frappe.db.sql(
            """select sum(mri.amount) from `tabMaterial Request Item` mri
            join `tabMaterial Request` mr on mr.name = mri.parent
            where mr.docstatus = 1 and mr.status != 'Stopped' and mr.material_request_type = 'Purchase'
            and mri.expense_account = %s and mri.cost_center = 'Corporate - CDE'
            and mr.transaction_date between '2026-07-01' and '2026-07-31'""",
            LIB_002,
        )[0][0]
        self.assertAlmostEqual(consumption[(LIB_002, "2026-07")], flt(july_without_stopped), places=2)

    def test_m3_mat_mr_2026_02080_prints_october(self):
        html = frappe.get_print("Material Request", "MAT-MR-2026-02080", print_format="Material Request Print Format")

        self.assertIn("October 2026", html)
