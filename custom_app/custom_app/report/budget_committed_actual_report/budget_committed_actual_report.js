// Copyright (c) 2026, . and contributors
// For license information, please see license.txt

frappe.query_reports["Budget Committed Actual Report"] = {
	"filters": [
		{
            "fieldname": "company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("Company"),
            "reqd": 1
        },
        {
            "fieldname": "cost_center",
            "label": __("Cost Center"),
            "fieldtype": "Link",
            "options": "Cost Center",
            "reqd": 0
        },
        {
            "fieldname": "fiscal_year",
            "label": __("Fiscal Year"),
            "fieldtype": "Link",
            "options": "Fiscal Year",
            "default": frappe.defaults.get_user_default("fiscal_year"),
            "reqd": 1
        }
	]
};
