import frappe
from frappe.model.document import Document
from custom_app.utils.saturday_utils import is_first_third_fifth_saturday

class CustomAttendance(Document):
    def validate(self):
        # Apply only on 1st / 3rd / 5th Saturdays
        if is_first_third_fifth_saturday(self.attendance_date):

            # Companies that should NOT be touched
            allowed_companies = [
                "Centre for Developmental Education",
                "Vijaybhoomi University"
            ]

            # If company is allowed → do nothing (skip)
            if self.company in allowed_companies:
                return

            # If company is NOT allowed → mark Absent
            self.status = "Absent"
            self.custom_weekly_off_marker = "Weekly Off (Auto)"