import frappe
from frappe import _
from custom_app.api.notification_utils import (
    get_user_from_employee,
    safe_sendmail,
)
 

def update_item_cost_center(doc, method):
    if not doc.employee:
        return

    # 1. Get employee department
    department = frappe.db.get_value(
        "Employee",
        doc.employee,
        "department"
    )

    if not department:
        frappe.throw(
            _("Department not found for Employee {0}").format(doc.employee)
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

    # 3. Set parent cost center
    doc.cost_center = cost_center

    #get fiscal year
    fiscal_year = frappe.db.get_value(
        "Fiscal Year",
        {"year_start_date": ("<=", doc.posting_date), "year_end_date": (">=", doc.posting_date), "disabled":0},
        "name"
    )
    if not fiscal_year:
        frappe.throw(
            _("No active Fiscal Year found for the posting date {0}").format(doc.posting_date)
        )
    for row in doc.expenses:
        row.cost_center = doc.cost_center

        # 1. Get default account for Expense Claim Type (company-wise)
        default_account = frappe.db.get_value(
            "Expense Claim Account",
            {
                "parent": row.expense_type,
                "company": doc.company
            },
            "default_account"
        )

        if not default_account:
            frappe.throw(
                _(
                    "Row {0}: No Default Account found for Expense Claim Type "
                    "<b>{1}</b> in Company <b>{2}</b>"
                ).format(row.idx, row.expense_type, doc.company)
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
# A.  after_insert — notify expense_approver
# ──────────────────────────────────────────────────────────────────────────────

def notify_approver_on_create(doc, method=None):
    """
    Triggered by doc_events → after_insert.
    Notifies the expense_approver that a new claim needs review.
    """
    approver = getattr(doc, "expense_approver", None)
    if not approver:
        return
 
    approver_email = frappe.db.get_value("User", approver, "email") or approver
    link = frappe.utils.get_url_to_form(doc.doctype, doc.name)
    subject = f"New Expense Claim: {doc.name}"
    message = f"""
    <p>A new Expense Claim has been submitted and requires your approval.</p>
    <table style="border-collapse:collapse; font-family:Arial,sans-serif;">
        <tr><td style="padding:4px 12px 4px 0;"><b>Claim ID</b></td>
            <td>{doc.name}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Employee</b></td>
            <td>{doc.employee or "—"}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Company</b></td>
            <td>{doc.company or "—"}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Cost Center</b></td>
            <td>{doc.cost_center or "—"}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Total Amount</b></td>
            <td>{doc.total_claimed_amount or 0}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Posting Date</b></td>
            <td>{doc.posting_date or "—"}</td></tr>
    </table>
    <br>
    <a href="{link}" style="background:#2490ef;color:#fff;padding:8px 16px;
       text-decoration:none;border-radius:4px;">Open Expense Claim</a>
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
# B.  on_update / on_update_after_submit — notify employee on Approved / Rejected
# ──────────────────────────────────────────────────────────────────────────────

_NOTIFY_STATES = {"Approved", "Rejected"}


def on_workflow_state_change(doc, method=None):
    current_state = getattr(doc, "workflow_state", None)
    if not current_state:
        return

    before = doc.get_doc_before_save()
    previous_state = before.get("workflow_state") if before else None

    if previous_state == current_state:
        return

    if current_state not in _NOTIFY_STATES:
        return

    employee = getattr(doc, "employee", None)
    if not employee:
        return

    employee_user = get_user_from_employee(employee)
    if not employee_user:
        return

    employee_email = frappe.db.get_value("User", employee_user, "email") or employee_user
    link = frappe.utils.get_url_to_form(doc.doctype, doc.name)

    state_color = "#28a745" if current_state == "Approved" else "#dc3545"
    subject = f"Expense Claim {doc.name} — {current_state}"
    message = f"""
    <p>Your Expense Claim has been
       <b style="color:{state_color};">{current_state}</b>.</p>
    <table style="border-collapse:collapse; font-family:Arial,sans-serif;">
        <tr><td style="padding:4px 12px 4px 0;"><b>Claim ID</b></td>
            <td>{doc.name}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Status</b></td>
            <td style="color:{state_color};"><b>{current_state}</b></td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Total Amount</b></td>
            <td>{doc.total_claimed_amount or 0}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Company</b></td>
            <td>{doc.company or "—"}</td></tr>
    </table>
    <br>
    <a href="{link}" style="background:#2490ef;color:#fff;padding:8px 16px;
       text-decoration:none;border-radius:4px;">View Expense Claim</a>
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