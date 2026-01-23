import frappe
from frappe import _

def validate(doc, method):
    # Apply only for Employee payments
    if doc.party_type == "Employee":
        # payment references child table
        if not doc.references or len(doc.references) == 0:
            frappe.throw(
                _("At least one Payment Reference is required for Employee Payment Entry")
            )
    
    if doc.party_type == "Supplier":
        # Ensure that all references are there
        if not doc.references or len(doc.references) == 0:
            frappe.throw(
                _("At least one Payment Reference is required for Supplier Payment Entry")
            )
        if doc.unallocated_amount > 0:
            frappe.throw(
                _("Unallocated Amount must be zero for Supplier Payment Entry with References")
            )