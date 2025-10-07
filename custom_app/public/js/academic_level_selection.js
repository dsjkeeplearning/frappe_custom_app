frappe.ui.form.on('Employee', {
    refresh(frm) {
        const is_teaching = frm.doc.custom_type === 'Teaching';

        // Show/hide fields
        frm.toggle_display(
            ['custom_academic_level', 'custom_category'],
            is_teaching
        );

        // Make mandatory only if Teaching
        frm.set_df_property('custom_academic_level', 'reqd', is_teaching);
        frm.set_df_property('custom_category', 'reqd', is_teaching);
    },

    custom_type(frm) {
        const is_teaching = frm.doc.custom_type === 'Teaching';

        // Show/hide fields
        frm.toggle_display(
            ['custom_academic_level', 'custom_category'],
            is_teaching
        );

        // Make mandatory only if Teaching
        frm.set_df_property('custom_academic_level', 'reqd', is_teaching);
        frm.set_df_property('custom_category', 'reqd', is_teaching);

        // Clear values if not teaching
        if (!is_teaching) {
            frm.set_value('custom_academic_level', '');
            frm.set_value('custom_category', '');
        }
    },

    custom_academic_level(frm) {
        const level = frm.doc.custom_academic_level;
        let max_categories = 0;

        // Map level labels to max categories
        switch (level) {
            case 'Asst Prof - 10': max_categories = 40; break;
            case 'Asst Prof - 11': max_categories = 38; break;
            case 'Asst Prof - 12': max_categories = 34; break;
            case 'Associate Prof - 13A': max_categories = 18; break;
            case 'Prof - 14': max_categories = 15; break;
            default: max_categories = 0;
        }

        // Filter category options dynamically
        if (max_categories > 0) {
            const allowed = Array.from({ length: max_categories }, (_, i) => (i + 1).toString());
            frm.set_df_property('custom_category', 'options', allowed.join('\n'));
        } else {
            frm.set_df_property('custom_category', 'options', '');
        }

        // Clear previously selected category
        frm.set_value('custom_category', '');
        frm.refresh_field('custom_category');
    }
});