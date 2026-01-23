import frappe

def expense_claim_permission_query(user):
    roles = frappe.get_roles(user)

    # System Manager → everything
    if "System Manager" in roles or "Auditor" in roles:
        return ""

    conditions = []

    # Finance Approver-> approved, finance approved, cancelled(in workflow state)
    if "Finance Approver" in roles:
        conditions.append(
            "`tabExpense Claim`.`workflow_state` IN ('Approved', 'Finance Approved', 'Cancelled')"
        )

    # AP User and AP Manager →  finance approved(in workflow state)
    if "AP User" in roles or "AP Manager" in roles:
        conditions.append(
            "`tabExpense Claim`.`workflow_state` IN ('Finance Approved')"
        )

    # Expense Approver → only assigned to him (User ID stored)
    if "Expense Approver" in roles:
        conditions.append(
            "`tabExpense Claim`.`expense_approver` = {}".format(
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
                "`tabExpense Claim`.`employee` = {}".format(
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
