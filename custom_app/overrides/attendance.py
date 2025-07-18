import frappe
from frappe.model.document import Document
from custom_app.utils.saturday_utils import is_first_third_fifth_saturday

class CustomAttendance(Document):
    def validate(self):
        if is_first_third_fifth_saturday(self.attendance_date):
            self.status = "Absent"  # use allowed status of absent and mark weekly off
            self.custom_weekly_off_marker = "Weekly Off (Auto)"
