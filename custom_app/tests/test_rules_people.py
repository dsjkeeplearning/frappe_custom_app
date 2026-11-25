"""Business rules of attendance, leave, probation, contracts and payslips (RULES.md AT, LV, PY).

No site or database is needed, see fake_site:

	python -m unittest custom_app.tests.test_rules_people
	bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_people
"""

import io
import os
import tempfile
import unittest
import zipfile
from datetime import date
from unittest.mock import MagicMock, patch

import frappe
import openpyxl

from custom_app.api import attendance_request, employee_checkin
from custom_app.api import paysquare_payslip_import_utils as paysquare
from custom_app.custom_app.doctype.attendance_excel_generator import attendance_excel_generator as sheet
from custom_app.custom_app.page.payslip_uploader import payslip_uploader
from custom_app.overrides.attendance import Attendance, CustomAttendance
from custom_app.overrides.leave_application import CustomLeaveApplication, LeaveApplication
from custom_app.overrides.salary_slip import CustomSalarySlip
from custom_app.overrides.shift_request import CustomShiftRequest, ShiftRequest
from custom_app.tasks import employee_contract_expiry_alert, end_probation, probation_reminder
from custom_app.tests.fake_site import Doc, SiteTest
from custom_app.utils.saturday_utils import is_first_third_fifth_saturday

CDE = "Centre for Developmental Education"
VU = "Vijaybhoomi University"


class TestCheckin(SiteTest):
	def check_in(self, allowed, referer):
		self.site.add("Employee", "EMP-1", custom_allow_checkincheckout_from_mobile_app=allowed)
		frappe.local.request = Doc(headers={"Referer": referer})
		employee_checkin.before_insert_checkin(Doc(employee="EMP-1"), None)

	def test_a_check_in_needs_an_employee(self):
		self.assertRefused("Employee field is mandatory", employee_checkin.before_insert_checkin, Doc(), None)

	def test_the_hr_app_takes_check_ins_only_from_those_allowed(self):
		self.check_in(1, "https://erp.example.com/hrms/home")
		self.check_in(0, "https://erp.example.com/app/employee-checkin")
		for referer in ("https://erp.example.com/hrms/home", "https://erp.example.com/hrms/home/"):
			with self.assertRaises(frappe.PermissionError):
				self.check_in(0, referer)


class TestSaturdays(SiteTest):
	def test_first_third_and_fifth_saturdays_are_found(self):
		# October 2026 has five Saturdays, from the 3rd to the 31st.
		found = [d for d in range(1, 32) if is_first_third_fifth_saturday(f"2026-10-{d:02d}")]
		self.assertEqual(found, [3, 17, 31])

	def saved(self, company, when, status="Present"):
		doc = object.__new__(CustomAttendance)
		doc.__dict__.update(company=company, attendance_date=when, status=status)
		with patch.object(Attendance, "validate"):
			doc.validate()
		return doc.status, doc.__dict__.get("custom_weekly_off_marker")

	def test_on_those_saturdays_other_companies_are_marked_absent(self):
		self.assertEqual(self.saved("DSJ Keep Learning", "2026-10-03"), ("Absent", "Weekly Off (Auto)"))
		self.assertEqual(self.saved("DSJ Keep Learning", "2026-10-10"), ("Present", None))

	def test_the_two_teaching_companies_keep_their_saturday_attendance(self):
		for company in (CDE, VU):
			self.assertEqual(self.saved(company, "2026-10-03"), ("Present", None))


class TestAttendanceRequest(SiteTest):
	def setUp(self):
		super().setUp()
		self.shifts = {}
		self.patch(
			"custom_app.api.attendance_request._resolve_shift_for_date",
			lambda employee, day: self.shifts.get(str(day)),
		)

	def request(self, **values):
		return Doc(
			**{"employee": "EMP-1", "from_date": "2026-10-01", "to_date": "2026-10-02", **values}
		)

	def test_the_shift_comes_from_the_shift_of_each_day(self):
		self.shifts = {"2026-10-01": "Day", "2026-10-02": "Day"}
		doc = self.request(shift="Typed")
		attendance_request.set_shift(doc)
		self.assertEqual(doc.shift, "Day")

	def test_a_request_over_two_shifts_must_be_split(self):
		self.shifts = {"2026-10-01": "Day", "2026-10-02": "Night"}
		self.assertRefused("split this request", attendance_request.set_shift, self.request())

	def test_days_with_no_shift_leave_it_empty(self):
		doc = self.request(shift="Typed")
		attendance_request.set_shift(doc)
		self.assertIsNone(doc.shift)

	def test_the_shift_is_worked_out_again_at_approval(self):
		self.shifts = {"2026-10-01": "Day"}
		doc = self.request(shift="Tampered")
		attendance_request.lock_shift_before_submit(doc)
		self.assertEqual(doc.shift, "Day")

	def test_the_preview_shows_a_shift_only_when_there_is_one(self):
		self.shifts = {"2026-10-01": "Day"}
		self.assertEqual(attendance_request.get_shift_preview("EMP-1", "2026-10-01", "2026-10-02"), "Day")
		self.shifts["2026-10-02"] = "Night"
		self.assertIsNone(attendance_request.get_shift_preview("EMP-1", "2026-10-01", "2026-10-02"))

	def share(self, can_submit, before=None):
		self.site.add("Employee", "EMP-1", leave_approver="boss@example.com")
		self.site.add("Employee", "EMP-2", leave_approver="old@example.com")
		with patch("frappe.has_permission", lambda **k: can_submit):
			attendance_request.share_with_leave_approver(
				Doc("Attendance Request", name="AR-1", employee="EMP-1", before=before)
			)

	def test_the_leave_approver_gets_the_request_with_submit_rights(self):
		self.share(can_submit=False)
		doctype, name, user, rights = self.site.shares[0]
		self.assertEqual((name, user, rights["submit"]), ("AR-1", "boss@example.com", 1))

	def test_an_approver_who_can_already_act_gets_no_share(self):
		self.share(can_submit=True)
		self.assertEqual(self.site.shares, [])

	def test_a_former_approver_loses_the_request(self):
		self.share(can_submit=False, before=Doc(employee="EMP-2"))
		self.assertEqual(self.site.removed_shares, [("Attendance Request", "AR-1", "old@example.com")])


class TestOwnApproval(SiteTest):
	def save(self, controller, parent, user, status):
		self.site.add("Employee", "EMP-1", user_id="staff@example.com")
		self.log_in(user)
		doc = object.__new__(controller)
		doc.__dict__.update(employee="EMP-1", status=status)
		with patch.object(parent, "validate"):
			doc.validate()

	def test_no_one_approves_their_own_leave(self):
		args = (CustomLeaveApplication, LeaveApplication)
		self.save(*args, "staff@example.com", "Open")
		self.save(*args, "boss@example.com", "Approved")
		self.assertRefused("cannot Approve/Reject your own", self.save, *args, "staff@example.com", "Approved")

	def test_no_one_approves_their_own_shift_request(self):
		args = (CustomShiftRequest, ShiftRequest)
		self.save(*args, "staff@example.com", "Draft")
		self.save(*args, "boss@example.com", "Approved")
		self.assertRefused("cannot Approve/Reject your own", self.save, *args, "staff@example.com", "Rejected")


class TestAttendanceSheet(SiteTest):
	def test_leave_types_become_payroll_codes(self):
		codes = {
			"Casual Leave CDE/VU": "CL",
			"Sick Leave": "SL",
			"Earned Leave CDE/VU": "EL",
			"Optional Holiday": "OH",
			"Paternity Leave": "PTRL",
			"Maternity Leave": "MTRL",
			"Marriage Leave": "MRGL",
			"Leave Without Pay": "LOP",
			"Sabbatical Leave": "L",
			None: "",
		}
		self.assertEqual({leave: sheet.map_leave_code(leave) for leave in codes}, codes)

	def test_a_holiday_is_a_week_off_or_a_public_holiday(self):
		self.site.add("Employee", "EMP-1", holiday_list="2026")
		self.site.add("Holiday", "h1", parent="2026", holiday_date="2026-10-04", description="Sunday")
		self.site.add("Holiday", "h2", parent="2026", holiday_date="2026-10-02", description="Gandhi Jayanti")
		self.assertEqual(sheet.get_holiday_code("EMP-1", "2026-10-04"), "WO")
		self.assertEqual(sheet.get_holiday_code("EMP-1", "2026-10-02"), "PH")
		self.assertIsNone(sheet.get_holiday_code("EMP-1", "2026-10-05"))

	def generate(self, employees, attendance):
		for name, values in employees.items():
			self.site.add("Employee", name, **{"company": CDE, "employee_name": name, "status": "Active", **values})
		for i, values in enumerate(attendance):
			self.site.add("Attendance", f"a{i}", docstatus=1, **values)
		path = os.path.join(tempfile.mkdtemp(), "out.xlsx")
		with patch("frappe.utils.get_site_path", lambda *a: path):
			sheet.generate_excel({"company": CDE, "from_date": "2026-10-05", "to_date": "2026-10-07"})
		rows = list(openpyxl.load_workbook(path).active.iter_rows(min_row=2, values_only=True))
		return {row[0]: [value or "" for value in row[4:]] for row in rows}

	def day(self, employee, day, status, **values):
		return {"employee": employee, "attendance_date": date(2026, 10, day), "status": status, **values}

	def test_each_day_shows_its_attendance_code(self):
		self.site.add("Attendance Request", "AR-1", reason="On Duty")
		rows = self.generate(
			{"E1": {}},
			[
				self.day("E1", 5, "Present", attendance_request="AR-1"),
				self.day("E1", 6, "On Leave", leave_type="Sick Leave"),
				self.day("E1", 7, "Half Day", leave_type="Casual Leave", half_day_status="Present"),
			],
		)
		self.assertEqual(rows["E1"], ["P(OD)", "SL", "HD, HDCL"])

	def test_days_before_joining_and_after_leaving_are_blank(self):
		everyday = [self.day("E1", d, "Present") for d in (5, 6, 7)]
		rows = self.generate(
			{"E1": {"date_of_joining": "2026-10-06", "relieving_date": "2026-10-06", "status": "Left"}}, everyday
		)
		self.assertEqual(rows["E1"], ["", "P", ""])

	def test_someone_who_left_with_no_date_or_was_not_employed_is_left_out(self):
		rows = self.generate(
			{"E1": {"status": "Left"}, "E2": {"date_of_joining": "2026-11-01"}, "E3": {}}, []
		)
		self.assertEqual(list(rows), ["E3"])



class TestProbationEnd(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Leave Type", "Earned Leave CDE/VU")
		self.patch("custom_app.tasks.end_probation.nowdate", lambda: "2026-10-01")

	def employee(self, name, **values):
		self.site.add(
			"Employee",
			name,
			**{"company": CDE, "status": "Active", "custom_probation_end_date": date(2026, 10, 1), **values},
		)

	def allocated(self):
		end_probation.allocate_earned_leaves_on_probation_end()
		return {doc.employee: doc for doc in self.site.made}

	def test_earned_leave_is_given_for_the_rest_of_the_year_on_the_day_probation_ends(self):
		self.employee("EMP-1")
		self.employee("EMP-2", custom_probation_end_date=date(2026, 10, 2))
		made = self.allocated()
		self.assertEqual(list(made), ["EMP-1"])
		# 1 October to 31 March is 182 days of 365, at 18 days a year.
		self.assertEqual(made["EMP-1"].new_leaves_allocated, 8.98)
		self.assertEqual((made["EMP-1"].to_date, made["EMP-1"].docstatus), (date(2027, 3, 31), 1))

	def test_only_the_two_teaching_companies_get_it(self):
		self.employee("EMP-1", company=VU)
		self.employee("EMP-2", company="DSJ Keep Learning")
		self.assertEqual(list(self.allocated()), ["EMP-1"])

	def test_it_is_given_once(self):
		self.employee("EMP-1")
		self.site.add(
			"Leave Allocation",
			"LA-1",
			employee="EMP-1",
			from_date=date(2026, 10, 1),
			to_date=date(2027, 3, 31),
			leave_type="Earned Leave CDE/VU",
			docstatus=1,
		)
		self.assertEqual(self.allocated(), {})

	def test_the_year_for_leave_ends_on_the_next_31_march(self):
		year = end_probation.get_financial_year_for_probation
		self.assertEqual(year(date(2027, 3, 31)), (date(2026, 4, 1), date(2027, 3, 31)))
		self.assertEqual(year(date(2027, 4, 1)), (date(2027, 4, 1), date(2028, 3, 31)))



class ReminderTest(SiteTest):
	"""The probation and contract reminders are alike but for the date they watch."""

	def staff(self, date_field):
		self.site.add("Employee", "BOSS", prefered_email="boss@example.com", employee_name="Boss", status="Active")
		self.site.add(
			"Employee", "HR", designation="Head-HR", status="Active", company_email="hr@example.com", company=CDE
		)
		self.site.add("Email Account", "CDE mail", custom_company=CDE, enable_outgoing=1, email_id="cde@example.com")
		for name, when, values in (
			("NOW", date(2026, 10, 31), {}),
			("NEXT", date(2026, 11, 30), {}),
			("LATER", date(2026, 12, 1), {}),
			("GONE", date(2026, 10, 20), {"status": "Left"}),
			("OTHER", date(2026, 10, 20), {"company": "DSJ Keep Learning"}),
			("ALONE", date(2026, 10, 20), {"reports_to": None}),
		):
			self.site.add(
				"Employee",
				name,
				**{
					"employee_name": name,
					"company": CDE,
					"status": "Active",
					"reports_to": "BOSS",
					date_field: when,
					**values,
				},
			)

	def sent(self, module, send):
		self.patch(f"{module.__name__}.today", lambda: "2026-10-01")
		send()
		return {email.recipients[0]: email for email in self.site.emails}

	def check(self, module, send, date_field):
		self.staff(date_field)
		sent = self.sent(module, send)
		self.assertEqual(set(sent), {"boss@example.com", "hr@example.com"})
		self.assertEqual(sent["boss@example.com"].sender, "cde@example.com")
		listed = lambda to: {n for n in ("NOW", "NEXT", "LATER", "GONE", "OTHER", "ALONE") if f"<td>{n}</td>" in sent[to].message}  # noqa: E731
		self.assertEqual(listed("boss@example.com"), {"NOW", "NEXT"})
		self.assertEqual(listed("hr@example.com"), {"NOW", "NEXT", "ALONE"})


class TestReminders(ReminderTest):
	def test_managers_and_head_hr_hear_of_probations_ending_this_month_or_next(self):
		self.check(probation_reminder, probation_reminder.send_probation_end_alerts, "custom_probation_end_date")

	def test_managers_and_head_hr_hear_of_contracts_ending_this_month_or_next(self):
		self.check(
			employee_contract_expiry_alert,
			employee_contract_expiry_alert.send_contract_expiry_alerts,
			"custom_contract_expiry_date",
		)

	def test_no_one_is_emailed_when_nothing_ends(self):
		self.assertEqual(self.sent(probation_reminder, probation_reminder.send_probation_end_alerts), {})


class TestSalarySlipEmail(SiteTest):
	def send(self, email, posting_date="2026-10-01"):
		self.site.add("Employee", "EMP-1", prefered_email=email)
		self.patch("frappe.get_single", lambda doctype: Doc(sender_email="pay@example.com"))
		doc = object.__new__(CustomSalarySlip)
		doc.__dict__.update(
			doctype="Salary Slip",
			name="SLIP-1",
			employee="EMP-1",
			employee_name="A",
			start_date="2026-09-01",
			end_date="2026-09-30",
			posting_date=posting_date,
			letter_head="DSJKL",
		)
		with (
			patch("frappe.attach_print", MagicMock(return_value="pdf")) as attach,
			patch("custom_app.overrides.salary_slip.msgprint") as told,
		):
			doc.email_salary_slip()
		return attach, told

	def test_the_emailed_slip_carries_its_own_letter_head(self):
		attach, _told = self.send("a@example.com")
		self.assertEqual(attach.call_args.kwargs["letterhead"], "DSJKL")
		self.assertEqual(self.site.emails[0].recipients, ["a@example.com"])

	def test_without_a_preferred_email_nothing_is_sent(self):
		_attach, told = self.send(None)
		self.assertEqual(self.site.emails, [])
		self.assertIn("email not found", told.call_args.args[0])


class TestPaysquareNames(SiteTest):
	def parsed(self, name, batch):
		return paysquare.parse_filename(name, batch)

	def test_a_combined_batch_reads_the_kind_from_the_file_name(self):
		slip = self.parsed("IFIM0001_PaySlip_Jun_2026.pdf", paysquare.BATCH_COMBINED)
		tax = self.parsed("IFIM0001_TAXSHEET_JUNE_2026.PDF", paysquare.BATCH_COMBINED)
		self.assertEqual((slip["target_doctype"], slip["month"], slip["year"]), ("Paysquare Salary Slip", "Jun", 2026))
		self.assertEqual((tax["target_doctype"], tax["month"]), ("Paysquare Tax Sheet", "Jun"))

	def test_a_combined_batch_skips_a_file_that_does_not_say_its_kind(self):
		for name in ("IFIM0001_Jun_2026.pdf", "IFIM0001_Other_Jun_2026.pdf"):
			with self.assertRaises(paysquare.SkipFile):
				self.parsed(name, paysquare.BATCH_COMBINED)

	def test_a_single_kind_batch_takes_its_kind_from_the_batch(self):
		for name in ("IFIM0001_Jun_2026.pdf", "IFIM0001_PaySlip_Jun_2026.pdf"):
			self.assertEqual(
				self.parsed(name, paysquare.BATCH_TAX_SHEET_ONLY)["target_doctype"], "Paysquare Tax Sheet"
			)

	def test_an_unknown_month_is_skipped(self):
		with self.assertRaises(paysquare.SkipFile):
			self.parsed("IFIM0001_Foo_2026.pdf", paysquare.BATCH_SALARY_SLIP_ONLY)

	def test_aes_zips_are_recognised(self):
		aes = (0x9901).to_bytes(2, "little") + (2).to_bytes(2, "little") + b"AE"
		other = (0x0001).to_bytes(2, "little") + (2).to_bytes(2, "little") + b"xx"
		self.assertTrue(paysquare._is_aes_encrypted(Doc(extra=other + aes)))
		self.assertFalse(paysquare._is_aes_encrypted(Doc(extra=other)))


class TestPaysquareImport(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Employee", "IFIM0001", company=CDE)

	def zip(self, *names):
		path = os.path.join(tempfile.mkdtemp(), "batch.zip")
		with zipfile.ZipFile(path, "w") as z:
			for name in names:
				z.writestr(name, b"%PDF")
		return path

	def run_batch(self, *names):
		path = self.zip(*names)
		return paysquare.process_zip_file(path, paysquare.BATCH_SALARY_SLIP_ONLY, "secret")

	def test_each_file_is_attached_to_its_employees_record(self):
		summary = self.run_batch("IFIM0001_Jun_2026.pdf", "readme.txt")
		self.assertEqual(len(summary["created"]), 1)
		record, file = self.site.made
		self.assertEqual((record.employee, record.company, record.month, record.year), ("IFIM0001", CDE, "Jun", 2026))
		self.assertEqual((file.is_private, file.attached_to_field), (1, "salary_slip_pdf"))

	def test_files_that_cannot_be_used_are_skipped_and_logged_once(self):
		summary = self.run_batch("IFIM9999_Jun_2026.pdf", "nonsense.pdf", "IFIM0001_Jun_2026.pdf")
		self.assertEqual((len(summary["created"]), len(summary["skipped"])), (1, 2))
		self.assertEqual(len(self.site.errors), 1)

	def test_only_pdfs_are_counted(self):
		self.assertEqual(paysquare.count_pdf_entries(self.zip("a.pdf", "b.PDF", "c.txt")), 2)

	def test_a_batch_needs_a_known_kind_and_a_password(self):
		self.assertRefused("Batch Type must be one of", paysquare.process_zip_file, "x.zip", "Other", "p")
		self.assertRefused(
			"Zip Password is required", paysquare.process_zip_file, "x.zip", paysquare.BATCH_COMBINED, ""
		)


	def start(self, files, *roles):
		self.log_in("hr@example.com", *roles)
		frappe.local.flags.in_test = False
		path = self.zip(*[f"IFIM0001_Jun_20{20 + i}.pdf" for i in range(files)])
		self.site.add("File", "F-1", file_url="/private/files/b.zip", get_full_path=lambda: path)
		with (
			patch("frappe.enqueue") as queued,
			patch.object(payslip_uploader, "_set_job_status"),
			patch.object(payslip_uploader, "process_zip_file", return_value={"created": []}),
		):
			result = payslip_uploader.start_import("/private/files/b.zip", paysquare.BATCH_SALARY_SLIP_ONLY, "p")
		return result, queued.called

	def test_only_hr_and_system_managers_may_import(self):
		for role in ("HR User", "HR Manager", "System Manager"):
			self.assertTrue(self.start(1, role)[0]["sync"])
		with self.assertRaises(frappe.PermissionError):
			self.start(1, "Employee")

	def test_up_to_ten_files_run_at_once_and_more_in_the_background(self):
		self.assertEqual(self.start(10, "HR User")[1], False)
		self.assertEqual(self.start(11, "HR User")[1], True)

	def test_the_uploaded_zip_is_deleted_afterwards(self):
		self.start(1, "HR User")
		self.assertEqual(self.site.deleted, [("File", "F-1")])


if __name__ == "__main__":
	unittest.main()
