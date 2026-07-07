import frappe


def get_requested_amount_fixed(args):
    """
    Patched replacement for erpnext.accounts.doctype.budget.budget.get_requested_amount.

    Upstream bug (still present on the version-15 branch, fixed on develop via
    commit 996a02180b): the original query does
        sum(child.stock_qty - child.ordered_qty) * rate
    with `rate` outside the SUM(), so on sql_mode without ONLY_FULL_GROUP_BY,
    MySQL/MariaDB picks an arbitrary row's rate and multiplies it by the total
    summed qty-difference across all matching rows, instead of summing
    (qty_diff * rate) per line. This inflates (or deflates) the "requested but
    not yet ordered" amount whenever more than one open Material Request line
    matches, causing false Budget Exceeded errors.

    Fix: bracket `rate` inside the SUM(), per line - matches the corrected
    query already merged upstream on develop.
    """
    from erpnext.accounts.doctype.budget.budget import get_other_condition

    item_code = args.get("item_code")
    condition = get_other_condition(args, "Material Request")

    data = frappe.db.sql(
        """ select ifnull(sum((child.stock_qty - child.ordered_qty) * child.rate), 0) as amount
        from `tabMaterial Request Item` child, `tabMaterial Request` parent where parent.name = child.parent and
        child.item_code = %s and parent.docstatus = 1 and child.stock_qty > child.ordered_qty and {} and
        parent.material_request_type = 'Purchase' and parent.status != 'Stopped'""".format(condition),
        item_code,
        as_list=1,
    )

    return data[0][0] if data else 0


def apply_budget_patch():
    from erpnext.accounts.doctype.budget import budget

    budget.get_requested_amount = get_requested_amount_fixed
