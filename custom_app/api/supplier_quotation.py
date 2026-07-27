import frappe

ORDER_STATUS_FIELD = "custom_order_status"
QTY_ORDERED_FIELD = "custom_qty_ordered"


def update_item_cost_center(doc, method):
    """
    Copy Material Request cost center
    to all rows in items table before save
    """
    if not doc.cost_center:
        return

    for item in doc.items:
        item.cost_center = doc.cost_center


# ─────────────────────────────────────────────────────────────────
# ORDERED-QTY TRACKING (driven by Purchase Order submit / cancel)
#
# Each Supplier Quotation Item carries `custom_qty_ordered` -- the running
# total of qty ordered against that quotation row through *submitted*
# Purchase Orders. On PO submit we add the PO row's qty; on PO cancel we
# subtract it. After each change the parent Supplier Quotation's
# `custom_order_status` select is recomputed (Not / Partially / Completely
# Ordered) so it always reflects reality without manual entry.
# ─────────────────────────────────────────────────────────────────

def update_ordered_qty_on_po_submit(doc, method):
    """doc_event: Purchase Order on_submit -> add ordered qty."""
    _apply_po_ordered_qty(doc, sign=1)


def update_ordered_qty_on_po_cancel(doc, method):
    """doc_event: Purchase Order on_cancel -> subtract ordered qty."""
    _apply_po_ordered_qty(doc, sign=-1)


def _apply_po_ordered_qty(po, sign):
    affected_sqs = set()

    for item in po.items:
        sq_item = item.get("supplier_quotation_item")
        sq_name = item.get("supplier_quotation")
        if not sq_item or not sq_name:
            continue

        current = frappe.db.get_value("Supplier Quotation Item", sq_item, QTY_ORDERED_FIELD) or 0
        new_val = current + sign * (item.qty or 0)
        if new_val < 0:
            new_val = 0  # never let rounding / out-of-order cancels drive it negative

        frappe.db.set_value(
            "Supplier Quotation Item", sq_item, QTY_ORDERED_FIELD, new_val,
            update_modified=False,
        )
        affected_sqs.add(sq_name)

    for sq_name in affected_sqs:
        _recompute_order_status(sq_name)


def _recompute_order_status(sq_name):
    items = frappe.get_all(
        "Supplier Quotation Item",
        filters={"parent": sq_name},
        fields=["qty", QTY_ORDERED_FIELD],
    )

    total_ordered = sum((i.get(QTY_ORDERED_FIELD) or 0) for i in items)

    if not items or total_ordered <= 0:
        status = "Not Ordered"
    elif all((i.get(QTY_ORDERED_FIELD) or 0) >= (i.get("qty") or 0) for i in items):
        status = "Completely Ordered"
    else:
        status = "Partially Ordered"

    frappe.db.set_value(
        "Supplier Quotation", sq_name, ORDER_STATUS_FIELD, status,
        update_modified=False,
    )

def set_default_order_status(doc, method):
    """
    doc_event: Supplier Quotation before_insert / validate
    Sirf tab set karo jab field khaali ho -- purane records ke
    correct/manually-fixed value ko kabhi overwrite nahi karega.
    """
    if not doc.get(ORDER_STATUS_FIELD):
        doc.set(ORDER_STATUS_FIELD, "Not Ordered")