# Copyright (c) 2026, . and contributors
# License: MIT
"""
Core engine for importing Paysquare's monthly zip (salary slips + tax
sheets) into ERPNext. Kept independent of *how* the zip arrives (manual
upload today, SFTP/IMAP auto-fetch later) AND independent of *where it
runs* (foreground call or background job) -- process_zip_file() takes an
optional progress_callback so a caller (e.g. a background job) can report
"processed X of Y" without this module knowing anything about jobs,
caches, or the UI.

IMPORTANT: the zip container itself is NOT password protected -- you can
list its contents freely. Each PDF *entry* inside it is individually
encrypted (standard zip encryption). Rather than trying to compute that
password, the user types it in on the uploader page (e.g. "ifim0626")
and the same password is tried against every entry in the batch -- this
matches how Paysquare actually sends things: one company, one month,
one password per batch.

Once extracted, PDFs are attached to their record exactly as they came
out of the zip -- no PDF-internal unlocking is performed (attaching a
file doesn't require decrypting it).

The `batch_type` the user selects (see BATCH_TYPES) decides whether the
filename needs a keyword to distinguish salary slip vs. tax sheet, or
whether every file in the batch is forced into a single doctype:

    Combined (Salary Slip + Tax Sheet):
        IFIM0713_PaySlip_Jun_2026.pdf
        IFIM0713_TAXSHEET_JUN_2026.pdf
        {EMPLOYEE_CODE}_{PaySlip|TaxSheet}_{Mon}_{YYYY}.pdf   (case-insensitive)
        -- the keyword is REQUIRED here, since it's the only way to tell
        the two document types apart within the same batch.

    Salary Slip Only / Tax Sheet Only:
        IFIM0713_Jun_2026.pdf
        {EMPLOYEE_CODE}_{Mon}_{YYYY}.pdf
        -- no keyword needed; every file in the batch is the selected
        type. A keyword in the filename is tolerated but ignored.

Unmatched employee codes, unparsable filenames, and entries that can't
be extracted with the given password are skipped. Skipped files and
unexpected per-file errors are NOT logged individually -- they're
collected during the run and written as a SINGLE combined Error Log
entry per batch (see _log_batch_issues), so a bad batch with many
mismatched files doesn't flood the Error Log list.

NOTE: Python's zipfile module only supports the classic "ZipCrypto"
per-entry encryption, not WinZip/7-Zip AES encryption. If Paysquare
ever switches to AES-encrypted zips, extraction will need the
third-party `pyzipper` library instead -- this module detects that case
and skips those files with an explicit message rather than silently
producing corrupt output.
"""

import os
import re
import shutil
import tempfile
import zipfile

import frappe

DOCTYPE_SALARY_SLIP = "Paysquare Salary Slip"
DOCTYPE_TAX_SHEET = "Paysquare Tax Sheet"

ATTACH_FIELD = {
	DOCTYPE_SALARY_SLIP: "salary_slip_pdf",
	DOCTYPE_TAX_SHEET: "tax_sheet_pdf",
}

BATCH_COMBINED = "Combined (Salary Slip + Tax Sheet)"
BATCH_SALARY_SLIP_ONLY = "Salary Slip Only"
BATCH_TAX_SHEET_ONLY = "Tax Sheet Only"

BATCH_TYPES = (BATCH_COMBINED, BATCH_SALARY_SLIP_ONLY, BATCH_TAX_SHEET_ONLY)

FORCED_DOCTYPE_FOR_BATCH = {
	BATCH_SALARY_SLIP_ONLY: DOCTYPE_SALARY_SLIP,
	BATCH_TAX_SHEET_ONLY: DOCTYPE_TAX_SHEET,
}

# Which field on Employee to match the filename's employee code against.
# "employee" checks the Employee ID itself (e.g. IFIM0713 is the Employee
# ID). Change this if your Employee IDs don't look like the Paysquare
# codes -- point it at a custom field instead (e.g.
# "custom_paysquare_employee_code").
EMPLOYEE_MATCH_FIELD = "employee"

MONTH_MAP = {
	"jan": "Jan", "january": "Jan",
	"feb": "Feb", "february": "Feb",
	"mar": "Mar", "march": "Mar",
	"apr": "Apr", "april": "Apr",
	"may": "May",
	"jun": "Jun", "june": "Jun",
	"jul": "Jul", "july": "Jul",
	"aug": "Aug", "august": "Aug",
	"sep": "Sep", "sept": "Sep", "september": "Sep",
	"oct": "Oct", "october": "Oct",
	"nov": "Nov", "november": "Nov",
	"dec": "Dec", "december": "Dec",
}

# Combined batches: keyword is required to tell the two doc types apart.
FILENAME_RE_WITH_KEYWORD = re.compile(
	r"^(?P<employee_code>[A-Za-z0-9]+)_(?P<doc_keyword>[A-Za-z]+)_(?P<month>[A-Za-z]+)_(?P<year>\d{4})\.pdf$",
	re.IGNORECASE,
)

# Single-type batches: no keyword needed.
FILENAME_RE_NO_KEYWORD = re.compile(
	r"^(?P<employee_code>[A-Za-z0-9]+)_(?P<month>[A-Za-z]+)_(?P<year>\d{4})\.pdf$",
	re.IGNORECASE,
)


class SkipFile(Exception):
	"""Raised (and caught) for files we deliberately skip -- not a real error."""
	pass


def _doctype_from_keyword(filename, keyword):
	keyword = keyword.lower()
	if "tax" in keyword:
		return DOCTYPE_TAX_SHEET
	if "pay" in keyword or "salary" in keyword:
		return DOCTYPE_SALARY_SLIP
	raise SkipFile(
		f"Filename '{filename}': could not tell if this is a salary slip or tax sheet from '{keyword}'"
	)


def parse_filename(filename, batch_type):
	"""
	Parses filename according to the selected batch_type:

	- Combined: requires EMPCODE_KEYWORD_MON_YYYY.pdf, keyword decides doctype.
	- Salary Slip Only / Tax Sheet Only: accepts either EMPCODE_MON_YYYY.pdf
	  or EMPCODE_KEYWORD_MON_YYYY.pdf, but the doctype is always forced to
	  the selected batch type (any keyword present is ignored).
	"""
	if batch_type == BATCH_COMBINED:
		match = FILENAME_RE_WITH_KEYWORD.match(filename)
		if not match:
			raise SkipFile(
				f"Filename '{filename}' does not match expected pattern "
				f"EMPCODE_TYPE_MON_YYYY.pdf (required for Combined batches)"
			)
		parts = match.groupdict()
		target_doctype = _doctype_from_keyword(filename, parts["doc_keyword"])
		month_str, year_str, employee_code = parts["month"], parts["year"], parts["employee_code"]

	else:
		# Single-type batch: try the no-keyword pattern first, fall back to
		# the with-keyword pattern (keyword is tolerated but ignored).
		match = FILENAME_RE_NO_KEYWORD.match(filename)
		if match:
			parts = match.groupdict()
		else:
			match = FILENAME_RE_WITH_KEYWORD.match(filename)
			if not match:
				raise SkipFile(
					f"Filename '{filename}' does not match expected pattern "
					f"EMPCODE_MON_YYYY.pdf or EMPCODE_TYPE_MON_YYYY.pdf"
				)
			parts = match.groupdict()

		target_doctype = FORCED_DOCTYPE_FOR_BATCH[batch_type]
		month_str, year_str, employee_code = parts["month"], parts["year"], parts["employee_code"]

	month = MONTH_MAP.get(month_str.lower())
	if not month:
		raise SkipFile(f"Filename '{filename}': unrecognised month '{month_str}'")

	return {
		"employee_code": employee_code,
		"target_doctype": target_doctype,
		"month": month,
		"year": int(year_str),
	}


def _is_aes_encrypted(zip_info):
	"""
	Detects WinZip/7-Zip AES encryption via the 0x9901 extra-field marker.
	Python's zipfile can't decrypt these (it only supports classic
	ZipCrypto) -- better to skip explicitly than silently extract garbage.
	"""
	extra = zip_info.extra
	i = 0
	while i + 4 <= len(extra):
		field_id = int.from_bytes(extra[i:i + 2], "little")
		field_size = int.from_bytes(extra[i + 2:i + 4], "little")
		if field_id == 0x9901:
			return True
		i += 4 + field_size
	return False


def _iter_pdf_entries(zf):
	"""Yields the ZipInfo entries in zf that this module will attempt to process."""
	for info in zf.infolist():
		if info.is_dir():
			continue
		if not os.path.basename(info.filename).lower().endswith(".pdf"):
			continue
		yield info


def count_pdf_entries(zip_path):
	"""
	Counts how many PDF entries a zip contains, without extracting
	anything. Used to give a "processed X of Y" total up front, since
	we don't otherwise know how many employees a batch touches.
	"""
	with zipfile.ZipFile(zip_path) as zf:
		return sum(1 for _ in _iter_pdf_entries(zf))


def find_employee(employee_code, match_field=EMPLOYEE_MATCH_FIELD):
	"""
	Looks up the Employee whose match_field equals employee_code, globally
	(no Company scoping, since there's no Company field on the uploader
	-- employee codes are assumed unique on their own).
	"""
	filters = {match_field: employee_code}
	if match_field == "employee":
		filters = {"name": employee_code}
	return frappe.db.get_value("Employee", filters, "name")


def create_or_update_record(parsed, employee, extracted_pdf_path, original_filename):
	"""
	Creates (or updates, if re-run for the same month) the
	Paysquare Salary Slip / Paysquare Tax Sheet record and attaches the
	PDF exactly as extracted (no PDF-internal unlocking). Naming follows
	the doctype's own autoname: {employee}-{month}-{year}. Company on the
	record is fetched from the matched Employee (informational only).
	"""
	target_doctype = parsed["target_doctype"]
	attach_field = ATTACH_FIELD[target_doctype]
	docname = f"{employee}-{parsed['month']}-{parsed['year']}"
	employee_company = frappe.db.get_value("Employee", employee, "company")

	if frappe.db.exists(target_doctype, docname):
		doc = frappe.get_doc(target_doctype, docname)
	else:
		doc = frappe.new_doc(target_doctype)
		doc.month = parsed["month"]
		doc.year = parsed["year"]

	doc.company = employee_company
	doc.employee = employee
	doc.status = "Imported"

	# The attach field is mandatory on these doctypes, but we only set it
	# right after insert/save (via db_set below), so skip the mandatory
	# check here -- save() doesn't accept ignore_mandatory as a kwarg like
	# insert() does, so set the flag directly instead.
	doc.flags.ignore_mandatory = True

	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)

	with open(extracted_pdf_path, "rb") as f:
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": original_filename,
			"attached_to_doctype": target_doctype,
			"attached_to_name": doc.name,
			"attached_to_field": attach_field,
			"is_private": 1,
			"content": f.read(),
		})
		file_doc.save(ignore_permissions=True)

	doc.db_set(attach_field, file_doc.file_url)
	return doc.name


def _log_batch_issues(batch_type, skipped, errors):
	"""
	Writes ONE combined Error Log entry for the whole batch run instead
	of logging each skipped/errored file separately -- a batch with many
	mismatched or bad files would otherwise flood the Error Log list.
	Does nothing if the batch had no issues.
	"""
	if not skipped and not errors:
		return

	lines = [f"Batch Type: {batch_type}", ""]

	if skipped:
		lines.append(f"-- {len(skipped)} file(s) skipped --")
		lines += [f"{row['file']}: {row['reason']}" for row in skipped]
		lines.append("")

	if errors:
		lines.append(f"-- {len(errors)} file(s) hit an unexpected error --")
		for row in errors:
			lines.append(f"{row['file']}: {row['reason']}")
			if row.get("traceback"):
				lines.append(row["traceback"])
			lines.append("")

	frappe.log_error(title="Paysquare Import: Batch Issues", message="\n".join(lines))


def process_zip_file(zip_path, batch_type, zip_password, progress_callback=None):
	"""
	Main entry point. Opens zip_path (the container needs no password)
	and, for every PDF entry: parses its filename for employee code /
	month / year, extracts it using the single zip_password the user
	supplied on the uploader page, matches the employee globally by
	code, and attaches the extracted PDF to the record as-is.
	`batch_type` (one of BATCH_TYPES) decides whether the filename needs
	a keyword to distinguish salary slip vs. tax sheet.

	progress_callback, if given, is called as progress_callback(processed,
	total) once per PDF entry handled (regardless of whether it was
	created, skipped, or errored), so a caller running this in a
	background job can report "X of Y done" without this module knowing
	anything about jobs or caches.

	Skipped files and unexpected per-file errors are collected during
	the run and written to Error Log as a single combined entry at the
	end (see _log_batch_issues) rather than one entry per file.

	Returns a summary dict:
	    {
	        "created": [{"file":..., "doctype":..., "docname":...}, ...],
	        "skipped": [{"file":..., "reason":...}, ...],
	        "errors":  [{"file":..., "reason":...}, ...],
	    }
	"""
	if batch_type not in BATCH_TYPES:
		frappe.throw(f"Batch Type must be one of: {', '.join(BATCH_TYPES)}")

	if not zip_password:
		frappe.throw("Zip Password is required")

	password_bytes = zip_password.encode()

	summary = {"created": [], "skipped": [], "errors": []}
	error_tracebacks = []  # parallel detail for summary["errors"], not sent to the client
	temp_dir = tempfile.mkdtemp(prefix="payslip_import_")

	try:
		try:
			zf = zipfile.ZipFile(zip_path)
		except Exception as e:
			frappe.log_error(title="Paysquare Import: Zip Open Error", message=f"{zip_path}: {e}")
			summary["errors"].append({"file": os.path.basename(zip_path), "reason": f"Could not open zip: {e}"})
			return summary

		with zf:
			pdf_entries = list(_iter_pdf_entries(zf))
			total = len(pdf_entries)
			processed = 0

			for info in pdf_entries:
				filename = os.path.basename(info.filename)

				try:
					parsed = parse_filename(filename, batch_type)

					employee = find_employee(parsed["employee_code"])
					if not employee:
						raise SkipFile(
							f"No Employee found matching code '{parsed['employee_code']}'"
						)

					if _is_aes_encrypted(info):
						raise SkipFile(
							f"'{filename}' uses AES zip encryption, which isn't supported "
							f"by the built-in extractor -- re-zip with standard ZipCrypto "
							f"encryption, or ask to add AES support"
						)

					try:
						extracted_path = zf.extract(info, path=temp_dir, pwd=password_bytes)
					except RuntimeError as e:
						raise SkipFile(
							f"Could not extract '{filename}' with the given zip password ({e})"
						)

					docname = create_or_update_record(parsed, employee, extracted_path, filename)
					summary["created"].append({
						"file": filename,
						"doctype": parsed["target_doctype"],
						"docname": docname,
					})

				except SkipFile as e:
					summary["skipped"].append({"file": filename, "reason": str(e)})

				except Exception as e:
					error_tracebacks.append(f"{filename}:\n{frappe.get_traceback()}")
					summary["errors"].append({"file": filename, "reason": str(e)})

				finally:
					processed += 1
					if progress_callback:
						progress_callback(processed, total)

	finally:
		shutil.rmtree(temp_dir, ignore_errors=True)

	errors_with_tb = [
		{**row, "traceback": tb}
		for row, tb in zip(summary["errors"], error_tracebacks)
	]
	_log_batch_issues(batch_type, summary["skipped"], errors_with_tb)

	return summary