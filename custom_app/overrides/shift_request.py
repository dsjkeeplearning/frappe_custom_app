import frappe
from hrms.hr.doctype.shift_request.shift_request import ShiftRequest

class CustomShiftRequest(ShiftRequest):
    def validate(self):
        super().validate()

        if not self.employee:
            return

        # Fetch user linked to the Employee
        employee_user = frappe.db.get_value("Employee", self.employee, "user_id")

        # Restrict if same employee user and status is not "draft"
        if employee_user == frappe.session.user and self.status != "Draft":
            frappe.throw(
                "You cannot Approve/Reject your own Shift Request."
            )