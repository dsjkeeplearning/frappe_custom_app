import frappe
from frappe import _

def update_item_cost_center(doc, method):
    """
    Copy Expense Claim cost center
    to all rows in items table before save
    """
    if not doc.cost_center:
        return
    
    for expense in doc.expenses:
        expense.cost_center = doc.cost_center