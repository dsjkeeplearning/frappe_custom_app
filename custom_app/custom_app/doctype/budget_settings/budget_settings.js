// Copyright (c) 2026, . and contributors
// For license information, please see license.txt

frappe.ui.form.on("Budget Settings", {
	refresh(frm) {
		// Only a System Manager turns Inter Department Transfer on or off. The server checks it too.
		frm.set_df_property("allow_inter_department_transfer", "read_only", !frappe.user.has_role("System Manager"));
	},
});
