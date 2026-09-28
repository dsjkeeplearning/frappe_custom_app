import json
import frappe
from frappe.model.mapper import get_mapped_doc
from erpnext.stock.doctype.material_request.material_request import (
    MaterialRequest,
    set_missing_values,
    update_item,
)
from erpnext.stock.get_item_details import (
    get_brand_defaults,
    get_default_expense_account,
    get_item_defaults,
    get_item_group_defaults,
)


class CustomMaterialRequest(MaterialRequest):
    def update_item_rates(self):
        """Stop ERPNext from overwriting user-entered item rates on first save.

        ERPNext v15 (since commit 18b15f2, Jul 2026) calls update_item_rates()
        from on_update to re-price every row from the Buying Price List when
        buying_price_list "changed", guarded by ``not self.is_new()``. That
        guard never works on insert: Frappe's db_insert() sets
        __islocal = False before on_update runs, and there is no
        doc-before-save, so has_value_changed() is always True. Result: rates
        typed on a new Material Request are silently reset to the price-list
        rate. Still present on version-15 / version-15-hotfix / develop.

        Skip the refresh while inserting. On later saves keep core behaviour
        (rates refresh only when the price list is actually changed).
        """
        if self.flags.in_insert or not self.get_doc_before_save():
            return

        super().update_item_rates()


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


def sync_expense_account(doc, method=None):
    """Re-derive Material Request Item.expense_account from the row's item.

    expense_account is only ever fetched by get_item_details when an item is
    picked in the grid, and the field is read-only in the form. Rows that
    arrive by any other route -- duplicating a document, amending, "Get Items
    From", the REST API, a data import -- keep whatever account came with
    them, even after the item is swapped. That stale account then drives
    budget validation against the wrong head, so re-derive it on every save.
    """
    if not doc.company:
        return

    company_default = frappe.get_cached_value(
        "Company", doc.company, "default_expense_account"
    )

    # item_code -> account, so a doc with many rows of the same item hits the
    # defaults lookups once rather than once per row.
    resolved = {}

    for row in doc.get("items") or []:
        if not row.item_code:
            continue

        if row.item_code not in resolved:
            resolved[row.item_code] = _expected_expense_account(
                row.item_code, doc.company, company_default
            )

        expected = resolved[row.item_code]
        if expected and row.expense_account != expected:
            row.expense_account = expected


def _expected_expense_account(item_code, company, company_default=None):
    """Mirror ERPNext's own precedence: item default -> item group -> brand -> company."""
    args = frappe._dict(
        {
            "company": company,
            "doctype": "Material Request",
            "expense_account": company_default,
        }
    )

    return get_default_expense_account(
        args,
        get_item_defaults(item_code, company),
        get_item_group_defaults(item_code, company),
        get_brand_defaults(item_code, company),
    )
