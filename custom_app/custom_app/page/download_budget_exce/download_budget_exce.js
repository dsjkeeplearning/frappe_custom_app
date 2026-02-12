frappe.pages['download-budget-exce'].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Download Budget Excel Format',
        single_column: true
    });

    const $container = $(`
        <div class="p-3">
            <div class="budget-company-field"></div>
        </div>
    `).appendTo(page.body);

    const company_field = frappe.ui.form.make_control({
        parent: $container.find('.budget-company-field'),
        df: {
            label: 'Company',
            fieldtype: 'Link',
            fieldname: 'company',
            options: 'Company',
            reqd: 1
        },
        render_input: true
    });

    // Set width (important)
    company_field.$wrapper.css({
        'max-width': '400px'
    });

    const $btn = $(`
        <button class="btn btn-primary mt-3">
            Download Excel
        </button>
    `).appendTo($container);

    $btn.on('click', function () {
        const company = company_field.get_value();

        if (!company) {
            frappe.msgprint(__('Please select a Company'));
            return;
        }

        window.open(
            `/api/method/custom_app.custom_app.page.download_budget_exce.download_budget_exce.download_budget_excel?company=${company}`
        );
    });
};
