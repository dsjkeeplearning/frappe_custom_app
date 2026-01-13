# File: your_app_name/your_app_name/doctype/budget/budget.py

import frappe
from frappe import _
from erpnext.accounts.doctype.budget.budget import Budget

class CustomBudget(Budget):
    def validate(self):
        super().validate()
        self.check_existing_submitted_budgets()
        self.validate_no_duplicate_accounts()
        self.validate_budget_against_allocated()
    
    def check_existing_submitted_budgets(self):
        """
        Prevent creation of new Budget if a submitted Budget
        with same Company, Fiscal Year, and Cost Center exists
        """
        if self.docstatus == 0:  # Only check for new documents
            existing_budget = frappe.db.exists({
                "doctype": "Budget",
                "company": self.company,
                "fiscal_year": self.fiscal_year,
                "cost_center": self.cost_center,
                "docstatus": 1  # Submitted budgets only
            })
            if existing_budget:
                frappe.throw(
                    _("A submitted Budget already exists for Company: {0}, Fiscal Year: {1}, Cost Center: {2}. Please edit the existing Budget.")
                    .format(frappe.bold(self.company), frappe.bold(self.fiscal_year), frappe.bold(self.cost_center)),
                    title=_("Duplicate Budget Found")
                )

    def validate_no_duplicate_accounts(self):
        """
        Ensure no account is repeated in accounts child table
        """
        seen_accounts = set()

        for row in self.accounts:
            if not row.account:
                continue

            if row.account in seen_accounts:
                frappe.throw(
                    _("Account <b>{0}</b> is repeated in Budget Accounts table. Please remove duplicates.")
                    .format(row.account),
                    title=_("Duplicate Account")
                )

            seen_accounts.add(row.account)

    def validate_budget_against_allocated(self):
        """
        Check if total of budget amounts in accounts table 
        does not exceed budget_allocated
        """
        # Only check if budget_allocated is set
        if not self.custom_budget_allocated:
            return
        
        # Calculate total of budget amounts from accounts child table
        total_budget_amount = 0
        
        for account in self.accounts:
            if account.budget_amount:
                total_budget_amount += account.budget_amount
        
        # Check if total exceeds budget_allocated
        if total_budget_amount > self.custom_budget_allocated:
            frappe.throw(
                _("Total Budget Amount ({0}) cannot be greater than Budget Allocated ({1})").format(
                    frappe.bold(frappe.format_value(total_budget_amount, {'fieldtype': 'Currency'})),
                    frappe.bold(frappe.format_value(self.custom_budget_allocated, {'fieldtype': 'Currency'}))
                ),
                title=_("Budget Validation Error")
            )


@frappe.whitelist()
def get_budget_allocated(company, cost_center, fiscal_year):
    """
    Fetch budget allocated from Master Budget
    """
    try:
        master_budget = frappe.db.get_value(
            "Master Budget",
            {
                "company": company,
                "fiscal_year": fiscal_year,
                "docstatus": ["!=", 2]
            },
            "name"
        )
        
        if not master_budget:
            return {
                "success": False,
                "message": _("No Master Budget found for {0} - {1}").format(company, fiscal_year),
                "budget": 0
            }
        
        budget_amount = frappe.db.get_value(
            "Master Budget Department",
            {
                "parent": master_budget,
                "cost_center": cost_center,
                "parenttype": "Master Budget",
                "parentfield": "department_budget"
            },
            "budget"
        )
        
        if budget_amount:
            return {
                "success": True,
                "message": _("Budget Allocated fetched from Master Budget"),
                "budget": budget_amount
            }
        else:
            return {
                "success": False,
                "message": _("Cost Center {0} not found in Master Budget").format(cost_center),
                "budget": 0
            }
    
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), _("Error fetching budget allocated"))
        return {
            "success": False,
            "message": _("Error: {0}").format(str(e)),
            "budget": 0
        }