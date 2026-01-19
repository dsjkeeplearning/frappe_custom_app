frappe.ui.form.on('Budget Upload', {
    refresh(frm) {
        // Load preview on form refresh if budget_file exists
        if (frm.doc.budget_file) {
            load_budget_preview(frm);
        }
    },

    company(frm) {
        frm.set_value('cost_center', null);
        frm.set_query('cost_center', () => {
            return { filters: { company: frm.doc.company } };
        });
    },

    budget_file(frm) {
        if (!frm.doc.budget_file) {
            frm.fields_dict.budget_preview.$wrapper.empty();
            frm.enable_save();
            return;
        }
        load_budget_preview(frm);
    },

    // Block submit if there are errors
    before_submit(frm) {
        if (frm._has_budget_errors) {
            frappe.throw(__('Cannot submit. Please fix the errors in the budget file first.'));
            return false;
        }
    }
});

function load_budget_preview(frm) {
    frm.call({
        method: 'get_excel_preview',
        doc: frm.doc
    }).then(r => {
        if (!r.message) return;

        // Show preview
        if (r.message.html) {
            frm.fields_dict.budget_preview.$wrapper.html(r.message.html);
        }

        // ❌ Errors found
        if (r.message.has_error) {
            frm.disable_save();
            frm._has_budget_errors = true;  // Flag to prevent submit

            // Debug: Check what we're getting
            console.log('Response:', r.message);
            console.log('Errors:', r.message.errors);

            // Use Dialog instead of msgprint for better HTML support
            let error_html = '<ul>';
            r.message.errors.forEach(e => {
                error_html += `<li>${e}</li>`;
            });
            error_html += '</ul>';

            let d = new frappe.ui.Dialog({
                title: __('Invalid Budget Values Found'),
                indicator: 'red',
                fields: [
                    {
                        fieldtype: 'HTML',
                        fieldname: 'error_msg',
                        options: `
                            <div style="padding: 10px;">
                                <p>Some cells contain <b>non-numeric values</b>. 
                                They are highlighted in <b style="color:red">RED</b> in the preview.</p>
                                <div style="max-height:300px; overflow:auto; margin-top: 10px; border: 1px solid #ddd; padding: 10px;">
                                    ${error_html}
                                </div>
                            </div>
                        `
                    }
                ]
            });
            d.show();
        } else {
            // ✅ No errors
            frm.enable_save();
            frm._has_budget_errors = false;  // Clear error flag
        }
    });
}