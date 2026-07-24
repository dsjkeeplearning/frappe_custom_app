# Copyright (c) 2026, . and contributors
# License: MIT
"""
Controller for the payslip-uploader page.

Processing runs as a background job (queue="long") since a batch can
contain an unknown, potentially large number of employees -- we don't
want to hold a web worker (or the browser) hostage for the whole run,
and long zip extractions risk hitting the http request timeout.

Job progress/results are tracked in frappe.cache() under a random
job_key rather than a new doctype -- it's transient, per-run data that
doesn't need to be queried, listed, or reported on later. Entries expire
automatically after JOB_CACHE_EXPIRY seconds so nothing accumulates.

Flow:
    1. JS uploads the zip via the standard FileUploader.
    2. JS calls start_import(), which validates inputs, generates a
       job_key, seeds its status as "queued", enqueues run_import_job(),
       and returns the job_key immediately.
    3. JS freezes the form and polls get_import_status(job_key) (both on
       a timer and via a manual Refresh button) until status is
       "success" or "failed".
    4. run_import_job() does the actual extraction work via
       process_zip_file(), updating the cached status as it goes so the
       UI can show "X of Y processed", and always cleans up the
       uploaded zip File doc afterwards -- whether it succeeded or not.
"""

import json

import frappe

from custom_app.api.paysquare_payslip_import_utils import (
	BATCH_TYPES,
	count_pdf_entries,
	process_zip_file,
)

ALLOWED_ROLES = ["System Manager", "HR Manager", "HR User"]

JOB_CACHE_PREFIX = "payslip_import_job::"
JOB_CACHE_EXPIRY = 60 * 60 * 24  # 24 hours -- generous, just to avoid stale entries lingering forever

# Batches at or below this many PDFs are processed synchronously in the
# web request itself (fast enough, and the user gets results instantly);
# anything bigger goes through the background worker as before.
SYNC_PROCESSING_LIMIT = 10


# ---------------------------------------------------------------------------
# whitelisted endpoints
# ---------------------------------------------------------------------------

@frappe.whitelist()
def start_import(file_url, batch_type, zip_password):
	"""
	Called from payslip_uploader.js right after the zip has been
	uploaded via Frappe's standard File Uploader. Validates the inputs,
	kicks off a background job to do the actual work, and returns a
	job_key the client polls for status.
	"""
	frappe.only_for(ALLOWED_ROLES)

	if batch_type not in BATCH_TYPES:
		frappe.throw(f"Batch Type must be one of: {', '.join(BATCH_TYPES)}")

	if not zip_password:
		frappe.throw("Zip Password is required")

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	zip_path = file_doc.get_full_path()

	# Small batch? Do it right here in the request -- no queue, no polling,
	# results come back instantly. Falls back to the background path if the
	# zip can't even be counted (process_zip_file will surface the real error
	# through the job flow).
	try:
		total = count_pdf_entries(zip_path)
	except Exception:
		total = None

	if total is not None and total <= SYNC_PROCESSING_LIMIT:
		try:
			summary = process_zip_file(zip_path, batch_type, zip_password)
			return {"sync": True, "summary": summary}
		except Exception:
			frappe.log_error(title="Paysquare Import: Sync Run Failed", message=frappe.get_traceback())
			frappe.throw("The batch failed while processing. See the Error Log doctype for details.")
		finally:
			frappe.db.commit()
			try:
				frappe.delete_doc("File", file_doc.name, ignore_permissions=True)
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()

	job_key = frappe.generate_hash(length=12)
	_set_job_status(job_key, {
		"status": "queued",
		"processed": 0,
		"total": None,
		"summary": None,
		"error": None,
	})

	frappe.enqueue(
		method="custom_app.custom_app.page.payslip_uploader.payslip_uploader.run_import_job",
		queue="long",
		timeout=6000,
		job_key=job_key,
		file_path=zip_path,
		file_doc_name=file_doc.name,
		batch_type=batch_type,
		zip_password=zip_password,
	)

	return {"job_key": job_key}


@frappe.whitelist()
def get_import_status(job_key):
	"""Polled by the client to check on a job started via start_import()."""
	frappe.only_for(ALLOWED_ROLES)

	status = _get_job_status(job_key)
	if status is None:
		# The cached entry expired (or the key is bogus). Don't throw --
		# that leaves the UI frozen on a job that can never resolve.
		# Log it as a failure and return a "failed" status so the client
		# clears its stored job_key and lets the user start a new batch.
		frappe.log_error(
			title="Paysquare Import: Job Expired",
			message=f"Job {job_key} was polled but its status is no longer in cache "
			f"(expired after {JOB_CACHE_EXPIRY}s or never existed). Marked as failed.",
		)
		return {
			"status": "failed",
			"processed": 0,
			"total": None,
			"summary": None,
			"error": "This batch's tracking info expired before it could be confirmed. Start a new batch.",
		}

	return status


# ---------------------------------------------------------------------------
# background job target (not whitelisted -- only reachable via frappe.enqueue)
# ---------------------------------------------------------------------------

def run_import_job(job_key, file_path, file_doc_name, batch_type, zip_password):
	"""
	Runs in the "long" worker queue. Does the actual extraction/matching
	via process_zip_file(), keeping the cached job status up to date so
	the UI can show progress, then always deletes the uploaded zip File
	doc regardless of outcome -- a batch, once attempted, shouldn't sit
	around in the File list either way.
	"""
	_set_job_status(job_key, {
		"status": "running",
		"processed": 0,
		"total": None,
		"summary": None,
		"error": None,
	})

	try:
		try:
			total = count_pdf_entries(file_path)
			_update_job_status(job_key, total=total)
		except Exception:
			# If we can't even count entries the zip is likely unreadable --
			# let process_zip_file below surface that properly.
			pass

		def report_progress(processed, total):
			_update_job_status(job_key, processed=processed, total=total)

		summary = process_zip_file(file_path, batch_type, zip_password, progress_callback=report_progress)
		_update_job_status(job_key, status="success", summary=summary)

	except Exception:
		frappe.log_error(title="Paysquare Import: Job Failed", message=frappe.get_traceback())
		_update_job_status(job_key, status="failed", error=frappe.get_traceback(with_context=False)[-500:])

	finally:
		frappe.db.commit()
		try:
			frappe.delete_doc("File", file_doc_name, ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()


# ---------------------------------------------------------------------------
# cache helpers
# ---------------------------------------------------------------------------

def _cache_key(job_key):
	return f"{JOB_CACHE_PREFIX}{job_key}"


def _set_job_status(job_key, data):
	frappe.cache().set_value(_cache_key(job_key), json.dumps(data), expires_in_sec=JOB_CACHE_EXPIRY)


def _get_job_status(job_key):
	raw = frappe.cache().get_value(_cache_key(job_key))
	if raw is None:
		return None
	if isinstance(raw, bytes):
		raw = raw.decode()
	return json.loads(raw)


def _update_job_status(job_key, **kwargs):
	data = _get_job_status(job_key) or {}
	data.update(kwargs)
	_set_job_status(job_key, data)