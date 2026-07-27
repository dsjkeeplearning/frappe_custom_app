import frappe
from frappe import _


# ─────────────────────────────────────────────────────────────────
# PERMISSION HELPERS
# ─────────────────────────────────────────────────────────────────

def _all_companies():
    return [r.name for r in frappe.db.sql(
        "SELECT name FROM `tabCompany` ORDER BY name", as_dict=True
    )]


def _get_permitted_companies():
    """
    Returns (companies_list, lock_company).

    System Manager   → all companies, lock=False
    Institution Head → User-Permission-scoped companies, lock=True
                       BUT if no user permissions configured → all companies, lock=False
    Others           → blocked at page level (roles config); raises PermissionError
    """
    roles = frappe.get_roles(frappe.session.user)

    if "System Manager" in roles:
        return _all_companies(), False

    if "Institution Head" in roles:
        from frappe.permissions import get_user_permissions
        permitted = get_user_permissions(frappe.session.user).get("Company", [])
        names = [p.get("doc") for p in permitted if p.get("doc")]

        if not names:
            # No user permissions configured → grant access to all companies
            return _all_companies(), False

        placeholders = ", ".join(["%s"] * len(names))
        companies = [r.name for r in frappe.db.sql(
            f"SELECT name FROM `tabCompany` WHERE name IN ({placeholders}) ORDER BY name",
            names, as_dict=True
        )]
        return companies, True  # locked to their permitted set

    # Should not be reachable given page roles config, but be safe
    frappe.throw(_("Not permitted"), frappe.PermissionError)


# ─────────────────────────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_filter_options():
    companies, lock_company = _get_permitted_companies()

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
        "approval_statuses": _get_approval_statuses(),
        "lock_company": lock_company,
    }


# "Search by" type key -> doctype, for the doctypes that actually carry a
# workflow (workflow_state). Only these types should ever offer the
# Approval Status filter on the frontend -- Purchase Receipt, Supplier
# Quotation and RFQ have no workflow attached here.
_WORKFLOW_TYPE_DOCTYPE_MAP = {
    "mr": "Material Request",
    "po": "Purchase Order",
    "pi": "Purchase Invoice",
}


def _get_approval_statuses():
    """
    Distinct workflow_state (approval status) values actually in use,
    grouped BY "Search by" type key (mr / po / pi).

    Only doctypes with a workflow attached are included, and only the
    states that are actually in use for that specific doctype are
    returned -- this powers a per-type "Approval Status" filter on the
    frontend instead of one flat, type-agnostic list.

    Returns e.g.:
        {
            "mr": ["Approved by Manager", "Draft", "Rejected", "Verified"],
            "po": ["Approved", "Draft", "Rejected"],
            "pi": ["Draft", "Submitted"],
        }
    A type key is omitted entirely if that doctype has no workflow_state
    column, or has the column but no non-empty values in use.
    """
    result = {}
    for type_key, doctype in _WORKFLOW_TYPE_DOCTYPE_MAP.items():
        # workflow_state is a standard field on workflow-enabled doctypes;
        # guard in case a given doctype has no workflow attached here.
        if not frappe.db.has_column(doctype, "workflow_state"):
            continue
        rows = frappe.db.sql(
            f"""
            SELECT DISTINCT workflow_state
            FROM `tab{doctype}`
            WHERE workflow_state IS NOT NULL AND workflow_state != ''
            """,
            as_dict=True,
        )
        states = sorted({r.workflow_state for r in rows})
        if states:
            result[type_key] = states
    return result


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
    pi_status=None,
    pr_status=None,
    sq_status=None,
    rfq_status=None,
    approval_status=None,
    date_from=None,
    date_to=None,
    limit=50,
):
    """
    Build a tree: MR → RFQ → SQ → PO → (PR + PI)
    Supports filtering from any document in the chain.
    Company access is enforced server-side based on role.
    """

    # ── Enforce company access server-side ─────────────────────────
    permitted_companies, lock_company = _get_permitted_companies()

    if lock_company:
        # Institution Head with user permissions set:
        # validate any explicitly passed company, then scope all queries
        if company and company not in permitted_companies:
            frappe.throw(_("Not permitted to access company: {0}").format(company), frappe.PermissionError)
        # If no company passed, scope to all permitted companies
        effective_companies = permitted_companies
    else:
        # System Manager or Institution Head with no user permissions (all companies)
        effective_companies = None  # None = no company filter applied

    mr_names = set()

    # ── Resolve starting MR names based on filter ──────────────────

    if material_request:
        # Validate the MR belongs to a permitted company when locked
        if lock_company:
            mr_company = frappe.db.get_value("Material Request", material_request, "company")
            if mr_company not in permitted_companies:
                frappe.throw(_("Not permitted"), frappe.PermissionError)
        mr_names.add(material_request)

    elif purchase_order:
        if lock_company:
            po_company = frappe.db.get_value("Purchase Order", purchase_order, "company")
            if po_company not in permitted_companies:
                frappe.throw(_("Not permitted"), frappe.PermissionError)
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
        if lock_company:
            pi_company = frappe.db.get_value("Purchase Invoice", purchase_invoice, "company")
            if pi_company not in permitted_companies:
                frappe.throw(_("Not permitted"), frappe.PermissionError)
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
        if lock_company:
            pr_company = frappe.db.get_value("Purchase Receipt", purchase_receipt, "company")
            if pr_company not in permitted_companies:
                frappe.throw(_("Not permitted"), frappe.PermissionError)
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
        if lock_company:
            sq_company = frappe.db.get_value("Supplier Quotation", supplier_quotation, "company")
            if sq_company not in permitted_companies:
                frappe.throw(_("Not permitted"), frappe.PermissionError)
        items = frappe.db.sql("""
            SELECT DISTINCT material_request FROM `tabSupplier Quotation Item`
            WHERE parent = %s AND material_request IS NOT NULL AND material_request != ''
        """, (supplier_quotation,), as_dict=True)
        for r in items:
            mr_names.add(r.material_request)

    elif rfq:
        if lock_company:
            rfq_company = frappe.db.get_value("Request for Quotation", rfq, "company")
            if rfq_company not in permitted_companies:
                frappe.throw(_("Not permitted"), frappe.PermissionError)
        items = frappe.db.sql("""
            SELECT DISTINCT material_request FROM `tabRequest for Quotation Item`
            WHERE parent = %s AND material_request IS NOT NULL AND material_request != ''
        """, (rfq,), as_dict=True)
        for r in items:
            mr_names.add(r.material_request)

    else:
        # No doc filter: list MRs based on attribute filters
        filters = {"docstatus": ["!=", 2]}

        # Company filter: use explicit value if provided (already validated above),
        # otherwise scope to permitted companies when locked
        if company:
            filters["company"] = company
        elif effective_companies is not None:
            # Lock_company=True and no specific company passed → scope to all permitted
            filters["company"] = ["in", effective_companies]

        if cost_center:
            filters["custom_cost_center"] = cost_center
        if mr_status:
            # Generic "Status" filter → the ERPNext status field. Workflow/
            # approval state has its own dedicated filter (approval_status).
            filters["status"] = mr_status
        if date_from and date_to:
            filters["transaction_date"] = ["between", [date_from, date_to]]
        elif date_from:
            filters["transaction_date"] = [">=", date_from]
        elif date_to:
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
            tree = _build_tree_for_mr(
                mr_name,
                supplier_filter=supplier,
                po_status_filter=po_status,
                rfq_status_filter=rfq_status,
                sq_status_filter=sq_status,
                pr_status_filter=pr_status,
                pi_status_filter=pi_status,
            )

            # The MR-listing query above only filters by mr_status -- it has
            # no idea whether this MR's children (PO/PI/PR/SQ/RFQ) match the
            # selected Status. _build_tree_for_mr already prunes non-matching
            # siblings out of each list, but that alone can leave a card on
            # screen with an empty PO/PI/etc. list. When a status filter is
            # active for the type being searched, drop the whole card here
            # unless it actually contains a matching document -- this is the
            # "only records with that status should show" behaviour.
            if po_status and not tree.get("purchase_orders"):
                continue
            if rfq_status and not tree.get("rfqs"):
                continue
            if sq_status and not tree.get("supplier_quotations"):
                continue
            if pr_status and not any(
                po.get("purchase_receipts") for po in tree.get("purchase_orders", [])
            ):
                continue
            if pi_status and not any(
                po.get("purchase_invoices") for po in tree.get("purchase_orders", [])
            ):
                continue

            trees.append(tree)
        except Exception as e:
            frappe.log_error(f"Error building tree for MR {mr_name}: {e}")

    # ── Approval Status (workflow_state) filter ────────────────────
    # Cross-cutting: keep a timeline if ANY document in it (MR, PO, or PI)
    # is in the selected workflow state, so the full chain stays visible
    # for context rather than hiding sibling documents.
    if approval_status:
        trees = [t for t in trees if _tree_has_workflow_state(t, approval_status)]

    # Sort by MR date descending
    trees.sort(key=lambda x: x.get("transaction_date") or "", reverse=True)

    return {
        "trees": trees,
        "total": len(trees),
    }


def _tree_has_workflow_state(tree, state):
    """True if the MR or any of its POs / PIs is in the given workflow_state."""
    if tree.get("workflow_state") == state:
        return True
    for po in tree.get("purchase_orders", []):
        if po.get("workflow_state") == state:
            return True
        for pi in po.get("purchase_invoices", []):
            if pi.get("workflow_state") == state:
                return True
    return False


def _build_tree_for_mr(
    mr_name,
    supplier_filter=None,
    po_status_filter=None,
    rfq_status_filter=None,
    sq_status_filter=None,
    pr_status_filter=None,
    pi_status_filter=None,
):
    """Build complete procurement tree rooted at a Material Request."""
    mr_data = _get_mr_details(mr_name)

    # RFQs -- keep the FULL unfiltered list of names for the SQ lookup below
    # (an SQ can be linked via an RFQ that itself doesn't match the status
    # filter; filtering rfq_names first would silently break that link).
    rfqs_all = _get_rfqs_for_mr(mr_name)
    rfq_names_all = [r["name"] for r in rfqs_all]
    rfqs = rfqs_all
    if rfq_status_filter:
        rfqs = [r for r in rfqs_all if r["status"] == rfq_status_filter]

    # Supplier Quotations
    sqs = _get_supplier_quotations_for_mr(mr_name, rfq_names_all)
    if supplier_filter:
        sqs = [s for s in sqs if s["supplier"] == supplier_filter]
    if sq_status_filter:
        sqs = [s for s in sqs if s["status"] == sq_status_filter]

    # Purchase Orders
    pos = _get_pos_for_mr(mr_name)
    if supplier_filter:
        pos = [p for p in pos if p["supplier"] == supplier_filter]
    if po_status_filter:
        # Generic "Status" filter → the ERPNext status field only. Approval
        # (workflow_state) is handled by the separate approval_status filter.
        pos = [p for p in pos if p["status"] == po_status_filter]

    # For each PO, get PR and PI, filtering each by its own Status when the
    # "Search by" type is Purchase Receipt / Purchase Invoice.
    for po in pos:
        prs = _get_purchase_receipts_for_po(po["name"])
        pis = _get_purchase_invoices_for_po(po["name"])
        if pr_status_filter:
            prs = [pr for pr in prs if pr["status"] == pr_status_filter]
        if pi_status_filter:
            pis = [pi for pi in pis if pi["status"] == pi_status_filter]
        po["purchase_receipts"] = prs
        po["purchase_invoices"] = pis

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