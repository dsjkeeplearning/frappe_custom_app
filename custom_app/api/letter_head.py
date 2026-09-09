import frappe


def set_letter_head(doc, method=None):
    """
    Auto-populate letter_head based on the document's Company,
    using the Company doctype's `default_letter_head` field.

    Applies to: Purchase Order, Purchase Receipt, Material Request, Purchase Invoice.

    Behavior:
    - New document: sets letter_head to the company's default_letter_head.
    - Existing document: only refreshes letter_head if company was changed.
    - If the company has no default_letter_head set, leave letter_head untouched.
    """
    if not doc.get("company"):
        return

    company_changed = doc.is_new() or doc.has_value_changed("company")

    if not company_changed:
        return

    default_letter_head = frappe.get_cached_value(
        "Company", doc.company, "default_letter_head"
    )

    if default_letter_head:
        doc.letter_head = default_letter_head