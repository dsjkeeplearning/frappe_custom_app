frappe.ui.form.on('Material Request', {
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