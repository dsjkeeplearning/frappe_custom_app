import frappe

def wb_task_permission_query(user):
    roles = frappe.get_roles(user)

    # System Manager → everything
    if "System Manager" in roles:
        return ""

    conditions = []

    # Employee → only tasks where he is the assigner or the assignee
    if "Employee" in roles:
        conditions.append(
            "`tabWB Task`.`assign_from` = {0} OR `tabWB Task`.`assign_to` = {0}".format(
                frappe.db.escape(user)
            )
        )

    # If no applicable role → no access
    if not conditions:
        return "1=0"

    # OR logic between conditions
    return "({})".format(" OR ".join(conditions))
