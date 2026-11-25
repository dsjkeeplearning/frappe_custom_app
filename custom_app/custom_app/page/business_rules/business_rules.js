// The business rules in plain words, for System Managers (RULES.md XX-06, XX-07).
// The server sends the rules from RULES.md and what was set up on this site.
// Page scripts share one global scope, so everything here is kept inside a function.
(() => {
frappe.pages["business-rules"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Business Rules"),
		single_column: true,
	});
	new BusinessRules(page);
};

// The main path of each tab, and where a document is stopped. Kinds: person, app, record.
const FLOWS = {
	budget: {
		steps: [
			["Master Budget", "a limit per department", "record"],
			["Budget Upload", "approved by finance", "person"],
			["Budget per month", "one per account", "record"],
			["Request checked", "against its own month", "app"],
			["Budget used", "counted once", "record"],
		],
		stops: ["Over the Master Budget", "Month has too little left", "Cut below what is used"],
	},
	purchase: {
		steps: [
			["Purchase request", "by an employee", "person"],
			["Verified", "for some cost centers", "person"],
			["Approved", "by the expense approver", "person"],
			["Quotation", "never above the request", "record"],
			["Purchase order", "approved by procurement", "person"],
			["Receipt", "against the order", "record"],
		],
		stops: ["No budget for the account", "Backdated", "Nothing ordered in 30 days", "Account differs from request"],
	},
	payment: {
		steps: [
			["Purchase invoice", "against the order", "record"],
			["Approved", "by finance", "person"],
			["Payment", "against what is due", "record"],
			["Approved", "by the AP manager", "person"],
		],
		stops: ["No purchase order", "Account differs", "No reference", "Amount left over"],
	},
	people: {
		steps: [
			["Check-in", "by the employee", "person"],
			["Attendance", "marked by the shift", "app"],
			["Attendance sheet", "in payroll codes", "record"],
			["Payslips imported", "by HR", "person"],
			["Payslip", "private to the employee", "record"],
		],
		stops: ["Check-in from the app not allowed", "Own leave or shift approved", "File name not understood"],
	},
	access: {
		steps: [
			["Draft", "by the maker", "person"],
			["Approved", "by another person", "person"],
			["Submitted", "final", "record"],
			["Cancelled", "by the approver", "person"],
		],
		stops: ["Rejected", "Wrong role", "Own draft"],
	},
	vendor: {
		steps: [
			["Vendor form", "on the website", "person"],
			["Vendor", "gets a code", "app"],
			["Emails", "from the company's mailbox", "app"],
			["Dashboards", "for the user's companies", "record"],
		],
		stops: ["Tax or bank details missing", "No company permission"],
	},
	site: {
		steps: [
			["Changed in the Desk", "script, workflow, field", "person"],
			["Read from the site", "each time this opens", "app"],
			["Compared with the app", "and shown below", "record"],
		],
		stops: ["Job stopped or failing"],
	},
	trust: {
		steps: [
			["Rule", "with its own number", "record"],
			["Test", "that proves it", "app"],
			["Code", "named by the rule", "record"],
			["Plain words", "on this page", "person"],
		],
		stops: ["Rule without plain words", "Test without a rule", "Custom code without a rule"],
	},
};

const PROOF = {
	tested: ["green", __("Tested")],
	site: ["blue", __("Seen on the site")],
};
const SOURCE = {
	app: ["green", __("Same as the app")],
	changed: ["orange", __("Differs from the app")],
	site: ["blue", __("Only on the site")],
};
const STATE = {
	on: ["green", __("On")],
	stopped: ["orange", __("Job stopped")],
	failing: ["red", __("Failing")],
};

class BusinessRules {
	constructor(page) {
		this.$body = $(page.body).addClass("br");
		add_style();
		this.$body.html(`<p class="br-note">${esc(__("Loading"))}</p>`);
		frappe
			.xcall("custom_app.custom_app.page.business_rules.business_rules.get")
			.then((data) => this.show(data));
	}

	show(data) {
		this.data = data;
		this.$body.html(`
			<div class="br-head">
				<p class="br-lead">${esc(
					__("{0} rules of this site. Only System Managers see this page.", [data.rules.length])
				)}</p>
				<div class="br-tools">
					<input type="search" class="form-control input-sm" aria-label="${esc(__("Search the rules"))}"
						placeholder="${esc(__("Search the rules"))}">
				</div>
			</div>
			<div class="br-tabs" role="tablist">${data.tabs.map((tab) => this.tab_html(tab)).join("")}</div>
			<div class="br-panel" role="tabpanel" tabindex="0"></div>`);
		this.$panel = this.$body.find(".br-panel");
		this.bind();
		const linked = data.rules.find((rule) => rule.id === window.location.hash.slice(1));
		const tab = linked && data.tabs.find((t) => t.groups.includes(linked.group));
		this.open((tab || data.tabs[0]).key);
		if (linked) this.$panel.find(`#${linked.id}`).addClass("br-rule--linked")[0].scrollIntoView({ block: "center" });
	}

	tab_html(tab) {
		const count = this.data.rules.filter((rule) => tab.groups.includes(rule.group)).length;
		return `<button role="tab" data-key="${tab.key}">${esc(__(tab.label))} <span>${count}</span></button>`;
	}

	bind() {
		const tabs = this.$body.find("[role=tab]");
		tabs.on("click", (e) => this.open(e.currentTarget.dataset.key));
		tabs.on("keydown", (e) => {
			const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
			if (!step) return;
			const next = tabs[(tabs.index(e.currentTarget) + step + tabs.length) % tabs.length];
			next.click();
			next.focus();
		});
		const $search = this.$body.find(".br-tools input");
		$search.on("input", frappe.utils.debounce(() => this.search($search.val().trim()), 150));
		this.$panel.on("click", ".br-rule__id", (e) => {
			const id = e.currentTarget.textContent;
			frappe.utils.copy_to_clipboard(`${window.location.origin}${window.location.pathname}#${id}`);
		});
	}

	open(key) {
		this.key = key;
		this.$body.find("[role=tab]").each((_, el) => {
			const on = el.dataset.key === key;
			el.setAttribute("aria-selected", on);
			el.tabIndex = on ? 0 : -1;
		});
		const tab = this.data.tabs.find((t) => t.key === key);
		this.$panel.html(
			flow_html(key) +
				this.groups_html(this.data.rules.filter((rule) => tab.groups.includes(rule.group))) +
				(key === "site" ? site_html(this.data.site) : "")
		);
	}

	search(term) {
		this.$body.find(".br-tabs").toggle(!term);
		if (!term) return this.open(this.key);
		const words = term.toLowerCase();
		const found = this.data.rules.filter((rule) =>
			`${rule.id} ${rule.title} ${rule.plain}`.toLowerCase().includes(words)
		);
		this.$panel.html(
			`<p class="br-note" role="status">${esc(__("{0} rules found", [found.length]))}</p>` + this.groups_html(found)
		);
	}

	groups_html(rules) {
		return [...new Set(rules.map((rule) => rule.group))]
			.map((key) => {
				const group = this.data.groups[key];
				return `<section>
					<h3>${esc(__(group.name))}</h3>
					<p class="br-note">${esc(__(group.summary))}</p>
					<ol>${rules.filter((rule) => rule.group === key).map(rule_html).join("")}</ol>
				</section>`;
			})
			.join("");
	}
}

function rule_html(rule) {
	return `<li class="br-rule" id="${rule.id}">
		<button class="br-rule__id" title="${esc(__("Copy a link to this rule"))}">${rule.id}</button>
		<div>
			<h4>${esc(__(rule.title))}</h4>
			<p>${esc(__(rule.plain))}</p>
		</div>
		${PROOF[rule.proof] ? pill(PROOF[rule.proof]) : ""}
	</li>`;
}

function flow_html(key) {
	const flow = FLOWS[key];
	return `<div class="br-flow">
		<ol>${flow.steps
			.map(
				([label, sub, kind]) =>
					`<li class="br-step br-step--${kind}"><b>${esc(__(label))}</b><span>${esc(__(sub))}</span></li>`
			)
			.join("")}</ol>
		<p><b>${esc(__("Stopped when"))}</b> ${flow.stops.map((stop) => `<span>${esc(__(stop))}</span>`).join("")}</p>
	</div>`;
}

// This site as it is now -----------------------------------------------------

function site_html(site) {
	return `<section class="br-site">
		<h3>${esc(__("This site, as it is now"))}</h3>
		${table("Settings", ["Setting", "Value"], site.settings.map((s) => [esc(__(s.label)), esc(__(s.value))]))}
		${table("Workflows", ["Workflow", "Steps", "Compared with the app"], site.workflows.map(workflow_row))}
		${table(
			"Scripts and notifications",
			["Name", "Runs on", "State"],
			[...site.scripts, ...site.notifications].map((s) => [esc(s.name), esc(s.runs), pill(STATE[s.state])])
		)}
		${table(
			"Fields changed on the site",
			["Document", "Field", "Change"],
			site.fields.map((f) => [esc(__(f.doctype)), esc(f.field), esc(__(f.change))])
		)}
	</section>`;
}

function workflow_row(workflow) {
	const steps = workflow.steps.map(
		(step) => `<li>${esc(step.state)} &rarr; ${esc(step.next_state)} <i>${esc(step.action)}, ${esc(step.allowed)}</i></li>`
	);
	return [
		`${esc(workflow.name)}<br><i>${esc(__(workflow.document_type))}</i>`,
		`<ul>${steps.join("")}</ul>`,
		pill(SOURCE[workflow.source]),
	];
}

function table(title, heads, rows) {
	const body = rows.length
		? rows.map((cells) => `<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")
		: `<tr><td colspan="${heads.length}">${esc(__("None"))}</td></tr>`;
	return `<h4>${esc(__(title))}</h4><div class="br-scroll"><table class="table table-bordered">
		<thead><tr>${heads.map((head) => `<th>${esc(__(head))}</th>`).join("")}</tr></thead>
		<tbody>${body}</tbody></table></div>`;
}

function pill([colour, label]) {
	return `<span class="indicator-pill no-indicator-dot ${colour}">${esc(label)}</span>`;
}

function esc(text) {
	return frappe.utils.escape_html(text == null ? "" : String(text));
}

function add_style() {
	if (document.getElementById("br-style")) return;
	$(`<style id="br-style">
		.br { max-width: 1080px; margin: 0 auto; padding: var(--padding-md) var(--padding-md) 64px; color: var(--text-color); }
		.br h3 { margin: 32px 0 4px; font-size: var(--text-xl); }
		.br h4 { margin: 0 0 2px; font-size: var(--text-base); font-weight: 600; }
		.br ol, .br ul { margin: 0; padding: 0; list-style: none; }
		.br-note, .br-lead { margin: 0; color: var(--text-muted); max-width: 70ch; }
		.br-head { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; }
		.br-tools { display: flex; gap: 8px; }
		.br-tools input { width: 220px; }
		.br-tabs { display: flex; gap: 4px; margin: 16px 0; overflow-x: auto; border-bottom: 1px solid var(--border-color); }
		.br-tabs button { flex: none; padding: 8px 10px; border: 0; border-bottom: 2px solid transparent; background: none;
			color: var(--text-muted); white-space: nowrap; }
		.br-tabs button[aria-selected=true] { color: var(--text-color); border-bottom-color: var(--text-color); }
		.br-tabs span { font-size: var(--text-xs); }
		.br-panel:focus { outline: none; }
		.br-flow { padding: 16px; border: 1px solid var(--border-color); border-radius: var(--border-radius-md);
			background: var(--fg-color); }
		.br-flow ol { display: flex; flex-wrap: wrap; gap: 10px 28px; }
		.br-step { position: relative; display: flex; flex-direction: column; padding: 8px 12px;
			border: 1px solid var(--border-color); border-left-width: 3px; border-radius: var(--border-radius); }
		.br-step span { font-size: var(--text-sm); color: var(--text-muted); }
		.br-step--person { border-left-color: var(--orange-500); }
		.br-step--app { border-left-color: var(--blue-500); }
		.br-step--record { border-left-color: var(--green-500); }
		.br-step:not(:last-child)::after { content: "\\2192"; position: absolute; right: -22px; top: 50%;
			transform: translateY(-50%); color: var(--text-muted); }
		.br-flow p { display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 14px 0 0; font-size: var(--text-sm); }
		.br-flow p span { color: var(--red-600); }
		.br-rule { display: grid; grid-template-columns: 68px 1fr auto; gap: 12px; align-items: start; padding: 12px 0;
			border-bottom: 1px solid var(--border-color); scroll-margin-top: 120px; }
		.br-rule--linked { background: var(--bg-yellow); }
		.br-rule p { margin: 0; max-width: 70ch; }
		.br-rule__id { padding: 1px 6px; border: 0; border-radius: 4px; background: var(--control-bg);
			color: var(--text-muted); font-size: var(--text-xs); }
		.br-site h4 { margin-top: 20px; }
		.br-scroll { overflow-x: auto; }
		.br-site table { margin: 6px 0 0; }
		.br-site i { color: var(--text-muted); }
		@media (max-width: 640px) { .br-rule { grid-template-columns: 1fr; gap: 4px; } .br-tools input { width: 150px; } }
	</style>`).appendTo("head");
}
})();
