// Copyright (c) 2025, . and contributors
// For license information, please see license.txt

frappe.ui.form.on("Attendance Excel Generator", {
    generate_excel: function(frm) {
        frappe.call({
            method: "custom_app.custom_app.doctype.attendance_excel_generator.attendance_excel_generator.generate_excel",
            args: { doc: frm.doc },
            callback: function(r) {
                if (r.message) {
                    window.open(r.message); // download file
                }
            }
        });
    }
});
