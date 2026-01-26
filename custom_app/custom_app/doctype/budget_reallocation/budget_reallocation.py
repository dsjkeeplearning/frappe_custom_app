from datetime import timedelta
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, add_months, add_days
import calendar
from datetime import date


class BudgetReallocation(Document):
    
    def validate(self):
        """Calculate current budget and validate changes"""
        self.calculate_current_budget()
        self.calculate_differences()
        self.validate_budget_limit()
        self.validate_material_requests()
    
    def validate_material_requests(self):
        if self.new_budget < self.current_budget:
        
            # get start and end date of the month
            start_date, end_date = self.get_month_start_end(self.fiscal_year, self.month)
            total_budget_till_month = self.get_total_budget_till_month()
            mrs = frappe.get_all('Material Request', filters={
                'custom_cost_center': self.cost_center,
                'company': self.company,
                'transaction_date': ['between', [start_date, end_date]],
                'docstatus': 1,
            }, fields=['name'])

            if not mrs:
                return

            total_mr_amount = 0
            for mr in mrs:
                mris = frappe.get_all('Material Request Item', filters={
                    'parent': mr.name,
                    'expense_account': self.account,
                    'cost_center': self.cost_center,
                }, fields=['amount'])
                for mri in mris:
                    total_mr_amount += mri.amount

            if total_mr_amount > total_budget_till_month + self.new_budget - self.current_budget:
                frappe.throw(_(
                    'Cannot reduce budget to {0:,.2f} as there are Material Requests '
                    'totaling {1:,.2f} for Account "{2}" in Cost Center "{3}" '
                    'till {4} {5}. Please adjust the budget accordingly.'
                ).format(
                    self.new_budget,
                    total_mr_amount,
                    self.account,
                    self.cost_center,
                    self.month,
                    self.fiscal_year
                ))

    def get_total_budget_till_month(self):
        # fetch budget till the selected month
        budgets = frappe.get_all('Budget', filters={
            'cost_center': self.cost_center,
            'company': self.company,
            'fiscal_year': self.fiscal_year,
            'docstatus': 1
        }, fields=['name', 'monthly_distribution'])
        if not budgets:
            return 0
        for budget in budgets:
            amount = frappe.db.get_value('Budget Account', filters={
                'parent': budget.name,
                'account': self.account
            }, fieldname=['budget_amount'])
            if amount:
                total_budget = 0
                monthly_distribution = frappe.get_doc('Monthly Distribution', budget.monthly_distribution)
                for row in monthly_distribution.percentages:
                    # from april to selected month
                    month_index = list(calendar.month_name).index(row.month)
                    selected_month_index = list(calendar.month_name).index(self.month)
                    if selected_month_index < 4:
                        selected_month_index += 12
                    if month_index < 4:
                        month_index += 12
                    if month_index <= selected_month_index and month_index != 0:
                        total_budget += (amount * row.percentage_allocation) / 100
                return total_budget
        return 0

    def get_month_start_end(self,fiscal_year, month_name):
        """
        Returns start_date and end_date of a given month in a fiscal year
        """

        # Fetch fiscal year dates
        fy = frappe.get_doc("Fiscal Year", fiscal_year)
        fy_start = getdate(fy.year_start_date)
        fy_end = getdate(fy.year_end_date)

        # Month name to month number
        month_number = list(calendar.month_name).index(month_name)

        # Determine correct year for the month
        year = fy_start.year
        if month_number < fy_start.month:
            year += 1

        # Month start & end
        start_date = date(year, month_number, 1)
        last_day = calendar.monthrange(year, month_number)[1]
        end_date = date(year, month_number, last_day)

        # Safety check (month must lie within fiscal year)
        if start_date < fy_start or end_date > fy_end:
            frappe.throw(f"{month_name} is outside Fiscal Year {fiscal_year}")

        return fy_start, end_date

    def on_submit(self):
        """Reallocate budget by updating Monthly Distribution and Budget"""
        self.reallocate_budget()
    
    @frappe.whitelist()
    def get_current_month_budget(self):
        """Get current month's budget - called from client side"""
        self.calculate_current_budget()
        
        return {
            'current_budget': self.current_budget,
            'total_annual_budget': self.total_annual_budget,
            'master_budget_limit': self.master_budget_limit,
            'total_allocated_budget': self.total_allocated_budget
        }
    
    def calculate_current_budget(self):
        """Get current month's budget based on Monthly Distribution"""
        # Find the Monthly Distribution
        distribution_id = f"{self.fiscal_year} - {self.cost_center} - {self.account}"
        
        if not frappe.db.exists('Monthly Distribution', distribution_id):
            frappe.throw(_(
                'Monthly Distribution not found for this combination. '
                'Please create a budget first using Budget Upload.'
            ))
        
        # Get the distribution
        distribution = frappe.get_doc('Monthly Distribution', distribution_id)
        
        # Get total annual budget for this account
        budget = self.get_budget_doc()
        
        if not budget:
            frappe.throw(_(
                'No Budget found for Account "{0}", Cost Center "{1}", Fiscal Year "{2}"'
            ).format(self.account, self.cost_center, self.fiscal_year))
        
        # Find the budget amount for this account
        annual_budget = 0
        for acc in budget.accounts:
            if acc.account == self.account:
                annual_budget = acc.budget_amount
                break
        
        # Calculate current month's budget based on percentage
        month_percentage = 0
        for row in distribution.percentages:
            if row.month == self.month:
                month_percentage = row.percentage_allocation
                break
        
        self.current_budget = (annual_budget * month_percentage) / 100
        self.total_annual_budget = annual_budget
        
        # Get master budget limit
        self.master_budget_limit = self.get_master_budget_limit()
        self.total_allocated_budget = self.get_total_allocated_budget()
    
    def calculate_differences(self):
        """Calculate difference and new totals"""
        if not self.new_budget:
            return
        
        self.difference = self.new_budget - self.current_budget
        
        if self.current_budget:
            self.percentage_change = (self.difference / self.current_budget) * 100
        
        # Calculate new annual total
        # New annual = Old annual - old month + new month
        self.new_total_annual_budget = self.total_annual_budget - self.current_budget + self.new_budget
    
    def validate_budget_limit(self):
        """Validate if budget increase is within master budget limit"""
        if not self.new_budget or not self.difference:
            return
        
        # If budget is decreasing, no validation needed
        if self.difference <= 0:
            return
        
        # If budget is increasing, check master budget limit
        if self.master_budget_limit:
            # Calculate new total allocated (excluding current account's old budget)
            other_accounts_budget = self.total_allocated_budget - self.total_annual_budget
            new_total_allocated = other_accounts_budget + self.new_total_annual_budget
            
            if new_total_allocated > self.master_budget_limit:
                frappe.throw(_(
                    'Budget Limit Exceeded!<br><br>'
                    '<b>Master Budget Limit:</b> {0:,.2f}<br>'
                    '<b>Current Total Allocated:</b> {1:,.2f}<br>'
                    '<b>Budget Increase:</b> {2:,.2f}<br>'
                    '<b>New Total Allocated:</b> {3:,.2f}<br>'
                    '<b>Excess Amount:</b> {4:,.2f}<br><br>'
                    'Please reduce the budget amount or update the Master Budget.'
                ).format(
                    self.master_budget_limit,
                    self.total_allocated_budget,
                    self.difference,
                    new_total_allocated,
                    new_total_allocated - self.master_budget_limit
                ))
    
    def reallocate_budget(self):
        """
        Reallocate budget by:
        1. Updating Monthly Distribution percentages
        2. Cancelling and amending the Budget
        """
        # Get distribution and budget
        distribution_id = f"{self.fiscal_year} - {self.cost_center} - {self.account}"
        distribution = frappe.get_doc('Monthly Distribution', distribution_id)
        budget = self.get_budget_doc()
        
        # Update Monthly Distribution
        self.update_monthly_distribution(distribution)
        
        # Cancel and amend Budget
        self.cancel_and_amend_budget(budget)
        
        frappe.msgprint(_(
            'Budget reallocated successfully!<br><br>'
            '<b>Account:</b> {0}<br>'
            '<b>Month:</b> {1}<br>'
            '<b>Old Budget:</b> {2:,.2f}<br>'
            '<b>New Budget:</b> {3:,.2f}<br>'
            '<b>Difference:</b> {4:,.2f}<br><br>'
            '<b>New Annual Total:</b> {5:,.2f}'
        ).format(
            self.account,
            self.month,
            self.current_budget,
            self.new_budget,
            self.difference,
            self.new_total_annual_budget
        ), indicator='green', title=_('Budget Reallocation Successful'))
    
    def update_monthly_distribution(self, distribution):
        """Update the Monthly Distribution with new percentages"""
        # Calculate new percentages based on new monthly budget
        new_annual_total = self.new_total_annual_budget
        
        # Update percentages for all months
        for row in distribution.percentages:
            if row.month == self.month:
                # Update the selected month's percentage
                row.percentage_allocation = (self.new_budget / new_annual_total * 100) if new_annual_total else 0
            else:
                # Recalculate other months based on new total
                month_budget = (self.total_annual_budget * row.percentage_allocation) / 100
                row.percentage_allocation = (month_budget / new_annual_total * 100) if new_annual_total else 0
        
        distribution.save()
        frappe.db.commit()
    
    def cancel_and_amend_budget(self, budget):
        """Cancel the current budget and create an amended version"""
        # Store the old name
        old_budget_name = budget.name

        # 🔥 IMPORTANT: Ignore link validations
        budget.flags.ignore_links = True
        budget.flags.ignore_validate = True
        budget.flags.ignore_mandatory = True
        
        # Cancel the budget
        budget.cancel()
        
        # Create amended budget
        new_budget = frappe.copy_doc(budget)
        new_budget.docstatus = 0
        new_budget.amended_from = old_budget_name
        
        # Update the budget amount for the specific account
        for acc in new_budget.accounts:
            if acc.account == self.account:
                acc.budget_amount = self.new_total_annual_budget
        
        new_budget.insert()
        new_budget.submit()
        # add old budget , new budget , approver name, date time in budget reallocation doctype
        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "old_budget_link": old_budget_name,
                "new_budget_link": new_budget.name,
                "approver": frappe.session.user,
                "approval_date": frappe.utils.now_datetime(),
            }
        )
        frappe.db.commit()
    
    def get_budget_doc(self):
        """Get the Budget document for this account"""
        budgets = frappe.get_all('Budget', filters={
            'cost_center': self.cost_center,
            'fiscal_year': self.fiscal_year,
            'docstatus': 1
        }, fields=['name'])
        
        # Find the budget that contains this account
        for budget_name in budgets:
            budget = frappe.get_doc('Budget', budget_name['name'])
            for acc in budget.accounts:
                if acc.account == self.account:
                    return budget
        
        return None
    
    def get_master_budget_limit(self):
        """Get master budget limit for the cost center"""
        try:
            master_budget = frappe.get_doc('Master Budget', {
                'company': self.company,
                'fiscal_year': self.fiscal_year,
                'docstatus': 1
            })
            
            for row in master_budget.department_budget:
                if row.cost_center == self.cost_center:
                    return row.budget
        except:
            pass
        
        return None
    
    def get_total_allocated_budget(self):
        """Get total allocated budget for all accounts in this cost center"""
        total_allocated = 0
        
        budgets = frappe.get_all('Budget', filters={
            'company': self.company,
            'cost_center': self.cost_center,
            'fiscal_year': self.fiscal_year,
            'docstatus': 1
        }, fields=['name'])
        
        for budget_name in budgets:
            budget = frappe.get_doc('Budget', budget_name['name'])
            for acc in budget.accounts:
                total_allocated += acc.budget_amount
        
        return total_allocated