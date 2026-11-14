// Copyright (c) 2026, . and contributors
// For license information, please see license.txt

frappe.ui.form.on("Mid Year Budget Upload", {
	setup(frm) {
		frm.set_query("cost_center", () => {
			return { filters: { company: frm.doc.company } };
		});
	},

	refresh(frm) {
		load_preview(frm);
	},

	company(frm) {
		frm.set_value("cost_center", null);
	},

	cost_center(frm) {
		load_preview(frm);
	},

	fiscal_year(frm) {
		load_preview(frm);
	},

	budget_file(frm) {
		load_preview(frm);
	},

	// Re-check right before submitting: the budgets may have changed since the
	// preview was drawn. Errors stop the submit, warnings ask for confirmation.
	before_submit(frm) {
		return frm.call({ method: "get_preview", doc: frm.doc }).then((r) => {
			const result = r.message || {};
			show_preview(frm, result);

			if (result.errors && result.errors.length) {
				frappe.validated = false;
				frappe.msgprint({
					title: __("Budget File Cannot Be Applied"),
					indicator: "red",
					message: __("Fix the errors listed on the form and upload the file again."),
				});
				return;
			}

			if (!result.has_changes) {
				frappe.validated = false;
				frappe.msgprint(__("Nothing to apply: every budget in the file is unchanged."));
				return;
			}

			if (result.warnings && result.warnings.length) {
				return new Promise((resolve) => {
					frappe.confirm(
						`<p>${__("These months are reduced below what is already consumed:")}</p>
						<ul><li>${result.warnings.join("</li><li>")}</li></ul>
						<p>${__("Apply the new budget anyway?")}</p>`,
						() => resolve(),
						() => {
							frappe.validated = false;
							resolve();
						}
					);
				});
			}
		});
	},
});

function load_preview(frm) {
	const doc = frm.doc;
	if (doc.docstatus !== 0) {
		return;
	}

	if (!(doc.company && doc.cost_center && doc.fiscal_year && doc.budget_file)) {
		frm.fields_dict.budget_preview.$wrapper.empty();
		return;
	}

	frm.call({ method: "get_preview", doc: doc }).then((r) => show_preview(frm, r.message || {}));
}

function show_preview(frm, result) {
	frm.fields_dict.budget_preview.$wrapper.html(result.html || "");
}
