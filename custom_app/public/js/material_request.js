frappe.ui.form.on('Material Request', {
    onload(frm) {
        set_employee_filter_if_applicable(frm);
        toggle_request_verifier(frm); // handle existing docs on load
    },

    custom_employee(frm) {
        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "Employee",
                filters: { name: frm.doc.custom_employee },
                fieldname: ["department", "expense_approver"]
            },
            callback(r) {
                if (r.message) {
                    if (r.message.department) {
                        set_cost_center_filter(frm, r.message.department);
                    }
                    if (r.message.expense_approver) {
                        frm.set_value("custom_request_approver", r.message.expense_approver);
                    }
                }
            }
        });
    },

    custom_cost_center(frm) {
        toggle_request_verifier(frm);
    },
});

function toggle_request_verifier(frm) {
    const cost_center = frm.doc.custom_cost_center;

    // Always hide + clear first, then re-evaluate
    frm.set_df_property("custom_request_verifier", "hidden", 1);
    frm.set_df_property("custom_request_verifier", "reqd", 0);

    if (!cost_center) return;

    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Verifier PR Details",
            parent: "Verifier PR Settings",
            filters: { cost_center: cost_center },
            fields: ["cost_center"],
            limit: 1
        },
        callback(r) {
            const in_list = r.message && r.message.length > 0;
            frm.set_df_property("custom_request_verifier", "hidden", in_list ? 0 : 1);
            frm.set_df_property("custom_request_verifier", "reqd",   in_list ? 1 : 0);
            if (!in_list) {
                frm.set_value("custom_request_verifier", null);
            }
        }
    });
}

function set_employee_filter_if_applicable(frm) {
    frappe.call({
        method: "frappe.client.get_value",
        args: {
            doctype: "Employee",
            filters: { user_id: frappe.session.user },
            fieldname: ["name"]
        },
        callback(r) {
            if (r.message && r.message.name) {
                frm.set_query("custom_employee", () => ({
                    filters: { name: r.message.name }
                }));
                if (!frm.doc.custom_employee) {
                    frm.set_value("custom_employee", r.message.name);
                }
            }
        }
    });
}

function set_cost_center_filter(frm, department) {
    frm.set_query("custom_cost_center", () => ({
        filters: {
            custom_department: department,
            is_group: 0
        }
    }));
}