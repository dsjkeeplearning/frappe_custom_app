import frappe
from frappe.model.document import Document
from frappe.utils.file_manager import get_file_path
from frappe import _
import pandas as pd
import math


class BudgetUpload(Document):

    def on_submit(self):
        """Automatically create monthly distributions and budgets on submit"""
        result = self.create_monthly_distributions()
        if result and result.get('status') == 'success':
            frappe.msgprint(
                _('{0}<br><br>{1}').format(
                    result.get('message'),
                    result.get('details', '')
                ),
                indicator='green',
                title=_('Budgets Created Successfully')
            )
    
    @frappe.whitelist()
    def get_excel_preview(self):
        if not self.budget_file:
            return

        file_path = get_file_path(self.budget_file)

        try:
            df = pd.read_excel(file_path, header=None)
        except Exception:
            return {
                "error": "Unable to read Excel file. Please upload a valid .xlsx file"
            }

        if df.empty or df.shape[1] < 2:
            return {
                "error": "Invalid budget format. File must contain months and values."
            }

        months = df.iloc[0, 1:].tolist()
        data_rows = df.iloc[1:]

        formatted_rows = []
        error_cells = []

        for excel_row_no, row in enumerate(data_rows.itertuples(index=False), start=2):
            account = row[0]
            if pd.isna(account):
                continue

            row_data = {"Account": account}

            for col_idx, month in enumerate(months, start=2):
                value = row[col_idx - 1]

                if pd.isna(value):
                    row_data[str(month)] = 0
                    continue

                if isinstance(value, (int, float)) and not math.isnan(value):
                    row_data[str(month)] = value
                else:
                    row_data[str(month)] = (
                        "<span style='color:red;font-weight:bold'>ERROR</span>"
                    )
                    error_cells.append(
                        f"Row {excel_row_no}, Column {col_idx} ({month}) "
                        f"for Account '{account}' → '{value}'"
                    )

            formatted_rows.append(row_data)

        result_df = pd.DataFrame(formatted_rows)
        html = result_df.to_html(
            index=False,
            escape=False,  # IMPORTANT: allow ERROR span
            classes="table table-bordered table-hover table-sm",
            border=0
        )

        return {
            "html": html,
            "has_error": bool(error_cells),
            "errors": error_cells
        }

    @frappe.whitelist()
    def create_monthly_distributions(self):
        """
        Process the uploaded Excel file and create Monthly Distributions and Budgets for each account
        """
        if not self.budget_file:
            frappe.throw(_('Please upload a budget file first'))

        if not self.cost_center:
            frappe.throw(_('Please select Cost Center'))

        if not self.fiscal_year:
            frappe.throw(_('Please select Fiscal Year'))

        # Get file path
        file_path = get_file_path(self.budget_file)

        # Load Excel using pandas
        try:
            df = pd.read_excel(file_path, header=None)
        except Exception as e:
            frappe.throw(_('Unable to read Excel file: {0}').format(str(e)))

        if df.empty or df.shape[1] < 13:
            frappe.throw(_('Invalid budget format. File must contain 12 months of data.'))

        # Check Master Budget
        master_budget_limit = self.get_master_budget_limit()
        if master_budget_limit is None:
            frappe.throw(_(
                'No Budget found for Cost Center "{2}" for Company "{0}", Fiscal Year "{1}".'
            ).format(self.company, self.fiscal_year, self.cost_center))
        
        # check for already allocated budget
        allocated_budget = self.get_allocated_budget()

        # Standard month names
        month_names = ['April', 'May', 'June', 'July', 'August', 'September',
                       'October', 'November', 'December', 'January', 'February', 'March']

        created_distributions = []
        created_budgets = []
        skipped_distributions = []
        skipped_budgets = []
        invalid_accounts = []
        budget_exceeded = []

        # Calculate total budget from Excel file first
        total_new_budget = 0
        data_rows = df.iloc[1:]
        
        for row_idx, row in enumerate(data_rows.itertuples(index=False), start=2):
            account_name = row[0]
            if pd.isna(account_name):
                continue
            
            # Collect monthly values
            row_total = 0
            for col_idx in range(1, 13):
                cell_value = row[col_idx]
                try:
                    if pd.isna(cell_value):
                        value = 0
                    else:
                        value = float(cell_value)
                    row_total += value
                except (ValueError, TypeError):
                    continue
            
            total_new_budget += row_total

        # Check if adding new budgets will exceed master budget
        if master_budget_limit is not None:
            if allocated_budget + total_new_budget > master_budget_limit:
                frappe.throw(_(
                    'Budget Limit Exceeded!<br><br>'
                    '<b>Master Budget Limit:</b> {0:,.2f}<br>'
                    '<b>Already Allocated:</b> {1:,.2f}<br>'
                    '<b>New Budget Total:</b> {2:,.2f}<br>'
                    '<b>Total After Upload:</b> {3:,.2f}<br>'
                    '<b>Excess Amount:</b> {4:,.2f}<br><br>'
                    'Please reduce the budget amounts or update the Master Budget.'
                ).format(
                    master_budget_limit,
                    allocated_budget,
                    total_new_budget,
                    allocated_budget + total_new_budget,
                    (allocated_budget + total_new_budget) - master_budget_limit
                ))

        # Process each row starting from row 2 (index 1)

        for row_idx, row in enumerate(data_rows.itertuples(index=False), start=2):
            account_name = row[0]

            # Skip if no account name
            if pd.isna(account_name):
                continue

            # Validate if account exists
            if not frappe.db.exists('Account', account_name):
                invalid_accounts.append(f"Row {row_idx}: {account_name}")
                continue

            # Collect monthly values (columns 1 to 12, indices 1 to 12 in row)
            monthly_values = []
            total_budget = 0

            for col_idx in range(1, 13):
                cell_value = row[col_idx]
                
                try:
                    if pd.isna(cell_value):
                        value = 0
                    else:
                        value = float(cell_value)
                    
                    monthly_values.append(value)
                    total_budget += value
                except (ValueError, TypeError):
                    frappe.throw(_(f'Invalid value at Row {row_idx}, Column {col_idx + 1}: {cell_value}'))

            # Skip if total budget is 0
            if total_budget == 0:
                continue

            # Create Monthly Distribution
            distribution_id = f"{self.fiscal_year} - {self.cost_center} - {account_name}"
            distribution_id = distribution_id[:140]  # Limit to 140 chars

            distribution_exists = frappe.db.exists('Monthly Distribution', distribution_id)
            
            # Check if budget already exists for this combination
            existing_budget = frappe.db.exists('Budget', {
                'cost_center': self.cost_center,
                'fiscal_year': self.fiscal_year,
                'docstatus': ['<', 2]  # Draft or Submitted
            })
            
            # If both exist, check if this specific account exists in any budget
            budget_exists_for_account = False
            if existing_budget:
                budget_accounts = frappe.db.sql("""
                    SELECT parent 
                    FROM `tabBudget Account` 
                    WHERE parent IN (
                        SELECT name FROM `tabBudget` 
                        WHERE cost_center = %s 
                        AND fiscal_year = %s 
                        AND docstatus < 2
                    ) 
                    AND account = %s
                    LIMIT 1
                """, (self.cost_center, self.fiscal_year, account_name), as_dict=True)
                
                if budget_accounts:
                    budget_exists_for_account = True
                    skipped_budgets.append(f"{account_name} (Budget: {budget_accounts[0].parent})")

            # Skip if distribution exists AND budget exists for this account
            if distribution_exists and budget_exists_for_account:
                skipped_distributions.append(distribution_id)
                continue

            # Create Monthly Distribution if it doesn't exist
            if not distribution_exists:
                distribution = frappe.new_doc('Monthly Distribution')
                distribution.distribution_id = distribution_id
                distribution.fiscal_year = self.fiscal_year
                
                # Add percentage for each month
                for month_name, value in zip(month_names, monthly_values):
                    percentage = (value / total_budget * 100) if total_budget > 0 else 0
                    distribution.append('percentages', {
                        'month': month_name,
                        'percentage_allocation': percentage
                    })

                distribution.insert()
                created_distributions.append(distribution_id)

            # Create Budget for this account if it doesn't exist
            if not budget_exists_for_account:
                budget = frappe.new_doc('Budget')
                budget.budget_against = "Cost Center"
                budget.company = self.company
                budget.monthly_distribution = distribution_id
                budget.cost_center = self.cost_center
                budget.fiscal_year = self.fiscal_year
                
                # Budget control settings
                budget.applicable_on_material_request = 1
                budget.action_if_annual_budget_exceeded_on_mr = "Stop"
                budget.action_if_accumulated_monthly_budget_exceeded_on_mr = "Warn"
                budget.applicable_on_purchase_order = 1
                budget.action_if_annual_budget_exceeded_on_po = "Stop"
                budget.action_if_accumulated_monthly_budget_exceeded_on_po = "Warn"
                budget.applicable_on_booking_actual_expenses = 1
                budget.action_if_annual_budget_exceeded = "Stop"
                budget.action_if_accumulated_monthly_budget_exceeded = "Warn"
                
                # Add account
                budget.append('accounts', {
                    'account': account_name,
                    'budget_amount': total_budget
                })
                
                budget.insert()
                budget.submit()
                created_budgets.append(budget.name)

        frappe.db.commit()

        # Build detailed message
        details = f"<b>Monthly Distributions Created:</b> {len(created_distributions)}<br>"
        details += f"<b>Budgets Created:</b> {len(created_budgets)}<br>"
        
        if invalid_accounts:
            details += f"<br><b style='color:red'>Invalid Accounts (Not Found in Chart of Accounts):</b> {len(invalid_accounts)}<br>"
            details += "<ul style='margin:5px 0;padding-left:20px;'>"
            for acc in invalid_accounts[:15]:  # Show first 15
                details += f"<li style='font-size:11px;color:red;'>{acc}</li>"
            if len(invalid_accounts) > 15:
                details += f"<li style='font-size:11px;'><i>...and {len(invalid_accounts) - 15} more</i></li>"
            details += "</ul>"
        
        if skipped_distributions:
            details += f"<br><b style='color:orange'>Skipped Distributions (Already Exists):</b> {len(skipped_distributions)}<br>"
            details += "<ul style='margin:5px 0;padding-left:20px;'>"
            for dist in skipped_distributions[:10]:  # Show first 10
                details += f"<li style='font-size:11px;'>{dist}</li>"
            if len(skipped_distributions) > 10:
                details += f"<li style='font-size:11px;'><i>...and {len(skipped_distributions) - 10} more</i></li>"
            details += "</ul>"
        
        if skipped_budgets:
            details += f"<br><b style='color:orange'>Skipped Budgets (Already Exists):</b> {len(skipped_budgets)}<br>"
            details += "<ul style='margin:5px 0;padding-left:20px;'>"
            for budget in skipped_budgets[:10]:  # Show first 10
                details += f"<li style='font-size:11px;'>{budget}</li>"
            if len(skipped_budgets) > 10:
                details += f"<li style='font-size:11px;'><i>...and {len(skipped_budgets) - 10} more</i></li>"
            details += "</ul>"

        return {
            'status': 'success',
            'message': f'Successfully created {len(created_distributions)} Monthly Distributions and {len(created_budgets)} Budgets',
            'details': details,
            'distributions': created_distributions,
            'budgets': created_budgets,
            'skipped_distributions': skipped_distributions,
            'skipped_budgets': skipped_budgets,
            'invalid_accounts': invalid_accounts
        }
    
    def get_master_budget_limit(self):
        master_budget = frappe.get_doc('Master Budget', {
            'company': self.company,
            "fiscal_year": self.fiscal_year,
            "docstatus": 1  # Submitted
        })
        for row in master_budget.department_budget:
            if row.cost_center == self.cost_center:
                return row.budget
        return None
    
    def get_allocated_budget(self):
        total_allocated = 0
        budgets = frappe.get_all('Budget',
            filters={
                'company': self.company,
                'cost_center': self.cost_center,
                'fiscal_year': self.fiscal_year,
                'docstatus': 1
            },
            fields=['name']
        )
    
        for budget in budgets:
            budget_doc = frappe.get_doc('Budget', budget.name)
            for row in budget_doc.accounts:
                total_allocated += row.budget_amount
        
        return total_allocated