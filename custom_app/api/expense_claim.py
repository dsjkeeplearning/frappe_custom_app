import frappe
from frappe import _

def update_item_cost_center(doc, method):
    if not doc.employee:
        return

    # 1. Get employee department
    department = frappe.db.get_value(
        "Employee",
        doc.employee,
        "department"
    )

    if not department:
        frappe.throw(
            _("Department not found for Employee {0}").format(doc.employee)
        )

    # 2. Get cost center mapped to department
    cost_center = frappe.db.get_value(
        "Cost Center",
        {"custom_department": department},
        "name"
    )

    if not cost_center:
        frappe.throw(
            _("No Cost Center found for Department {0}").format(department)
        )

    # 3. Set parent cost center
    doc.cost_center = cost_center

    #get fiscal year
    fiscal_year = frappe.db.get_value(
        "Fiscal Year",
        {"year_start_date": ("<=", doc.posting_date), "year_end_date": (">=", doc.posting_date), "disabled":0},
        "name"
    )
    if not fiscal_year:
        frappe.throw(
            _("No active Fiscal Year found for the posting date {0}").format(doc.posting_date)
        )
    for row in doc.expenses:
        row.cost_center = doc.cost_center

        # 1. Get default account for Expense Claim Type (company-wise)
        default_account = frappe.db.get_value(
            "Expense Claim Account",
            {
                "parent": row.expense_type,
                "company": doc.company
            },
            "default_account"
        )

        if not default_account:
            frappe.throw(
                _(
                    "Row {0}: No Default Account found for Expense Claim Type "
                    "<b>{1}</b> in Company <b>{2}</b>"
                ).format(row.idx, row.expense_claim_type, doc.company)
            )

        # 2. Check Budget with company + cost center + fiscal year + account
        budget_exists = frappe.db.sql(
            """
            select b.name
            from `tabBudget` b
            join `tabBudget Account` ba on ba.parent = b.name
            where
                ba.account = %s
                and b.company = %s
                and b.cost_center = %s
                and b.fiscal_year = %s
                and b.docstatus = 1
            limit 1
            """,
            (
                default_account,
                doc.company,
                row.cost_center,
                fiscal_year,
            ),
            as_dict=True,
        )

        if not budget_exists:
            frappe.throw(
                _(
                    "Row {0}: No submitted Budget found for Account "
                    "<b>{1}</b>, Cost Center <b>{2}</b>, Fiscal Year <b>{3}</b>"
                ).format(
                    row.idx,
                    default_account,
                    row.cost_center,
                    fiscal_year,
                )
            )