frappe.ui.form.on('Material Request', {
    onload(frm) {
        // apply employee filter only if logged-in user has an employee
        set_employee_filter_if_applicable(frm);
    },
    custom_employee(frm) {
        frappe.call({
            method: "frappe.client.get_value",
            args: {
                doctype: "Employee",
                filters: { name: frm.doc.custom_employee },
                fieldname: ["department", "expense_approver"]  // Add request approver field
            },
            callback(r) {
                if (r.message) {
                    // Set department-based cost center filter
                    if (r.message.department) {
                        set_cost_center_filter(frm, r.message.department);
                    }
                    
                    // Set request approver from employee
                    if (r.message.expense_approver) {
                        frm.set_value("custom_request_approver", r.message.expense_approver);
                    }
                }
            }
        });
    },
});

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
                frm.set_query("custom_employee", () => {
                    return {
                        filters: {
                            name: r.message.name
                        }
                    };
                });

                // auto set employee if empty
                if (!frm.doc.custom_employee) {
                    frm.set_value("custom_employee", r.message.name);
                }
            }
            // else → do nothing (HR/Admin can see all employees)
        }
    });
}

function set_cost_center_filter(frm, department) {
    frm.set_query("custom_cost_center", () => {
        return {
            filters: {
                custom_department: department,
                is_group: 0
            }
        };
    });
}