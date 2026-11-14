// Copyright (c) 2026, . and contributors
// For license information, please see license.txt

frappe.query_reports["Budget Availability Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
			reqd: 1,
			get_query: function () {
				let company = frappe.query_report.get_filter_value("company");

				if (!company) {
					return {};
				}

				return {
					filters: {
						company: company,
					},
				};
			},
		},
		{
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: frappe.defaults.get_user_default("fiscal_year"),
			reqd: 1,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!(column.fieldname && column.fieldname.endsWith("_left") && data)) {
			return value;
		}

		// "<month>_capped" is set when the cumulative balance up to that month
		// is lower than the month's own balance, so Left is not Budget - Consumed.
		const capped = data[column.fieldname.replace(/_left$/, "_capped")];
		const title = capped ? __("Limited by the cumulative balance up to this month") : "";

		if (data[column.fieldname] < 0) {
			// Overspent heads stand out.
			value = `<span style="color: var(--red-500)" title="${title}">${value}</span>`;
		} else if (capped) {
			value = `<span style="color: var(--orange-500)" title="${title}">${value}</span>`;
		}

		return value;
	},
};
