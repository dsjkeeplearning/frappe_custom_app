import frappe
from frappe import _, msgprint
from frappe.utils import getdate
from frappe.utils.background_jobs import enqueue
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip, generate_password_for_pdf


class CustomSalarySlip(SalarySlip):
    def email_salary_slip(self):
        """
        Same as stock HRMS's email_salary_slip(), except the PDF attachment
        is generated with this document's own `letter_head` explicitly.

        Stock HRMS calls frappe.attach_print() without a `letterhead` arg.
        When that's omitted, frappe.attach_print() (frappe/__init__.py)
        substitutes the site-wide *default* Letter Head record for every
        emailed slip, ignoring self.letter_head entirely - so a DSJKL
        employee's auto-emailed slip could show another company's (e.g.
        CDE's) letterhead if that one happens to be flagged default,
        even though the slip's own letter_head field is correctly DSJKL.
        Manual/portal PDF downloads go through a different code path
        (frappe/www/printview.py) that falls back to doc.letter_head when
        no explicit letterhead is given, which is why those already show
        the correct letterhead - only this emailed-attachment path was wrong.
        """
        receiver = frappe.db.get_value("Employee", self.employee, "prefered_email", cache=True)
        payroll_settings = frappe.get_single("Payroll Settings")

        subject = f"Salary Slip - from {self.start_date} to {self.end_date}"
        message = _("Please see attachment")
        if payroll_settings.email_template:
            email_template = frappe.get_doc("Email Template", payroll_settings.email_template)
            context = self.as_dict()
            subject = frappe.render_template(email_template.subject, context)
            message = frappe.render_template(email_template.response, context)

        password = None
        if payroll_settings.encrypt_salary_slips_in_emails:
            password = generate_password_for_pdf(payroll_settings.password_policy, self.employee)
            if not payroll_settings.email_template:
                message += "<br>" + _(
                    "Note: Your salary slip is password protected, the password to unlock the PDF is of the format {0}."
                ).format(payroll_settings.password_policy)

        if receiver:
            posting_date = getdate(self.posting_date)
            email_args = {
                "sender": payroll_settings.sender_email,
                "recipients": [receiver],
                "message": message,
                "subject": subject,
                "attachments": [
                    frappe.attach_print(
                        self.doctype,
                        self.name,
                        file_name=self.name,
                        password=password,
                        letterhead=self.letter_head,
                    )
                ],
                "reference_doctype": self.doctype,
                "reference_name": self.name,
                "send_after": posting_date if posting_date > getdate() else None,
            }
            if not frappe.flags.in_test:
                enqueue(method=frappe.sendmail, queue="short", timeout=300, is_async=True, **email_args)
            else:
                frappe.sendmail(**email_args)
        else:
            msgprint(_("{0}: Employee email not found, hence email not sent").format(self.employee_name))
