frappe.pages['payslip-uploader'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Paysquare Payslip & Taxsheet uploader',
		single_column: true,
	});

	new PayslipUploader(page);
};

const JOB_KEY_STORAGE_KEY = 'payslip_uploader_active_job_key';
const POLL_INTERVAL_MS = 4000;

class PayslipUploader {
	constructor(page) {
		this.page = page;
		this.job_key = null;
		this.poll_timer = null;
		this.make_ui();
		this.restore_active_job();
	}

	make_ui() {
		this.$body = $(`
			<div class="payslip-uploader-wrapper" style="max-width: 800px; margin: 20px auto;">
				<div class="alert alert-info">
					Pick what this batch contains, enter the password Paysquare
					used to protect the PDFs, then upload
					the monthly zip. Each PDF inside is matched to an Employee by
					the code in its filename (e.g.
					<b>IFIM0713_PaySlip_Jun_2026.pdf</b> or, for single-type
					batches, simply <b>IFIM0713_Jun_2026.pdf</b>), extracted
					using the password you entered, and attached to the record
					as-is. Unmatched, malformed, or un-extractable files are
					skipped and logged &mdash; they will not stop the rest of
					the batch.
					<br><br>
					Processing runs as a background job, since a batch can
					contain any number of employees. While a batch is
					running, the fields below are locked and you can check
					progress with the Refresh button until it finishes.
				</div>

				<div class="form-group batch-type-field-wrapper"></div>
				<div class="form-group password-field-wrapper"></div>

				<button class="btn btn-primary btn-upload-zip" disabled>
					Upload &amp; Process Zip
				</button>
				<button class="btn btn-default btn-refresh-status" style="display: none;">
					<i class="fa fa-refresh"></i> Refresh
				</button>
				<small class="text-muted d-block" style="margin-top: 4px;">Select a Batch Type and enter the Zip Password first.</small>

				<div class="payslip-job-status" style="margin-top: 15px;"></div>
				<div class="payslip-results" style="margin-top: 25px;"></div>
			</div>
		`).appendTo(this.page.main);

		this.batch_type_control = frappe.ui.form.make_control({
			parent: this.$body.find('.batch-type-field-wrapper'),
			df: {
				fieldtype: 'Select',
				fieldname: 'batch_type',
				label: 'Batch Type',
				reqd: 1,
				options: [
					'',
					'Combined (Salary Slip + Tax Sheet)',
					'Salary Slip Only',
					'Tax Sheet Only',
				].join('\n'),
				description: 'Combined batches require PaySlip/TaxSheet in the filename to tell the two apart. Single-type batches don\'t need a keyword in the filename at all.',
				change: () => this.update_upload_button_state(),
			},
			render_input: true,
		});
		this.batch_type_control.refresh();

		this.password_control = frappe.ui.form.make_control({
			parent: this.$body.find('.password-field-wrapper'),
			df: {
				fieldtype: 'Password',
				fieldname: 'zip_password',
				label: 'Zip Password',
				reqd: 1,
				description: 'The password Paysquare used to protect each PDF in this batch. The same password is tried for every file in the zip.',
				change: () => this.update_upload_button_state(),
			},
			render_input: true,
		});
		this.password_control.refresh();

		this.$body.find('.btn-upload-zip').on('click', () => this.upload_zip());
		this.$body.find('.btn-refresh-status').on('click', () => this.check_status());
	}

	// ---------- field state helpers ----------

	update_upload_button_state() {
		if (this.job_key) return; // frozen while a job is running
		const ready = !!this.batch_type_control.get_value() && !!this.password_control.get_value();
		this.$body.find('.btn-upload-zip').prop('disabled', !ready);
	}

	freeze_fields() {
		this.batch_type_control.$input.prop('disabled', true);
		this.password_control.$input.prop('disabled', true);
		this.$body.find('.btn-upload-zip').prop('disabled', true).hide();
		this.$body.find('.btn-refresh-status').show();
	}

	unfreeze_fields({ reset } = { reset: false }) {
		this.batch_type_control.$input.prop('disabled', false);
		this.password_control.$input.prop('disabled', false);
		this.$body.find('.btn-refresh-status').hide();
		this.$body.find('.btn-upload-zip').show();

		if (reset) {
			this.batch_type_control.set_value('');
			this.password_control.set_value('');
		}
		this.update_upload_button_state();
	}

	// ---------- upload + job lifecycle ----------

	upload_zip() {
		const batch_type = this.batch_type_control.get_value();
		const zip_password = this.password_control.get_value();

		if (!batch_type || !zip_password) {
			frappe.msgprint('Please select a Batch Type and enter the Zip Password first.');
			return;
		}

		new frappe.ui.FileUploader({
			allow_multiple: false,
			restrictions: {
				allowed_file_types: ['.zip'],
			},
			on_success: (file_doc) => {
				this.start_import(file_doc.file_url, batch_type, zip_password);
			},
		});
	}

	start_import(file_url, batch_type, zip_password) {
		this.$body.find('.payslip-results').html('');
		this.render_status(`<div class="text-muted">Starting import...</div>`);

		frappe.call({
			method: 'custom_app.custom_app.page.payslip_uploader.payslip_uploader.start_import',
			args: { file_url, batch_type, zip_password },
			freeze: true,
			freeze_message: 'Processing the batch...',
			callback: (r) => {
				if (!r.message) {
					this.render_status(`<div class="alert alert-danger">Could not start the import job.</div>`);
					return;
				}
				// Small batches are processed synchronously on the server --
				// the summary comes back right away, no polling needed.
				if (r.message.sync) {
					this.render_status('');
					this.render_results(r.message.summary);
					this.unfreeze_fields({ reset: true });
					return;
				}
				if (!r.message.job_key) {
					this.render_status(`<div class="alert alert-danger">Could not start the import job.</div>`);
					return;
				}
				this.set_active_job(r.message.job_key);
				this.check_status();
			},
			error: () => {
				this.render_status(`<div class="alert alert-danger">Something went wrong starting the job. Check the Error Log doctype for details.</div>`);
			},
		});
	}

	set_active_job(job_key) {
		this.job_key = job_key;
		localStorage.setItem(JOB_KEY_STORAGE_KEY, job_key);
		this.freeze_fields();
		this.start_polling();
	}

	restore_active_job() {
		const stored_key = localStorage.getItem(JOB_KEY_STORAGE_KEY);
		if (!stored_key) return;
		this.job_key = stored_key;
		this.freeze_fields();
		this.render_status(`<div class="text-muted">Checking status of the batch already in progress...</div>`);
		this.check_status();
		this.start_polling();
	}

	start_polling() {
		this.stop_polling();
		this.poll_timer = setInterval(() => this.check_status(), POLL_INTERVAL_MS);
	}

	stop_polling() {
		if (this.poll_timer) {
			clearInterval(this.poll_timer);
			this.poll_timer = null;
		}
	}

	check_status() {
		if (!this.job_key) return;

		frappe.call({
			method: 'custom_app.custom_app.page.payslip_uploader.payslip_uploader.get_import_status',
			args: { job_key: this.job_key },
			callback: (r) => this.handle_status(r.message),
			error: () => {
				this.render_status(`<div class="alert alert-danger">Could not fetch job status. It may have expired &mdash; try Refresh again, or start a new batch.</div>`);
			},
		});
	}

	handle_status(status) {
		if (!status) return;

		if (status.status === 'queued') {
			this.render_status(`<div class="text-muted"><i class="fa fa-clock-o"></i> Queued, waiting for a worker to pick it up...</div>`);
			return;
		}

		if (status.status === 'running') {
			const total = status.total != null ? status.total : '?';
			this.render_status(`<div class="text-muted"><i class="fa fa-spinner fa-spin"></i> Processing... ${status.processed || 0} / ${total} file(s) handled so far.</div>`);
			return;
		}

		if (status.status === 'success') {
			this.stop_polling();
			this.render_status('');
			this.render_results(status.summary);
			this.job_key = null;
			localStorage.removeItem(JOB_KEY_STORAGE_KEY);
			this.unfreeze_fields({ reset: true });
			return;
		}

		if (status.status === 'failed') {
			this.stop_polling();
			this.render_status(`
				<div class="alert alert-danger">
					The batch failed before it could finish: ${frappe.utils.escape_html(status.error || 'Unknown error')}.
					See the Error Log doctype for the full traceback. Your Batch Type and Password are kept below
					&mdash; re-select the zip and click Upload &amp; Process Zip to try again.
				</div>
			`);
			this.job_key = null;
			localStorage.removeItem(JOB_KEY_STORAGE_KEY);
			this.unfreeze_fields({ reset: false });
			return;
		}
	}

	render_status(html) {
		this.$body.find('.payslip-job-status').html(html);
	}

	// ---------- results table (unchanged from the synchronous version) ----------

	render_results(summary) {
		const $results = this.$body.find('.payslip-results');
		if (!summary) {
			$results.html('');
			return;
		}

		const created = summary.created || [];
		const skipped = summary.skipped || [];
		const errors = summary.errors || [];

		let html = `
			<div class="alert alert-success">
				<b>${created.length}</b> record(s) created/updated successfully.
			</div>
		`;

		if (created.length) {
			html += this.build_table(created, (row) => `
				<td>${frappe.utils.escape_html(row.file)}</td>
				<td>${frappe.utils.escape_html(row.doctype)}</td>
				<td><a href="/app/${frappe.router.slug(row.doctype)}/${encodeURIComponent(row.docname)}" target="_blank">${frappe.utils.escape_html(row.docname)}</a></td>
			`, ['File', 'Doctype', 'Record']);
		}

		if (skipped.length) {
			html += `<div class="alert alert-warning"><b>${skipped.length}</b> file(s) skipped (no matching employee, bad filename, or wrong password):</div>`;
			html += this.build_table(skipped, (row) => `
				<td>${frappe.utils.escape_html(row.file)}</td>
				<td>${frappe.utils.escape_html(row.reason)}</td>
			`, ['File', 'Reason']);
		}

		if (errors.length) {
			html += `<div class="alert alert-danger"><b>${errors.length}</b> file(s) hit an unexpected error (see Error Log):</div>`;
			html += this.build_table(errors, (row) => `
				<td>${frappe.utils.escape_html(row.file)}</td>
				<td>${frappe.utils.escape_html(row.reason)}</td>
			`, ['File', 'Reason']);
		}

		$results.html(html);
	}

	build_table(rows, row_renderer, headers) {
		return `
			<table class="table table-bordered table-sm">
				<thead>
					<tr>${headers.map((h) => `<th>${h}</th>`).join('')}</tr>
				</thead>
				<tbody>
					${rows.map((row) => `<tr>${row_renderer(row)}</tr>`).join('')}
				</tbody>
			</table>
		`;
	}
}