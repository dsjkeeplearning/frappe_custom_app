# Copyright (c) 2025
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import openpyxl
from openpyxl.styles import Font, Alignment
from frappe.utils import getdate, add_days
from frappe import _
import json


class AttendanceExcelGenerator(Document):
    pass


# ---------------------------------------
# LEAVE CODE MAPPING
# ---------------------------------------
def map_leave_code(leave_type):
    if not leave_type:
        return ""

    leave_type = leave_type.lower()

    if leave_type.startswith("casual"):
        return "CL"
    elif leave_type.startswith("sick"):
        return "SL"
    elif leave_type.startswith("earn"):
        return "EL"
    elif leave_type.startswith("option") or leave_type.startswith("optional"):
        return "OH"
    elif leave_type.startswith("pat"):
        return "PTRL"
    elif leave_type.startswith("mat"):
        return "MTRL"
    elif leave_type.startswith("leave without pay") or leave_type.startswith("lop"):
        return "LOP"
    else:
        return "L"


# ---------------------------------------
# MAIN FUNCTION
# ---------------------------------------
@frappe.whitelist()
def generate_excel(doc):

    # Convert JSON from client → python dict
    if isinstance(doc, str):
        doc = json.loads(doc)

    doc = frappe._dict(doc)

    if not (doc.company and doc.from_date and doc.to_date):
        frappe.throw(_("Please select Company, From Date and To Date"))

    # Fetch employees of the company
    employees = frappe.get_all(
        "Employee",
        filters={"company": doc.company},
        fields=["name", "employee", "employee_name", "employee_number"]
    )

    # Date range list
    start = getdate(doc.from_date)
    end = getdate(doc.to_date)

    dates = []
    d = start
    while d <= end:
        dates.append(d)
        d = add_days(d, 1)

    # Create workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Attendance Report"

    # HEADER
    ws.cell(row=1, column=1, value="EmpCode").font = Font(bold=True)
    ws.cell(row=1, column=2, value="Short Name").font = Font(bold=True)
    ws.cell(row=1, column=3, value="FromDate").font = Font(bold=True)
    ws.cell(row=1, column=4, value="ToDate").font = Font(bold=True)

    formatted_from_date = getdate(doc.from_date).strftime("%d/%m/%Y")
    formatted_to_date = getdate(doc.to_date).strftime("%d/%m/%Y")

    # DATE COLUMNS
    for i, date in enumerate(dates):
        col = i + 5
        ws.cell(row=1, column=col, value=date.strftime("%d/%m/%Y"))
        ws.cell(row=1, column=col).font = Font(bold=True)
        ws.cell(row=1, column=col).alignment = Alignment(horizontal="center")

    # BODY ROWS
    row = 2
    for emp in employees:

        ws.cell(row=row, column=1, value=emp.employee_number or emp.name)
        ws.cell(row=row, column=2, value=emp.employee_name)
        ws.cell(row=row, column=3, value=formatted_from_date)
        ws.cell(row=row, column=4, value=formatted_to_date)

        for i, date in enumerate(dates):
            col = i + 5

            # Fetch submitted attendances only
            attendance = frappe.get_value(
                "Attendance",
                {
                    "employee": emp.name,
                    "attendance_date": date,
                    "docstatus": 1      # <-- Only Submitted
                },
                ["status", "leave_type", "half_day_status"],
                as_dict=True
            )

            value = ""

            if attendance:
                status = (attendance.status or "").lower()
                leave_type = (attendance.leave_type or "")
                half_day_status = (attendance.half_day_status or "").lower()
                leave_code = map_leave_code(leave_type)

                # ----------------------------
                # HALF DAY LOGIC
                # ----------------------------
                if status == "half day":

                    # Half Day + Present → "HD, HD<leavecode>"
                    if half_day_status == "present":
                        if leave_code:
                            value = f"HD, HD{leave_code}"   # EX: HD, HDSL
                        else:
                            value = "HD"

                    # Half Day + Absent → "HD<leavecode>"
                    elif half_day_status == "absent":
                        if leave_code:
                            value = f"HD{leave_code}"       # EX: HDSL
                        else:
                            value = "HD"

                # ----------------------------
                # FULL DAY LOGIC
                # ----------------------------
                elif status == "present":
                    value = "P"

                elif status == "absent":
                    value = "A"

                elif status == "work from home":
                    value = "WFH"

                elif status == "on leave":
                    value = leave_code or "L"

            else:
                value = ""

            ws.cell(row=row, column=col, value=value)

        row += 1

    # SAVE FILE
    filename = f"Attendance-{doc.company}-{doc.from_date}-to-{doc.to_date}.xlsx"
    filepath = frappe.utils.get_site_path("public", "files", filename)

    wb.save(filepath)

    return f"/files/{filename}"