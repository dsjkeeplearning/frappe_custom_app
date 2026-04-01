import frappe

# Mapping of company name → letter head
COMPANY_LETTER_HEAD_MAP = {
    "Centre for Developmental Education": "CDE",
    "Vijaybhoomi University": "VU",
}

def set_letter_head(doc, method):
    """
    Auto-populate letter_head based on company before save.
    Applies to: Purchase Order, Purchase Receipt, Material Request.
    """
    letter_head = COMPANY_LETTER_HEAD_MAP.get(doc.company)
    if letter_head:
        doc.letter_head = letter_head
    # If company not in map, leave letter_head untouched (no override)