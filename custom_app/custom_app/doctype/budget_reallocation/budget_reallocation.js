frappe.ui.form.on('Budget Reallocation', {
    company(frm) {
        // Clear dependent fields
        frm.set_value('cost_center', null);
        frm.set_value('account', null);
        frm.set_value('month', null);
        frm.set_value('new_budget', null);
        clear_budget_fields(frm);
        
        // Set filter for cost center
        frm.set_query('cost_center', () => {
            return {
                filters: {
                    company: frm.doc.company,
                    is_group: 0
                }
            };
        });
    },
    
    cost_center(frm) {
        // Clear dependent fields
        frm.set_value('account', null);
        frm.set_value('month', null);
        frm.set_value('new_budget', null);
        clear_budget_fields(frm);
    },
    
    fiscal_year(frm) {
        // Clear dependent fields
        frm.set_value('account', null);
        frm.set_value('month', null);
        frm.set_value('new_budget', null);
        clear_budget_fields(frm);
    },
    
    account(frm) {
        // Clear dependent fields
        frm.set_value('month', null);
        frm.set_value('new_budget', null);
        clear_budget_fields(frm);
    },
    
    month(frm) {
        if (frm.doc.company && frm.doc.cost_center && frm.doc.fiscal_year && 
            frm.doc.account && frm.doc.month) {
            // Fetch current budget for this month
            frm.call({
                method: 'get_current_month_budget',
                doc: frm.doc,
                callback: (r) => {
                    if (r.message) {
                        frm.set_value('current_budget', r.message.current_budget);
                        frm.set_value('total_annual_budget', r.message.total_annual_budget);
                        frm.set_value('master_budget_limit', r.message.master_budget_limit);
                        frm.set_value('total_allocated_budget', r.message.total_allocated_budget);
                        
                        frm.refresh_fields();
                    }
                }
            });
        }
    },
    
    new_budget(frm) {
        if (frm.doc.current_budget && frm.doc.new_budget) {
            // Calculate difference
            let difference = frm.doc.new_budget - frm.doc.current_budget;
            frm.set_value('difference', difference);
            
            // Calculate percentage change
            if (frm.doc.current_budget) {
                let percentage_change = (difference / frm.doc.current_budget) * 100;
                frm.set_value('percentage_change', percentage_change);
            }
            
            // Calculate new total annual budget
            let new_total = frm.doc.total_annual_budget - frm.doc.current_budget + frm.doc.new_budget;
            frm.set_value('new_total_annual_budget', new_total);
            
            // Show warning if exceeding limit
            if (frm.doc.master_budget_limit && difference > 0) {
                let other_accounts = frm.doc.total_allocated_budget - frm.doc.total_annual_budget;
                let new_total_allocated = other_accounts + new_total;
                
                if (new_total_allocated > frm.doc.master_budget_limit) {
                    frappe.msgprint({
                        title: __('Budget Limit Warning'),
                        indicator: 'red',
                        message: __(
                            'New budget will exceed Master Budget Limit!<br><br>' +
                            '<b>Master Budget Limit:</b> {0}<br>' +
                            '<b>Current Total Allocated:</b> {1}<br>' +
                            '<b>New Total Allocated:</b> {2}<br>' +
                            '<b>Excess Amount:</b> {3}',
                            [
                                format_currency(frm.doc.master_budget_limit),
                                format_currency(frm.doc.total_allocated_budget),
                                format_currency(new_total_allocated),
                                format_currency(new_total_allocated - frm.doc.master_budget_limit)
                            ]
                        )
                    });
                }
            }
            
            frm.refresh_fields();
        }
    }
});

function clear_budget_fields(frm) {
    frm.set_value('current_budget', null);
    frm.set_value('difference', null);
    frm.set_value('percentage_change', null);
    frm.set_value('total_annual_budget', null);
    frm.set_value('new_total_annual_budget', null);
    frm.set_value('master_budget_limit', null);
    frm.set_value('total_allocated_budget', null);
}