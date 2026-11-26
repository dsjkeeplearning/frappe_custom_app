// The business rules in plain words, for System Managers (RULES.md XX-06, XX-07).
// The server sends the rules from RULES.md and what was set up on this site.
// Each tab opens on a diagram of its part of the work, with dots that move along
// the paths a document takes. The dots stop for a reader who asks for less motion.
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

// Each node: column, row, label, a short line under it, and its kind.
// Kinds: person (someone acts), app (the app acts), record (a document), stop (refused).
// Each run: the nodes a document passes, and how it ends (go, wait or stop).
const FLOWS = {
	budget: {
		summary: "Finance sets the Master Budget and uploads each department's budget. Every purchase request is then checked against its own month.",
		nodes: {
			master: [0, 0, "Master Budget", "a limit per department", "person"],
			upload: [1, 0, "Budget uploaded", "approved by finance", "person"],
			month: [2, 0, "Budget per month", "from the monthly split", "record"],
			check: [3, 0, "Request checked", "against its own month", "app"],
			used: [4, 0, "Budget used", "counted once", "record"],
			over: [1, 1, "Over the limit", "the upload is refused", "stop"],
			moved: [2, 1, "Reallocation", "moves money to a month", "person"],
			short: [3, 1, "Too little left", "the request is refused", "stop"],
		},
		edges: [["master", "upload"], ["upload", "month"], ["month", "check"], ["check", "used"], ["upload", "over"],
			["moved", "month"], ["check", "short"]],
		runs: [
			[["master", "upload", "month", "check", "used"], "go"],
			[["moved", "month", "check", "used"], "wait"],
			[["master", "upload", "over"], "stop"],
			[["month", "check", "short"], "stop"],
		],
	},
	purchase: {
		summary: "An employee raises a purchase request. It is verified where its cost center needs it, approved, quoted and ordered.",
		nodes: {
			request: [0, 0, "Purchase request", "raised by an employee", "person"],
			approved: [1, 0, "Approved", "by the expense approver", "person"],
			quote: [2, 0, "Quotation", "never above the request", "record"],
			order: [3, 0, "Purchase order", "approved by procurement", "person"],
			receipt: [4, 0, "Receipt", "against the order", "record"],
			refused: [0, 1, "Refused", "no budget, or backdated", "stop"],
			verified: [1, 1, "Verified", "for some cost centers", "person"],
			cancelled: [2, 1, "Cancelled", "nothing ordered in 30 days", "app"],
		},
		edges: [["request", "approved"], ["approved", "quote"], ["quote", "order"], ["order", "receipt"], ["request", "refused"],
			["request", "verified"], ["verified", "approved"], ["approved", "cancelled"]],
		runs: [
			[["request", "approved", "quote", "order", "receipt"], "go"],
			[["request", "verified", "approved", "quote"], "wait"],
			[["request", "refused"], "stop"],
			[["approved", "cancelled"], "stop"],
		],
	},
	payment: {
		summary: "Finance books the vendor's invoice against its order, and accounts payable pays only what is due. A claim is approved twice before it is paid.",
		nodes: {
			invoice: [0, 0, "Purchase invoice", "against its order", "record"],
			finance: [1, 0, "Approved", "by finance", "person"],
			payment: [2, 0, "Payment", "against what is due", "record"],
			paid: [3, 0, "Paid", "approved by the AP manager", "person"],
			claim: [0, 1, "Expense claim", "on the department's budget", "person"],
			twice: [1, 1, "Approved twice", "manager, then finance", "person"],
			refused: [2, 1, "Refused", "no reference, or left over", "stop"],
		},
		edges: [["invoice", "finance"], ["finance", "payment"], ["payment", "paid"], ["claim", "twice"], ["twice", "payment"],
			["payment", "refused"]],
		runs: [
			[["invoice", "finance", "payment", "paid"], "go"],
			[["claim", "twice", "payment", "paid"], "wait"],
			[["invoice", "finance", "payment", "refused"], "stop"],
		],
	},
	people: {
		summary: "Check-ins become attendance, attendance becomes the sheet payroll uses, and payslips come back from the payroll vendor.",
		nodes: {
			checkin: [0, 0, "Check-in", "in the office or the app", "person"],
			attendance: [1, 0, "Attendance", "marked by the shift", "app"],
			sheet: [2, 0, "Attendance sheet", "in payroll codes", "record"],
			imported: [3, 0, "Payslips imported", "by HR", "person"],
			payslip: [4, 0, "Payslip", "seen by its employee only", "record"],
			blocked: [0, 1, "App not allowed", "the check-in is refused", "stop"],
			request: [1, 1, "Attendance request", "for the leave approver", "person"],
			skipped: [3, 1, "File skipped", "its name is not understood", "stop"],
		},
		edges: [["checkin", "attendance"], ["attendance", "sheet"], ["sheet", "imported"], ["imported", "payslip"],
			["checkin", "blocked"], ["request", "attendance"], ["imported", "skipped"]],
		runs: [
			[["checkin", "attendance", "sheet", "imported", "payslip"], "go"],
			[["request", "attendance", "sheet"], "wait"],
			[["checkin", "blocked"], "stop"],
			[["sheet", "imported", "skipped"], "stop"],
		],
	},
	access: {
		summary: "Each document is approved by its own role, never by the person who made it. Each list shows a role only the records it needs.",
		nodes: {
			draft: [0, 0, "Draft", "made by an employee", "person"],
			approved: [1, 0, "Approved", "by another person", "person"],
			submitted: [2, 0, "Submitted", "final", "record"],
			listed: [3, 0, "Listed", "to the roles that need it", "app"],
			verified: [1, 1, "Verified", "when a verifier is named", "person"],
			rejected: [2, 1, "Rejected", "stays a draft", "stop"],
		},
		edges: [["draft", "approved"], ["approved", "submitted"], ["submitted", "listed"], ["draft", "verified"],
			["verified", "approved"], ["verified", "rejected"]],
		runs: [
			[["draft", "approved", "submitted", "listed"], "go"],
			[["draft", "verified", "approved", "submitted"], "wait"],
			[["draft", "verified", "rejected"], "stop"],
		],
	},
	vendor: {
		summary: "A vendor registers on the website and gets its code. Emails and letter heads follow the company of each document.",
		nodes: {
			form: [0, 0, "Vendor form", "on the website", "person"],
			vendor: [1, 0, "Vendor", "coded by company and year", "app"],
			document: [2, 0, "Document", "order, invoice or slip", "record"],
			email: [3, 0, "Email", "from the company's mailbox", "app"],
			missing: [0, 1, "Details missing", "tax, contact or bank", "stop"],
			letterhead: [3, 1, "Letter head", "of the same company", "app"],
		},
		edges: [["form", "vendor"], ["vendor", "document"], ["document", "email"], ["form", "missing"],
			["document", "letterhead"]],
		runs: [
			[["form", "vendor", "document", "email"], "go"],
			[["vendor", "document", "letterhead"], "go"],
			[["form", "missing"], "stop"],
		],
	},
	site: {
		summary: "Much of the logic was set up in the Desk. This tab reads it each time it opens and compares it with the app.",
		nodes: {
			desk: [0, 0, "Changed in the Desk", "scripts, workflows, fields", "person"],
			read: [1, 0, "Read from the site", "each time this opens", "app"],
			compared: [2, 0, "Compared", "with the app", "app"],
			shown: [3, 0, "Shown below", "never a field's value", "record"],
			stopped: [2, 1, "Job stopped", "or failing", "stop"],
		},
		edges: [["desk", "read"], ["read", "compared"], ["compared", "shown"], ["compared", "stopped"]],
		runs: [
			[["desk", "read", "compared", "shown"], "go"],
			[["read", "compared", "stopped"], "stop"],
		],
	},
	trust: {
		summary: "Every rule has its number, the code that keeps it and the test that proves it. A check fails when they drift apart.",
		nodes: {
			rule: [0, 0, "Rule", "with its own number", "record"],
			code: [1, 0, "Code", "named by the rule", "record"],
			test: [2, 0, "Test", "proves the rule", "app"],
			words: [3, 0, "Plain words", "on this page", "person"],
			fails: [2, 1, "Check fails", "a rule, test or code is missing", "stop"],
		},
		edges: [["rule", "code"], ["code", "test"], ["test", "words"], ["test", "fails"]],
		runs: [
			[["rule", "code", "test", "words"], "go"],
			[["rule", "code", "test", "fails"], "stop"],
		],
	},
};

const COL = 196;
const ROW = 108;
const NODE_W = 166;
const NODE_H = 66;
const SUB_FIT = 30;

const ICONS = {
	person: `<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>`,
	app: `<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>`,
	record: `<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>`,
	stop: `<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>`,
};
const SEARCH_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
	stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>`;

const STATE = { on: ["green", __("On")], stopped: ["orange", __("Job stopped")], failing: ["red", __("Failing")] };
const SOURCE = {
	app: ["green", __("Same as the app")],
	changed: ["orange", __("Differs from the app")],
	site: ["blue", __("Only on the site")],
};

class BusinessRules {
	constructor(page) {
		this.$body = $(page.body).addClass("br");
		add_style();
		this.$body.html(`<p class="br-muted">${esc(__("Loading"))}</p>`);
		frappe
			.xcall("custom_app.custom_app.page.business_rules.business_rules.get")
			.then((data) => this.show(data));
	}

	show(data) {
		this.data = data;
		this.$body.html(`
			<div class="br-head">
				<p class="br-lead">${esc(
					__(
						"Every business rule of this site, in plain words. {0} rules in {1} areas. Each rule has an id, such as PR-06, that the documents cite.",
						[data.rules.length, data.tabs.length]
					)
				)}</p>
				<label class="br-search">${SEARCH_ICON}
					<input type="search" placeholder="${esc(__("Search the rules, or type an id"))}"
						aria-label="${esc(__("Search the rules"))}">
				</label>
			</div>
			<div class="br-tabs" role="tablist">${data.tabs.map((tab) => this.tab_html(tab)).join("")}</div>
			<div class="br-panel" role="tabpanel" tabindex="0"></div>`);
		this.$panel = this.$body.find(".br-panel");
		this.bind();
		const linked = this.rule(window.location.hash.slice(1));
		linked ? this.go_to(linked) : this.open(data.tabs[0].key);
	}

	tab_html(tab) {
		const count = this.data.rules.filter((rule) => tab.groups.includes(rule.group)).length;
		return `<button role="tab" id="br-tab-${tab.key}" data-key="${tab.key}">
			${esc(__(tab.label))} <span class="br-count">${count}</span></button>`;
	}

	rule(id) {
		return id && this.data.rules.find((rule) => rule.id === id.toUpperCase());
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
		const $search = this.$body.find(".br-search input");
		$search.on("input", frappe.utils.debounce(() => this.search($search.val().trim()), 150));
		this.$panel.on("click", ".br-rule__id", (e) => {
			const id = e.currentTarget.textContent;
			frappe.utils.copy_to_clipboard(`${window.location.origin}${window.location.pathname}#${id}`);
			history.replaceState(null, "", `#${id}`);
		});
		this.$panel.on("click", ".br-flow__pause", (e) => toggle_motion(e.currentTarget));
	}

	open(key) {
		this.key = key;
		this.$body.find(".br-tabs").show();
		this.$body.find("[role=tab]").each((_, el) => {
			const on = el.dataset.key === key;
			el.setAttribute("aria-selected", on);
			el.tabIndex = on ? 0 : -1;
		});
		const tab = this.data.tabs.find((t) => t.key === key);
		this.$panel.attr("aria-labelledby", `br-tab-${key}`).html(
			flow_html(key) +
				this.groups_html(this.data.rules.filter((rule) => tab.groups.includes(rule.group))) +
				(key === "site" ? site_html(this.data.site) : "")
		);
	}

	go_to(rule) {
		this.open(this.data.tabs.find((tab) => tab.groups.includes(rule.group)).key);
		const row = this.$panel.find(`#${rule.id}`).addClass("br-rule--linked")[0];
		row.scrollIntoView({ block: "center" });
	}

	search(term) {
		if (!term) return this.open(this.key);
		const exact = this.rule(term);
		if (exact) return this.go_to(exact);
		const words = term.toLowerCase();
		const found = this.data.rules.filter((rule) =>
			`${rule.id} ${rule.title} ${rule.plain}`.toLowerCase().includes(words)
		);
		this.$body.find(".br-tabs").hide();
		this.$panel.removeAttr("aria-labelledby").html(`
			<p class="br-muted br-found" role="status">${esc(
				found.length === 1 ? __("1 rule matches.") : __("{0} rules match.", [found.length])
			)}</p>${this.groups_html(found, term)}`);
	}

	groups_html(rules, term) {
		return [...new Set(rules.map((rule) => rule.group))]
			.map((key) => {
				const group = this.data.groups[key];
				return `<section class="br-group">
					<h2>${esc(__(group.name))}</h2>
					${term ? "" : `<p class="br-muted">${esc(__(group.summary))}</p>`}
					<ol>${rules.filter((rule) => rule.group === key).map((rule) => rule_html(rule, term)).join("")}</ol>
				</section>`;
			})
			.join("");
	}
}

function rule_html(rule, term) {
	return `<li class="br-rule" id="${rule.id}">
		<button class="br-rule__id" title="${esc(__("Copy a link to this rule"))}">${rule.id}</button>
		<div>
			<h3>${mark(rule.title, term)}</h3>
			<p>${mark(rule.plain, term)}</p>
		</div>
	</li>`;
}

function mark(text, term) {
	const safe = esc(__(text));
	if (!term) return safe;
	const at = safe.toLowerCase().indexOf(esc(term).toLowerCase());
	if (at < 0) return safe;
	const end = at + esc(term).length;
	return `${safe.slice(0, at)}<mark>${safe.slice(at, end)}</mark>${safe.slice(end)}`;
}

// The diagram ----------------------------------------------------------------

function flow_html(key) {
	const flow = FLOWS[key];
	const at = (id) => ({ x: 16 + flow.nodes[id][0] * COL, y: 24 + flow.nodes[id][1] * ROW });
	const width = 32 + Math.max(...Object.values(flow.nodes).map((n) => n[0])) * COL + NODE_W;
	const height = 48 + Math.max(...Object.values(flow.nodes).map((n) => n[1])) * ROW + NODE_H;
	const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

	const edges = flow.edges
		.map(([a, b]) => `<path class="br-flow__edge" d="${edge(at(a), at(b))}" marker-end="url(#br-arrow-${key})"/>`)
		.join("");
	const dots = still
		? ""
		: flow.runs
				.map(([path, tone], i) => {
					const d = path.slice(1).map((id, j) => run(at(path[j]), at(id), j === 0)).join(" ");
					const dur = 2.2 * (path.length - 1);
					const begin = (i * 1.7).toFixed(1);
					return `<circle r="6" class="br-flow__dot br-flow__dot--${tone}" opacity="0">
						<animateMotion dur="${dur}s" begin="${begin}s" repeatCount="indefinite" path="${d}"/>
						<animate attributeName="opacity" dur="${dur}s" begin="${begin}s" repeatCount="indefinite"
							values="0;1;1;0" keyTimes="0;0.06;0.9;1"/>
					</circle>`;
				})
				.join("");
	const nodes = Object.entries(flow.nodes)
		.map(([id, [, , label, sub, kind]]) => {
			const { x, y } = at(id);
			return `<g class="br-flow__node br-flow__node--${kind}">
				<rect x="${x}" y="${y}" width="${NODE_W}" height="${NODE_H}" rx="8"/>
				<svg x="${x + 10}" y="${y + 12}" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
					stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="br-flow__icon">${ICONS[kind]}</svg>
				<text x="${x + 30}" y="${y + 24}" class="br-flow__label">${esc(__(label))}</text>
				${lines(__(sub))
					.map((line, i) => `<text x="${x + 10}" y="${y + 44 + i * 14}" class="br-flow__sub">${esc(line)}</text>`)
					.join("")}
			</g>`;
		})
		.join("");

	return `<figure class="br-flow">
		<div class="br-flow__scroll">
			<svg viewBox="0 0 ${width} ${height}" style="max-width: ${width}px" role="img" aria-label="${esc(__(flow.summary))}">
				<defs><marker id="br-arrow-${key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
					orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker></defs>
				${edges}${dots}${nodes}
			</svg>
		</div>
		<figcaption>
			<span>${esc(__(flow.summary))}</span>
			<span class="br-flow__legend" aria-hidden="true">
				<i class="br-key br-key--go"></i>${esc(__("goes through"))}
				<i class="br-key br-key--wait"></i>${esc(__("waits for a person"))}
				<i class="br-key br-key--stop"></i>${esc(__("stopped"))}
			</span>
			${still ? "" : `<button class="btn btn-default btn-xs br-flow__pause" aria-pressed="false">${esc(__("Pause"))}</button>`}
		</figcaption>
	</figure>`;
}

// A line from one node's border to the next: straight along a row or a column, curved otherwise.
function edge(a, b) {
	if (a.y === b.y) {
		const forward = b.x > a.x;
		const y = a.y + NODE_H / 2;
		return `M${forward ? a.x + NODE_W : a.x} ${y} L${forward ? b.x - 2 : b.x + NODE_W + 2} ${y}`;
	}
	const down = b.y > a.y;
	if (a.x === b.x) {
		const x = a.x + NODE_W / 2;
		return `M${x} ${down ? a.y + NODE_H : a.y} L${x} ${down ? b.y - 2 : b.y + NODE_H + 2}`;
	}
	// Across and up or down: leave from the side facing the other node, arrive at its top or bottom.
	const right = b.x > a.x;
	const sx = right ? a.x + NODE_W : a.x;
	const sy = a.y + NODE_H / 2;
	const ex = b.x + NODE_W / 2;
	const ey = down ? b.y - 2 : b.y + NODE_H + 2;
	return `M${sx} ${sy} C${ex} ${sy} ${ex} ${sy} ${ex} ${ey}`;
}

// A dot runs from centre to centre, so it passes under each node it visits.
function run(a, b, first) {
	const ac = { x: a.x + NODE_W / 2, y: a.y + NODE_H / 2 };
	const bc = { x: b.x + NODE_W / 2, y: b.y + NODE_H / 2 };
	const start = first ? `M${ac.x} ${ac.y} ` : "";
	if (ac.x === bc.x || ac.y === bc.y) return `${start}L${bc.x} ${bc.y}`;
	return `${start}C${bc.x} ${ac.y} ${bc.x} ${ac.y} ${bc.x} ${bc.y}`;
}

function lines(text) {
	if (text.length <= SUB_FIT) return [text];
	const words = text.split(" ");
	let first = "";
	while (words.length && `${first} ${words[0]}`.trim().length <= SUB_FIT) first = `${first} ${words.shift()}`.trim();
	return [first, words.join(" ")];
}

function toggle_motion(button) {
	const svg = button.closest(".br-flow").querySelector("svg");
	const paused = button.getAttribute("aria-pressed") === "true";
	paused ? svg.unpauseAnimations() : svg.pauseAnimations();
	button.setAttribute("aria-pressed", String(!paused));
	button.textContent = paused ? __("Pause") : __("Play");
}

// This site, as it is now -------------------------------------------------------

function site_html(site) {
	return `<section class="br-group br-site">
		<h2>${esc(__("This site, as it is now"))}</h2>
		<p class="br-muted">${esc(__("Read from the site when this page opened."))}</p>
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
		(step) =>
			`<li>${esc(step.state)} &rarr; ${esc(step.next_state)} <span class="br-muted">${esc(step.action)}, ${esc(step.allowed)}</span></li>`
	);
	return [
		`${esc(workflow.name)}<br><span class="br-muted">${esc(__(workflow.document_type))}</span>`,
		`<ul>${steps.join("")}</ul>`,
		pill(SOURCE[workflow.source]),
	];
}

function table(title, heads, rows) {
	const body = rows.length
		? rows.map((cells) => `<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")
		: `<tr><td colspan="${heads.length}" class="br-muted">${esc(__("None"))}</td></tr>`;
	return `<h3>${esc(__(title))}</h3><div class="br-table"><table>
		<thead><tr>${heads.map((head) => `<th>${esc(__(head))}</th>`).join("")}</tr></thead>
		<tbody>${body}</tbody></table></div>`;
}

function pill([colour, label]) {
	return `<span class="indicator-pill no-indicator-dot whitespace-nowrap ${colour}">${esc(label)}</span>`;
}

function esc(text) {
	return frappe.utils.escape_html(text == null ? "" : String(text));
}

function add_style() {
	if (document.getElementById("br-style")) return;
	$(`<style id="br-style">
		.br { max-width: 1140px; margin: 0 auto; padding: 8px 16px 64px; color: var(--text-color); }
		.br h2, .br h3, .br p, .br ol, .br ul, .br figure { margin: 0; }
		.br ol, .br ul { padding: 0; list-style: none; }
		.br-muted { color: var(--text-muted); }
		.br-head { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center; justify-content: space-between;
			margin-bottom: 16px; }
		.br-lead { max-width: 37rem; font-size: var(--text-base); line-height: 1.5; color: var(--text-muted); }
		.br-search { display: flex; align-items: center; gap: 8px; margin: 0; padding: 0 12px; height: 32px;
			min-width: 16rem; border-radius: var(--border-radius); background: var(--control-bg); color: var(--text-light); }
		.br-search:focus-within { box-shadow: 0 0 0 2px var(--gray-300); }
		.br-search input { flex: 1; min-width: 0; border: 0; background: none; outline: none;
			font-size: var(--text-sm); color: var(--text-color); }
		.br-tabs { display: flex; gap: 4px; margin-bottom: 20px; overflow-x: auto; scrollbar-width: none;
			border-bottom: 1px solid var(--border-color); }
		.br-tabs::-webkit-scrollbar { display: none; }
		.br-tabs [role=tab] { flex: none; display: flex; align-items: center; gap: 6px; padding: 8px 10px;
			border: 0; border-bottom: 2px solid transparent; background: none; font-size: var(--text-sm);
			font-weight: 500; color: var(--text-muted); white-space: nowrap; }
		.br-tabs [role=tab]:hover { color: var(--heading-color); }
		.br-tabs [aria-selected=true] { color: var(--heading-color); border-bottom-color: var(--heading-color); }
		.br-count { padding: 0 6px; border-radius: 10px; font-size: var(--text-xs); background: var(--subtle-fg);
			color: var(--text-muted); font-variant-numeric: tabular-nums; }
		.br-panel:focus-visible { outline: none; }
		.br .br-flow { margin-bottom: 32px; overflow: hidden; border: 1px solid var(--border-color);
			border-radius: var(--border-radius-lg); background: var(--subtle-accent); }
		.br-flow__scroll { overflow-x: auto; padding: 12px 8px 4px; }
		.br-flow svg { display: block; width: 100%; min-width: 640px; height: auto; margin: 0 auto; }
		.br-flow__edge { fill: none; stroke: var(--gray-400); stroke-width: 1.5; }
		.br-flow marker path { fill: var(--gray-400); }
		.br-flow__node rect { fill: var(--fg-color); stroke: var(--border-color); stroke-width: 1.2; }
		.br-flow__node--person rect { stroke: var(--amber-500); }
		.br-flow__node--app rect { stroke: var(--blue-500); }
		.br-flow__node--stop rect { stroke: var(--red-500); }
		.br-flow__icon { color: var(--text-light); }
		.br-flow__node--person .br-flow__icon { color: var(--amber-500); }
		.br-flow__node--app .br-flow__icon { color: var(--blue-500); }
		.br-flow__node--stop .br-flow__icon { color: var(--red-500); }
		.br-flow__label { font-size: 13px; font-weight: 600; fill: var(--heading-color); }
		.br-flow__sub { font-size: 11px; fill: var(--text-muted); }
		.br-flow__dot { stroke: var(--fg-color); stroke-width: 2; }
		.br-flow__dot--go, .br-key--go { fill: var(--green-600); background: var(--green-600); }
		.br-flow__dot--wait, .br-key--wait { fill: var(--amber-500); background: var(--amber-500); }
		.br-flow__dot--stop, .br-key--stop { fill: var(--red-500); background: var(--red-500); }
		.br-flow figcaption { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; padding: 10px 16px;
			border-top: 1px solid var(--border-color); background: var(--fg-color); font-size: var(--text-sm);
			color: var(--text-muted); }
		.br-flow figcaption > span:first-child { flex: 1 1 24rem; line-height: 1.5; }
		.br-flow__legend { display: flex; align-items: center; gap: 6px; font-size: var(--text-xs); white-space: nowrap; }
		.br-key { display: inline-block; width: 8px; height: 8px; margin-left: 6px; border-radius: 50%; }
		.br-group { margin-bottom: 32px; }
		.br-group h2 { font-size: var(--text-lg); font-weight: 600; color: var(--heading-color); }
		.br-group > p { max-width: 42rem; margin-top: 4px; font-size: var(--text-sm); line-height: 1.5; }
		.br-group > ol { margin-top: 12px; border-top: 1px solid var(--border-color); }
		.br-rule { display: grid; grid-template-columns: 5rem 1fr; gap: 12px; padding: 14px 0;
			border-bottom: 1px solid var(--border-color); scroll-margin-top: 120px; }
		.br-rule--linked { background: var(--subtle-fg); }
		.br-rule__id { align-self: start; justify-self: start; padding: 1px 6px; border: 0;
			border-radius: var(--border-radius-tiny); background: var(--subtle-fg); color: var(--text-muted);
			font-size: var(--text-xs); letter-spacing: 0.04em; font-variant-numeric: tabular-nums; cursor: copy; }
		.br-rule__id:hover { color: var(--heading-color); }
		.br-rule h3 { font-size: var(--text-base); font-weight: 600; color: var(--heading-color); }
		.br-rule p { max-width: 44rem; margin-top: 2px; font-size: var(--text-sm); line-height: 1.55; }
		.br-rule mark { padding: 0 1px; background: var(--yellow-100); color: inherit; }
		.br-found { margin-bottom: 16px; font-size: var(--text-sm); }
		.br-site h3 { margin: 20px 0 6px; font-size: var(--text-base); font-weight: 600; color: var(--heading-color); }
		.br-table { overflow-x: auto; border: 1px solid var(--border-color); border-radius: var(--border-radius-md); }
		.br-table table { width: 100%; font-size: var(--text-sm); }
		.br-table th { padding: 8px 12px; background: var(--subtle-accent); color: var(--text-muted); font-weight: 500;
			text-align: left; border-bottom: 1px solid var(--border-color); }
		.br-table td { padding: 8px 12px; vertical-align: top; border-bottom: 1px solid var(--border-color); }
		.br-table tr:last-child td { border-bottom: 0; }
		@media (max-width: 640px) {
			.br-rule { grid-template-columns: 1fr; gap: 4px; }
			.br-search { min-width: 0; flex: 1 1 100%; }
		}
	</style>`).appendTo("head");
}
})();
