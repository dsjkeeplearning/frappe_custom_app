import frappe

def update_item_cost_center(doc, method):
    """
    Copy Material Request cost center
    to all rows in items table before save
    """
    if not doc.custom_cost_center:
        return

    for item in doc.items:
        item.cost_center = doc.custom_cost_center