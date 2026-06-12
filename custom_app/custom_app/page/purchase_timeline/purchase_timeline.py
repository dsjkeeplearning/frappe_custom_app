import frappe
from frappe import _


# ─────────────────────────────────────────────────────────────────
# PERMISSION HELPERS
# ─────────────────────────────────────────────────────────────────

def _get_permitted_companies():
    if "System Manager" in frappe.get_roles(frappe.session.user):
        return [r.name for r in frappe.db.sql(
            "SELECT name FROM `tabCompany` ORDER BY name", as_dict=True
        )]
    from frappe.permissions import get_user_permissions
    permitted = get_user_permissions(frappe.session.user).get("Company", [])
    names = [p.get("doc") for p in permitted if p.get("doc")]
    if not names:
        return []
    placeholders = ", ".join(["%s"] * len(names))
    return [r.name for r in frappe.db.sql(
        f"SELECT name FROM `tabCompany` WHERE name IN ({placeholders}) ORDER BY name",
        names, as_dict=True
    )]


# ─────────────────────────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_filter_options():
    companies = _get_permitted_companies()
    is_sm = "System Manager" in frappe.get_roles(frappe.session.user)

    cost_centers = frappe.db.sql(
        "SELECT name FROM `tabCost Center` WHERE is_group=0 ORDER BY name", as_dict=True
    )
    suppliers = frappe.db.sql(
        "SELECT name FROM `tabSupplier` ORDER BY name", as_dict=True
    )

    # MR statuses from workflow
    mr_statuses = ["Draft", "Verified", "Approved by Manager", "Rejected", "Cancelled"]
    po_statuses = ["Draft", "Approved", "Rejected", "Cancelled"]

    return {
        "companies": companies,
        "cost_centers": [r.name for r in cost_centers],
        "suppliers": [r.name for r in suppliers],
        "mr_statuses": mr_statuses,
        "po_statuses": po_statuses,
        "lock_company": not is_sm,
    }


# ─────────────────────────────────────────────────────────────────
# SEARCH HELPERS - list docs for filter dropdowns
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def search_material_requests(txt="", company=None, cost_center=None, limit=20):
    filters = {"docstatus": ["!=", 2]}
    if company:
        filters["company"] = company
    if cost_center:
        filters["custom_cost_center"] = cost_center
    if txt:
        filters["name"] = ["like", f"%{txt}%"]

    docs = frappe.get_all(
        "Material Request",
        filters=filters,
        fields=["name", "transaction_date", "workflow_state", "custom_employee"],
        order_by="transaction_date desc",
        limit=limit,
    )
    return docs


@frappe.whitelist()
def search_purchase_orders(txt="", company=None, supplier=None, limit=20):
    filters = {"docstatus": ["!=", 2]}
    if company:
        filters["company"] = company
    if supplier:
        filters["supplier"] = supplier
    if txt:
        filters["name"] = ["like", f"%{txt}%"]

    docs = frappe.get_all(
        "Purchase Order",
        filters=filters,
        fields=["name", "transaction_date", "workflow_state", "supplier"],
        order_by="transaction_date desc",
        limit=limit,
    )
    return docs


@frappe.whitelist()
def search_purchase_invoices(txt="", company=None, supplier=None, limit=20):
    filters = {"docstatus": ["!=", 2]}
    if company:
        filters["company"] = company
    if supplier:
        filters["supplier"] = supplier
    if txt:
        filters["name"] = ["like", f"%{txt}%"]

    docs = frappe.get_all(
        "Purchase Invoice",
        filters=filters,
        fields=["name", "posting_date", "workflow_state", "supplier"],
        order_by="posting_date desc",
        limit=limit,
    )
    return docs


@frappe.whitelist()
def search_purchase_receipts(txt="", company=None, supplier=None, limit=20):
    filters = {"docstatus": ["!=", 2]}
    if company:
        filters["company"] = company
    if supplier:
        filters["supplier"] = supplier
    if txt:
        filters["name"] = ["like", f"%{txt}%"]

    docs = frappe.get_all(
        "Purchase Receipt",
        filters=filters,
        fields=["name", "posting_date", "supplier"],
        order_by="posting_date desc",
        limit=limit,
    )
    return docs


@frappe.whitelist()
def search_supplier_quotations(txt="", company=None, supplier=None, limit=20):
    filters = {"docstatus": ["!=", 2]}
    if company:
        filters["company"] = company
    if supplier:
        filters["supplier"] = supplier
    if txt:
        filters["name"] = ["like", f"%{txt}%"]

    docs = frappe.get_all(
        "Supplier Quotation",
        filters=filters,
        fields=["name", "transaction_date", "supplier"],
        order_by="transaction_date desc",
        limit=limit,
    )
    return docs


@frappe.whitelist()
def search_rfqs(txt="", company=None, limit=20):
    filters = {"docstatus": ["!=", 2]}
    if company:
        filters["company"] = company
    if txt:
        filters["name"] = ["like", f"%{txt}%"]

    docs = frappe.get_all(
        "Request for Quotation",
        filters=filters,
        fields=["name", "transaction_date"],
        order_by="transaction_date desc",
        limit=limit,
    )
    return docs


# ─────────────────────────────────────────────────────────────────
# CORE: Build the full procurement tree from a Material Request
# ─────────────────────────────────────────────────────────────────

def _get_mr_details(mr_name):
    mr = frappe.get_doc("Material Request", mr_name)

    # Get creator full name
    creator_name = frappe.db.get_value("User", mr.owner, "full_name") or mr.owner
    approver_name = None
    if mr.get("custom_request_approver"):
        approver_name = frappe.db.get_value("User", mr.custom_request_approver, "full_name") or mr.custom_request_approver

    verifier_name = None
    if mr.get("custom_request_verifier"):
        verifier_name = frappe.db.get_value("User", mr.custom_request_verifier, "full_name") or mr.custom_request_verifier

    employee_name = None
    if mr.get("custom_employee"):
        employee_name = frappe.db.get_value("Employee", mr.custom_employee, "employee_name") or mr.custom_employee

    items = []
    for item in mr.items:
        items.append({
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": item.qty,
            "uom": item.uom,
            "rate": item.rate,
            "amount": item.amount,
            "cost_center": item.cost_center,
            "expense_account": item.get("expense_account"),
        })

    return {
        "name": mr.name,
        "doctype": "Material Request",
        "transaction_date": str(mr.transaction_date) if mr.transaction_date else None,
        "company": mr.company,
        "cost_center": mr.get("custom_cost_center"),
        "workflow_state": mr.get("workflow_state") or mr.status,
        "status": mr.status,
        "owner": mr.owner,
        "creator_name": creator_name,
        "employee": mr.get("custom_employee"),
        "employee_name": employee_name,
        "approver": mr.get("custom_request_approver"),
        "approver_name": approver_name,
        "verifier": mr.get("custom_request_verifier"),
        "verifier_name": verifier_name,
        "notes": mr.get("custom_notes"),
        "tender_type": mr.get("custom_tender_type"),
        "type_of_pr": mr.get("custom_type_of_pr"),
        "total_value": mr.get("custom_total_value"),
        "attachment": mr.get("custom_attachment"),
        "modified": str(mr.modified),
        "items": items,
        "items_count": len(items),
    }


def _get_rfqs_for_mr(mr_name):
    """Get RFQs that have this MR's items linked."""
    rfq_items = frappe.db.sql("""
        SELECT DISTINCT ri.parent as rfq_name
        FROM `tabRequest for Quotation Item` ri
        WHERE ri.material_request = %s
        AND ri.docstatus != 2
    """, (mr_name,), as_dict=True)

    rfq_names = [r.rfq_name for r in rfq_items]
    result = []

    for rfq_name in rfq_names:
        try:
            rfq = frappe.get_doc("Request for Quotation", rfq_name)
            suppliers = [s.supplier for s in rfq.suppliers]
            supplier_names = {}
            for s in rfq.suppliers:
                sname = frappe.db.get_value("Supplier", s.supplier, "supplier_name") or s.supplier
                supplier_names[s.supplier] = sname

            items = []
            for item in rfq.items:
                items.append({
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "qty": item.qty,
                    "uom": item.uom,
                    "material_request": item.get("material_request"),
                })

            result.append({
                "name": rfq.name,
                "doctype": "Request for Quotation",
                "transaction_date": str(rfq.transaction_date) if rfq.transaction_date else None,
                "status": rfq.status,
                "company": rfq.company,
                "cost_center": rfq.get("custom_cost_center"),
                "suppliers": suppliers,
                "supplier_names": supplier_names,
                "modified": str(rfq.modified),
                "items": items,
                "items_count": len(items),
            })
        except Exception:
            pass

    return result


def _get_supplier_quotations_for_mr(mr_name, rfq_names=None):
    """Get Supplier Quotations linked to this MR (via RFQ or direct)."""
    sq_names_set = set()

    # Via RFQ
    if rfq_names:
        for rfq_name in rfq_names:
            sqs = frappe.db.sql("""
                SELECT DISTINCT sqi.parent as sq_name
                FROM `tabSupplier Quotation Item` sqi
                WHERE sqi.request_for_quotation = %s
                AND sqi.docstatus != 2
            """, (rfq_name,), as_dict=True)
            for sq in sqs:
                sq_names_set.add(sq.sq_name)

    # Direct via MR item
    direct_sqs = frappe.db.sql("""
        SELECT DISTINCT sqi.parent as sq_name
        FROM `tabSupplier Quotation Item` sqi
        WHERE sqi.material_request = %s
        AND sqi.docstatus != 2
    """, (mr_name,), as_dict=True)
    for sq in direct_sqs:
        sq_names_set.add(sq.sq_name)

    result = []
    for sq_name in sq_names_set:
        try:
            sq = frappe.get_doc("Supplier Quotation", sq_name)
            supplier_name = frappe.db.get_value("Supplier", sq.supplier, "supplier_name") or sq.supplier

            items = []
            for item in sq.items:
                items.append({
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "qty": item.qty,
                    "uom": item.uom,
                    "rate": item.rate,
                    "amount": item.amount,
                    "material_request": item.get("material_request"),
                    "request_for_quotation": item.get("request_for_quotation"),
                })

            result.append({
                "name": sq.name,
                "doctype": "Supplier Quotation",
                "transaction_date": str(sq.transaction_date) if sq.transaction_date else None,
                "supplier": sq.supplier,
                "supplier_name": supplier_name,
                "status": sq.status,
                "grand_total": sq.grand_total,
                "currency": sq.currency,
                "company": sq.company,
                "cost_center": sq.get("cost_center"),
                "modified": str(sq.modified),
                "items": items,
                "items_count": len(items),
            })
        except Exception:
            pass

    return result


def _get_pos_for_mr(mr_name):
    """Get Purchase Orders linked to this Material Request."""
    po_items = frappe.db.sql("""
        SELECT DISTINCT poi.parent as po_name
        FROM `tabPurchase Order Item` poi
        WHERE poi.material_request = %s
        AND poi.docstatus != 2
    """, (mr_name,), as_dict=True)

    po_names = [r.po_name for r in po_items]
    result = []

    for po_name in po_names:
        try:
            po = frappe.get_doc("Purchase Order", po_name)
            supplier_name = frappe.db.get_value("Supplier", po.supplier, "supplier_name") or po.supplier

            items = []
            for item in po.items:
                if item.get("material_request") == mr_name or not item.get("material_request"):
                    items.append({
                        "item_code": item.item_code,
                        "item_name": item.item_name,
                        "qty": item.qty,
                        "uom": item.uom,
                        "rate": item.rate,
                        "amount": item.amount,
                        "material_request": item.get("material_request"),
                        "supplier_quotation": item.get("supplier_quotation"),
                        "cost_center": item.get("cost_center"),
                        "received_qty": item.get("received_qty", 0),
                        "billed_qty": item.get("billed_qty", 0),
                    })

            result.append({
                "name": po.name,
                "doctype": "Purchase Order",
                "transaction_date": str(po.transaction_date) if po.transaction_date else None,
                "supplier": po.supplier,
                "supplier_name": supplier_name,
                "workflow_state": po.get("workflow_state") or po.status,
                "status": po.status,
                "grand_total": po.grand_total,
                "currency": po.currency,
                "company": po.company,
                "cost_center": po.get("cost_center"),
                "modified": str(po.modified),
                "items": items,
                "items_count": len(items),
                "per_received": po.get("per_received", 0),
                "per_billed": po.get("per_billed", 0),
            })
        except Exception:
            pass

    return result


def _get_purchase_receipts_for_po(po_name):
    """Get Purchase Receipts for a given PO."""
    pr_items = frappe.db.sql("""
        SELECT DISTINCT pri.parent as pr_name
        FROM `tabPurchase Receipt Item` pri
        WHERE pri.purchase_order = %s
        AND pri.docstatus != 2
    """, (po_name,), as_dict=True)

    pr_names = [r.pr_name for r in pr_items]
    result = []

    for pr_name in pr_names:
        try:
            pr = frappe.get_doc("Purchase Receipt", pr_name)
            supplier_name = frappe.db.get_value("Supplier", pr.supplier, "supplier_name") or pr.supplier

            items = []
            for item in pr.items:
                if item.get("purchase_order") == po_name:
                    items.append({
                        "item_code": item.item_code,
                        "item_name": item.item_name,
                        "qty": item.qty,
                        "accepted_qty": item.get("accepted_qty", 0),
                        "rejected_qty": item.get("rejected_qty", 0),
                        "uom": item.uom,
                        "rate": item.rate,
                        "amount": item.amount,
                        "cost_center": item.get("cost_center"),
                        "purchase_order": item.get("purchase_order"),
                    })

            result.append({
                "name": pr.name,
                "doctype": "Purchase Receipt",
                "posting_date": str(pr.posting_date) if pr.posting_date else None,
                "supplier": pr.supplier,
                "supplier_name": supplier_name,
                "status": pr.status,
                "grand_total": pr.grand_total,
                "currency": pr.currency,
                "company": pr.company,
                "cost_center": pr.get("cost_center"),
                "modified": str(pr.modified),
                "items": items,
                "items_count": len(items),
            })
        except Exception:
            pass

    return result


def _get_purchase_invoices_for_po(po_name):
    """Get Purchase Invoices for a given PO."""
    pi_items = frappe.db.sql("""
        SELECT DISTINCT pii.parent as pi_name
        FROM `tabPurchase Invoice Item` pii
        WHERE pii.purchase_order = %s
        AND pii.docstatus != 2
    """, (po_name,), as_dict=True)

    pi_names = [r.pi_name for r in pi_items]
    result = []

    for pi_name in pi_names:
        try:
            pi = frappe.get_doc("Purchase Invoice", pi_name)
            supplier_name = frappe.db.get_value("Supplier", pi.supplier, "supplier_name") or pi.supplier

            items = []
            for item in pi.items:
                if item.get("purchase_order") == po_name:
                    items.append({
                        "item_code": item.item_code,
                        "item_name": item.item_name,
                        "qty": item.qty,
                        "uom": item.uom,
                        "rate": item.rate,
                        "amount": item.amount,
                        "cost_center": item.get("cost_center"),
                        "purchase_order": item.get("purchase_order"),
                        "purchase_receipt": item.get("purchase_receipt"),
                    })

            result.append({
                "name": pi.name,
                "doctype": "Purchase Invoice",
                "posting_date": str(pi.posting_date) if pi.posting_date else None,
                "supplier": pi.supplier,
                "supplier_name": supplier_name,
                "workflow_state": pi.get("workflow_state") or pi.status,
                "status": pi.status,
                "grand_total": pi.grand_total,
                "outstanding_amount": pi.outstanding_amount,
                "currency": pi.currency,
                "company": pi.company,
                "cost_center": pi.get("cost_center"),
                "modified": str(pi.modified),
                "items": items,
                "items_count": len(items),
                "is_return": pi.get("is_return", 0),
            })
        except Exception:
            pass

    return result


# ─────────────────────────────────────────────────────────────────
# MAIN API: get_procurement_tree
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_procurement_tree(
    # Filter by document
    material_request=None,
    purchase_order=None,
    purchase_invoice=None,
    purchase_receipt=None,
    supplier_quotation=None,
    rfq=None,
    # Filter by attributes
    company=None,
    cost_center=None,
    supplier=None,
    mr_status=None,
    po_status=None,
    date_from=None,
    date_to=None,
    limit=50,
):
    """
    Build a tree: MR → RFQ → SQ → PO → (PR + PI)
    Supports filtering from any document in the chain.
    """

    mr_names = set()

    # ── Resolve starting MR names based on filter ──────────────────

    if material_request:
        mr_names.add(material_request)

    elif purchase_order:
        # Backtrack: PO → MR
        items = frappe.db.sql("""
            SELECT DISTINCT material_request FROM `tabPurchase Order Item`
            WHERE parent = %s AND material_request IS NOT NULL AND material_request != ''
        """, (purchase_order,), as_dict=True)
        for r in items:
            mr_names.add(r.material_request)
        if not mr_names:
            # Build without MR as root — create a virtual root
            return _build_tree_from_po(purchase_order)

    elif purchase_invoice:
        # Backtrack: PI → PO → MR
        po_names = frappe.db.sql("""
            SELECT DISTINCT purchase_order FROM `tabPurchase Invoice Item`
            WHERE parent = %s AND purchase_order IS NOT NULL AND purchase_order != ''
        """, (purchase_invoice,), as_dict=True)
        for po_row in po_names:
            items = frappe.db.sql("""
                SELECT DISTINCT material_request FROM `tabPurchase Order Item`
                WHERE parent = %s AND material_request IS NOT NULL AND material_request != ''
            """, (po_row.purchase_order,), as_dict=True)
            for r in items:
                mr_names.add(r.material_request)

    elif purchase_receipt:
        # Backtrack: PR → PO → MR
        po_names = frappe.db.sql("""
            SELECT DISTINCT purchase_order FROM `tabPurchase Receipt Item`
            WHERE parent = %s AND purchase_order IS NOT NULL AND purchase_order != ''
        """, (purchase_receipt,), as_dict=True)
        for po_row in po_names:
            items = frappe.db.sql("""
                SELECT DISTINCT material_request FROM `tabPurchase Order Item`
                WHERE parent = %s AND material_request IS NOT NULL AND material_request != ''
            """, (po_row.purchase_order,), as_dict=True)
            for r in items:
                mr_names.add(r.material_request)

    elif supplier_quotation:
        # Backtrack: SQ → MR
        items = frappe.db.sql("""
            SELECT DISTINCT material_request FROM `tabSupplier Quotation Item`
            WHERE parent = %s AND material_request IS NOT NULL AND material_request != ''
        """, (supplier_quotation,), as_dict=True)
        for r in items:
            mr_names.add(r.material_request)

    elif rfq:
        # Backtrack: RFQ → MR
        items = frappe.db.sql("""
            SELECT DISTINCT material_request FROM `tabRequest for Quotation Item`
            WHERE parent = %s AND material_request IS NOT NULL AND material_request != ''
        """, (rfq,), as_dict=True)
        for r in items:
            mr_names.add(r.material_request)

    else:
        # No doc filter: list MRs based on attribute filters
        filters = {"docstatus": ["!=", 2]}
        if company:
            filters["company"] = company
        if cost_center:
            filters["custom_cost_center"] = cost_center
        if mr_status:
            filters["workflow_state"] = mr_status
        if date_from:
            filters["transaction_date"] = [">=", date_from]
        if date_to:
            filters.setdefault("transaction_date", ["<=", date_to])
            if isinstance(filters["transaction_date"], list) and filters["transaction_date"][0] == ">=":
                filters["transaction_date"] = ["between", [date_from, date_to]]
            else:
                filters["transaction_date"] = ["<=", date_to]

        mrs = frappe.get_all(
            "Material Request",
            filters=filters,
            fields=["name"],
            order_by="transaction_date desc",
            limit=int(limit),
        )
        for r in mrs:
            mr_names.add(r.name)

    # ── Build tree for each MR ─────────────────────────────────────
    trees = []
    for mr_name in list(mr_names)[:int(limit)]:
        try:
            tree = _build_tree_for_mr(mr_name, supplier_filter=supplier, po_status_filter=po_status)
            trees.append(tree)
        except Exception as e:
            frappe.log_error(f"Error building tree for MR {mr_name}: {e}")

    # Sort by MR date descending
    trees.sort(key=lambda x: x.get("transaction_date") or "", reverse=True)

    return {
        "trees": trees,
        "total": len(trees),
    }


def _build_tree_for_mr(mr_name, supplier_filter=None, po_status_filter=None):
    """Build complete procurement tree rooted at a Material Request."""
    mr_data = _get_mr_details(mr_name)

    # RFQs
    rfqs = _get_rfqs_for_mr(mr_name)
    rfq_names = [r["name"] for r in rfqs]

    # Supplier Quotations
    sqs = _get_supplier_quotations_for_mr(mr_name, rfq_names)
    if supplier_filter:
        sqs = [s for s in sqs if s["supplier"] == supplier_filter]

    # Purchase Orders
    pos = _get_pos_for_mr(mr_name)
    if supplier_filter:
        pos = [p for p in pos if p["supplier"] == supplier_filter]
    if po_status_filter:
        pos = [p for p in pos if p["workflow_state"] == po_status_filter or p["status"] == po_status_filter]

    # For each PO, get PR and PI
    for po in pos:
        po["purchase_receipts"] = _get_purchase_receipts_for_po(po["name"])
        po["purchase_invoices"] = _get_purchase_invoices_for_po(po["name"])

    mr_data["rfqs"] = rfqs
    mr_data["supplier_quotations"] = sqs
    mr_data["purchase_orders"] = pos

    return mr_data


def _build_tree_from_po(po_name):
    """Fallback: build tree rooted at PO when no MR is linked."""
    try:
        po = frappe.get_doc("Purchase Order", po_name)
        supplier_name = frappe.db.get_value("Supplier", po.supplier, "supplier_name") or po.supplier

        items = []
        for item in po.items:
            items.append({
                "item_code": item.item_code,
                "item_name": item.item_name,
                "qty": item.qty,
                "uom": item.uom,
                "rate": item.rate,
                "amount": item.amount,
                "cost_center": item.get("cost_center"),
            })

        po_data = {
            "name": po.name,
            "doctype": "Purchase Order",
            "transaction_date": str(po.transaction_date) if po.transaction_date else None,
            "supplier": po.supplier,
            "supplier_name": supplier_name,
            "workflow_state": po.get("workflow_state") or po.status,
            "status": po.status,
            "grand_total": po.grand_total,
            "currency": po.currency,
            "company": po.company,
            "cost_center": po.get("cost_center"),
            "items": items,
            "items_count": len(items),
            "purchase_receipts": _get_purchase_receipts_for_po(po_name),
            "purchase_invoices": _get_purchase_invoices_for_po(po_name),
        }

        return {
            "trees": [{
                "name": "No MR",
                "doctype": "Material Request",
                "transaction_date": None,
                "no_mr": True,
                "rfqs": [],
                "supplier_quotations": [],
                "purchase_orders": [po_data],
            }],
            "total": 1,
        }
    except Exception as e:
        return {"trees": [], "total": 0, "error": str(e)}