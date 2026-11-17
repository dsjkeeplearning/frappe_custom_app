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
    """Install the fixed get_requested_amount, only on ERPNext that needs it.

    v15.125+ ships the same fix (rate inside the SUM) and changed
    get_other_condition to take 4 arguments and return query-builder
    conditions, which this replacement cannot call. There, keep core.
    """
    from erpnext.accounts.doctype.budget import budget

    from custom_app.api.budget_control import core_uses_query_builder_conditions

    if not core_uses_query_builder_conditions():
        budget.get_requested_amount = get_requested_amount_fixed


def validate_master_budget_limit(doc, method=None):
    """Budget before_submit: the cost center's budgets must fit its Master Budget.

    Budget Upload, Mid Year Budget Upload and Budget Reallocation already check
    this for the whole change; this catches a Budget created or amended from
    the Budget form. A cost center with no row in the submitted Master Budget
    is not checked, as before.

    The total is every submitted Budget of the cost center and fiscal year
    except this one, plus this one. An amendment's original is cancelled
    before the amendment is submitted, so it is not counted twice.
    """
    from frappe import _
    from frappe.utils import flt, fmt_money

    if doc.budget_against != "Cost Center" or not doc.cost_center:
        return

    master_budget = frappe.db.get_value(
        "Master Budget", {"company": doc.company, "fiscal_year": doc.fiscal_year, "docstatus": 1}
    )
    if not master_budget:
        return

    limit = frappe.db.get_value(
        "Master Budget Department",
        {"parent": master_budget, "parenttype": "Master Budget", "cost_center": doc.cost_center},
        "budget",
    )
    if limit is None:
        return

    others = frappe.db.sql(
        """
        select sum(ba.budget_amount)
        from `tabBudget Account` ba
        inner join `tabBudget` b on b.name = ba.parent
        where b.docstatus = 1
            and b.company = %s
            and b.fiscal_year = %s
            and b.cost_center = %s
            and b.name != %s
        """,
        (doc.company, doc.fiscal_year, doc.cost_center, doc.name),
    )[0][0]

    this_budget = sum(flt(row.budget_amount) for row in doc.accounts)
    total = flt(others) + this_budget

    if total > flt(limit) + 0.005:
        currency = frappe.get_cached_value("Company", doc.company, "default_currency")
        frappe.throw(
            _(
                "Master Budget limit exceeded for Cost Center {0}, Fiscal Year {1}."
                "<br><br>Master Budget limit: {2}"
                "<br>Other budgets of this cost center: {3}"
                "<br>This budget: {4}"
                "<br>Excess: {5}"
                "<br><br>Reduce the budget or revise the Master Budget ({6}) first."
            ).format(
                frappe.bold(doc.cost_center),
                doc.fiscal_year,
                frappe.bold(fmt_money(limit, currency=currency)),
                fmt_money(others, currency=currency),
                fmt_money(this_budget, currency=currency),
                frappe.bold(fmt_money(total - flt(limit), currency=currency)),
                master_budget,
            ),
            title=_("Master Budget Limit Exceeded"),
        )
