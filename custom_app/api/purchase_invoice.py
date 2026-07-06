import frappe
from frappe import _

def validate_pi_items(doc, method):
    for row in doc.items:

        # 1️⃣ Purchase Order must be present (remove this block if PI without PO is allowed)
        if not row.purchase_order:
            frappe.throw(
                _("Row {0}: Purchase Order is mandatory.")
                .format(row.idx)
            )

        # 2️⃣ Expense Account must match the Purchase Order row's Expense Account
        if row.po_detail:
            po_expense_account = frappe.db.get_value(
                "Purchase Order Item",
                row.po_detail,
                "expense_account"
            )

            if po_expense_account and row.expense_account != po_expense_account:
                frappe.throw(
                    _("Row {0}: Expense Account ({1}) does not match the Expense Account "
                      "({2}) set in Purchase Order {3}.")
                    .format(row.idx, row.expense_account, po_expense_account, row.purchase_order)
                )

        # 3️⃣ Expense Account must match the Material Request row's Expense Account
        if row.material_request_item:
            mr_expense_account = frappe.db.get_value(
                "Material Request Item",
                row.material_request_item,
                "expense_account"
            )

            if mr_expense_account and row.expense_account != mr_expense_account:
                frappe.throw(
                    _("Row {0}: Expense Account ({1}) does not match the Expense Account "
                      "({2}) set in Material Request {3}.")
                    .format(row.idx, row.expense_account, mr_expense_account, row.material_request)
                )