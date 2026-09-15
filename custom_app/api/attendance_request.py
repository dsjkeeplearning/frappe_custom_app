"""
Attendance Request visibility.

ERPNext/HRMS shares every Leave Application with the employee's leave
approver, which is why approvers can act on them even when User Permissions
would otherwise hide the record. Attendance Request has no such approver
field and no sharing, so approvers currently cannot see their reportees'
requests at all once a Company or Employee user permission is in play.

This module mirrors the Leave Application behaviour for Attendance Request:
the request is shared, with submit rights, to the employee's leave approver.

HR is deliberately NOT handled by sharing. HR users already have the HR
User / HR Manager role, so what they can see is decided by their Company
user permission - which is the correct, company-scoped behaviour. Use
audit_hr_visibility() to find HR users whose permissions block them.
"""

import frappe
from frappe import _
from frappe.query_builder import Criterion
from frappe.utils import add_days, date_diff


def _leave_approver(employee):
    if not employee:
        return None
    return frappe.db.get_value("Employee", employee, "leave_approver")


def _resolve_shift_for_date(employee, date):
    """Shift Assignment covering this date, else the Employee's default shift."""
    SA = frappe.qb.DocType("Shift Assignment")
    result = (
        frappe.qb.from_(SA)
        .select(SA.shift_type)
        .where(
            (SA.employee == employee)
            & (SA.docstatus == 1)
            & (SA.start_date <= date)
            & (Criterion.any([SA.end_date.isnull(), SA.end_date >= date]))
        )
        .orderby(SA.start_date, order=frappe.qb.desc)
        .limit(1)
    ).run()

    if result:
        return result[0][0]

    return frappe.db.get_value("Employee", employee, "default_shift", cache=True)


def _get_shifts_in_range(employee, from_date, to_date):
    shifts = set()
    days = date_diff(to_date, from_date) + 1
    for day in range(days):
        date = add_days(from_date, day)
        shift = _resolve_shift_for_date(employee, date)
        if shift:
            shifts.add(shift)
    return list(shifts)


def _resolve_and_set_shift(doc):
    """
    Fills doc.shift from Shift Assignment (falling back to the employee's
    default shift), resolved per day across from_date..to_date, instead of
    stock HRMS's validate_shifts()/get_active_shifts() which only auto-fills
    when exactly one Shift Assignment covers the *entire* date range - every
    other case (no assignment, multiple assignments, partial coverage) left
    `shift` blank. A blank shift makes create_or_update_attendance()'s
    employee+date+shift lookup miss the original Attendance record, so
    approving the request created a duplicate Attendance row instead of
    updating the Absent one - see the Attendance Request bug report.
    """
    if not (doc.employee and doc.from_date and doc.to_date):
        return

    shifts = _get_shifts_in_range(doc.employee, doc.from_date, doc.to_date)
    if len(shifts) > 1:
        frappe.throw(
            _(
                "There are multiple shifts assigned to the employee across this date range. "
                "Please split this request by shift period."
            )
        )
    doc.shift = shifts[0] if shifts else None


def set_shift(doc, method=None):
    """doc_event: Attendance Request before_validate"""
    _resolve_and_set_shift(doc)


def lock_shift_before_submit(doc, method=None):
    """
    doc_event: Attendance Request before_submit

    Re-resolves the shift fresh at approval time rather than trusting
    whatever was set when the request was first saved, so a stale or
    manually-tampered value can never reach the Attendance record that
    create_attendance_records() is about to create/update.
    """
    _resolve_and_set_shift(doc)


@frappe.whitelist()
def get_shift_preview(employee: str, from_date: str, to_date: str):
    if not (employee and from_date and to_date):
        return None
    shifts = _get_shifts_in_range(employee, from_date, to_date)
    return shifts[0] if len(shifts) == 1 else None


def share_with_leave_approver(doc, method=None):
    """
    doc_event: Attendance Request on_update

    Mirrors hrms.hr.utils.share_doc_with_approver - only shares when the
    approver cannot already act on the document, so no redundant DocShare
    rows are created for approvers who are covered by user permissions.
    """
    approver = _leave_approver(doc.employee)
    if not approver:
        return

    if not frappe.has_permission(doc=doc, ptype="submit", user=approver):
        frappe.share.add_docshare(
            doc.doctype, doc.name, approver, submit=1,
            flags={"ignore_share_permission": True},
        )

    # If the employee's approver changed since this document was last saved,
    # drop the old share so a former approver keeps no access.
    before = doc.get_doc_before_save()
    if before and before.get("employee") != doc.employee:
        old_approver = _leave_approver(before.get("employee"))
        if old_approver and old_approver != approver:
            frappe.share.remove(doc.doctype, doc.name, old_approver)
