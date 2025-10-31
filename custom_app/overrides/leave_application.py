import frappe
from hrms.hr.doctype.leave_application.leave_application import LeaveApplication

class CustomLeaveApplication(LeaveApplication):
    def validate(self):
        super().validate()

        # Skip if no employee selected
        if not self.employee:
            return

        # Get the user_id linked to this employee
        employee_user = frappe.db.get_value("Employee", self.employee, "user_id")

        # If the employee's user matches the logged-in user AND status is NOT "open", block
        if employee_user == frappe.session.user and self.status != "Open":
            frappe.throw("You cannot Approve/Reject your own Leave Application.")