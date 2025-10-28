import frappe
from frappe import _

def before_insert_checkin(doc, method):
    try:
        # Get employee
        if not doc.employee:
            frappe.throw(_("Employee field is mandatory."))

        employee = frappe.get_doc("Employee", doc.employee)

        # Get request info
        request = getattr(frappe.local, "request", None)
        headers = dict(request.headers) if request else {}
        referer = headers.get("Referer", "")
        
        # Validation Logic
        if not employee.custom_allow_checkincheckout_from_mobile_app:
            # If referer ends with hrms/home → block
            if referer and referer.rstrip("/").endswith("hrms/home"):
                frappe.throw(
                    _("You are not allowed to Check-in or Check-out from HRMS web portal/mobile app."),
                    frappe.PermissionError
                )

    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.logger().error(f"❌ Error in before_insert_checkin: {e}")
        raise