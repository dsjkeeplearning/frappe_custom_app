import frappe

def material_request_permission_query(user):
    roles = frappe.get_roles(user)

    # System Manager → everything
    if "System Manager" in roles:
        return ""

    conditions = []

    # Procurement User → all Accepted
    if "Procurement User" in roles:
        conditions.append(
            "`tabMaterial Request`.`workflow_state` = 'Approved'"
        )

    # Expense Approver → only assigned to him
    if "Expense Approver" in roles:
        conditions.append(
            "`tabMaterial Request`.`custom_request_approver` = {}".format(
                frappe.db.escape(user)
            )
        )

    # If no applicable role → no access
    if not conditions:
        return "1=0"

    # OR logic between conditions
    return "({})".format(" OR ".join(conditions))