import frappe
from datetime import datetime

def set_vendor_code(doc, method):
    mapping = {
        "DSJ Keep Learning": "DSJ",
        "Centre for Developmental Education": "CDE",
        "Vijaybhoomi University": "VU"
    }

    abbr = mapping.get(doc.custom_company, "GEN")
    year = datetime.now().year

    prefix = f"{abbr}-{year}-"

    # 🔍 Get last vendor code
    last = frappe.db.sql("""
        SELECT custom_vendor_code
        FROM `tabSupplier`
        WHERE custom_vendor_code LIKE %s
        ORDER BY creation DESC
        LIMIT 1
    """, (f"{prefix}%",), as_dict=True)

    if last and last[0].custom_vendor_code:
        last_code = last[0].custom_vendor_code

        try:
            last_number = int(last_code.split("-")[-1])
        except:
            last_number = 0
    else:
        last_number = 0

    new_number = last_number + 1

    doc.custom_vendor_code = f"{prefix}{str(new_number).zfill(4)}"