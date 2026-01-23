import frappe

def material_request_permission_query(user):
    roles = frappe.get_roles(user)

    # System Manager → everything
    if "System Manager" in roles or "Auditor" in roles:
        return ""

    conditions = []

    # Procurement User → all Approved
    if "Procurement User" in roles:
        conditions.append(
            "`tabMaterial Request`.`workflow_state` = 'Approved'"
        )

    # Expense Approver → only assigned to him (User ID stored)
    if "Expense Approver" in roles:
        conditions.append(
            "`tabMaterial Request`.`custom_request_approver` = {}".format(
                frappe.db.escape(user)
            )
        )

    # Employee → only own requests (Employee linked to User)
    if "Employee" in roles:
        employee = frappe.db.get_value(
            "Employee",
            {"user_id": user},
            "name"
        )

        if employee:
            conditions.append(
                "`tabMaterial Request`.`custom_employee` = {}".format(
                    frappe.db.escape(employee)
                )
            )
        else:
            # User has Employee role but no Employee record
            conditions.append("1=0")

    # If no applicable role → no access
    if not conditions:
        return "1=0"

    # OR logic between conditions
    return "({})".format(" OR ".join(conditions))
