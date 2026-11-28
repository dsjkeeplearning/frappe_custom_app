// Budget Reallocation: move budget from one month of an account to another, in one step.
// The Transfer Type decides what the two sides share; see budget_reallocation.py.

const SAME_MONTH = "Within Same Month";
const CARRY_FORWARD = "Carry Forward";
const INTER_DEPARTMENT = "Inter Department Transfer";
const SINGLE_ACCOUNT = "Single Account";
const TRANSFER_TYPES = [SAME_MONTH, CARRY_FORWARD, INTER_DEPARTMENT];
const REALLOCATION = "custom_app.custom_app.doctype.budget_reallocation.budget_reallocation";

const HELP = {
	[SAME_MONTH]: __("Moves budget from one account to another, in the same month and cost center."),
	[CARRY_FORWARD]: __("Moves an account's budget from one month to another, in the same cost center."),
	[INTER_DEPARTMENT]: __(
		"Moves budget from one cost center to another. The accounts and months may differ. The Master Budget limits move with it."
	),
	[SINGLE_ACCOUNT]: __("Made with the earlier form: one account's month set to a new amount."),
};

const FROM_SIDE = ["from_cost_center", "from_account", "from_month"];
const TO_SIDE = ["to_cost_center", "to_account", "to_month"];
const FIGURES = [
	"from_month_budget",
	"from_month_used",
	"left_to_move",
	"from_new_month_budget",
	"from_year_budget",
	"from_new_year_budget",
	"to_month_budget",
	"to_new_month_budget",
	"to_year_budget",
	"to_new_year_budget",
	"from_master_limit",
	"from_new_master_limit",
	"to_master_limit",
	"to_new_master_limit",
];

frappe.ui.form.on("Budget Reallocation", {
	setup(frm) {
		// Only cost centers and accounts with an approved budget for the year.
		frm.set_query("from_cost_center", () => cost_center_query(frm));
		frm.set_query("to_cost_center", () => cost_center_query(frm, frm.doc.from_cost_center));
		frm.set_query("from_account", () => account_query(frm, frm.doc.from_cost_center));
		frm.set_query("to_account", () =>
			account_query(
				frm,
				frm.doc.to_cost_center,
				frm.doc.reallocation_type === SAME_MONTH ? frm.doc.from_account : ""
			)
		);

	},

	refresh(frm) {
		show_help(frm);
		if (frm.doc.reallocation_type === SINGLE_ACCOUNT && !frm.is_new()) {
			// Made with the earlier form: kept as a record. The server refuses any change too.
			frm.set_intro(
				__("This reallocation was made with the earlier form. It is kept as a record and can no longer be changed, approved or rejected."),
				"orange"
			);
			frm.disable_form();
			return;
		}
		if (frm.doc.docstatus === 0) {
			set_transfer_types(frm);
		}
	},

	reallocation_type(frm) {
		show_help(frm);
		if (!is_transfer(frm)) return;
		// The giving side stays; the receiving side follows the new type.
		clear(frm, TO_SIDE).then(() => fill_receiving_side(frm));
	},

	company(frm) {
		clear(frm, [...FROM_SIDE, ...TO_SIDE]);
	},

	fiscal_year(frm) {
		clear(frm, [...FROM_SIDE, ...TO_SIDE]);
	},

	from_cost_center(frm) {
		clear(frm, ["from_account"]).then(() => fill_receiving_side(frm));
	},

	from_account(frm) {
		fill_receiving_side(frm);
	},

	from_month(frm) {
		fill_receiving_side(frm);
	},

	to_cost_center(frm) {
		if (frm.doc.reallocation_type === INTER_DEPARTMENT) {
			clear(frm, ["to_account"]).then(() => refresh_figures(frm));
		}
	},

	to_account(frm) {
		refresh_figures(frm);
	},

	to_month(frm) {
		refresh_figures(frm);
	},

	amount(frm) {
		refresh_figures(frm);
	},

});

function is_transfer(frm) {
	return TRANSFER_TYPES.includes(frm.doc.reallocation_type);
}

function show_help(frm) {
	frm.set_df_property("reallocation_type", "description", HELP[frm.doc.reallocation_type] || "");
}

function set_transfer_types(frm) {
	// Inter Department Transfer is offered only while Budget Settings allow it.
	frappe.xcall(`${REALLOCATION}.get_transfer_types`).then((types) => {
		const current = frm.doc.reallocation_type;
		if (current && !types.includes(current)) types.push(current);
		frm.set_df_property("reallocation_type", "options", ["", ...types].join("\n"));
	});
}

function cost_center_query(frm, leave_out) {
	return {
		query: `${REALLOCATION}.budgeted_cost_centers`,
		filters: { company: frm.doc.company, fiscal_year: frm.doc.fiscal_year, leave_out: leave_out || "" },
	};
}

function account_query(frm, cost_center, leave_out) {
	return {
		query: `${REALLOCATION}.budgeted_accounts`,
		filters: {
			company: frm.doc.company,
			fiscal_year: frm.doc.fiscal_year,
			cost_center: cost_center || "",
			leave_out: leave_out || "",
		},
	};
}

function clear(frm, fields) {
	const values = {};
	for (const field of fields) {
		if (frm.doc[field]) values[field] = null;
	}
	return Object.keys(values).length ? frm.set_value(values) : Promise.resolve();
}

function fill_receiving_side(frm) {
	// What the Transfer Type keeps the same is copied from the giving side.
	const values = {};
	const type = frm.doc.reallocation_type;
	if (type === SAME_MONTH || type === CARRY_FORWARD) {
		values.to_cost_center = frm.doc.from_cost_center || null;
	}
	if (type === CARRY_FORWARD) {
		values.to_account = frm.doc.from_account || null;
	}
	if (type === SAME_MONTH) {
		values.to_month = frm.doc.from_month || null;
	}
	const changed = Object.keys(values).filter((field) => (frm.doc[field] || null) !== values[field]);
	const done = changed.length
		? frm.set_value(Object.fromEntries(changed.map((field) => [field, values[field]])))
		: Promise.resolve();
	return done.then(() => refresh_figures(frm));
}

const refresh_figures = frappe.utils.debounce((frm) => {
	if (frm.doc.docstatus !== 0 || !is_transfer(frm)) return;
	const filled = [...FROM_SIDE, ...TO_SIDE].every((field) => frm.doc[field]);
	if (!filled) {
		clear(frm, FIGURES);
		return;
	}
	frm.call({ method: "get_figures", doc: frm.doc }).then((r) => {
		if (!r.message) return;
		frm.set_value(r.message).then(() => warn_if_too_much(frm));
	});
}, 300);

function warn_if_too_much(frm) {
	const too_much = frm.doc.amount && frm.doc.amount > (frm.doc.left_to_move || 0) + 0.005;
	frm.set_df_property(
		"amount",
		"description",
		too_much
			? `<span class="text-danger">${__("More than the {0} left to move from {1}.", [
					format_currency(frm.doc.left_to_move || 0),
					__(frm.doc.from_month),
			  ])}</span>`
			: ""
	);
}
