import frappe

def set_company_email_account(doc, method):
    """
    Set outgoing Email Account based on linked document's company before Communication is created.
    """
    try:
        # Only apply for outgoing emails
        if doc.sent_or_received != "Sent":
            return

        company = None

        # Check if Communication is linked to a document with company
        if doc.reference_doctype and doc.reference_name:
            ref_doc = frappe.get_doc(doc.reference_doctype, doc.reference_name)
            if hasattr(ref_doc, "company"):
                company = ref_doc.company

        # Fallback: try to get company from current user
        if not company and frappe.session.user not in ["Administrator", "Guest"]:
            company = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "company")

        if not company:
            return  # No company found, skip custom logic

        # Get Email Account for this company
        email_account_name = frappe.db.get_value("Email Account", {"custom_company": company}, "name")
        if not email_account_name:
            frappe.logger().warning(f"No Email Account found for company {company}")
            return

        # Assign this account to Communication
        doc.email_account = email_account_name

        # Optionally override the sender
        sender = frappe.db.get_value("Email Account", email_account_name, "email_id")
        if sender:
            doc.sender = sender

        frappe.logger().info(f"📧 Using {email_account_name} for {company} Communication")

    except Exception as e:
        frappe.log_error(f"Company-based Communication email routing failed: {e}")
