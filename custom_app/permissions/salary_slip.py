import frappe

# Roles that may see every salary slip (still bound by Company user permissions).
# Everyone else, including managers who see their reportees' other records
# through the Employee tree user permission, only sees their own slips.
FULL_ACCESS_ROLES = {"System Manager", "HR Manager", "HR User"}


def _has_full_access(user):
    return bool(FULL_ACCESS_ROLES.intersection(frappe.get_roles(user)))


def _employees_of(user):
    return frappe.get_all("Employee", filters={"user_id": user}, pluck="name", ignore_permissions=True)


def salary_slip_permission_query(user):
    user = user or frappe.session.user
    if _has_full_access(user):
        return ""

    employees = _employees_of(user)
    if not employees:
        return "1=0"

    return "`tabSalary Slip`.`employee` in ({})".format(
        ", ".join(frappe.db.escape(e) for e in employees)
    )


def has_permission(doc, ptype=None, user=None, debug=False):
    user = user or frappe.session.user
    if _has_full_access(user):
        return True

    return bool(doc.get("employee")) and doc.get("employee") in _employees_of(user)
