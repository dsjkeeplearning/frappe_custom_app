import json
import frappe
from frappe.model.mapper import get_mapped_doc
from erpnext.stock.doctype.material_request.material_request import (
    set_missing_values,
    update_item,
)
from erpnext.stock.get_item_details import get_item_defaults


@frappe.whitelist()
def make_supplier_quotation(source_name, target_doc=None):

    def postprocess(source, target_doc):
        set_missing_values(source, target_doc)

        # 🔹 Map custom_cost_center → cost_center
        if source.custom_cost_center:
            target_doc.cost_center = source.custom_cost_center

    doclist = get_mapped_doc(
        "Material Request",
        source_name,
        {
            "Material Request": {
                "doctype": "Supplier Quotation",
                "validation": {
                    "docstatus": ["=", 1],
                    "material_request_type": ["=", "Purchase"]
                },
            },
            "Material Request Item": {
                "doctype": "Supplier Quotation Item",
                "field_map": {
                    "name": "material_request_item",
                    "parent": "material_request",
                    "sales_order": "sales_order",
                },
            },
        },
        target_doc,
        postprocess,
    )

    doclist.set_onload("load_after_mapping", False)
    return doclist

@frappe.whitelist()
def make_request_for_quotation(source_name, target_doc=None):

    def postprocess(source, target):
        # 🔹 Map custom_cost_center → cost_center
        if source.custom_cost_center:
            target.cost_center = source.custom_cost_center

    doclist = get_mapped_doc(
        "Material Request",
        source_name,
        {
            "Material Request": {
                "doctype": "Request for Quotation",
                "validation": {
                    "docstatus": ["=", 1],
                    "material_request_type": ["=", "Purchase"]
                },
            },
            "Material Request Item": {
                "doctype": "Request for Quotation Item",
                "field_map": [
                    ["name", "material_request_item"],
                    ["parent", "material_request"],
                    ["project", "project_name"],
                ],
            },
        },
        target_doc,
        postprocess,
    )

    return doclist

@frappe.whitelist()
def make_purchase_order(source_name, target_doc=None, args=None):
    if args is None:
        args = {}
    if isinstance(args, str):
        args = json.loads(args)

    def postprocess(source, target_doc):
        # Core ERPNext logic (UNCHANGED)
        if frappe.flags.args and frappe.flags.args.default_supplier:
            supplier_items = []
            for d in target_doc.items:
                default_supplier = get_item_defaults(
                    d.item_code, target_doc.company
                ).get("default_supplier")
                if frappe.flags.args.default_supplier == default_supplier:
                    supplier_items.append(d)
            target_doc.items = supplier_items

        set_missing_values(source, target_doc)

        # 🔹 CUSTOM: Map custom_cost_center → cost_center
        if source.custom_cost_center:
            target_doc.cost_center = source.custom_cost_center

    def select_item(d):
        filtered_items = args.get("filtered_children", [])
        child_filter = d.name in filtered_items if filtered_items else True

        qty = d.ordered_qty or d.received_qty
        return qty < d.stock_qty and child_filter

    doclist = get_mapped_doc(
        "Material Request",
        source_name,
        {
            "Material Request": {
                "doctype": "Purchase Order",
                "validation": {
                    "docstatus": ["=", 1],
                    "material_request_type": ["=", "Purchase"],
                },
            },
            "Material Request Item": {
                "doctype": "Purchase Order Item",
                "field_map": [
                    ["name", "material_request_item"],
                    ["parent", "material_request"],
                    ["uom", "stock_uom"],
                    ["uom", "uom"],
                    ["sales_order", "sales_order"],
                    ["sales_order_item", "sales_order_item"],
                    ["wip_composite_asset", "wip_composite_asset"],
                ],
                "postprocess": update_item,
                "condition": select_item,
            },
        },
        target_doc,
        postprocess,
    )

    doclist.set_onload("load_after_mapping", False)
    return doclist
