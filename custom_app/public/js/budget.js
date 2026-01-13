// File: Custom Script for Budget OR your_app_name/your_app_name/public/js/budget.js

frappe.ui.form.on('Budget', {
    refresh: function(frm) {
        // Run ONLY for Draft documents
        if (frm.doc.docstatus === 1 || frm.doc.docstatus === 2) {
            return;
        }

        // Avoid repeated calls on refresh
        if (frm._budget_allocated_fetched) {
            return;
        }

        fetch_budget_allocated(frm);
        frm._budget_allocated_fetched = true;
    },
    company: function(frm) {
        fetch_budget_allocated(frm);
    },
    cost_center: function(frm) {
        fetch_budget_allocated(frm);
    },
    fiscal_year: function(frm) {
        fetch_budget_allocated(frm);
    },
    budget_against: function(frm) {
        fetch_budget_allocated(frm);
    }
});

function fetch_budget_allocated(frm) {
    // Only proceed if budget_against is 'Cost Center'
    if (frm.doc.budget_against !== 'Cost Center') {
        frm.set_value('custom_budget_allocated', 0);
        return;
    }
    
    // Check if all required fields are filled
    if (!frm.doc.company || !frm.doc.cost_center || !frm.doc.fiscal_year) {
        return;
    }
    
    // Call the whitelisted server method
    frappe.call({
        method: 'custom_app.overrides.budget.get_budget_allocated',
        args: {
            company: frm.doc.company,
            cost_center: frm.doc.cost_center,
            fiscal_year: frm.doc.fiscal_year
        },
        callback: function(r) {
            if (r.message) {
                // Set the budget value
                frm.set_value('custom_budget_allocated', r.message.budget);
                
                // Show appropriate alert
                if (r.message.success) {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'green'
                    }, 3);
                } else {
                    frappe.show_alert({
                        message: r.message.message,
                        indicator: 'orange'
                    }, 5);
                }
            }
        }
    });
}