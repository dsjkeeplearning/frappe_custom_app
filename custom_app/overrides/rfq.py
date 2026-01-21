import frappe
from frappe.model.mapper import get_mapped_doc
from erpnext.buying.doctype.request_for_quotation.request_for_quotation import (
	set_missing_values as erpnext_set_missing_values,
)
from erpnext.accounts.party import get_party_details, get_party_account_currency


@frappe.whitelist()
def make_supplier_quotation_from_rfq(source_name, target_doc=None, for_supplier=None):

	def postprocess(source, target):

		# ✅ SET HEADER COST CENTER BEFORE set_missing_values
		if source.get("custom_cost_center"):
			target.cost_center = source.custom_cost_center

		# --- Standard ERPNext logic ---
		if for_supplier:
			target.supplier = for_supplier
			args = get_party_details(
				for_supplier,
				party_type="Supplier",
				ignore_permissions=True,
			)

			target.currency = (
				args.currency
				or get_party_account_currency("Supplier", for_supplier, source.company)
			)

			target.buying_price_list = (
				args.buying_price_list
				or frappe.db.get_value("Buying Settings", None, "buying_price_list")
			)

		# ⚠️ This will propagate header cost center to items
		erpnext_set_missing_values(source, target)

	doc = get_mapped_doc(
		"Request for Quotation",
		source_name,
		{
			"Request for Quotation": {
				"doctype": "Supplier Quotation",
				"validation": {"docstatus": ["=", 1]},
			},
			"Request for Quotation Item": {
				"doctype": "Supplier Quotation Item",
			},
		},
		target_doc,
		postprocess,
	)

	return doc
