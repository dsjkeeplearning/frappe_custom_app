import frappe
from frappe.model.workflow import get_workflow_name
from frappe.utils import add_days, cint, getdate, nowdate

from custom_app.api.notification_utils import (
    get_user_from_employee,
    safe_sendmail,
)

# A Purchase Request is auto-cancelled this many days after its transaction date
# if no Purchase Order has been raised against it.
AUTO_CANCEL_AFTER_DAYS = 30

# Statuses that mean procurement already moved ahead (or the PR was halted
# deliberately) — these are never auto-cancelled.
SKIP_STATUSES = ["Stopped", "Ordered", "Partially Ordered", "Cancelled"]


def cancel_unordered_material_requests(dry_run=False, only=None):
    """
    Daily job: cancel submitted Purchase Requests (Material Requests of type
    "Purchase") that are still open after AUTO_CANCEL_AFTER_DAYS days with no
    Purchase Order raised against them.

    Approved requests are included — approval alone does not exempt a PR.
    A PR with only draft (rejected) Purchase Orders against it is still
    cancelled; each of those POs gets a comment recording why. A PR with a
    SUBMITTED Purchase Order is left alone — procurement has committed.

    dry_run: report what would be cancelled without changing anything or
             sending any email. Always run this first on a live site.
    only:    restrict the run to specific Material Request names (list, or a
             comma-separated string). Use it to roll out in small batches.
    """
    cutoff = add_days(getdate(nowdate()), -AUTO_CANCEL_AFTER_DAYS)

    filters = {
        "docstatus": 1,
        "material_request_type": "Purchase",
        "status": ["not in", SKIP_STATUSES],
        "per_ordered": 0,
        "transaction_date": ["<=", cutoff],
    }

    if only:
        if isinstance(only, str):
            only = [n.strip() for n in only.split(",") if n.strip()]
        filters["name"] = ["in", only]

    requests = frappe.get_all(
        "Material Request",
        filters=filters,
        fields=["name", "transaction_date", "status", "workflow_state"],
    )

    if not requests:
        return {
            "eligible": 0,
            "cancelled": [],
            "skipped_has_submitted_po": [],
            "commented_pos": [],
        }

    cancelled = []
    skipped = []
    commented_pos = []

    for mr in requests:
        purchase_orders = get_linked_purchase_orders(mr.name)

        # A submitted PO means procurement has committed — never cancel under it.
        # per_ordered should already exclude these, but it can go stale.
        if any(po.docstatus == 1 for po in purchase_orders):
            skipped.append(mr.name)
            continue

        # Anything left is a draft PO (in practice a rejected one, which stays
        # at docstatus 0). Frappe forbids cancelling a draft, so it is left as
        # it is and annotated instead.
        if dry_run:
            cancelled.append(mr.name)
            commented_pos.extend(po.name for po in purchase_orders)
            continue

        try:
            doc = frappe.get_doc("Material Request", mr.name)
            doc.flags.ignore_permissions = True
            set_cancelled_workflow_state(doc)
            doc.cancel()

            doc.add_comment(
                "Comment",
                f"Automatically cancelled: no Purchase Order was raised within "
                f"{AUTO_CANCEL_AFTER_DAYS} days of {mr.transaction_date}.",
            )
            for po in purchase_orders:
                comment_on_purchase_order(po.name, mr.name, mr.transaction_date)
                commented_pos.append(po.name)

            frappe.db.commit()

            cancelled.append(mr.name)
            notify_requester(doc)
        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                frappe.get_traceback(),
                f"[auto-cancel PR] Failed to cancel {mr.name}",
            )

    if cancelled:
        frappe.logger().info(
            f"[auto-cancel PR] {'Would cancel' if dry_run else 'Cancelled'} "
            f"{len(cancelled)} unordered Purchase Request(s): {cancelled}"
        )

    return {
        "dry_run": bool(dry_run),
        "cutoff": str(cutoff),
        "eligible": len(requests),
        "cancelled": cancelled,
        "skipped_has_submitted_po": skipped,
        "commented_pos": commented_pos,
    }


def set_cancelled_workflow_state(doc):
    """
    Frappe skips _validate() when the action is "cancel", so the workflow state
    is never advanced automatically. Set it to the workflow's doc_status 2
    state ourselves, otherwise the PR shows "Cancelled" with a stale
    "Approved by Manager" workflow state.
    """
    workflow_name = get_workflow_name(doc.doctype)
    if not workflow_name:
        return

    workflow = frappe.get_cached_doc("Workflow", workflow_name)
    for state in workflow.states:
        if cint(state.doc_status) == 2:
            doc.set(workflow.workflow_state_field, state.state)
            return


def get_linked_purchase_orders(material_request: str) -> list:
    """
    Non-cancelled Purchase Orders referencing this request, with their docstatus.

    Drafts matter here because per_ordered only counts submitted POs, so a
    draft never shows up in the Material Request's own figures.
    """
    return frappe.db.sql(
        """
        select distinct po.name, po.docstatus
        from `tabPurchase Order Item` poi
        join `tabPurchase Order` po on po.name = poi.parent
        where poi.material_request = %s
          and po.docstatus < 2
        """,
        material_request,
        as_dict=True,
    )


def comment_on_purchase_order(purchase_order: str, material_request: str, transaction_date):
    """
    Record on the draft Purchase Order that its Purchase Request was cancelled.

    The PO is deliberately left at its current docstatus: Frappe forbids
    cancelling a draft, and these are already terminal (workflow state
    "Rejected"), so annotating preserves the audit trail.
    """
    frappe.get_doc("Purchase Order", purchase_order).add_comment(
        "Comment",
        f"Purchase Request {material_request} was automatically cancelled: "
        f"no Purchase Order was raised within {AUTO_CANCEL_AFTER_DAYS} days of "
        f"{transaction_date}. This draft Purchase Order is no longer required.",
    )


def notify_requester(doc):
    """Tell the requesting employee their Purchase Request was auto-cancelled."""
    employee = getattr(doc, "custom_employee", None)
    if not employee:
        return

    employee_user = get_user_from_employee(employee)
    if not employee_user:
        return

    employee_email = frappe.db.get_value("User", employee_user, "email") or employee_user
    link = frappe.utils.get_url_to_form(doc.doctype, doc.name)

    subject = f"Purchase Request {doc.name} — Cancelled"
    message = f"""
    <p>Your Purchase Request has been
       <b style="color:#dc3545;">Cancelled</b> automatically because no Purchase
       Order was raised against it within {AUTO_CANCEL_AFTER_DAYS} days.</p>
    <table style="border-collapse:collapse; font-family:Arial,sans-serif;">
        <tr><td style="padding:4px 12px 4px 0;"><b>Request ID</b></td>
            <td>{doc.name}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Request Date</b></td>
            <td>{doc.transaction_date}</td></tr>
        <tr><td style="padding:4px 12px 4px 0;"><b>Company</b></td>
            <td>{doc.company or "—"}</td></tr>
    </table>
    <br>
    <p>Please raise a new Purchase Request if this is still required.</p>
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
