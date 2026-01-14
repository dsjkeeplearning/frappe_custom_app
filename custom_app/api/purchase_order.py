import frappe
from frappe import _

def validate_po_items(doc, method):
    for row in doc.items:
        # 1️⃣ Material Request must be present
        if not row.material_request:
            frappe.throw(
                _("Row {0}: Material Request is mandatory.")
                .format(row.idx)
            )

        # 2️⃣ If Supplier Quotation is missing
        if not row.supplier_quotation:
            default_supplier = frappe.db.get_value(
                "Item Default",
                {
                    "parent": row.item_code,
                    "company": doc.company
                },
                "default_supplier"
            )

            # No default supplier found
            if not default_supplier:
                frappe.throw(
                    _("Row {0}: No Supplier Quotation and no Default Supplier set for Item {1} in Company {2}.")
                    .format(row.idx, row.item_code, doc.company)
                )

            # Default supplier mismatch
            if default_supplier != doc.supplier:
                frappe.throw(
                    _("Row {0}: Supplier Quotation missing and Default Supplier ({1}) "
                      "does not match Purchase Order Supplier ({2}).")
                    .format(row.idx, default_supplier, doc.supplier)
                )
            row.cost_center = doc.cost_center