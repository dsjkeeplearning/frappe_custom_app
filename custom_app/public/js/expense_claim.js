frappe.ui.form.on('Expense Claim', {
    onload(frm) {
        // apply employee filter only if logged-in user has an employee
        set_employee_filter_if_applicable(frm);
    },

    employee(frm) {
        if (!frm.doc.employee) return;

        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "Employee",
                filters: { name: frm.doc.employee },
                fieldname: ["department"]
            },
            callback(r) {
                if (!r.message || !r.message.department) return;

                const department = r.message.department;

                // set cost center filter
                set_cost_center_filter(frm, department);

                // fetch default cost center for department
                frappe.call({
                    method: "frappe.client.get_value",
                    args: {
                        doctype: "Cost Center",
                        filters: {
                            custom_department: department,
                            is_group: 0
                        },
                        fieldname: ["name"]
                    },
                    callback(res) {
                        if (res.message) {
                            frm.set_value("cost_center", res.message.name);
                        }
                    }
                });
            }
        });
    }
});

/* ---------------- Helpers ---------------- */

function set_employee_filter_if_applicable(frm) {
    frappe.call({
        method: "frappe.client.get_value",
        args: {
            doctype: "Employee",
            filters: { user_id: frappe.session.user },
            fieldname: ["name"]
        },
        callback(r) {
            // if user has an employee → restrict employee field
            if (r.message && r.message.name) {
                frm.set_query("employee", () => {
                    return {
                        filters: {
                            name: r.message.name
                        }
                    };
                });

                // auto set employee if empty
                if (!frm.doc.employee) {
                    frm.set_value("employee", r.message.name);
                }
            }
            // else → do nothing (HR/Admin can see all employees)
        }
    });
}

function set_cost_center_filter(frm, department) {
    frm.set_query("cost_center", () => {
        return {
            filters: {
                custom_department: department,
                is_group: 0
            }
        };
    });
}
