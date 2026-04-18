import frappe
from frappe import _
from custom_app.api.notification_utils import (
    get_user_from_employee,
    safe_sendmail,
)

def update_item_cost_center(doc, method):
    """
    Copy Material Request cost center
    to all rows in items table before save
    """
    if not doc.custom_cost_center:
        return

    # 1. Get employee department
    department = frappe.db.get_value(
        "Employee",
        doc.custom_employee,
        "department"
    )

    if not department:
        frappe.throw(
            _("Department not found for Employee {0}").format(doc.custom_employee)
        )

    # 2. Get cost center mapped to department
    cost_center = frappe.db.get_value(
        "Cost Center",
        {"custom_department": department},
        "name"
    )

    if not cost_center:
        frappe.throw(
            _("No Cost Center found for Department {0}").format(department)
        )

    #get fiscal year
    fiscal_year = frappe.db.get_value(
        "Fiscal Year",
        {"year_start_date": ("<=", doc.transaction_date), "year_end_date": (">=", doc.transaction_date), "disabled":0},
        "name"
    )
    if not fiscal_year:
        frappe.throw(
            _("No active Fiscal Year found for the posting date {0}").format(doc.transaction_date)
        )
    for row in doc.items:
        row.cost_center = doc.custom_cost_center

        # 1. Get default account for Expense Claim Type (company-wise)
        default_account = frappe.db.get_value(
            "Item Default",
            {
                "parent": row.item_code,
                "company": doc.company
            },
            "expense_account"
        )

        if not default_account:
            frappe.throw(
                _(
                    "Row {0}: No Default Account found for Item "
                    "<b>{1}</b> in Company <b>{2}</b>"
                ).format(row.idx, row.item_code, doc.company)
            )

        # 2. Check Budget with company + cost center + fiscal year + account
        budget_exists = frappe.db.sql(
            """
            select b.name
            from `tabBudget` b
            join `tabBudget Account` ba on ba.parent = b.name
            where
                ba.account = %s
                and b.company = %s
                and b.cost_center = %s
                and b.fiscal_year = %s
                and b.docstatus = 1
            limit 1
            """,
            (
                default_account,
                doc.company,
                row.cost_center,
                fiscal_year,
            ),
            as_dict=True,
        )

        if not budget_exists:
            frappe.throw(
                _(
                    "Row {0}: No submitted Budget found for Account "
                    "<b>{1}</b>, Cost Center <b>{2}</b>, Fiscal Year <b>{3}</b>"
                ).format(
                    row.idx,
                    default_account,
                    row.cost_center,
                    fiscal_year,
                )
            )
 
 
# ──────────────────────────────────────────────────────────────────────────────
# A.  after_insert — notify the request approver
# ──────────────────────────────────────────────────────────────────────────────
 
def notify_approver_on_create(doc, method=None):
    """
    Triggered by doc_events → after_insert.
    Sends a notification to doc.custom_request_approver.
    """
    approver = getattr(doc, "custom_request_approver", None)
    if not approver:
        frappe.logger().warning(
            f"[MR notify] {doc.name}: custom_request_approver not set — skipping."
        )
        return
 
    # Resolve approver email (field is Link → User, so name == email in Frappe)
    approver_email = frappe.db.get_value("User", approver, "email") or approver
 
    link = frappe.utils.get_url_to_form(doc.doctype, doc.name)
    subject = f"New Purchase Request: {doc.name}"
    message = f"""
    <p>A new Purchase Request requires your approval.</p>
    <table style="border-collapse:collapse; font-family:Arial,sans-serif;">
        <tr><td style="padding:4px 12px 4px 0;"><b>Request ID</b></td>
            <td>{doc.name}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Employee</b></td>
            <td>{doc.custom_employee or "—"}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Company</b></td>
            <td>{doc.company or "—"}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Cost Center</b></td>
            <td>{getattr(doc, "custom_cost_center", "") or "—"}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Date</b></td>
            <td>{doc.transaction_date or "—"}</td></tr>
    </table>
    <br>
    <a href="{link}" style="background:#2490ef;color:#fff;padding:8px 16px;
       text-decoration:none;border-radius:4px;">Open Purchase Request</a>
    <br><br>
    <p>Please log in to review and take action.</p>
    """
 
    safe_sendmail(
        recipients=[approver_email],
        subject=subject,
        message=message,
        reference_doctype=doc.doctype,
        reference_name=doc.name,
    )
 
 
# ──────────────────────────────────────────────────────────────────────────────
# B.  on_update — notify employee on state change
# ──────────────────────────────────────────────────────────────────────────────
 
_FINAL_STATES = {"Approved", "Rejected"}
 
 
def notify_employee_on_status_change(doc, method=None):
    """
    Triggered by doc_events → on_update.
    Sends a notification to the linked employee when the workflow
    state transitions to Approved or Rejected.
    """
    # Guard: workflow_state must have actually changed
    if not doc.has_value_changed("workflow_state"):
        return
 
    state = getattr(doc, "workflow_state", None)
    if state not in _FINAL_STATES:
        return
 
    employee = getattr(doc, "custom_employee", None)
    if not employee:
        frappe.logger().warning(
            f"[MR notify] {doc.name}: custom_employee not set — skipping employee notification."
        )
        return
 
    employee_user = get_user_from_employee(employee)
    if not employee_user:
        return
 
    employee_email = frappe.db.get_value("User", employee_user, "email") or employee_user
    link = frappe.utils.get_url_to_form(doc.doctype, doc.name)
 
    state_color = "#28a745" if state == "Approved" else "#dc3545"
    subject = f"Purchase Request {doc.name} — {state}"
    message = f"""
    <p>Your Purchase Request has been
       <b style="color:{state_color};">{state}</b>.</p>
    <table style="border-collapse:collapse; font-family:Arial,sans-serif;">
        <tr><td style="padding:4px 12px 4px 0;"><b>Request ID</b></td>
            <td>{doc.name}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Status</b></td>
            <td style="color:{state_color};"><b>{state}</b></td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Company</b></td>
            <td>{doc.company or "—"}</td></tr>
    </table>
    <br>
    <a href="{link}" style="background:#2490ef;color:#fff;padding:8px 16px;
       text-decoration:none;border-radius:4px;">View Purchase Request</a>
    <br><br>
    <p>Regards,<br>System</p>
    """
 
    safe_sendmail(
        recipients=[employee_email],
        subject=subject,
        message=message,
        reference_doctype=doc.doctype,
        reference_name=doc.name,
    )
 