import frappe
from frappe.utils import nowdate, getdate
from datetime import date

def allocate_earned_leaves_on_probation_end():
    today = getdate(nowdate())

    # Find employees whose probation ends today
    employees = frappe.get_all(
        "Employee",
        filters={
            "custom_probation_end_date": today,
            "company": ["in", ["Vijaybhoomi University", "Centre for Developmental Education"]]
        },
        fields=["name", "employee_name", "custom_probation_end_date", "company"]
    )

    if not employees:
        return

    for emp in employees:
        probation_end = getdate(emp.custom_probation_end_date)

        # Determine financial year start & end
        fy_start, fy_end = get_financial_year_for_probation(probation_end)

        # Calculate pro rata leaves
        total_days = (fy_end - probation_end).days + 1
        earned_per_year = 18
        prorata_leaves = round((total_days / 365) * earned_per_year, 2)
        leave_type_name = "Earned Leave"
        if not frappe.db.exists("Leave Type", leave_type_name):
            frappe.throw(f"Leave Type '{leave_type_name}' not found. Please create it first.")
        
        # Check if Leave Allocation already exists
        allocation_name = frappe.db.get_value(
            "Leave Allocation",
            {
                "employee": emp.name,
                "from_date": probation_end,
                "to_date": fy_end,
                "leave_type": leave_type_name,
                "docstatus": 1
            },
            "name"
        )

        if not allocation_name:
            # Create a new allocation
            allocation_doc = frappe.new_doc("Leave Allocation")
            allocation_doc.employee = emp.name
            allocation_doc.from_date = probation_end
            allocation_doc.to_date = fy_end
            allocation_doc.leave_type = leave_type_name  # Change if needed
            allocation_doc.new_leaves_allocated = prorata_leaves
            allocation_doc.submit()

        frappe.db.commit()


def get_financial_year_for_probation(probation_end: date):
    year = probation_end.year
    # If probation end date is before April, FY ends on 31 March of same year
    # Else ends next year
    if probation_end.month < 4:
        fy_start = date(year - 1, 4, 1)
        fy_end = date(year, 3, 31)
    else:
        fy_start = date(year, 4, 1)
        fy_end = date(year + 1, 3, 31)

    return fy_start, fy_end
