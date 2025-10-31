import frappe
from hrms.hr.doctype.expense_claim.expense_claim import ExpenseClaim

class CustomExpenseClaim(ExpenseClaim):
    def validate(self):
        super().validate()

        if not self.employee:
            return

        employee_user = frappe.db.get_value("Employee", self.employee, "user_id")

        # Restrict if logged-in user is the same employee and status is not "draft"
        if employee_user == frappe.session.user and self.approval_status != "Draft":
            frappe.throw(
                "You cannot Approve/Reject your own Expense Claim."
            )