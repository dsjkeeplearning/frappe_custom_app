frappe.pages["finance-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "Finance Dashboard",
		single_column: true,
	});

	if (!document.getElementById("fin-dash-fonts")) {
		const link = document.createElement("link");
		link.id = "fin-dash-fonts";
		link.rel = "stylesheet";
		link.href = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap";
		document.head.appendChild(link);
	}

	if (!document.getElementById("fin-dash-base-style")) {
		const s = document.createElement("style");
		s.id = "fin-dash-base-style";
		s.textContent = `.page-head { display: none !important; }`;
		document.head.appendChild(s);
	}

	window._finDash = new FinanceDashboard(wrapper);
};

// ═══════════════════════════════════════════════════════════════
class FinanceDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.filters = {
			company: "",
			cost_center: "",
			fiscal_year: "",
			period: "month",
			date_from: "",
			date_to: "",
		};
		this._charts = {};
		this.render_shell();
		this._read_url_params();
		this.load_filter_options().then(() => {
			this._apply_url_params_to_ui();
			this.load_all();
		});
	}

	// ─────────────────────────────────────────────────────────────
	// URL / FILTER HELPERS
	// ─────────────────────────────────────────────────────────────
	_read_url_params() {
		const p = new URLSearchParams(window.location.search);
		["company", "cost_center", "fiscal_year", "period", "date_from", "date_to"].forEach((k) => {
			if (p.get(k)) this.filters[k] = p.get(k);
		});
		if (this.filters.date_from && this.filters.date_to) this.filters.period = "custom";
	}

	_apply_url_params_to_ui() {
		if (this.filters.company) document.getElementById("fin-f-company").value = this.filters.company;
		if (this.filters.cost_center) document.getElementById("fin-f-cc").value = this.filters.cost_center;
		if (this.filters.fiscal_year) document.getElementById("fin-f-fy").value = this.filters.fiscal_year;
		if (this.filters.date_from) document.getElementById("fin-f-from").value = this.filters.date_from;
		if (this.filters.date_to) document.getElementById("fin-f-to").value = this.filters.date_to;
		document.querySelectorAll(".fin-period-btn").forEach((b) => {
			b.classList.toggle("active", b.dataset.p === this.filters.period);
		});
		document.getElementById("fin-date-range").style.display =
			this.filters.period === "custom" ? "flex" : "none";
	}

	_sync_url() {
		const p = new URLSearchParams();
		Object.entries(this.filters).forEach(([k, v]) => { if (v) p.set(k, v); });
		window.history.replaceState(null, "", window.location.pathname + (p.toString() ? "?" + p.toString() : ""));
	}

	_common_args() {
		const a = {
			company: this.filters.company,
			cost_center: this.filters.cost_center,
			fiscal_year: this.filters.fiscal_year,
			period: this.filters.period,
		};
		if (this.filters.period === "custom") {
			a.date_from = this.filters.date_from;
			a.date_to = this.filters.date_to;
		}
		return a;
	}

	_fmt(val) {
		if (!val) return "₹0";
		const n = Math.abs(val);
		let s;
		if (n >= 10000000) s = "₹" + (val / 10000000).toFixed(2) + " Cr";
		else if (n >= 100000) s = "₹" + (val / 100000).toFixed(2) + " L";
		else if (n >= 1000) s = "₹" + (val / 1000).toFixed(1) + "K";
		else s = "₹" + parseFloat(val).toFixed(2);
		return s;
	}

	_make_chart(id, config) {
		const el = document.getElementById(id);
		if (!el) return;
		if (this._charts[id]) this._charts[id].destroy();
		this._charts[id] = new Chart(el.getContext("2d"), config);
	}

	// ─────────────────────────────────────────────────────────────
	// REDIRECT HELPERS
	// ─────────────────────────────────────────────────────────────
	_report_url(reportName, extraFilters = {}) {
		const base = `/app/query-report/${encodeURIComponent(reportName)}`;
		const p = new URLSearchParams();
		if (this.filters.company) p.set("company", this.filters.company);
		Object.entries(extraFilters).forEach(([k, v]) => { if (v) p.set(k, v); });
		return p.toString() ? base + "?" + p.toString() : base;
	}

	_go_report(reportName, extraFilters = {}) {
		const filters = {};
		if (this.filters.company) filters.company = this.filters.company;
		if (this.filters.cost_center) filters.cost_center = this.filters.cost_center;
		if (this.filters.fiscal_year) filters.fiscal_year = this.filters.fiscal_year;
		Object.assign(filters, extraFilters);
		frappe.set_route("query-report", reportName, filters);
	}

	_go_list(doctype, extraFilters = {}) {
		const filters = {};
		if (this.filters.company) filters.company = this.filters.company;
		Object.assign(filters, extraFilters);
		frappe.set_route("List", doctype, filters);
	}

	_go_form(doctype, name) {
		frappe.set_route("Form", doctype, name);
	}

	_goto_ap(extraFilters = {}) {
		const today = new Date().toISOString().split("T")[0];
		this._go_report("Accounts Payable", {
			report_date: today,
			ageing_based_on: document.getElementById("fin-ageing-basis")?.value || "posting_date",
			...extraFilters,
		});
	}

	_goto_bvr(extraFilters = {}) {
		this._go_report("Budget Committed Actual Report", {
			fiscal_year: this.filters.fiscal_year,
			cost_center: this.filters.cost_center,
			...extraFilters,
		});
	}

	// ─────────────────────────────────────────────────────────────
	// SHELL
	// ─────────────────────────────────────────────────────────────
	render_shell() {
		$(this.wrapper).find(".page-content").html(`
<style>
:root {
	--bg:#f0f2f5; --card:#fff; --border:#e2e6ea;
	--ink:#1a1d23; --muted:#6c757d; --light:#adb5bd;
	--blue:#2563eb; --blue-lt:#eff6ff;
	--green:#16a34a; --green-lt:#f0fdf4;
	--red:#dc2626; --red-lt:#fef2f2;
	--amber:#d97706; --amber-lt:#fffbeb;
	--purple:#7c3aed; --purple-lt:#f5f3ff;
	--teal:#0d9488; --teal-lt:#f0fdfa;
	--orange:#ea580c; --orange-lt:#fff7ed;
	--r:12px; --r-sm:8px;
	--shadow:0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04);
	--shadow-md:0 4px 16px rgba(0,0,0,.08);
}
*{box-sizing:border-box;margin:0;padding:0;}
#fin-root{background:var(--bg);min-height:100vh;padding:0 0 60px;font-family:'Inter',sans-serif;color:var(--ink);}

.fin-header{background:linear-gradient(135deg,#0f172a 0%,#1e293b 60%,#0f2027 100%);padding:22px 28px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;}
.fin-header-left h1{font-size:22px;font-weight:700;color:#fff;letter-spacing:-.4px;}
.fin-header-left h1 span{color:#38bdf8;}
.fin-header-left p{font-size:11px;color:rgba(255,255,255,.4);margin-top:3px;letter-spacing:.5px;text-transform:uppercase;}
.fin-header-actions{display:flex;gap:8px;align-items:center;}
.fin-btn{display:flex;align-items:center;gap:6px;padding:8px 16px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);border-radius:var(--r-sm);font-size:13px;font-weight:500;color:#fff;cursor:pointer;transition:all .15s;text-decoration:none;}
.fin-btn:hover{background:rgba(255,255,255,.15);}

.fin-filter-bar{background:#fff;border-bottom:1px solid var(--border);padding:12px 28px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;position:sticky;top:0;z-index:100;}
.fin-filter-group{display:flex;align-items:center;gap:6px;}
.fin-filter-label{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;}
.fin-filter-select,.fin-filter-input{padding:6px 10px;border:1px solid var(--border);border-radius:var(--r-sm);font-size:12px;font-family:'Inter',sans-serif;color:var(--ink);background:#fff;outline:none;cursor:pointer;transition:border-color .15s;min-width:130px;}
.fin-filter-select:focus,.fin-filter-input:focus{border-color:var(--blue);}
.fin-period-toggle{display:flex;background:var(--bg);border:1px solid var(--border);border-radius:var(--r-sm);overflow:hidden;}
.fin-period-btn{padding:6px 12px;font-size:12px;font-weight:500;border:none;background:transparent;color:var(--muted);cursor:pointer;transition:all .15s;border-right:1px solid var(--border);}
.fin-period-btn:last-child{border-right:none;}
.fin-period-btn.active{background:var(--blue);color:#fff;}
.fin-filter-sep{width:1px;height:24px;background:var(--border);margin:0 6px;}

.fin-tabs{background:#fff;border-bottom:2px solid var(--border);padding:0 28px;display:flex;gap:0;overflow-x:auto;}
.fin-tab{padding:14px 20px;font-size:13px;font-weight:600;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .15s;white-space:nowrap;display:flex;align-items:center;gap:6px;}
.fin-tab:hover{color:var(--ink);}
.fin-tab.active{color:var(--blue);border-bottom-color:var(--blue);}

.fin-body{padding:24px 28px;}
.fin-section{display:none;}
.fin-section.active{display:block;}

.fin-section-hd{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;}
.fin-section-title{font-size:16px;font-weight:700;color:var(--ink);}
.fin-section-sub{font-size:12px;color:var(--muted);margin-top:2px;}
.fin-section-link{font-size:12px;color:var(--blue);cursor:pointer;text-decoration:none;display:flex;align-items:center;gap:4px;padding:6px 12px;border:1px solid var(--blue);border-radius:var(--r-sm);transition:all .15s;}
.fin-section-link:hover{background:var(--blue-lt);}

.fin-g4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;}
.fin-g3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
.fin-g2{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.fin-g2-1{display:grid;grid-template-columns:2fr 1fr;gap:16px;}
@media(max-width:1200px){.fin-g4{grid-template-columns:repeat(2,1fr);}.fin-g2-1{grid-template-columns:1fr;}}
@media(max-width:768px){.fin-g4,.fin-g3,.fin-g2,.fin-g2-1{grid-template-columns:1fr;}}

.fin-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:20px;box-shadow:var(--shadow);transition:box-shadow .2s;}
.fin-card:hover{box-shadow:var(--shadow-md);}
.fin-card-hd{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;}
.fin-card-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);}
.fin-card-icon{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;}

.fin-card-link{cursor:pointer;position:relative;}
.fin-card-link::after{content:"↗";position:absolute;top:14px;right:14px;font-size:11px;color:var(--light);opacity:0;transition:opacity .15s;}
.fin-card-link:hover::after{opacity:1;}
.fin-card-link:hover{border-color:var(--blue);}

.fin-kpi-val{font-size:28px;font-weight:700;font-family:'JetBrains Mono',monospace;letter-spacing:-1px;line-height:1.1;}
.fin-kpi-label{font-size:11px;color:var(--muted);margin-top:4px;}
.fin-kpi-sub{font-size:11px;color:var(--light);margin-top:8px;padding-top:8px;border-top:1px solid var(--border);}

.fb{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;}
.fb-blue{background:var(--blue-lt);color:var(--blue);}
.fb-green{background:var(--green-lt);color:var(--green);}
.fb-red{background:var(--red-lt);color:var(--red);}
.fb-amber{background:var(--amber-lt);color:var(--amber);}
.fb-purple{background:var(--purple-lt);color:var(--purple);}
.fb-teal{background:var(--teal-lt);color:var(--teal);}
.fb-orange{background:var(--orange-lt);color:var(--orange);}

.fin-risk-high{background:#fef2f2;color:#dc2626;padding:4px 14px;border-radius:20px;font-size:14px;font-weight:700;}
.fin-risk-medium{background:#fffbeb;color:#d97706;padding:4px 14px;border-radius:20px;font-size:14px;font-weight:700;}
.fin-risk-low{background:#f0fdf4;color:#16a34a;padding:4px 14px;border-radius:20px;font-size:14px;font-weight:700;}

.fin-prog-wrap{background:var(--bg);border-radius:4px;height:8px;overflow:hidden;margin-top:4px;}
.fin-prog-fill{height:100%;border-radius:4px;transition:width .6s ease;}

.fin-tbl{width:100%;border-collapse:collapse;font-size:12px;}
.fin-tbl th{padding:9px 12px;text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);border-bottom:2px solid var(--border);white-space:nowrap;}
.fin-tbl td{padding:10px 12px;border-bottom:1px solid var(--border);color:var(--ink);vertical-align:middle;}
.fin-tbl tr:last-child td{border-bottom:none;}
.fin-tbl tbody tr:hover td{background:#f8fafc;cursor:pointer;}
.fin-tbl td.mono{font-family:'JetBrains Mono',monospace;font-size:11px;}
.fin-tbl td.right{text-align:right;}
.fin-tbl td.center{text-align:center;}
.fin-tbl .row-link{color:var(--blue);text-decoration:none;font-weight:600;}
.fin-tbl .row-link:hover{text-decoration:underline;}

.fin-chart-wrap{position:relative;width:100%;margin-top:8px;}

.fin-loading{display:flex;align-items:center;justify-content:center;height:120px;color:var(--light);font-size:12px;gap:8px;}
.fin-spin{width:18px;height:18px;border:2px solid var(--border);border-top-color:var(--blue);border-radius:50%;animation:fin-spin .7s linear infinite;}
@keyframes fin-spin{to{transform:rotate(360deg);}}
.fin-empty{text-align:center;padding:32px 20px;color:var(--muted);font-size:13px;}

.fin-bucket-item{display:flex;align-items:center;gap:10px;margin-bottom:12px;cursor:pointer;padding:4px;border-radius:6px;transition:background .15s;}
.fin-bucket-item:hover{background:var(--bg);}
.fin-bucket-label{font-size:12px;font-weight:700;color:var(--ink);width:70px;flex-shrink:0;}
.fin-bucket-bar-wrap{flex:1;background:var(--bg);border-radius:4px;height:22px;overflow:hidden;position:relative;}
.fin-bucket-bar-fill{height:100%;border-radius:4px;display:flex;align-items:center;padding-left:8px;font-size:10px;font-weight:700;color:#fff;transition:width .6s ease;}
.fin-bucket-amount{font-size:12px;font-family:'JetBrains Mono',monospace;color:var(--ink);width:110px;text-align:right;flex-shrink:0;}

#fin-date-range{display:none;align-items:center;gap:10px;}
</style>

<div id="fin-root">

<!-- HEADER -->
<div class="fin-header">
  <div class="fin-header-left">
    <h1>Finance <span>Analytics</span> Dashboard</h1>
    <p id="fin-last-updated">Loading…</p>
  </div>
  <div class="fin-header-actions">
    <button class="fin-btn" onclick="window._finDash.load_all()">↻ Refresh</button>
  </div>
</div>

<!-- FILTER BAR -->
<div class="fin-filter-bar">
  <div class="fin-filter-group">
    <span class="fin-filter-label">Company</span>
    <select class="fin-filter-select" id="fin-f-company"><option value="">All</option></select>
  </div>
  <div class="fin-filter-sep"></div>
  <div class="fin-filter-group">
    <span class="fin-filter-label">Cost Centre</span>
    <select class="fin-filter-select" id="fin-f-cc"><option value="">All</option></select>
  </div>
  <div class="fin-filter-sep"></div>
  <div class="fin-filter-group">
    <span class="fin-filter-label">Fiscal Year</span>
    <select class="fin-filter-select" id="fin-f-fy"><option value="">Current</option></select>
  </div>
  <div class="fin-filter-sep"></div>
  <div class="fin-filter-group">
    <span class="fin-filter-label">Period</span>
    <div class="fin-period-toggle">
      <button class="fin-period-btn active" data-p="month">Month</button>
      <button class="fin-period-btn" data-p="quarter">Quarter</button>
      <button class="fin-period-btn" data-p="year">Year</button>
      <button class="fin-period-btn" data-p="custom">Custom</button>
    </div>
  </div>
  <div id="fin-date-range">
    <div class="fin-filter-sep"></div>
    <div class="fin-filter-group">
      <span class="fin-filter-label">From</span>
      <input type="date" class="fin-filter-input" id="fin-f-from" />
    </div>
    <div class="fin-filter-group">
      <span class="fin-filter-label">To</span>
      <input type="date" class="fin-filter-input" id="fin-f-to" />
    </div>
  </div>
</div>

<!-- TABS -->
<div class="fin-tabs">
  <div class="fin-tab active" data-tab="creditor">📦 Creditor Ageing</div>
  <div class="fin-tab" data-tab="budget">📊 Expense vs Budget</div>
  <div class="fin-tab" data-tab="nonbudget">⚠️ Non-Budgeted Payments</div>
  <div class="fin-tab" data-tab="vendor">🔗 Vendor Concentration</div>
</div>

<!-- BODY -->
<div class="fin-body">

  <!-- ── 1. CREDITOR AGEING ── -->
  <div class="fin-section active" id="tab-creditor">
    <div class="fin-section-hd">
      <div>
        <div class="fin-section-title">Creditor (Supplier) Ageing Distribution</div>
        <div class="fin-section-sub">Outstanding purchase invoice balances bucketed by age — click any card or bar to open the filtered Accounts Payable report</div>
      </div>
      <a class="fin-section-link" id="creditor-report-link" onclick="window._finDash._goto_ap()">Open Accounts Payable ↗</a>
    </div>
    <div class="fin-g4" id="creditor-kpis">
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
    </div>
    <div class="fin-g2-1" style="margin-top:16px;">
      <div class="fin-card" id="creditor-buckets"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card" id="creditor-top"><div class="fin-loading"><div class="fin-spin"></div></div></div>
    </div>
    <div class="fin-card" style="margin-top:16px;">
      <div class="fin-card-hd">
        <div class="fin-card-title">Outstanding by Ageing Bucket</div>
        <div class="fin-filter-group">
          <span class="fin-filter-label" style="font-size:10px;">Based On</span>
          <select class="fin-filter-select" id="fin-ageing-basis" style="min-width:100px;padding:4px 8px;font-size:11px;">
            <option value="posting_date">Posting Date</option>
            <option value="due_date">Due Date</option>
          </select>
        </div>
      </div>
      <div class="fin-chart-wrap"><canvas id="chart-creditor-bar" height="80"></canvas></div>
    </div>
  </div>

  <!-- ── 2. EXPENSE VS BUDGET ── -->
  <div class="fin-section" id="tab-budget">
    <div class="fin-section-hd">
      <div>
        <div class="fin-section-title">Expense vs Budget</div>
        <div class="fin-section-sub">Budget utilisation per account (source: Budget Committed Actual Report) — click any row or bar to open the full report</div>
      </div>
      <a class="fin-section-link" onclick="window._finDash._goto_bvr()">Open Budget Committed Actual Report ↗</a>
    </div>
    <div class="fin-g4" id="budget-kpis">
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
    </div>
    <div class="fin-g2" style="margin-top:16px;">
      <div class="fin-card">
        <div class="fin-card-hd"><div class="fin-card-title">Top Accounts by Utilisation %</div></div>
        <div class="fin-chart-wrap"><canvas id="chart-budget-bar" height="160"></canvas></div>
      </div>
      <div class="fin-card">
        <div class="fin-card-hd"><div class="fin-card-title">Account-wise Breakdown</div></div>
        <div id="budget-table-wrap"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      </div>
    </div>
  </div>

  <!-- ── 3. NON-BUDGETED PAYMENTS ── -->
  <div class="fin-section" id="tab-nonbudget">
    <div class="fin-section-hd">
      <div>
        <div class="fin-section-title">Non-Budgeted Payments</div>
        <div class="fin-section-sub">Payments made against accounts with no active budget — each row opens the exact document</div>
      </div>
    <!-- <a class="fin-section-link" onclick="window._finDash._goto_bvr()">View Budget Committed Actual Report ↗</a> -->
    </div>
    <div class="fin-g3" id="nonbudget-kpis">
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
    </div>
    <div class="fin-g2-1" style="margin-top:16px;">
      <div class="fin-card">
        <div class="fin-card-hd"><div class="fin-card-title">Non-Budgeted Transactions</div></div>
        <div id="nonbudget-table-wrap"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      </div>
      <div class="fin-card">
        <div class="fin-card-hd"><div class="fin-card-title">Unbudgeted Spend by Account</div></div>
        <div class="fin-chart-wrap"><canvas id="chart-nonbudget-pie" height="180"></canvas></div>
      </div>
    </div>
  </div>

  <!-- ── 4. VENDOR CONCENTRATION ── -->
  <div class="fin-section" id="tab-vendor">
    <div class="fin-section-hd">
      <div>
        <div class="fin-section-title">Vendor Concentration Risk</div>
        <div class="fin-section-sub">High risk if top 3 suppliers exceed 40% of spend — click any supplier to see their invoices</div>
      </div>
      <a class="fin-section-link" onclick="window._finDash._go_report('Purchase Analytics',{based_on:'Supplier'})">Open Purchase Analytics ↗</a>
    </div>
    <div class="fin-g4" id="vendor-kpis">
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      <div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>
    </div>
    <div class="fin-g2" style="margin-top:16px;">
      <div class="fin-card">
        <div class="fin-card-hd"><div class="fin-card-title">Spend by Supplier — Pareto Chart (click bar → that supplier's invoices)</div></div>
        <div class="fin-chart-wrap"><canvas id="chart-vendor-pareto" height="180"></canvas></div>
      </div>
      <div class="fin-card">
        <div class="fin-card-hd"><div class="fin-card-title">Supplier Spend Ranking</div></div>
        <div id="vendor-table-wrap"><div class="fin-loading"><div class="fin-spin"></div></div></div>
      </div>
    </div>
  </div>

</div><!-- /.fin-body -->
</div><!-- /#fin-root -->
`);

		// ── TAB SWITCHING
		document.querySelectorAll(".fin-tab").forEach((tab) => {
			tab.addEventListener("click", () => {
				document.querySelectorAll(".fin-tab").forEach((t) => t.classList.remove("active"));
				document.querySelectorAll(".fin-section").forEach((s) => s.classList.remove("active"));
				tab.classList.add("active");
				document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
				({ creditor: () => this.load_creditor_ageing(),
				   budget: () => this.load_expense_vs_budget(),
				   nonbudget: () => this.load_non_budgeted(),
				   vendor: () => this.load_vendor_concentration() })[tab.dataset.tab]?.();
			});
		});

		// ── PERIOD BUTTONS
		document.querySelectorAll(".fin-period-btn").forEach((btn) => {
			btn.addEventListener("click", () => {
				document.querySelectorAll(".fin-period-btn").forEach((b) => b.classList.remove("active"));
				btn.classList.add("active");
				this.filters.period = btn.dataset.p;
				const dr = document.getElementById("fin-date-range");
				if (this.filters.period === "custom") { dr.style.display = "flex"; }
				else {
					dr.style.display = "none";
					this.filters.date_from = ""; this.filters.date_to = "";
					document.getElementById("fin-f-from").value = "";
					document.getElementById("fin-f-to").value = "";
					this._sync_url(); this.load_all();
				}
			});
		});

		// ── GLOBAL FILTERS
		["fin-f-company", "fin-f-cc", "fin-f-fy"].forEach((id) => {
			document.getElementById(id).addEventListener("change", () => {
				this.filters.company = document.getElementById("fin-f-company").value;
				this.filters.cost_center = document.getElementById("fin-f-cc").value;
				this.filters.fiscal_year = document.getElementById("fin-f-fy").value;
				this._sync_url(); this.load_all();
			});
		});

		// ── DATE INPUTS
		["fin-f-from", "fin-f-to"].forEach((id) => {
			document.getElementById(id).addEventListener("change", () => {
				if (this.filters.period !== "custom") return;
				this.filters.date_from = document.getElementById("fin-f-from").value;
				this.filters.date_to = document.getElementById("fin-f-to").value;
				if (this.filters.date_from && this.filters.date_to && this.filters.date_from < this.filters.date_to) {
					this._sync_url(); this.load_all();
				}
			});
		});

		// ── AGEING BASIS CHANGE
		document.getElementById("fin-ageing-basis").addEventListener("change", () => {
			this.load_creditor_ageing();
		});
	}

	// ─────────────────────────────────────────────────────────────
	// FILTER OPTIONS
	// ─────────────────────────────────────────────────────────────
	async load_filter_options() {
		return new Promise((resolve) => {
			frappe.call({
				method: "custom_app.custom_app.page.finance_dashboard.finance_dashboard.get_filter_options",
				callback: (r) => {
					if (!r.message) { resolve(); return; }
					const d = r.message;
					[["fin-f-company", d.companies], ["fin-f-cc", d.cost_centers], ["fin-f-fy", d.fiscal_years]].forEach(([id, list]) => {
						const sel = document.getElementById(id);
						(list || []).forEach((v) => { const o = document.createElement("option"); o.value = v; o.textContent = v; sel.appendChild(o); });
					});
					if (d.fiscal_years?.length && !this.filters.fiscal_year) {
						this.filters.fiscal_year = d.fiscal_years[0];
						document.getElementById("fin-f-fy").value = d.fiscal_years[0];
					}
					resolve();
				},
			});
		});
	}

	// ─────────────────────────────────────────────────────────────
	// LOAD ALL
	// ─────────────────────────────────────────────────────────────
	load_all() {
		if (this.filters.period === "custom" && (!this.filters.date_from || !this.filters.date_to)) return;
		const now = new Date().toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
		document.getElementById("fin-last-updated").textContent = `Updated: ${now}`;
		const active = document.querySelector(".fin-tab.active")?.dataset?.tab;
		({ creditor: () => this.load_creditor_ageing(),
		   budget: () => this.load_expense_vs_budget(),
		   nonbudget: () => this.load_non_budgeted(),
		   vendor: () => this.load_vendor_concentration() })[active]?.();
	}

	// ─────────────────────────────────────────────────────────────
	// 1. CREDITOR AGEING
	// ─────────────────────────────────────────────────────────────
	load_creditor_ageing() {
		["creditor-kpis", "creditor-buckets", "creditor-top"].forEach((id) => {
			const el = document.getElementById(id);
			if (el) el.innerHTML = `<div class="fin-loading"><div class="fin-spin"></div></div>`;
		});

		const ageing_based_on = document.getElementById("fin-ageing-basis")?.value || "posting_date";

		frappe.call({
			method: "custom_app.custom_app.page.finance_dashboard.finance_dashboard.get_creditor_ageing",
			args: { ...this._common_args(), ageing_based_on },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;
				const today = d.as_on_date;

				const bucketColors = { "0-30": "#16a34a", "31-60": "#d97706", "61-90": "#ea580c", "91-120": "#dc2626", "120+": "#7f1d1d" };
				const overdue = d.chart_data.filter((b) => b.label !== "0-30").reduce((s, b) => s + b.amount, 0);
				const critical = (d.chart_data.find((b) => b.label === "120+") || {}).amount || 0;
				const current = (d.chart_data.find((b) => b.label === "0-30") || {}).amount || 0;

				document.getElementById("creditor-kpis").innerHTML = `
					<div class="fin-card fin-card-link" onclick="window._finDash._goto_ap()">
						<div class="fin-card-hd">
							<div class="fin-card-title">Total Outstanding</div>
							<div class="fin-card-icon" style="background:var(--blue-lt);">💳</div>
						</div>
						<div class="fin-kpi-val">${this._fmt(d.total_outstanding)}</div>
						<div class="fin-kpi-label">${d.invoice_count} unpaid invoices</div>
						<div class="fin-kpi-sub">As on ${today} · Opens Accounts Payable ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._goto_ap()">
						<div class="fin-card-hd">
							<div class="fin-card-title">Current (0–30 days)</div>
							<div class="fin-card-icon" style="background:var(--green-lt);">✅</div>
						</div>
						<div class="fin-kpi-val" style="color:var(--green)">${this._fmt(current)}</div>
						<div class="fin-kpi-label">${d.total_outstanding > 0 ? Math.round((current / d.total_outstanding) * 100) : 0}% of total outstanding</div>
						<div class="fin-kpi-sub">Opens AP filtered to this company ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._goto_ap()">
						<div class="fin-card-hd">
							<div class="fin-card-title">Overdue (31+ days)</div>
							<div class="fin-card-icon" style="background:var(--amber-lt);">⏰</div>
						</div>
						<div class="fin-kpi-val" style="color:var(--amber)">${this._fmt(overdue)}</div>
						<div class="fin-kpi-label">${d.total_outstanding > 0 ? Math.round((overdue / d.total_outstanding) * 100) : 0}% of total — needs action</div>
						<div class="fin-kpi-sub">Opens AP report ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._goto_ap()">
						<div class="fin-card-hd">
							<div class="fin-card-title">Critical (120+ days)</div>
							<div class="fin-card-icon" style="background:var(--red-lt);">🚨</div>
						</div>
						<div class="fin-kpi-val" style="color:var(--red)">${this._fmt(critical)}</div>
						<div class="fin-kpi-label">${d.total_outstanding > 0 ? Math.round((critical / d.total_outstanding) * 100) : 0}% severely overdue</div>
						<div class="fin-kpi-sub">Opens AP report ↗</div>
					</div>`;

				const maxAmt = Math.max(...d.chart_data.map((b) => b.amount), 1);
				const bucketsHtml = d.chart_data.map((b) => {
					const pct = Math.round((b.amount / maxAmt) * 100);
					return `<div class="fin-bucket-item" title="Click to open Accounts Payable"
						onclick="window._finDash._goto_ap()">
						<div class="fin-bucket-label">${b.label} days</div>
						<div class="fin-bucket-bar-wrap">
							<div class="fin-bucket-bar-fill" style="width:${pct}%;background:${bucketColors[b.label]};">
								${pct > 25 ? b.suppliers + " suppliers" : ""}
							</div>
						</div>
						<div class="fin-bucket-amount">${this._fmt(b.amount)}</div>
					</div>`;
				}).join("");

				document.getElementById("creditor-buckets").innerHTML = `
					<div class="fin-card-hd"><div class="fin-card-title">Ageing Buckets — click to open AP Report</div></div>
					${bucketsHtml}`;

				const topHtml = (d.top_suppliers || []).map((s) => `
					<div style="display:flex;align-items:center;gap:10px;padding:8px;border-bottom:1px solid var(--border);
						cursor:pointer;border-radius:6px;transition:background .15s;" class="fin-card-link"
						title="Click → Accounts Payable filtered to ${s.name}"
						onclick="window._finDash._goto_ap({supplier: '${s.name.replace(/'/g,"\\'")}', party_type:'Supplier'})">
						<div style="flex:1;min-width:0;">
							<div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${s.name}</div>
							<div style="font-size:11px;color:var(--muted);">${s.count} invoice${s.count !== 1 ? "s" : ""}</div>
						</div>
						<div style="font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--red);white-space:nowrap;">${this._fmt(s.amount)}</div>
					</div>`).join("");

				document.getElementById("creditor-top").innerHTML = `
					<div class="fin-card-hd"><div class="fin-card-title">Top Creditors — click to filter AP</div></div>
					${topHtml || '<div class="fin-empty">No outstanding balances</div>'}`;

				this._make_chart("chart-creditor-bar", {
					type: "bar",
					data: {
						labels: d.chart_data.map((b) => b.label + " days"),
						datasets: [{
							label: "Outstanding Amount",
							data: d.chart_data.map((b) => b.amount),
							backgroundColor: d.chart_data.map((b) => bucketColors[b.label]),
							borderRadius: 6, borderSkipped: false,
						}],
					},
					options: {
						responsive: true, maintainAspectRatio: true,
						onClick: () => this._goto_ap(),
						plugins: {
							legend: { display: false },
							tooltip: { callbacks: { label: (ctx) => ` ${this._fmt(ctx.parsed.y)}` } },
						},
						scales: {
							y: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { font: { size: 10 }, callback: (v) => this._fmt(v) } },
							x: { grid: { display: false }, ticks: { font: { size: 11 } } },
						},
					},
				});
			},
		});
	}

	// ─────────────────────────────────────────────────────────────
	// 2. EXPENSE VS BUDGET  (Budget Committed Actual Report)
	// ─────────────────────────────────────────────────────────────
	load_expense_vs_budget() {
		document.getElementById("budget-kpis").innerHTML =
			Array(4).fill(`<div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>`).join("");
		document.getElementById("budget-table-wrap").innerHTML = `<div class="fin-loading"><div class="fin-spin"></div></div>`;

		frappe.call({
			method: "custom_app.custom_app.page.finance_dashboard.finance_dashboard.get_expense_vs_budget",
			args: {
				company: this.filters.company,
				fiscal_year: this.filters.fiscal_year,
				cost_center: this.filters.cost_center,
			},
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;
				const utilColor = d.total_utilisation >= 90 ? "var(--red)" : d.total_utilisation >= 70 ? "var(--amber)" : "var(--green)";

				// 4 KPI cards: Total Budget, Actual Spend, Committed (PR/EC raised), Remaining
				document.getElementById("budget-kpis").innerHTML = `
					<div class="fin-card fin-card-link" onclick="window._finDash._goto_bvr()">
						<div class="fin-card-hd">
							<div class="fin-card-title">Total Budget</div>
							<div class="fin-card-icon" style="background:var(--blue-lt);">📋</div>
						</div>
						<div class="fin-kpi-val">${this._fmt(d.total_budget)}</div>
						<div class="fin-kpi-label">FY ${d.fiscal_year || "—"} · ${d.rows.length} accounts</div>
						<div class="fin-kpi-sub">Opens Budget Committed Actual Report ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._goto_bvr()">
						<div class="fin-card-hd">
							<div class="fin-card-title">Actual Spend</div>
							<div class="fin-card-icon" style="background:var(--purple-lt);">💸</div>
						</div>
						<div class="fin-kpi-val" style="color:${utilColor}">${this._fmt(d.total_actual)}</div>
						<div class="fin-kpi-label">${d.total_utilisation}% of budget utilised</div>
						<div class="fin-kpi-sub">Finance-Approved EC + Submitted PI · Opens Report ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._goto_bvr()">
						<div class="fin-card-hd">
							<div class="fin-card-title">Committed (PR / EC Raised)</div>
							<div class="fin-card-icon" style="background:var(--amber-lt);">📝</div>
						</div>
						<div class="fin-kpi-val" style="color:var(--amber)">${this._fmt(d.total_committed)}</div>
						<div class="fin-kpi-label">Material Requests + Expense Claims raised</div>
						<div class="fin-kpi-sub">Opens Budget Committed Actual Report ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._goto_bvr()">
						<div class="fin-card-hd">
							<div class="fin-card-title">Remaining Budget</div>
							<div class="fin-card-icon" style="background:${d.total_variance >= 0 ? "var(--green-lt)" : "var(--red-lt)"}">
								${d.total_variance >= 0 ? "✅" : "🚨"}
							</div>
						</div>
						<div class="fin-kpi-val" style="color:${d.total_variance >= 0 ? "var(--green)" : "var(--red)"}">
							${this._fmt(Math.abs(d.total_variance))}
						</div>
						<div class="fin-kpi-label">${d.total_variance >= 0 ? "Under budget" : "OVER budget"}</div>
						<div class="fin-kpi-sub">Opens Budget Committed Actual Report ↗</div>
					</div>`;

				// Horizontal bar chart — Budget vs Committed vs Actual, top 10 accounts
				const top10 = d.rows.slice(0, 10);
				this._make_chart("chart-budget-bar", {
					type: "bar",
					data: {
						labels: top10.map((r) => r.account.split(" - ")[0]),
						datasets: [
							{
								label: "Budget",
								data: top10.map((r) => r.budget),
								backgroundColor: "rgba(37,99,235,.18)",
								borderColor: "#2563eb", borderWidth: 1.5, borderRadius: 4,
							},
							{
								label: "Committed",
								data: top10.map((r) => r.committed),
								backgroundColor: "rgba(217,119,6,.55)",
								borderRadius: 4,
							},
							{
								label: "Actual",
								data: top10.map((r) => r.actual),
								backgroundColor: top10.map((r) =>
									r.utilisation_pct > 100 ? "rgba(220,38,38,.75)"
									: r.utilisation_pct > 80  ? "rgba(217,119,6,.75)"
									: "rgba(22,163,74,.75)"),
								borderRadius: 4,
							},
						],
					},
					options: {
						indexAxis: "y", responsive: true, maintainAspectRatio: true,
						onClick: () => this._goto_bvr(),
						plugins: {
							legend: { position: "top", labels: { font: { size: 11 }, boxWidth: 12, padding: 10 } },
							tooltip: {
								callbacks: {
									label: (ctx) => {
										const acc = top10[ctx.dataIndex];
										if (ctx.dataset.label === "Budget") return ` Budget: ${this._fmt(ctx.parsed.x)}`;
										if (ctx.dataset.label === "Committed") return ` Committed: ${this._fmt(ctx.parsed.x)}`;
										return ` Actual: ${this._fmt(ctx.parsed.x)} (${acc?.utilisation_pct}% used)`;
									},
									footer: () => "Click → Budget Committed Actual Report",
								},
							},
						},
						scales: {
							x: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { font: { size: 9 }, callback: (v) => this._fmt(v) } },
							y: { grid: { display: false }, ticks: { font: { size: 9 } } },
						},
					},
				});

				// Table with Budget / Committed / Actual / Utilisation / Variance columns
				const tableRows = d.rows.map((row) => {
					const barColor = row.utilisation_pct > 100 ? "var(--red)" : row.utilisation_pct > 80 ? "var(--amber)" : "var(--green)";
					const pct = Math.min(row.utilisation_pct, 100);
					return `<tr onclick="window._finDash._goto_bvr()" title="Click → Budget Committed Actual Report">
						<td><span class="row-link" title="${row.account}">${row.account.length > 30 ? row.account.slice(0, 30) + "…" : row.account}</span></td>
						<td class="mono right">${this._fmt(row.budget)}</td>
						<td class="mono right" style="color:var(--amber);">${this._fmt(row.committed)}</td>
						<td class="mono right">${this._fmt(row.actual)}</td>
						<td style="min-width:110px;">
							<div style="font-size:10px;color:${barColor};margin-bottom:2px;font-weight:700;">${row.utilisation_pct}%</div>
							<div class="fin-prog-wrap"><div class="fin-prog-fill" style="width:${pct}%;background:${barColor};"></div></div>
						</td>
						<td class="mono right" style="color:${row.variance >= 0 ? "var(--green)" : "var(--red)"};">${row.variance < 0 ? "▲ " : ""}${this._fmt(Math.abs(row.variance))}</td>
					</tr>`;
				}).join("");

				document.getElementById("budget-table-wrap").innerHTML = `
					<div style="overflow-x:auto;max-height:380px;overflow-y:auto;">
						<table class="fin-tbl">
							<thead><tr>
								<th>Account</th>
								<th class="right">Budget</th>
								<th class="right">Committed</th>
								<th class="right">Actual</th>
								<th>Used</th>
								<th class="right">Variance</th>
							</tr></thead>
							<tbody>${tableRows || '<tr><td colspan="6"><div class="fin-empty">No budget data found for these filters</div></td></tr>'}</tbody>
						</table>
					</div>`;
			},
		});
	}

	// ─────────────────────────────────────────────────────────────
	// 3. NON-BUDGETED PAYMENTS
	// ─────────────────────────────────────────────────────────────
	load_non_budgeted() {
		document.getElementById("nonbudget-kpis").innerHTML =
			Array(3).fill(`<div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>`).join("");
		document.getElementById("nonbudget-table-wrap").innerHTML = `<div class="fin-loading"><div class="fin-spin"></div></div>`;

		frappe.call({
			method: "custom_app.custom_app.page.finance_dashboard.finance_dashboard.get_non_budgeted_payments",
			args: { company: this.filters.company, fiscal_year: this.filters.fiscal_year, cost_center: this.filters.cost_center },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;

				const piRows = d.rows.filter((x) => x.doctype === "Purchase Invoice");
				const ecRows = d.rows.filter((x) => x.doctype === "Expense Claim");

				const piListFilters = { docstatus: 1 };
				if (this.filters.company) piListFilters.company = this.filters.company;

				const ecListFilters = { docstatus: 1, workflow_state: "Finance Approved" };
				if (this.filters.company) ecListFilters.company = this.filters.company;

				document.getElementById("nonbudget-kpis").innerHTML = `
					<div class="fin-card">
						<div class="fin-card-hd">
							<div class="fin-card-title">Total Non-Budgeted Amount</div>
							<div class="fin-card-icon" style="background:var(--red-lt);">⚠️</div>
						</div>
						<div class="fin-kpi-val" style="color:var(--red)">${this._fmt(d.total_amount)}</div>
						<div class="fin-kpi-label">${d.total_count} transactions · FY ${d.fiscal_year || "—"}</div>
						<div class="fin-kpi-sub">Spend with no matching submitted Budget</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._go_list('Purchase Invoice',${JSON.stringify(piListFilters)})">
						<div class="fin-card-hd">
							<div class="fin-card-title">Unbudgeted Purchase Invoices</div>
							<div class="fin-card-icon" style="background:var(--orange-lt);">🧾</div>
						</div>
						<div class="fin-kpi-val" style="color:var(--orange)">${piRows.length}</div>
						<div class="fin-kpi-label">PIs with no budget allocation</div>
						<div class="fin-kpi-sub">Opens Purchase Invoice list (company filtered) ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._go_list('Expense Claim',${JSON.stringify(ecListFilters)})">
						<div class="fin-card-hd">
							<div class="fin-card-title">Unbudgeted Expense Claims</div>
							<div class="fin-card-icon" style="background:var(--purple-lt);">🗂️</div>
						</div>
						<div class="fin-kpi-val" style="color:var(--purple)">${ecRows.length}</div>
						<div class="fin-kpi-label">Finance-Approved ECs with no budget</div>
						<div class="fin-kpi-sub">Opens Expense Claim list (Finance Approved) ↗</div>
					</div>`;

				const tableRows = d.rows.map((row) => {
					const dtIcon = row.doctype === "Purchase Invoice" ? "🧾" : "🗂️";
					const dtBadge = row.doctype === "Purchase Invoice"
						? `<span class="fb fb-orange">PI</span>`
						: `<span class="fb fb-purple">EC</span>`;
					return `<tr onclick="window._finDash._go_form('${row.doctype}','${row.document}')"
						title="Click → open ${row.doctype} ${row.document}">
						<td>${dtIcon} <span class="row-link">${row.document}</span></td>
						<td>${dtBadge}</td>
						<td style="max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${row.party || ''}">${row.party || "—"}</td>
						<td class="mono">${row.posting_date || "—"}</td>
						<td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${row.account || ''}">${(row.account || "—").split(" - ")[0]}</td>
						<td class="mono right" style="color:var(--red);font-weight:700;">${this._fmt(parseFloat(row.amount) || 0)}</td>
					</tr>`;
				}).join("");

				document.getElementById("nonbudget-table-wrap").innerHTML = `
					<div style="overflow-x:auto;max-height:400px;overflow-y:auto;">
						<table class="fin-tbl">
							<thead><tr><th>Document ↗</th><th>Type</th><th>Party</th><th>Date</th><th>Account</th><th class="right">Amount</th></tr></thead>
							<tbody>${tableRows || '<tr><td colspan="6"><div class="fin-empty">✅ All payments are within budget allocations</div></td></tr>'}</tbody>
						</table>
					</div>`;

				if (d.account_summary?.length > 0) {
					const top8 = d.account_summary.slice(0, 8);
					this._make_chart("chart-nonbudget-pie", {
						type: "doughnut",
						data: {
							labels: top8.map((a) => a.account.split(" - ")[0]),
							datasets: [{
								data: top8.map((a) => a.amount),
								backgroundColor: ["#dc2626","#ea580c","#d97706","#16a34a","#2563eb","#7c3aed","#0d9488","#6b7280"],
								borderWidth: 2, borderColor: "#fff", hoverOffset: 6,
							}],
						},
						options: {
							responsive: true, cutout: "55%",
							onClick: (evt, elements) => {
								if (!elements.length) return;
								const filters = { docstatus: 1 };
								if (this.filters.company) filters.company = this.filters.company;
								if (this.filters.fiscal_year) filters.fiscal_year = this.filters.fiscal_year;
								this._go_list("Budget", filters);
							},
							plugins: {
								legend: { position: "bottom", labels: { font: { size: 10 }, boxWidth: 10, padding: 8 } },
								tooltip: {
									callbacks: {
										label: (ctx) => ` ${ctx.label}: ${this._fmt(ctx.parsed)}`,
										footer: () => "Click → open Budget list for this account",
									},
								},
							},
						},
					});
				}
			},
		});
	}

	// ─────────────────────────────────────────────────────────────
	// 4. VENDOR CONCENTRATION
	// ─────────────────────────────────────────────────────────────
	load_vendor_concentration() {
		document.getElementById("vendor-kpis").innerHTML =
			Array(4).fill(`<div class="fin-card"><div class="fin-loading"><div class="fin-spin"></div></div></div>`).join("");
		document.getElementById("vendor-table-wrap").innerHTML = `<div class="fin-loading"><div class="fin-spin"></div></div>`;

		frappe.call({
			method: "custom_app.custom_app.page.finance_dashboard.finance_dashboard.get_vendor_concentration",
			args: {
				company: this.filters.company,
				fiscal_year: this.filters.fiscal_year,
				date_from: this.filters.period === "custom" ? this.filters.date_from : null,
				date_to: this.filters.period === "custom" ? this.filters.date_to : null,
				top_n: 10,
			},
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;
				const riskClass = d.risk_level === "High" ? "fin-risk-high" : d.risk_level === "Medium" ? "fin-risk-medium" : "fin-risk-low";
				const riskIcon = d.risk_level === "High" ? "🔴" : d.risk_level === "Medium" ? "🟡" : "🟢";

				const piBase = { docstatus: 1 };
				if (this.filters.company) piBase.company = this.filters.company;

				document.getElementById("vendor-kpis").innerHTML = `
					<div class="fin-card fin-card-link" onclick="window._finDash._go_list('Purchase Invoice',${JSON.stringify(piBase)})">
						<div class="fin-card-hd">
							<div class="fin-card-title">Total Procurement Spend</div>
							<div class="fin-card-icon" style="background:var(--blue-lt);">💼</div>
						</div>
						<div class="fin-kpi-val">${this._fmt(d.total_spend)}</div>
						<div class="fin-kpi-label">${d.supplier_count} suppliers · ${d.date_from} to ${d.date_to}</div>
						<div class="fin-kpi-sub">Opens Purchase Invoice list ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._go_report('Purchase Analytics',{based_on:'Supplier',company:window._finDash.filters.company||undefined})">
						<div class="fin-card-hd">
							<div class="fin-card-title">Concentration Risk</div>
							<div class="fin-card-icon" style="background:var(--red-lt);">${riskIcon}</div>
						</div>
						<div style="margin-top:4px;"><span class="${riskClass}">${d.risk_level} Risk</span></div>
						<div class="fin-kpi-label" style="margin-top:10px;">Top 3 = ${d.top3_pct}% · threshold 40%</div>
						<div class="fin-kpi-sub">Opens Purchase Analytics grouped by Supplier ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._go_report('Purchase Analytics',{based_on:'Supplier',company:window._finDash.filters.company||undefined})">
						<div class="fin-card-hd">
							<div class="fin-card-title">Top 3 Vendors Share</div>
							<div class="fin-card-icon" style="background:var(--amber-lt);">🏆</div>
						</div>
						<div class="fin-kpi-val" style="color:${d.top3_pct > 40 ? "var(--red)" : "var(--amber)"}">
							${d.top3_pct}<span style="font-size:18px;color:var(--muted);">%</span>
						</div>
						<div class="fin-kpi-label">of total procurement</div>
						<div class="fin-kpi-sub">Opens Purchase Analytics ↗</div>
					</div>
					<div class="fin-card fin-card-link" onclick="window._finDash._go_report('Purchase Analytics',{based_on:'Supplier',company:window._finDash.filters.company||undefined})">
						<div class="fin-card-hd">
							<div class="fin-card-title">Top 10 Vendors Share</div>
							<div class="fin-card-icon" style="background:var(--teal-lt);">📊</div>
						</div>
						<div class="fin-kpi-val" style="color:var(--teal)">
							${d.top_n_pct}<span style="font-size:18px;color:var(--muted);">%</span>
						</div>
						<div class="fin-kpi-label">Top ${d.top_n} of ${d.supplier_count} suppliers</div>
						<div class="fin-kpi-sub">Opens Purchase Analytics ↗</div>
					</div>`;

				const palette = ["#dc2626","#ea580c","#d97706","#16a34a","#2563eb","#7c3aed","#0d9488","#6b7280","#ec4899","#f59e0b","#94a3b8"];
				this._make_chart("chart-vendor-pareto", {
					type: "bar",
					data: {
						labels: d.chart_labels,
						datasets: [
							{
								label: "Spend (₹)", type: "bar",
								data: d.chart_values,
								backgroundColor: d.chart_labels.map((_, i) => palette[i % palette.length]),
								borderRadius: 5, borderSkipped: false, yAxisID: "y",
							},
							{
								label: "Cumulative %", type: "line",
								data: (() => { let cum = 0, total = d.chart_values.reduce((a, b) => a + b, 0) || 1;
									return d.chart_values.map((v) => { cum += v; return Math.round((cum / total) * 100); }); })(),
								borderColor: "#1a1d23", borderWidth: 2,
								pointBackgroundColor: "#1a1d23", pointRadius: 3,
								fill: false, tension: 0.1, yAxisID: "y1",
							},
						],
					},
					options: {
						responsive: true, maintainAspectRatio: true,
						onClick: (evt, elements) => {
							if (!elements.length) return;
							const idx = elements[0].index;
							const supplier = d.rows[idx]?.supplier;
							if (!supplier) return;
							const f = { docstatus: 1, supplier };
							if (this.filters.company) f.company = this.filters.company;
							if (d.date_from) f.posting_date = [">=", d.date_from];
							this._go_list("Purchase Invoice", f);
						},
						plugins: {
							legend: { position: "top", labels: { font: { size: 11 }, boxWidth: 12, padding: 10 } },
							tooltip: {
								callbacks: {
									label: (ctx) => ctx.dataset.yAxisID === "y"
										? ` ${ctx.label}: ${this._fmt(ctx.parsed.y)}`
										: ` Cumulative: ${ctx.parsed.y}%`,
									footer: (items) => items[0]?.dataset?.yAxisID === "y"
										? "Click → Purchase Invoices for this supplier" : "",
								},
							},
						},
						scales: {
							y: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { font: { size: 9 }, callback: (v) => this._fmt(v) } },
							y1: { beginAtZero: true, max: 100, position: "right", grid: { display: false }, ticks: { font: { size: 9 }, callback: (v) => v + "%" } },
							x: { grid: { display: false }, ticks: { font: { size: 9 }, maxRotation: 30 } },
						},
					},
				});

				const tableRows = d.rows.slice(0, 25).map((row) => {
					const barColor = row.rank <= 3 ? "var(--red)" : row.rank <= 5 ? "var(--amber)" : "var(--blue)";
					const rowFilters = { docstatus: 1, supplier: row.supplier };
					if (this.filters.company) rowFilters.company = this.filters.company;
					if (d.date_from) rowFilters.posting_date = ["Between", [d.date_from, d.date_to]];
					return `<tr onclick="window._finDash._go_list('Purchase Invoice',${JSON.stringify(rowFilters).replace(/"/g, "&quot;")})"
						title="Click → Purchase Invoices for ${row.supplier_name || row.supplier}">
						<td class="mono center" style="font-weight:700;color:${barColor}">#${row.rank}</td>
						<td><span class="row-link" title="${row.supplier}">${(row.supplier_name || row.supplier).length > 26 ? (row.supplier_name || row.supplier).slice(0, 26) + "…" : (row.supplier_name || row.supplier)}</span></td>
						<td class="mono right" style="font-weight:700;">${this._fmt(row.total_spend)}</td>
						<td class="mono center">${row.invoice_count}</td>
						<td style="min-width:100px;">
							<div class="fin-prog-wrap" style="height:6px;">
								<div class="fin-prog-fill" style="width:${Math.min(row.pct_of_total * 2.5, 100)}%;background:${barColor};"></div>
							</div>
							<div style="font-size:10px;color:${barColor};margin-top:2px;font-weight:600;">${row.pct_of_total}%</div>
						</td>
						<td class="mono center" style="color:var(--muted);">${row.cumulative_pct}%</td>
					</tr>`;
				}).join("");

				document.getElementById("vendor-table-wrap").innerHTML = `
					<div style="overflow-x:auto;max-height:420px;overflow-y:auto;">
						<table class="fin-tbl">
							<thead><tr><th class="center">Rank</th><th>Supplier ↗</th><th class="right">Spend</th><th class="center">Invoices</th><th>Share</th><th class="center">Cumulative</th></tr></thead>
							<tbody>${tableRows || '<tr><td colspan="6"><div class="fin-empty">No procurement data found</div></td></tr>'}</tbody>
						</table>
					</div>`;
			},
		});
	}
}