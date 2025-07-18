from frappe.utils import getdate

def is_first_third_fifth_saturday(date_str):
    date_obj = getdate(date_str)
    if date_obj.weekday() != 5:  # Not Saturday
        return False

    count = 0
    for d in range(1, date_obj.day + 1):
        if getdate(f"{date_obj.year}-{date_obj.month}-{d}").weekday() == 5:
            count += 1

    return count in [1, 3, 5]
from frappe.utils import getdate

def is_first_third_fifth_saturday(date_str):
    date_obj = getdate(date_str)
    if date_obj.weekday() != 5:  # Not Saturday
        return False

    count = 0
    for d in range(1, date_obj.day + 1):
        if getdate(f"{date_obj.year}-{date_obj.month}-{d}").weekday() == 5:
            count += 1

    return count in [1, 3, 5]

