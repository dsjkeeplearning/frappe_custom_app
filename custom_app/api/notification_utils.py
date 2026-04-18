import frappe


# ──────────────────────────────────────────────
# 1.  Employee → User resolution
# ──────────────────────────────────────────────

def get_user_from_employee(employee: str) -> str | None:
    """
    Return the user_id linked to an Employee record.
    Returns None (never raises) if the employee or user_id is missing.
    """
    if not employee:
        return None
    user_id = frappe.db.get_value("Employee", employee, "user_id")
    if not user_id:
        frappe.logger().warning(
            f"[notifications] Employee {employee!r} has no user_id — skipping."
        )
    return user_id or None


# ──────────────────────────────────────────────
# 2.  Role → User list
# ──────────────────────────────────────────────

def get_users_by_role(role: str) -> list[str]:
    """
    Return a deduplicated list of enabled user emails that hold *role*.
    """
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.email
        FROM   `tabUser` u
        JOIN   `tabHas Role` hr ON hr.parent = u.name
        WHERE  hr.role        = %s
          AND  u.enabled      = 1
          AND  u.email        != ''
          AND  u.name        NOT IN ('Administrator', 'Guest')
        """,
        (role,),
        as_dict=True,
    )
    return [r.email for r in rows if r.email]


# ──────────────────────────────────────────────
# 3.  Finance Approvers filtered by company / cost-center
# ──────────────────────────────────────────────

def get_finance_approvers(company: str, cost_center: str | None = None) -> list[str]:
    """
    Return Finance Approver emails whose linked Employee belongs to
    the same *company*.  If *cost_center* is supplied, further filter
    by the cost-center mapped on the Employee's department.

    Strategy
    --------
    1.  Start from all users with role 'Finance Approver'.
    2.  Cross-join with Employee (via user_id) to get company.
    3.  Filter by company.
    4.  Optionally filter by cost_center via Cost Center.custom_department
        → Employee.department chain.
    """
    if not company:
        return get_users_by_role("Finance Approver")

    # Base query: Finance Approvers whose employee record matches company
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.email
        FROM   `tabUser`     u
        JOIN   `tabHas Role` hr ON hr.parent    = u.name
        JOIN   `tabEmployee` e  ON e.user_id    = u.name
        WHERE  hr.role     = 'Finance Approver'
          AND  u.enabled   = 1
          AND  u.email    != ''
          AND  u.name    NOT IN ('Administrator', 'Guest')
          AND  e.company   = %s
          AND  e.status    = 'Active'
        """,
        (company,),
        as_dict=True,
    )
    candidates = [r.email for r in rows if r.email]

    # Optional cost-center filter
    if cost_center and candidates:
        dept = frappe.db.get_value(
            "Cost Center", cost_center, "custom_department"
        )
        if dept:
            dept_filtered = frappe.db.sql(
                """
                SELECT DISTINCT u.email
                FROM   `tabUser`     u
                JOIN   `tabHas Role` hr ON hr.parent    = u.name
                JOIN   `tabEmployee` e  ON e.user_id    = u.name
                WHERE  hr.role        = 'Finance Approver'
                  AND  u.enabled      = 1
                  AND  u.email       != ''
                  AND  u.name       NOT IN ('Administrator', 'Guest')
                  AND  e.company      = %s
                  AND  e.status       = 'Active'
                  AND  e.department   = %s
                """,
                (company, dept),
                as_dict=True,
            )
            dept_emails = [r.email for r in dept_filtered if r.email]
            # Use narrower list only when it is non-empty
            if dept_emails:
                return dept_emails

    return candidates


# ──────────────────────────────────────────────
# 4.  Safe email dispatch
# ──────────────────────────────────────────────

def safe_sendmail(
    recipients: list[str],
    subject: str,
    message: str,
    reference_doctype: str | None = None,
    reference_name: str | None = None,
) -> None:
    """
    Deduplicate recipients, validate they are non-empty, then send.
    Never raises — errors are logged.
    """
    from custom_app.api.email import send_company_email  # local import avoids circular

    unique = list({r.strip().lower() for r in recipients if r and r.strip()})
    if not unique:
        frappe.logger().warning(
            f"[notifications] No valid recipients for {reference_doctype} "
            f"{reference_name!r} — email skipped."
        )
        return

    try:
        send_company_email(
            recipients=unique,
            subject=subject,
            message=message,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
        )
        frappe.logger().info(
            f"[notifications] Sent '{subject}' → {unique} "
            f"({reference_doctype} {reference_name!r})"
        )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"[notifications] Failed sending '{subject}' for "
            f"{reference_doctype} {reference_name!r}",
        )