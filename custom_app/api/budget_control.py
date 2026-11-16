import frappe
from frappe import _
from frappe.utils import add_months, flt, fmt_money, get_first_day, get_last_day, getdate, today

from erpnext.accounts.doctype.budget import budget as core_budget
from erpnext.accounts.utils import FiscalYearError, get_fiscal_year


# Budget a PR line occupies, for queries joining `tabMaterial Request` mr and
# `tabMaterial Request Item` mri. A stopped PR releases its budget, as in
# ERPNext's own check (budget.get_requested_amount skips status "Stopped"),
# except for the part already ordered, which still becomes a real cost.
PR_CONSUMED_AMOUNT = (
    "if(mr.status = 'Stopped',"
    " mri.amount * least(ifnull(mri.ordered_qty / nullif(mri.stock_qty, 0), 0), 1),"
    " mri.amount)"
)


def get_budget_settings():
    return frappe.get_cached_doc("Budget Settings")


def use_transaction_date_for_pr_budget():
    """True when ERPNext's standard PR budget check should use Transaction Date.

    Uses .get() so the check is simply off on a site that has not migrated
    the new Budget Settings field yet.
    """
    return bool(get_budget_settings().get("use_transaction_date_for_pr_budget"))


# ---------------------------------------------------------------------------
# ERPNext core budget check: Required By date -> Transaction Date for PRs
#
# ERPNext v15 (and develop) hardcode the Required By date (schedule_date) for
# Material Requests in two places, with no setting to change it:
#   1. BuyingController.validate_budget() passes schedule_date as the
#      posting_date, which picks the fiscal year and the month used for the
#      "Accumulated Monthly" budget and for actual expenses up to month end.
#      -> overridden in CustomMaterialRequest.validate_budget().
#   2. budget.get_other_condition() matches pending (not yet ordered) PRs to
#      the fiscal year by schedule_date.
#      -> replaced below by get_other_condition().
# Both changes apply only to Material Requests and only while
# Budget Settings > "Use Transaction Date for PR Budget Check" is ticked.
# ---------------------------------------------------------------------------


def get_other_condition(args, for_doc):
    """budget.get_other_condition, matching PRs by transaction_date when enabled."""
    if for_doc != "Material Request" or not use_transaction_date_for_pr_budget():
        return _core_get_other_condition(args, for_doc)

    condition = f"expense_account = {frappe.db.escape(args.expense_account)}"
    budget_against_field = args.get("budget_against_field")

    if budget_against_field and args.get(budget_against_field):
        condition += (
            f" and child.{budget_against_field} = {frappe.db.escape(args.get(budget_against_field))}"
        )

    if args.get("fiscal_year"):
        start_date, end_date = frappe.get_cached_value(
            "Fiscal Year", args.get("fiscal_year"), ["year_start_date", "year_end_date"]
        )
        condition += (
            f" and parent.transaction_date between {frappe.db.escape(str(start_date))}"
            f" and {frappe.db.escape(str(end_date))}"
        )

    return condition


# Keep a handle on the real core function even if this module is reloaded
# after the patch has been applied (avoids wrapping our own function).
_core_get_other_condition = getattr(
    core_budget.get_other_condition, "_core_original", core_budget.get_other_condition
)
get_other_condition._core_original = _core_get_other_condition


def patch_core_budget():
    """Route core's PR fiscal-year matching through get_other_condition.

    Idempotent. budget.get_requested_amount() looks get_other_condition up in
    the budget module's globals at call time, so replacing the module
    attribute is enough. Behaviour is unchanged while the setting is off.
    """
    if core_budget.get_other_condition is not get_other_condition:
        core_budget.get_other_condition = get_other_condition


@frappe.whitelist()
def get_pr_restrictions():
    """Flags the Material Request form needs; readable by every PR raiser."""
    settings = get_budget_settings()
    return {
        "restrict_backdated_pr": settings.restrict_backdated_pr,
        "restrict_pr_to_current_month_budget": settings.restrict_pr_to_current_month_budget,
    }


def validate_material_request(doc, method=None):
    settings = get_budget_settings()

    if settings.restrict_backdated_pr:
        validate_backdated_pr(doc)

    if settings.restrict_pr_to_current_month_budget:
        validate_current_month_budget(doc)


def validate_backdated_pr(doc):
    """Block a Material Request whose Transaction Date is before today.

    Only checked when the date is set or changed, so a draft raised yesterday
    can still move through the approval workflow / be submitted today.
    """
    if not doc.transaction_date:
        return

    if not (doc.is_new() or doc.has_value_changed("transaction_date")):
        return

    if getdate(doc.transaction_date) < getdate(today()):
        frappe.throw(
            _("Backdated Material Request is not allowed. Transaction Date {0} is before today ({1}).").format(
                frappe.bold(frappe.format(doc.transaction_date, "Date")),
                frappe.bold(frappe.format(today(), "Date")),
            ),
            title=_("Backdated PR Not Allowed"),
        )


def validate_current_month_budget(doc):
    """Allow a Purchase PR to consume only its own month's budget.

    Monthly budget = Budget Account amount x the month's Monthly Distribution
    percentage (1/12 when the Budget has no distribution). Unused budget of
    earlier months is NOT carried forward, unlike ERPNext's "Accumulated
    Monthly" check.

    Consumption is submitted Material Requests (by transaction_date) and
    Expense Claims (by posting_date) of the same account and cost center in
    that month. Stopped PRs count only for the part already ordered, see
    PR_CONSUMED_AMOUNT. Expense Claims count at their sanctioned amount, which
    is what ERPNext posts to the ledger (zero for a rejected claim).
    """
    if doc.material_request_type != "Purchase" or not doc.transaction_date:
        return

    try:
        fiscal_year = get_fiscal_year(doc.transaction_date, company=doc.company, verbose=0)[0]
    except FiscalYearError:
        return

    # Rows are grouped so a PR with several items on one head is checked once
    # against its combined amount.
    requested = {}
    for row in doc.get("items") or []:
        cost_center = doc.get("custom_cost_center") or row.cost_center
        if not (row.expense_account and cost_center):
            continue
        key = (row.expense_account, cost_center)
        requested[key] = requested.get(key, 0) + flt(row.amount)

    if not requested:
        return

    month_start = get_first_day(doc.transaction_date)
    month_end = get_last_day(doc.transaction_date)
    month_name = month_start.strftime("%B")
    currency = frappe.get_cached_value("Company", doc.company, "default_currency")

    for (account, cost_center), amount in requested.items():
        month_budget = get_month_budget(doc.company, fiscal_year, account, cost_center, month_name)
        if month_budget is None:
            # No Budget applicable on Material Request for this head.
            continue

        used = get_month_consumption(doc, account, cost_center, month_start, month_end)
        available = month_budget - used

        if flt(amount, 2) > flt(available, 2):
            frappe.throw(
                _(
                    "Insufficient budget for {0} {1} for Account {2} against Cost Center {3}."
                    "<br><br>Budget for the month: {4}"
                    "<br>Already raised (PR/EC): {5}"
                    "<br>Available: {6}"
                    "<br>This PR: {7}"
                    "<br><br>Unused budget of previous months cannot be used."
                ).format(
                    month_name,
                    month_start.year,
                    frappe.bold(account),
                    frappe.bold(cost_center),
                    frappe.bold(fmt_money(month_budget, currency=currency)),
                    fmt_money(used, currency=currency),
                    frappe.bold(fmt_money(max(available, 0), currency=currency)),
                    frappe.bold(fmt_money(amount, currency=currency)),
                ),
                title=_("Monthly Budget Exceeded"),
            )


def get_month_budget(company, fiscal_year, account, cost_center, month_name):
    """Return the month's budget, or None when no MR-applicable Budget exists."""
    budgets = frappe.db.sql(
        """
        select ba.budget_amount, b.monthly_distribution
        from `tabBudget` b
        inner join `tabBudget Account` ba on ba.parent = b.name
        where b.docstatus = 1
            and b.company = %(company)s
            and b.fiscal_year = %(fiscal_year)s
            and b.budget_against = 'Cost Center'
            and b.cost_center = %(cost_center)s
            and b.applicable_on_material_request = 1
            and ba.account = %(account)s
        """,
        {
            "company": company,
            "fiscal_year": fiscal_year,
            "cost_center": cost_center,
            "account": account,
        },
        as_dict=True,
    )

    if not budgets:
        return None

    total = 0
    for budget in budgets:
        if budget.monthly_distribution:
            percentage = frappe.db.get_value(
                "Monthly Distribution Percentage",
                {"parent": budget.monthly_distribution, "month": month_name},
                "percentage_allocation",
            )
        else:
            percentage = 100.0 / 12

        total += flt(budget.budget_amount) * flt(percentage) / 100

    return total


def get_month_consumption(doc, account, cost_center, month_start, month_end):
    params = {
        "company": doc.company,
        "account": account,
        "cost_center": cost_center,
        "from_date": month_start,
        "to_date": month_end,
        "name": doc.name,
    }

    mr_amount = frappe.db.sql(
        f"""
        select sum({PR_CONSUMED_AMOUNT})
        from `tabMaterial Request Item` mri
        inner join `tabMaterial Request` mr on mri.parent = mr.name
        where mr.docstatus = 1
            and mr.name != %(name)s
            and mr.company = %(company)s
            and mr.material_request_type = 'Purchase'
            and mr.transaction_date between %(from_date)s and %(to_date)s
            and mri.expense_account = %(account)s
            and mri.cost_center = %(cost_center)s
        """,
        params,
    )[0][0]

    ec_amount = frappe.db.sql(
        """
        select sum(ecd.sanctioned_amount)
        from `tabExpense Claim Detail` ecd
        inner join `tabExpense Claim` ec on ecd.parent = ec.name
        where ec.docstatus = 1
            and ec.company = %(company)s
            and ec.posting_date between %(from_date)s and %(to_date)s
            and ecd.default_account = %(account)s
            and ecd.cost_center = %(cost_center)s
        """,
        params,
    )[0][0]

    return flt(mr_amount) + flt(ec_amount)


# ---------------------------------------------------------------------------
# Month-wise consumption for a whole fiscal year
#
# Shared by the Budget Availability report and Mid Year Budget Upload.
# ---------------------------------------------------------------------------


def get_pr_date_basis(settings=None):
    """Which date decides the month (and fiscal year) a PR consumed budget in.

    ERPNext checks a PR against the budget of its Required By date. Budget
    Settings > "Use Transaction Date for PR Budget Check" moved that to the
    Transaction Date, but only for PRs raised after it was switched on: older
    PRs were approved against, and still occupy, their Required By month.

    Returns a dict with:
        use_transaction_date: the setting is on
        effective_from: PRs raised before this date keep their Required By
            month (None = every PR is counted by Transaction Date)
    """
    settings = settings or get_budget_settings()
    use_transaction_date = bool(settings.get("use_transaction_date_for_pr_budget"))
    effective_from = settings.get("pr_transaction_date_effective_from") if use_transaction_date else None

    return frappe._dict(
        use_transaction_date=use_transaction_date,
        effective_from=getdate(effective_from) if effective_from else None,
    )


def get_fiscal_year_months(fiscal_year):
    """Months of the fiscal year in order (Apr to Mar for an April-March year)."""
    year_start, year_end = frappe.get_cached_value(
        "Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"]
    )

    months = []
    current = get_first_day(year_start)
    while current <= getdate(year_end):
        months.append(
            frappe._dict(
                key=current.strftime("%Y-%m"),
                name=current.strftime("%B"),
                label=current.strftime("%b"),
                fieldname=current.strftime("%b").lower(),
            )
        )
        current = add_months(current, 1)

    return months


def get_monthly_consumption(company, cost_center, fiscal_year, pr_dates=None):
    """(account, 'YYYY-MM') -> amount consumed in that month of the fiscal year.

    Same documents as get_month_consumption (the check that blocks a PR):
    submitted Purchase Material Requests plus submitted Expense Claims (by
    Posting Date, at the sanctioned amount, so a rejected claim counts for
    nothing), on the account and cost center. Stopped PRs count only for the
    part already ordered. A PR falls in the month, and fiscal year, of the
    date it was budget-checked against, see get_pr_date_basis().
    """
    pr_dates = pr_dates or get_pr_date_basis()
    year_start, year_end = frappe.get_cached_value(
        "Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"]
    )
    params = {
        "company": company,
        "cost_center": cost_center,
        "from_date": year_start,
        "to_date": year_end,
        "effective_from": pr_dates.effective_from,
    }

    required_by = "ifnull(mr.schedule_date, mr.transaction_date)"
    if not pr_dates.use_transaction_date:
        pr_date = required_by
    elif pr_dates.effective_from:
        pr_date = f"if(mr.transaction_date < %(effective_from)s, {required_by}, mr.transaction_date)"
    else:
        pr_date = "mr.transaction_date"

    material_requests = frappe.db.sql(
        f"""
        select mri.expense_account as account,
            date_format({pr_date}, '%%Y-%%m') as month,
            sum({PR_CONSUMED_AMOUNT}) as amount
        from `tabMaterial Request Item` mri
        inner join `tabMaterial Request` mr on mri.parent = mr.name
        where mr.docstatus = 1
            and mr.company = %(company)s
            and mr.material_request_type = 'Purchase'
            and {pr_date} between %(from_date)s and %(to_date)s
            and mri.cost_center = %(cost_center)s
        group by mri.expense_account, month
        """,
        params,
        as_dict=True,
    )

    expense_claims = frappe.db.sql(
        """
        select ecd.default_account as account,
            date_format(ec.posting_date, '%%Y-%%m') as month,
            sum(ecd.sanctioned_amount) as amount
        from `tabExpense Claim Detail` ecd
        inner join `tabExpense Claim` ec on ecd.parent = ec.name
        where ec.docstatus = 1
            and ec.company = %(company)s
            and ec.posting_date between %(from_date)s and %(to_date)s
            and ecd.cost_center = %(cost_center)s
        group by ecd.default_account, month
        """,
        params,
        as_dict=True,
    )

    consumption = {}
    for row in material_requests + expense_claims:
        key = (row.account, row.month)
        consumption[key] = consumption.get(key, 0) + flt(row.amount)

    return consumption
