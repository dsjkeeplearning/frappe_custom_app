"""Budget Reallocation: move budget from one month of an account to another, in one step.

A transfer takes an amount off one budget month (the giving side) and adds it to
another (the receiving side). The company, the fiscal year and the amount are the
same on both sides. The Transfer Type decides what may differ:

    Within Same Month          two accounts of one cost center, in one month
    Carry Forward              one account of one cost center, between two months
    Inter Department Transfer  two cost centers, with any accounts and months.
                               Offered only when Budget Settings allow it. The
                               Master Budget limits move with the budget.

Nothing changes until the reallocation is approved. Approval amends the Budget of
each account it touches (and the Master Budget for an inter department transfer)
in one transaction, so either every part is done or none.

Reallocations made with the earlier form changed one account's month to a new
amount, so a move between accounts took two of them. They are marked "Single
Account" (see the patch mark_old_budget_reallocations) and kept as a record: they
cannot be changed, approved or rejected.
"""

from itertools import accumulate

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.workflow import get_workflow_name
from frappe.utils import cint, flt, fmt_money, now_datetime

SAME_MONTH = "Within Same Month"
CARRY_FORWARD = "Carry Forward"
INTER_DEPARTMENT = "Inter Department Transfer"
TRANSFER_TYPES = (SAME_MONTH, CARRY_FORWARD, INTER_DEPARTMENT)
SINGLE_ACCOUNT = "Single Account"

# Amounts are worked out from percentages, so they carry float noise.
TOLERANCE = 0.005

# What a transfer needs, with the labels of budget_reallocation.json.
TRANSFER_FIELDS = {
    "company": "Company",
    "fiscal_year": "Fiscal Year",
    "from_cost_center": "From Cost Center",
    "from_account": "From Account",
    "from_month": "From Month",
    "to_cost_center": "To Cost Center",
    "to_account": "To Account",
    "to_month": "To Month",
    "amount": "Amount to Move",
}

# What the form shows while a transfer is filled in, worked out by set_figures.
FIGURES = (
    "from_month_budget",
    "from_month_used",
    "left_to_move",
    "from_new_month_budget",
    "from_year_budget",
    "from_new_year_budget",
    "to_month_budget",
    "to_new_month_budget",
    "to_year_budget",
    "to_new_year_budget",
    "from_master_limit",
    "from_new_master_limit",
    "to_master_limit",
    "to_new_master_limit",
)


class BudgetReallocation(Document):

    def validate(self):
        self.refuse_earlier_form()
        self.validate_transfer()

    def on_submit(self):
        self.transfer_budget()

    def refuse_earlier_form(self):
        """A reallocation made with the earlier form is kept as a record, and a new one is a transfer."""
        if self.is_new():
            if self.reallocation_type == SINGLE_ACCOUNT:
                frappe.throw(
                    _("A new reallocation is one of: {0}.").format(", ".join(_(t) for t in TRANSFER_TYPES)),
                    title=_("Choose a Transfer Type"),
                )
            return

        before = self.get_doc_before_save()
        if SINGLE_ACCOUNT in (self.reallocation_type, before and before.get("reallocation_type")):
            frappe.throw(
                _(
                    "This reallocation was made with the earlier form. It is kept as a record and can no "
                    "longer be changed, approved or rejected. To move budget, make a new reallocation."
                ),
                title=_("Kept as a Record"),
            )

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------

    def validate_transfer(self):
        self.check_transfer_type()
        self.fill_receiving_side()
        self.check_both_sides()
        self.set_figures()
        self.check_amount_left()
        self.check_year_keeps_a_budget()
        self.check_master_budget()

    def check_transfer_type(self):
        if self.reallocation_type not in TRANSFER_TYPES:
            frappe.throw(
                _("Choose the Transfer Type: {0}.").format(", ".join(_(t) for t in TRANSFER_TYPES)),
                title=_("Choose a Transfer Type"),
            )
        if self.reallocation_type == INTER_DEPARTMENT and not inter_department_allowed():
            frappe.throw(
                _("Inter Department Transfer is turned off. A System Manager can turn it on in Budget Settings."),
                title=_("Not Allowed"),
            )

    def fill_receiving_side(self):
        """The receiving side repeats what the Transfer Type keeps the same."""
        if self.reallocation_type in (SAME_MONTH, CARRY_FORWARD):
            self.to_cost_center = self.from_cost_center
        if self.reallocation_type == CARRY_FORWARD:
            self.to_account = self.from_account
        if self.reallocation_type == SAME_MONTH:
            self.to_month = self.from_month

    def check_both_sides(self):
        missing = [_(label) for field, label in TRANSFER_FIELDS.items() if not self.get(field)]
        if missing:
            frappe.throw(_("Fill in: {0}.").format(", ".join(missing)), title=_("Missing Values"))

        if flt(self.amount) <= 0:
            frappe.throw(_("Amount to Move must be more than zero."))

        if self.reallocation_type == SAME_MONTH and self.from_account == self.to_account:
            frappe.throw(
                _("Choose two different accounts. To move an account's budget between months, use Carry Forward.")
            )
        if self.reallocation_type == CARRY_FORWARD and self.from_month == self.to_month:
            frappe.throw(
                _("Choose two different months. To move budget between accounts in one month, use Within Same Month.")
            )
        if self.reallocation_type == INTER_DEPARTMENT and self.from_cost_center == self.to_cost_center:
            frappe.throw(
                _(
                    "Choose two different cost centers. Within one cost center, use Within Same Month or "
                    "Carry Forward."
                )
            )

        for cost_center in {self.from_cost_center, self.to_cost_center}:
            company = frappe.get_cached_value("Cost Center", cost_center, "company")
            if company != self.company:
                frappe.throw(
                    _('Cost Center "{0}" does not belong to {1}.').format(cost_center, self.company),
                    title=_("Wrong Company"),
                )

    def is_one_budget_line(self):
        """Carry Forward moves budget within one account of one cost center."""
        return (self.from_cost_center, self.from_account) == (self.to_cost_center, self.to_account)

    def set_figures(self):
        """Each side's month and year before and after, what is left to move, and the limits."""
        amount = flt(self.amount)
        giving = self.get_budget_line(self.from_cost_center, self.from_account)
        receiving = giving if self.is_one_budget_line() else self.get_budget_line(self.to_cost_center, self.to_account)

        giving.after = dict(giving.months)
        receiving.after = giving.after if receiving is giving else dict(receiving.months)
        giving.after[self.from_month] -= amount
        receiving.after[self.to_month] += amount

        # Shown in rupees and paise. The months themselves keep their full figures.
        self.from_month_budget = flt(giving.months[self.from_month], 2)
        self.from_new_month_budget = flt(giving.after[self.from_month], 2)
        self.from_year_budget = flt(giving.annual, 2)
        self.from_new_year_budget = flt(sum(giving.after.values()), 2)
        self.to_month_budget = flt(receiving.months[self.to_month], 2)
        self.to_new_month_budget = flt(receiving.after[self.to_month], 2)
        self.to_year_budget = flt(receiving.annual, 2)
        self.to_new_year_budget = flt(sum(receiving.after.values()), 2)
        self.flags.budget_lines = (giving, receiving)

        self.set_left_to_move(giving)
        self.set_master_budget_figures()

    def get_budget_line(self, cost_center, account):
        """The approved Budget of an account in a cost center, and its months in fiscal year order."""
        from custom_app.api.budget_control import get_fiscal_year_months

        found = frappe.db.sql(
            """
            select b.name, b.monthly_distribution, ba.budget_amount
            from `tabBudget` b
            inner join `tabBudget Account` ba on ba.parent = b.name
            where b.docstatus = 1
                and b.company = %(company)s
                and b.fiscal_year = %(fiscal_year)s
                and b.budget_against = 'Cost Center'
                and b.cost_center = %(cost_center)s
                and ba.account = %(account)s
            """,
            {
                "company": self.company,
                "fiscal_year": self.fiscal_year,
                "cost_center": cost_center,
                "account": account,
            },
            as_dict=True,
        )
        if not found:
            frappe.throw(
                _('Account "{0}" has no approved budget in Cost Center "{1}" for {2}.').format(
                    account, cost_center, self.fiscal_year
                ),
                title=_("No Budget"),
            )

        row = found[0]
        if not row.monthly_distribution:
            frappe.throw(
                _("Budget {0} has no Monthly Distribution, so its months cannot be changed here.").format(row.name),
                title=_("No Monthly Distribution"),
            )

        budget = frappe.get_doc("Budget", row.name)
        if len(budget.accounts) > 1:
            # Its accounts share one monthly split, so changing a month for one changes it for all.
            frappe.throw(
                _(
                    "Budget {0} holds more than one account, and they share one monthly split. "
                    "Budget can be moved only for an account that has a Budget of its own."
                ).format(budget.name),
                title=_("Shared Budget"),
            )

        distribution = frappe.get_doc("Monthly Distribution", row.monthly_distribution)
        shares = {share.month: flt(share.percentage_allocation) for share in distribution.percentages}
        annual = flt(row.budget_amount)

        return frappe._dict(
            cost_center=cost_center,
            account=account,
            budget=budget,
            distribution=distribution,
            annual=annual,
            months={
                month.name: annual * shares.get(month.name, 0) / 100
                for month in get_fiscal_year_months(self.fiscal_year)
            },
        )

    def set_left_to_move(self, giving):
        """How much of the giving month can move: its budget less what it has used.

        "Used" is what the request check and the Budget Availability report count
        (get_monthly_consumption): requests, claims and Journal Entries.

        With "Restrict PR to Current Month Budget" on, a month spends only its own
        budget, so only the giving month counts. With it off, unused budget rolls
        forward, so every month from the giving month on must keep its budget to
        date at or above its use to date. When the budget moves to a later month
        of the same account, the months from there on get it back, so they do not
        limit the move.
        """
        from custom_app.api.budget_control import (
            get_budget_settings,
            get_fiscal_year_months,
            get_monthly_consumption,
        )

        months = get_fiscal_year_months(self.fiscal_year)
        names = [month.name for month in months]
        consumption = get_monthly_consumption(self.company, giving.cost_center, self.fiscal_year)
        used = [flt(consumption.get((giving.account, month.key))) for month in months]
        budget = [giving.months[name] for name in names]
        start = names.index(self.from_month)

        self.from_month_used = flt(used[start], 2)
        self.flags.month_restricted = bool(get_budget_settings().get("restrict_pr_to_current_month_budget"))

        if self.flags.month_restricted:
            left = budget[start] - used[start]
        else:
            end = names.index(self.to_month) if self.is_one_budget_line() else len(names)
            budget_to_date = running_totals(budget)
            used_to_date = running_totals(used)
            room = [budget_to_date[i] - used_to_date[i] for i in range(start, end)]
            left = min([budget[start], *room])

        # A month's budget cannot go below nothing.
        self.left_to_move = flt(max(min(left, budget[start]), 0), 2)

    def check_amount_left(self):
        if flt(self.amount) <= flt(self.left_to_move) + TOLERANCE:
            return

        currency = frappe.get_cached_value("Company", self.company, "default_currency")
        message = _(
            'Only {0} is left to move from {1} for Account "{2}" in Cost Center "{3}". '
            "{1} has a budget of {4}, and {5} of it is already used."
        ).format(
            fmt_money(self.left_to_move, currency=currency),
            self.from_month,
            self.from_account,
            self.from_cost_center,
            fmt_money(self.from_month_budget, currency=currency),
            fmt_money(self.from_month_used, currency=currency),
        )
        if not self.flags.month_restricted:
            message += " " + _(
                "Unused budget rolls forward, so the months after {0} must also keep enough budget "
                "up to them for what they have used."
            ).format(self.from_month)

        frappe.throw(message, title=_("Not Enough Budget Left"))

    def check_year_keeps_a_budget(self):
        """ERPNext does not check a Budget of nothing, so a Budget is never brought down to nothing."""
        if self.is_one_budget_line() or flt(self.from_new_year_budget) > TOLERANCE:
            return
        frappe.throw(
            _(
                'This would leave Account "{0}" in Cost Center "{1}" with no budget for {2}. '
                "Move less, so the account keeps some budget for the year."
            ).format(self.from_account, self.from_cost_center, self.fiscal_year),
            title=_("No Budget Left for the Year"),
        )

    def set_master_budget_figures(self):
        """An inter department transfer moves the two cost centers' Master Budget limits with it."""
        for field in ("from_master_limit", "from_new_master_limit", "to_master_limit", "to_new_master_limit"):
            setattr(self, field, None)
        self.flags.master_budget = None

        if self.reallocation_type != INTER_DEPARTMENT:
            return

        name = frappe.db.get_value(
            "Master Budget", {"company": self.company, "fiscal_year": self.fiscal_year, "docstatus": 1}
        )
        if not name:
            return

        master_budget = frappe.get_doc("Master Budget", name)
        giving = master_budget_row(master_budget, self.from_cost_center)
        receiving = master_budget_row(master_budget, self.to_cost_center)
        if not (giving or receiving):
            return

        amount = flt(self.amount)
        if giving:
            self.from_master_limit = flt(giving.budget)
            self.from_new_master_limit = flt(giving.budget) - amount
        if receiving:
            self.to_master_limit = flt(receiving.budget)
            self.to_new_master_limit = flt(receiving.budget) + amount
        self.flags.master_budget = frappe._dict(doc=master_budget, giving=giving, receiving=receiving)

    def check_master_budget(self):
        master = self.flags.master_budget
        if not master:
            return

        currency = frappe.get_cached_value("Company", self.company, "default_currency")
        amount = flt(self.amount)

        if master.giving and flt(master.giving.budget) < amount - TOLERANCE:
            frappe.throw(
                _(
                    'The Master Budget {0} gives Cost Center "{1}" a limit of {2}, so its limit cannot '
                    "go down by {3}."
                ).format(
                    master.doc.name,
                    self.from_cost_center,
                    fmt_money(master.giving.budget, currency=currency),
                    fmt_money(amount, currency=currency),
                ),
                title=_("Master Budget Limit Too Low"),
            )

        if master.receiving and not master.giving:
            rows = sum(flt(row.budget) for row in master.doc.department_budget)
            total = flt(master.doc.total_budget)
            if total and rows + amount > total + TOLERANCE:
                frappe.throw(
                    _(
                        'Cost Center "{0}" has no row in the Master Budget {1}, so nothing comes off it. '
                        'Raising the limit of "{2}" by {3} would take the rows to {4}, over the Total Budget '
                        "of {5}."
                    ).format(
                        self.from_cost_center,
                        master.doc.name,
                        self.to_cost_center,
                        fmt_money(amount, currency=currency),
                        fmt_money(rows + amount, currency=currency),
                        fmt_money(total, currency=currency),
                    ),
                    title=_("Over the Master Budget Total"),
                )

    @frappe.whitelist()
    def get_figures(self):
        """The figures of a transfer that is being filled in, for the form."""
        if self.reallocation_type not in TRANSFER_TYPES:
            return {}
        self.fill_receiving_side()
        if not all(self.get(field) for field in TRANSFER_FIELDS if field != "amount"):
            return {}
        self.set_figures()
        return {field: self.get(field) for field in FIGURES}

    def transfer_budget(self):
        """On approval: amend the Master Budget, the giving Budget, then the receiving Budget.

        The order keeps every Budget within its Master Budget row as it is submitted
        (overrides/budget.py checks that): the limits move first, and the giving
        Budget goes down before the receiving one goes up.
        """
        if not self.flags.budget_lines:
            self.set_figures()
        giving, receiving = self.flags.budget_lines

        record = {}
        if self.flags.master_budget:
            record["old_master_budget"] = self.flags.master_budget.doc.name
            record["new_master_budget"] = self.move_master_budget_limits(self.flags.master_budget)

        record["from_old_budget"], record["from_new_budget"] = self.amend_budget_line(giving)
        if receiving is giving:
            record["to_old_budget"], record["to_new_budget"] = record["from_old_budget"], record["from_new_budget"]
        else:
            record["to_old_budget"], record["to_new_budget"] = self.amend_budget_line(receiving)

        record["approver"] = frappe.session.user
        record["approval_date"] = now_datetime()
        self.db_set(record)

        currency = frappe.get_cached_value("Company", self.company, "default_currency")
        frappe.msgprint(
            _('{0} moved from Account "{1}", {2}, in Cost Center "{3}" to Account "{4}", {5}, in Cost Center "{6}".').format(
                fmt_money(self.amount, currency=currency),
                self.from_account,
                self.from_month,
                self.from_cost_center,
                self.to_account,
                self.to_month,
                self.to_cost_center,
            ),
            title=_("Budget Moved"),
            indicator="green",
        )

    def amend_budget_line(self, line):
        """Write the line's new months into its Monthly Distribution and amend its Budget."""
        new_annual = sum(line.after.values())

        # Other months keep their amounts: each share is worked out again on the new total.
        distribution = line.distribution
        present = {row.month for row in distribution.percentages}
        for row in distribution.percentages:
            if row.month in line.after:
                row.percentage_allocation = line.after[row.month] / new_annual * 100
        for month, amount in line.after.items():
            if month not in present:
                distribution.append("percentages", {"month": month, "percentage_allocation": amount / new_annual * 100})
        distribution.flags.ignore_permissions = True
        distribution.save()

        def set_amount(budget):
            for row in budget.accounts:
                if row.account == line.account:
                    row.budget_amount = new_annual

        return line.budget.name, amend(line.budget, set_amount)

    def move_master_budget_limits(self, master):
        amount = flt(self.amount)

        def move(master_budget):
            giving = master_budget_row(master_budget, self.from_cost_center)
            receiving = master_budget_row(master_budget, self.to_cost_center)
            if giving:
                giving.budget = flt(giving.budget) - amount
            if receiving:
                receiving.budget = flt(receiving.budget) + amount

        return amend(master.doc, move)


def running_totals(amounts):
    """Each month's amount added to those before it: [1, 2, 3] -> [1, 3, 6]."""
    return list(accumulate(amounts))


def master_budget_row(master_budget, cost_center):
    return next((row for row in master_budget.department_budget if row.cost_center == cost_center), None)


def workflow_states(doctype):
    """The workflow state field of a doctype and its cancelled state, while a workflow is active."""
    name = get_workflow_name(doctype)
    if not name:
        return None, None
    workflow = frappe.get_cached_doc("Workflow", name)
    if not frappe.get_meta(doctype).has_field(workflow.workflow_state_field):
        return None, None
    cancelled = next((state.state for state in workflow.states if cint(state.doc_status) == 2), None)
    return workflow.workflow_state_field, cancelled


def amend(doc, change):
    """Cancel a submitted document and submit an amended copy with `change` made to it.

    Reallocations and uploads keep links to the old version, so links are not
    checked on cancel. The approval of the reallocation is what allows the
    change, so the approver's own rights on the document are not asked for.
    Under a workflow, the old version gets the cancelled state, and the copy
    starts from the first state and takes the approved one when submitted.
    """
    state_field, cancelled_state = workflow_states(doc.doctype)

    doc.flags.ignore_links = True
    doc.flags.ignore_permissions = True
    doc.cancel()
    if state_field and cancelled_state:
        doc.db_set(state_field, cancelled_state, update_modified=False)

    copy = frappe.copy_doc(doc)
    copy.docstatus = 0
    copy.amended_from = doc.name
    if state_field:
        copy.set(state_field, None)
    change(copy)
    copy.flags.ignore_permissions = True
    copy.insert()
    copy.submit()
    return copy.name


def inter_department_allowed():
    from custom_app.api.budget_control import get_budget_settings

    return bool(get_budget_settings().get("allow_inter_department_transfer"))


@frappe.whitelist()
def get_transfer_types():
    """The Transfer Types a new reallocation may take on this site."""
    frappe.has_permission("Budget Reallocation", "read", throw=True)
    return [kind for kind in TRANSFER_TYPES if kind != INTER_DEPARTMENT or inter_department_allowed()]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def budgeted_cost_centers(doctype, txt, searchfield, start, page_len, filters):
    """Cost centers with an approved Budget in the company and fiscal year."""
    frappe.has_permission("Budget Reallocation", "read", throw=True)
    filters = frappe._dict(filters or {})
    if not (filters.company and filters.fiscal_year):
        return []

    return frappe.db.sql(
        """
        select distinct b.cost_center
        from `tabBudget` b
        where b.docstatus = 1
            and b.budget_against = 'Cost Center'
            and b.company = %(company)s
            and b.fiscal_year = %(fiscal_year)s
            and b.cost_center like %(txt)s
            and b.cost_center != %(leave_out)s
        order by b.cost_center
        limit %(page_len)s offset %(start)s
        """,
        {
            "company": filters.company,
            "fiscal_year": filters.fiscal_year,
            "txt": f"%{txt}%",
            "leave_out": filters.leave_out or "",
            "page_len": page_len,
            "start": start,
        },
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def budgeted_accounts(doctype, txt, searchfield, start, page_len, filters):
    """Accounts with an approved Budget in the cost center, company and fiscal year."""
    frappe.has_permission("Budget Reallocation", "read", throw=True)
    filters = frappe._dict(filters or {})
    if not (filters.company and filters.fiscal_year and filters.cost_center):
        return []

    return frappe.db.sql(
        """
        select distinct ba.account
        from `tabBudget Account` ba
        inner join `tabBudget` b on b.name = ba.parent
        where b.docstatus = 1
            and b.budget_against = 'Cost Center'
            and b.company = %(company)s
            and b.fiscal_year = %(fiscal_year)s
            and b.cost_center = %(cost_center)s
            and ba.account like %(txt)s
            and ba.account != %(leave_out)s
        order by ba.account
        limit %(page_len)s offset %(start)s
        """,
        {
            "company": filters.company,
            "fiscal_year": filters.fiscal_year,
            "cost_center": filters.cost_center,
            "txt": f"%{txt}%",
            "leave_out": filters.leave_out or "",
            "page_len": page_len,
            "start": start,
        },
    )
