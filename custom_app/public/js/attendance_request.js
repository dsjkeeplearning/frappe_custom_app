frappe.ui.form.on("Attendance Request", {
	setup(frm) {
		frm.set_df_property("shift", "read_only", 1);
	},
	employee(frm) {
		fetch_shift_preview(frm);
	},
	from_date(frm) {
		fetch_shift_preview(frm);
	},
	to_date(frm) {
		fetch_shift_preview(frm);
	},
});

function fetch_shift_preview(frm) {
	if (!(frm.doc.employee && frm.doc.from_date && frm.doc.to_date)) {
		return;
	}
	frappe.call({
		method: "custom_app.api.attendance_request.get_shift_preview",
		args: {
			employee: frm.doc.employee,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date,
		},
		callback(r) {
			frm.set_value("shift", r.message || "");
		},
	});
}
