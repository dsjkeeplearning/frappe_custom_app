import frappe
from frappe.utils import get_first_day, get_last_day, add_months, today, formatdate

def send_contract_expiry_alerts():
    # Date range: this month + next month
    start_date = get_first_day(today())
    end_date = get_last_day(add_months(today(), 1))

    # Company filter
    company_filter = ["Vijaybhoomi University", "Centre for Developmental Education"]

    # Fetch employees whose contract expires in this or next month
    employees = frappe.get_all(
        "Employee",
        filters={
            "custom_contract_expiry_date": ["between", [start_date, end_date]],
            "company": ["in", company_filter],
            "status": "Active"
        },
        fields=["name", "employee_name", "custom_contract_expiry_date", "reports_to", "company"]
    )

    if not employees:
        return

    # Group employees by reporting manager
    manager_dict = {}
    for emp in employees:
        if emp.reports_to:
            manager_dict.setdefault(emp.reports_to, []).append(emp)

    # 1️⃣ Send mail to each manager
    for manager_id, emp_list in manager_dict.items():
        manager = frappe.get_doc("Employee", manager_id)
        manager_email = manager.prefered_email or manager.company_email
        manager_name = manager.employee_name or "Manager"

        if not manager_email:
            continue

        emp_list.sort(key=lambda x: x.custom_contract_expiry_date)
        emp_table = "".join([
            f"<tr><td>{e.employee_name}</td><td>{e.name}</td><td>{e.company}</td><td>{formatdate(e.custom_contract_expiry_date)}</td></tr>"
            for e in emp_list
        ])

        message = f"""
            <p>Dear {manager_name},</p>
            <p>The following employees under your supervision have contracts expiring soon:</p>
            <table border="1" cellpadding="5" cellspacing="0">
                <tr>
                    <th>Employee Name</th>
                    <th>Employee ID</th>
                    <th>Company</th>
                    <th>Contract Expiry Date</th>
                </tr>
                {emp_table}
            </table>
            <p>Regards,</p>
        """

        # Get sender dynamically based on employee company
        email_account_name = frappe.db.get_value(
            "Email Account",
            {"custom_company": emp_list[0].company, "enable_outgoing": 1},
            "name"
        )
        sender_email = frappe.db.get_value("Email Account", email_account_name, "email_id") if email_account_name else None

        frappe.sendmail(
            recipients=[manager_email],
            sender=sender_email,
            subject="Employee Contract Expiry Alert",
            message=message
        )

    # 2️⃣ Send consolidated mail to Head-HR
    head_hr_list = frappe.get_all(
        "Employee",
        filters={"designation": "Head-HR", "status": "Active"},
        fields=["name", "employee_name", "prefered_email", "company", "company_email"]
    )

    for hr in head_hr_list:
        hr_email = hr.prefered_email or hr.company_email
        if not hr_email:
            continue

        emp_table = "".join([
            f"<tr><td>{e.employee_name}</td><td>{e.name}</td><td>{e.company}</td><td>{formatdate(e.custom_contract_expiry_date)}</td></tr>"
            for e in employees
        ])

        message = f"""
            <p>Dear {hr.employee_name},</p>
            <p>The following employees have contracts expiring this or next month:</p>
            <table border="1" cellpadding="5" cellspacing="0">
                <tr>
                    <th>Employee Name</th>
                    <th>Employee ID</th>
                    <th>Company</th>
                    <th>Contract Expiry Date</th>
                </tr>
                {emp_table}
            </table>
            <p>Regards,</p>
        """

        # Use sender email dynamically based on Head-HR's company
        email_account_name = frappe.db.get_value(
            "Email Account",
            {"custom_company": hr.company, "enable_outgoing": 1},
            "name"
        )
        sender_email = frappe.db.get_value("Email Account", email_account_name, "email_id") if email_account_name else None

        frappe.sendmail(
            recipients=[hr_email],
            sender=sender_email,
            subject="Employee Contract Expiry Summary",
            message=message
        )
