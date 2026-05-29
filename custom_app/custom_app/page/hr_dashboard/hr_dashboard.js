frappe.pages["hr-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "HR Dashboard",
		single_column: true,
	});

	// ── Fonts
	if (!document.getElementById("hr-dashboard-fonts")) {
		const link = document.createElement("link");
		link.id = "hr-dashboard-fonts";
		link.rel = "stylesheet";
		link.href = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap";
		document.head.appendChild(link);
	}

	// ── Hide Frappe page header
	if (!document.getElementById("hr-dashboard-base-style")) {
		const s = document.createElement("style");
		s.id = "hr-dashboard-base-style";
		s.textContent = `.page-head { display: none !important; }`;
		document.head.appendChild(s);
	}

	window._hrDash = new HRDashboard(wrapper);
};

// ═══════════════════════════════════════════════════════════════
class HRDashboard {
	constructor(wrapper) {
		this.wrapper      = wrapper;
		this.student_counts = {};
		this.filters      = { period: "month", company: "", department: "", school: "", date_from: "", date_to: "" };
		this._charts      = {};   // chart.js instances keyed by canvas id
		this.render_shell();
		this.load_filter_options().then(() => this.load_all());
	}

	// ── CSS ────────────────────────────────────────────────────────
	render_shell() {
		$(this.wrapper).find(".page-content").html(`
<style>
:root{
	--bg:#f0f2f5;--card:#fff;--border:#e2e6ea;
	--ink:#1a1d23;--muted:#6c757d;--light:#adb5bd;
	--blue:#2563eb;--blue-lt:#eff6ff;
	--green:#16a34a;--green-lt:#f0fdf4;
	--red:#dc2626;--red-lt:#fef2f2;
	--amber:#d97706;--amber-lt:#fffbeb;
	--purple:#7c3aed;--purple-lt:#f5f3ff;
	--teal:#0d9488;--teal-lt:#f0fdfa;
	--r:12px;--r-sm:8px;
	--shadow:0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04);
	--shadow-md:0 4px 16px rgba(0,0,0,.08);
}
*{box-sizing:border-box;margin:0;padding:0;}
#hr-root{background:var(--bg);min-height:100vh;padding:0 0 60px;font-family:'Inter',sans-serif;color:var(--ink);}

/* ── HEADER */
.hr-header{background:var(--ink);padding:20px 28px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;}
.hr-header-left h1{font-size:20px;font-weight:700;color:#fff;letter-spacing:-.3px;}
.hr-header-left h1 span{color:#60a5fa;}
.hr-header-left p{font-size:11px;color:rgba(255,255,255,.45);margin-top:3px;letter-spacing:.4px;text-transform:uppercase;}
.hr-refresh-btn{display:flex;align-items:center;gap:6px;padding:8px 16px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);border-radius:var(--r-sm);font-size:13px;font-weight:500;color:#fff;cursor:pointer;transition:all .15s;}
.hr-refresh-btn:hover{background:rgba(255,255,255,.15);}

/* ── FILTER BAR */
.hr-filter-bar{background:#fff;border-bottom:1px solid var(--border);padding:12px 28px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.hr-filter-group{display:flex;align-items:center;gap:6px;}
.hr-filter-label{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;}
.hr-filter-select,.hr-filter-input{padding:6px 10px;border:1px solid var(--border);border-radius:var(--r-sm);font-size:12px;font-family:'Inter',sans-serif;color:var(--ink);background:#fff;outline:none;cursor:pointer;transition:border-color .15s;}
.hr-filter-select:focus,.hr-filter-input:focus{border-color:var(--blue);}
.hr-period-toggle{display:flex;gap:0;background:var(--bg);border:1px solid var(--border);border-radius:var(--r-sm);overflow:hidden;}
.hr-period-btn{padding:6px 12px;font-size:12px;font-weight:500;border:none;background:transparent;color:var(--muted);cursor:pointer;transition:all .15s;border-right:1px solid var(--border);}
.hr-period-btn:last-child{border-right:none;}
.hr-period-btn.active{background:var(--blue);color:#fff;}
.hr-filter-sep{width:1px;height:24px;background:var(--border);margin:0 6px;}

/* ── BODY */
.hr-body{padding:24px 28px;}

/* ── SECTION */
.hr-section{margin-bottom:28px;}
.hr-section-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:14px;display:flex;align-items:center;gap:8px;}
.hr-section-title::after{content:'';flex:1;height:1px;background:var(--border);}

/* ── GRIDS */
.hr-g4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;}
.hr-g3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
.hr-g2{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;}
.hr-g1{display:grid;grid-template-columns:1fr;gap:16px;}
.hr-g3-1{display:grid;grid-template-columns:1fr 2fr;gap:16px;}
.hr-g1-2{display:grid;grid-template-columns:2fr 1fr;gap:16px;}
@media(max-width:1200px){.hr-g4{grid-template-columns:repeat(2,1fr);}.hr-g3,.hr-g3-1,.hr-g1-2{grid-template-columns:1fr 1fr;}}
@media(max-width:768px){.hr-g4,.hr-g3,.hr-g2,.hr-g3-1,.hr-g1-2{grid-template-columns:1fr;}}

/* ── CARD */
.hr-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:20px;box-shadow:var(--shadow);transition:box-shadow .2s;}
.hr-card:hover{box-shadow:var(--shadow-md);}
.hr-card-hd{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;}
.hr-card-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);}
.hr-card-icon{width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:15px;}

/* ── METRIC */
.hr-metric{font-size:34px;font-weight:700;letter-spacing:-1px;line-height:1;font-family:'JetBrains Mono',monospace;}
.hr-metric-unit{font-size:18px;font-weight:500;color:var(--muted);}
.hr-metric-label{font-size:12px;color:var(--muted);margin-top:6px;}
.hr-metric-sub{font-size:11px;color:var(--light);margin-top:10px;padding-top:10px;border-top:1px solid var(--border);}

/* ── BADGE */
.hb{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;}
.hb-blue{background:var(--blue-lt);color:var(--blue);}
.hb-green{background:var(--green-lt);color:var(--green);}
.hb-red{background:var(--red-lt);color:var(--red);}
.hb-amber{background:var(--amber-lt);color:var(--amber);}
.hb-purple{background:var(--purple-lt);color:var(--purple);}
.hb-teal{background:var(--teal-lt);color:var(--teal);}

/* ── CAVEAT */
.hr-caveat{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:var(--amber);background:var(--amber-lt);padding:3px 8px;border-radius:20px;margin-top:8px;}

/* ── TABLE */
.hr-tbl{width:100%;border-collapse:collapse;font-size:12px;}
.hr-tbl th{padding:8px 10px;text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);border-bottom:1px solid var(--border);}
.hr-tbl td{padding:10px 10px;border-bottom:1px solid var(--border);color:var(--ink);}
.hr-tbl tr:last-child td{border-bottom:none;}
.hr-tbl tr:hover td{background:var(--bg);}
.hr-tbl td.mono{font-family:'JetBrains Mono',monospace;}
.hr-tbl td.center{text-align:center;}

/* ── PROGRESS */
.hr-prog-wrap{background:var(--bg);border-radius:4px;height:6px;overflow:hidden;margin-top:4px;}
.hr-prog-fill{height:100%;border-radius:4px;transition:width .5s ease;}

/* ── FUNNEL */
.hr-funnel{display:flex;align-items:stretch;gap:0;overflow-x:auto;padding-bottom:2px;}
.hr-funnel-step{display:flex;flex-direction:column;align-items:center;gap:8px;flex:1;min-width:90px;position:relative;}
.hr-funnel-step:not(:last-child)::after{content:'›';position:absolute;right:-10px;top:18px;font-size:20px;color:var(--light);z-index:1;}
.hr-funnel-box{width:100%;padding:14px 8px;border-radius:var(--r-sm);text-align:center;font-weight:700;font-size:24px;font-family:'JetBrains Mono',monospace;line-height:1;}
.hr-funnel-lbl{font-size:10px;color:var(--muted);text-align:center;font-weight:600;text-transform:uppercase;letter-spacing:.4px;}
.hr-funnel-sub{font-size:10px;color:var(--light);text-align:center;}

/* ── MOVEMENT */
.hr-mv-item{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--border);}
.hr-mv-item:last-child{border-bottom:none;}
.hr-mv-avatar{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;}
.hr-mv-info{flex:1;min-width:0;}
.hr-mv-name{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.hr-mv-meta{font-size:11px;color:var(--muted);}
.hr-mv-date{font-size:11px;color:var(--light);font-family:'JetBrains Mono',monospace;white-space:nowrap;}

/* ── STUDENT INPUT */
.hr-stu-input{width:80px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;font-family:'JetBrains Mono',monospace;text-align:right;background:var(--bg);}
.hr-stu-input:focus{outline:none;border-color:var(--blue);background:#fff;}

/* ── STAT ROW */
.hr-stat-row{display:flex;gap:4px;flex-wrap:wrap;margin-top:10px;}

/* ── CANVAS */
.hr-chart-wrap{position:relative;width:100%;margin-top:8px;}

/* ── LOADING */
.hr-loading{display:flex;align-items:center;justify-content:center;height:80px;color:var(--light);font-size:12px;gap:8px;}
.hr-spin{width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--blue);border-radius:50%;animation:hr-spin .7s linear infinite;}
@keyframes hr-spin{to{transform:rotate(360deg);}}

/* ── DONUT LEGEND */
.hr-donut-wrap{display:flex;align-items:center;gap:20px;}
.hr-donut-legend{flex:1;}
.hr-legend-item{display:flex;align-items:center;gap:8px;margin-bottom:10px;font-size:12px;}
.hr-legend-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}
.hr-legend-lbl{color:var(--muted);flex:1;}
.hr-legend-val{font-weight:700;font-family:'JetBrains Mono',monospace;}
</style>

<div id="hr-root">

<!-- HEADER -->
<div class="hr-header">
  <div class="hr-header-left">
    <h1>HR <span>Analytics</span> Dashboard</h1>
    <p id="hr-last-updated">Loading...</p>
  </div>
  <button class="hr-refresh-btn" onclick="window._hrDash.load_all()">↻ Refresh</button>
</div>

<!-- FILTER BAR -->
<div class="hr-filter-bar">
  <div class="hr-filter-group">
    <span class="hr-filter-label">Period</span>
    <div class="hr-period-toggle" id="hr-period-toggle">
      <button class="hr-period-btn active" data-p="month">Month</button>
      <button class="hr-period-btn" data-p="quarter">Quarter</button>
      <button class="hr-period-btn" data-p="year">Year</button>
    </div>
  </div>
  <div class="hr-filter-sep"></div>
  <div class="hr-filter-group">
    <span class="hr-filter-label">Company</span>
    <select class="hr-filter-select" id="hr-f-company"><option value="">All</option></select>
  </div>
  <div class="hr-filter-group">
    <span class="hr-filter-label">Department</span>
    <select class="hr-filter-select" id="hr-f-dept"><option value="">All</option></select>
  </div>
  <div class="hr-filter-group">
    <span class="hr-filter-label">School</span>
    <select class="hr-filter-select" id="hr-f-school"><option value="">All</option></select>
  </div>
  <div class="hr-filter-sep"></div>
  <div class="hr-filter-group">
    <span class="hr-filter-label">From</span>
    <input type="date" class="hr-filter-input" id="hr-f-from" />
  </div>
  <div class="hr-filter-group">
    <span class="hr-filter-label">To</span>
    <input type="date" class="hr-filter-input" id="hr-f-to" />
  </div>
</div>

<!-- BODY -->
<div class="hr-body">

  <!-- ROW 1: KPI Cards -->
  <div class="hr-section">
    <div class="hr-section-title">Key Metrics</div>
    <div class="hr-g4">
      <div class="hr-card" id="hr-kpi-headcount"><div class="hr-loading"><div class="hr-spin"></div></div></div>
      <div class="hr-card" id="hr-kpi-faculty-pct"><div class="hr-loading"><div class="hr-spin"></div></div></div>
      <div class="hr-card" id="hr-kpi-attrition"><div class="hr-loading"><div class="hr-spin"></div></div></div>
      <div class="hr-card" id="hr-kpi-offer"><div class="hr-loading"><div class="hr-spin"></div></div></div>
    </div>
  </div>

  <!-- ROW 2: Workforce Split + Headcount Trend -->
  <div class="hr-section">
    <div class="hr-section-title">Workforce Composition</div>
    <div class="hr-g3-1">
      <div class="hr-card" id="hr-card-typesplit"><div class="hr-loading"><div class="hr-spin"></div></div></div>
      <div class="hr-card" id="hr-card-join-trend">
        <div class="hr-card-hd"><div class="hr-card-title">Monthly Joiners (6 months)</div></div>
        <div class="hr-chart-wrap"><canvas id="chart-join-trend" height="100"></canvas></div>
      </div>
    </div>
  </div>

  <!-- ROW 3: Time to Hire + Attrition Trend -->
  <div class="hr-section">
    <div class="hr-section-title">Hiring Analytics</div>
    <div class="hr-g2">
      <div class="hr-card" id="hr-card-timetohire"><div class="hr-loading"><div class="hr-spin"></div></div></div>
      <div class="hr-card" id="hr-card-attrition-trend">
        <div class="hr-card-hd"><div class="hr-card-title">Monthly Attrition (6 months)</div></div>
        <div class="hr-chart-wrap"><canvas id="chart-attrition-trend" height="110"></canvas></div>
      </div>
    </div>
  </div>

  <!-- ROW 4: Recruitment Funnel -->
  <div class="hr-section">
    <div class="hr-section-title">Recruitment Pipeline</div>
    <div class="hr-g1">
      <div class="hr-card" id="hr-card-pipeline"><div class="hr-loading"><div class="hr-spin"></div></div></div>
    </div>
  </div>

  <!-- ROW 5: Requisition Status + Offer Breakdown -->
  <div class="hr-section">
    <div class="hr-section-title">Requisition & Offer Breakdown</div>
    <div class="hr-g2">
      <div class="hr-card">
        <div class="hr-card-hd"><div class="hr-card-title">Job Requisition Status</div></div>
        <div class="hr-chart-wrap"><canvas id="chart-req-status" height="140"></canvas></div>
      </div>
      <div class="hr-card">
        <div class="hr-card-hd"><div class="hr-card-title">Offer Outcome</div></div>
        <div class="hr-chart-wrap"><canvas id="chart-offer-status" height="140"></canvas></div>
      </div>
    </div>
  </div>

  <!-- ROW 6: Staffing Plan -->
  <div class="hr-section">
    <div class="hr-section-title">Headcount vs Staffing Plan</div>
    <div class="hr-g1">
      <div class="hr-card" id="hr-card-staffingplan"><div class="hr-loading"><div class="hr-spin"></div></div></div>
    </div>
  </div>

  <!-- ROW 7: Department chart + School table -->
  <div class="hr-section">
    <div class="hr-section-title">Institution Breakdown</div>
    <div class="hr-g2">
      <div class="hr-card">
        <div class="hr-card-hd"><div class="hr-card-title">Headcount by Department (Top 10)</div></div>
        <div class="hr-chart-wrap"><canvas id="chart-dept" height="180"></canvas></div>
      </div>
      <div class="hr-card" id="hr-card-schooldata"><div class="hr-loading"><div class="hr-spin"></div></div></div>
    </div>
  </div>

  <!-- ROW 8: Faculty-Student Ratio -->
  <div class="hr-section">
    <div class="hr-section-title">Faculty-Student Ratio</div>
    <div class="hr-g1">
      <div class="hr-card" id="hr-card-ratios"><div class="hr-loading"><div class="hr-spin"></div></div></div>
    </div>
  </div>

  <!-- ROW 9: Recent Movements -->
  <div class="hr-section">
    <div class="hr-section-title">Recent Movements</div>
    <div class="hr-g2">
      <div class="hr-card" id="hr-card-joiners"><div class="hr-loading"><div class="hr-spin"></div></div></div>
      <div class="hr-card" id="hr-card-leavers"><div class="hr-loading"><div class="hr-spin"></div></div></div>
    </div>
  </div>

</div><!-- /.hr-body -->
</div><!-- /#hr-root -->
		`);

		// Period toggle events
		document.querySelectorAll(".hr-period-btn").forEach(btn => {
			btn.addEventListener("click", () => {
				document.querySelectorAll(".hr-period-btn").forEach(b => b.classList.remove("active"));
				btn.classList.add("active");
				this.filters.period = btn.dataset.p;
				this.load_all();
			});
		});

		// Filter change events
		["hr-f-company","hr-f-dept","hr-f-school","hr-f-from","hr-f-to"].forEach(id => {
			document.getElementById(id).addEventListener("change", () => this._read_filters_and_reload());
		});
	}

	// ── FILTER OPTIONS ─────────────────────────────────────────────
	async load_filter_options() {
		return new Promise(resolve => {
			frappe.call({
				method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_filter_options",
				callback: (r) => {
					if (!r.message) { resolve(); return; }
					const d = r.message;
					["company","department","school"].forEach((key, i) => {
						const ids = ["hr-f-company","hr-f-dept","hr-f-school"];
						const list = [d.companies, d.departments, d.schools][i];
						const sel = document.getElementById(ids[i]);
						list.forEach(v => {
							const o = document.createElement("option");
							o.value = v; o.textContent = v;
							sel.appendChild(o);
						});
					});
					resolve();
				}
			});
		});
	}

	_read_filters_and_reload() {
		this.filters.company    = document.getElementById("hr-f-company").value;
		this.filters.department = document.getElementById("hr-f-dept").value;
		this.filters.school     = document.getElementById("hr-f-school").value;
		this.filters.date_from  = document.getElementById("hr-f-from").value;
		this.filters.date_to    = document.getElementById("hr-f-to").value;
		this.load_all();
	}

	// ── CHART HELPER ───────────────────────────────────────────────
	_make_chart(id, config) {
		const el = document.getElementById(id);
		if (!el) return;
		if (this._charts[id]) { this._charts[id].destroy(); }
		this._charts[id] = new Chart(el.getContext("2d"), config);
	}

	// ── LOAD ALL ───────────────────────────────────────────────────
	load_all() {
		const now = new Date().toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
		document.getElementById("hr-last-updated").textContent = `Updated: ${now}`;
		this.load_headcount();
		this.load_attrition();
		this.load_time_to_hire();
		this.load_offer_acceptance();
		this.load_pipeline();
		this.load_staffing_plan();
		this.load_school_ratios();
		this.load_recent_movements();
	}

	// ── 1. HEADCOUNT ───────────────────────────────────────────────
	load_headcount() {
		frappe.call({
			method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_headcount_summary",
			args: { company: this.filters.company, department: this.filters.department, school: this.filters.school },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;

				// KPI card 1 — total headcount
				document.getElementById("hr-kpi-headcount").innerHTML = `
					<div class="hr-card-hd">
						<div class="hr-card-title">Total Headcount</div>
						<div class="hr-card-icon" style="background:var(--blue-lt);">👥</div>
					</div>
					<div class="hr-metric">${d.total}</div>
					<div class="hr-metric-label">Active employees</div>
					<div class="hr-metric-sub">
						<span class="hb hb-blue">Teaching: ${d.teaching}</span>&nbsp;
						<span class="hb hb-purple">Non-Teaching: ${d.non_teaching}</span>
						${d.unclassified > 0 ? `&nbsp;<span class="hb hb-amber">Unclassified: ${d.unclassified}</span>` : ""}
					</div>`;

				// KPI card 2 — faculty %
				const pct = d.teaching_pct;
				const pctColor = pct >= 50 ? "var(--green)" : pct >= 30 ? "var(--amber)" : "var(--red)";
				document.getElementById("hr-kpi-faculty-pct").innerHTML = `
					<div class="hr-card-hd">
						<div class="hr-card-title">Faculty % of Headcount</div>
						<div class="hr-card-icon" style="background:var(--green-lt);">🎓</div>
					</div>
					<div class="hr-metric" style="color:${pctColor}">${pct}<span class="hr-metric-unit">%</span></div>
					<div class="hr-metric-label">${d.teaching} teaching of ${d.total} total</div>
					<div class="hr-metric-sub">
						Non-Teaching: ${d.non_teaching} (${d.total > 0 ? Math.round((d.non_teaching/d.total)*100) : 0}%)
					</div>`;

				// Donut chart card
				this._render_donut(d.teaching, d.non_teaching, d.unclassified);

				// Joining trend bar chart
				if (d.join_trend && d.join_trend.length) {
					this._make_chart("chart-join-trend", {
						type: "bar",
						data: {
							labels: d.join_trend.map(t => t.label),
							datasets: [{
								label: "Joiners",
								data: d.join_trend.map(t => t.value),
								backgroundColor: "#2563eb",
								borderRadius: 5,
								borderSkipped: false,
							}]
						},
						options: {
							responsive: true, maintainAspectRatio: true,
							plugins: { legend: { display: false } },
							scales: {
								y: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { font: { size: 10 } } },
								x: { grid: { display: false }, ticks: { font: { size: 10 } } }
							}
						}
					});
				}

				// Dept horizontal bar chart
				if (d.dept_data && d.dept_data.length) {
					this._make_chart("chart-dept", {
						type: "bar",
						data: {
							labels: d.dept_data.map(r => r.department),
							datasets: [{
								label: "Employees",
								data: d.dept_data.map(r => r.total),
								backgroundColor: d.dept_data.map((_, i) =>
									["#2563eb","#7c3aed","#16a34a","#d97706","#0d9488","#dc2626","#f59e0b","#3b82f6","#8b5cf6","#10b981"][i % 10]
								),
								borderRadius: 4,
								borderSkipped: false,
							}]
						},
						options: {
							indexAxis: "y",
							responsive: true, maintainAspectRatio: true,
							plugins: { legend: { display: false } },
							scales: {
								x: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { font: { size: 10 } } },
								y: { grid: { display: false }, ticks: { font: { size: 10 } } }
							}
						}
					});
				}
			}
		});
	}

	_render_donut(teaching, non_teaching, unclassified) {
		const total = teaching + non_teaching + unclassified || 1;
		const data = [
			{ label: "Teaching",      value: teaching,     color: "#2563eb" },
			{ label: "Non-Teaching",  value: non_teaching, color: "#7c3aed" },
			...(unclassified > 0 ? [{ label: "Unclassified", value: unclassified, color: "#d97706" }] : [])
		];
		const teachingPct = Math.round((teaching / total) * 100);

		document.getElementById("hr-card-typesplit").innerHTML = `
			<div class="hr-card-hd"><div class="hr-card-title">Workforce Type Split</div></div>
			<div class="hr-donut-wrap">
				<canvas id="chart-donut" width="120" height="120" style="flex-shrink:0;width:120px;height:120px;"></canvas>
				<div class="hr-donut-legend">
					${data.map(d => `
						<div class="hr-legend-item">
							<div class="hr-legend-dot" style="background:${d.color}"></div>
							<div class="hr-legend-lbl">${d.label}</div>
							<div class="hr-legend-val">${d.value}</div>
						</div>`).join("")}
					<div style="margin-top:8px;font-size:18px;font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--blue);">
						${teachingPct}% <span style="font-size:11px;font-weight:500;color:var(--muted);">Faculty</span>
					</div>
				</div>
			</div>`;

		// Chart.js doughnut
		this._make_chart("chart-donut", {
			type: "doughnut",
			data: {
				labels: data.map(d => d.label),
				datasets: [{ data: data.map(d => d.value), backgroundColor: data.map(d => d.color), borderWidth: 2, borderColor: "#fff", hoverOffset: 4 }]
			},
			options: {
				responsive: false, cutout: "70%",
				plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed} (${Math.round((ctx.parsed/total)*100)}%)` } } }
			}
		});
	}

	// ── 2. ATTRITION ──────────────────────────────────────────────
	load_attrition() {
		frappe.call({
			method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_attrition_rate",
			args: { period: this.filters.period, company: this.filters.company, department: this.filters.department, school: this.filters.school },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;
				const rateColor = d.rate > 15 ? "var(--red)" : d.rate > 8 ? "var(--amber)" : "var(--green)";

				// KPI card 3
				document.getElementById("hr-kpi-attrition").innerHTML = `
					<div class="hr-card-hd">
						<div class="hr-card-title">Attrition Rate</div>
						<div class="hr-card-icon" style="background:var(--red-lt);">📉</div>
					</div>
					<div class="hr-metric" style="color:${rateColor}">${d.rate}<span class="hr-metric-unit">%</span></div>
					<div class="hr-metric-label">${d.separations} left / ${d.avg_headcount} avg headcount</div>
					<div class="hr-metric-sub">${d.period_label}</div>
					${d.missing_relieving_date > 0 ? `<div class="hr-caveat">⚠ ${d.missing_relieving_date} missing relieving date</div>` : ""}`;

				// Attrition trend line chart
				if (d.trend && d.trend.length) {
					this._make_chart("chart-attrition-trend", {
						type: "line",
						data: {
							labels: d.trend.map(t => t.label),
							datasets: [{
								label: "Separations",
								data: d.trend.map(t => t.value),
								borderColor: "#dc2626",
								backgroundColor: "rgba(220,38,38,.08)",
								borderWidth: 2,
								pointBackgroundColor: "#dc2626",
								pointRadius: 4,
								fill: true,
								tension: 0.3,
							}]
						},
						options: {
							responsive: true, maintainAspectRatio: true,
							plugins: { legend: { display: false } },
							scales: {
								y: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { font: { size: 10 } } },
								x: { grid: { display: false }, ticks: { font: { size: 10 } } }
							}
						}
					});
				}
			}
		});
	}

	// ── 3. TIME TO HIRE ───────────────────────────────────────────
	load_time_to_hire() {
		frappe.call({
			method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_time_to_hire",
			args: { company: this.filters.company, department: this.filters.department, date_from: this.filters.date_from, date_to: this.filters.date_to },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;
				document.getElementById("hr-card-timetohire").innerHTML = `
					<div class="hr-card-hd">
						<div class="hr-card-title">Time to Hire</div>
						<div class="hr-card-icon" style="background:var(--teal-lt);">⏱</div>
					</div>
					<div style="display:flex;gap:24px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px;">
						<div>
							<div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Avg. Days</div>
							<div class="hr-metric">${d.avg_days}<span class="hr-metric-unit"> d</span></div>
						</div>
						<div>
							<div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Min</div>
							<div style="font-size:22px;font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--green);">${d.min_days}d</div>
						</div>
						<div>
							<div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">Max</div>
							<div style="font-size:22px;font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--red);">${d.max_days}d</div>
						</div>
					</div>
					<div class="hr-metric-sub" style="margin-top:0;">
						Based on <b>${d.total_hires}</b> hires with full Job Opening → Job Offer trail
						${d.first_opening_date ? `<br>First opening: <b>${d.first_opening_date}</b>${d.first_applicant !== "—" ? ` — first applicant: <b>${d.first_applicant}</b>` : ""}` : ""}
					</div>
					${d.excluded_count > 0 ? `<div class="hr-caveat">⚠ ${d.excluded_count} active employees have no applicant linked</div>` : ""}
					<div class="hr-chart-wrap" style="margin-top:16px;"><canvas id="chart-tth-trend" height="100"></canvas></div>`;

				if (d.trend && d.trend.length) {
					this._make_chart("chart-tth-trend", {
						type: "line",
						data: {
							labels: d.trend.map(t => t.label),
							datasets: [{
								label: "Avg days to hire",
								data: d.trend.map(t => t.value),
								borderColor: "#0d9488",
								backgroundColor: "rgba(13,148,136,.08)",
								borderWidth: 2,
								pointBackgroundColor: "#0d9488",
								pointRadius: 4,
								fill: true,
								tension: 0.3,
							}]
						},
						options: {
							responsive: true, maintainAspectRatio: true,
							plugins: { legend: { display: false } },
							scales: {
								y: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { font: { size: 10 } } },
								x: { grid: { display: false }, ticks: { font: { size: 10 } } }
							}
						}
					});
				}
			}
		});
	}

	// ── 4. OFFER ACCEPTANCE ───────────────────────────────────────
	load_offer_acceptance() {
		frappe.call({
			method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_offer_acceptance",
			args: { company: this.filters.company, date_from: this.filters.date_from, date_to: this.filters.date_to },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;
				const rateColor = d.rate >= 80 ? "var(--green)" : d.rate >= 60 ? "var(--amber)" : "var(--red)";

				// KPI card 4
				document.getElementById("hr-kpi-offer").innerHTML = `
					<div class="hr-card-hd">
						<div class="hr-card-title">Offer Acceptance</div>
						<div class="hr-card-icon" style="background:var(--green-lt);">✅</div>
					</div>
					<div class="hr-metric" style="color:${rateColor}">${d.rate}<span class="hr-metric-unit">%</span></div>
					<div class="hr-metric-label">${d.accepted} accepted of ${d.total} offers</div>
					<div class="hr-metric-sub">
						<span class="hb hb-red">Rejected: ${d.rejected}</span>&nbsp;
						<span class="hb hb-amber">Awaiting: ${d.awaiting}</span>
					</div>
					${d.awaiting > 0 ? `<div class="hr-caveat">⚠ ${d.awaiting} offers awaiting response</div>` : ""}`;

				// Offer outcome doughnut
				this._make_chart("chart-offer-status", {
					type: "doughnut",
					data: {
						labels: ["Accepted", "Rejected", "Awaiting"],
						datasets: [{ data: d.chart_data, backgroundColor: ["#16a34a","#dc2626","#d97706"], borderWidth: 2, borderColor: "#fff", hoverOffset: 4 }]
					},
					options: {
						responsive: true, cutout: "65%",
						plugins: {
							legend: { position: "bottom", labels: { font: { size: 11 }, boxWidth: 12, padding: 12 } },
							tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed}` } }
						}
					}
				});
			}
		});
	}

	// ── 5. RECRUITMENT PIPELINE ───────────────────────────────────
	load_pipeline() {
		frappe.call({
			method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_recruitment_pipeline",
			args: { company: this.filters.company, department: this.filters.department, date_from: this.filters.date_from, date_to: this.filters.date_to },
			callback: (r) => {
				if (!r.message) return;
				const d = r.message;

				// ── FUNNEL
				const steps = [
					{ label: "Requisitions",  sub: `${d.requisitions.approved} approved`,     value: d.requisitions.total, color: "#eff6ff", tc: "#2563eb" },
					{ label: "Job Openings",  sub: `${d.openings.open} open`,                  value: d.openings.total,      color: "#f5f3ff", tc: "#7c3aed" },
					{ label: "Applicants",    sub: `${d.applicants.open} active`,               value: d.applicants.total,    color: "#fffbeb", tc: "#d97706" },
					{ label: "Offers Sent",   sub: `${d.offers.awaiting} awaiting`,             value: d.offers.sent,         color: "#f0fdfa", tc: "#0d9488" },
					{ label: "Accepted",      sub: `${d.offers.rejected} rejected`,             value: d.offers.accepted,     color: "#f0fdf4", tc: "#16a34a" },
					{ label: "Hired",         sub: "employees created",                          value: d.hired,               color: "#f0fdf4", tc: "#16a34a" },
				];

				const funnelHtml = steps.map((s, i) => `
					${i > 0 ? `<div style="font-size:22px;color:var(--light);align-self:center;padding:0 4px;flex-shrink:0;">›</div>` : ""}
					<div class="hr-funnel-step">
						<div class="hr-funnel-box" style="background:${s.color};color:${s.tc};">${s.value}</div>
						<div class="hr-funnel-lbl">${s.label}</div>
						<div class="hr-funnel-sub">${s.sub}</div>
					</div>`).join("");

				// ── Applicant status badges
				const appBadges = `
					<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:14px;padding-top:12px;border-top:1px solid var(--border);">
						<span class="hb hb-blue">Open: ${d.applicants.open}</span>
						<span class="hb hb-purple">Replied: ${d.applicants.replied}</span>
						<span class="hb hb-amber">Hold: ${d.applicants.hold}</span>
						<span class="hb hb-green">Accepted: ${d.applicants.accepted}</span>
						<span class="hb hb-red">Rejected: ${d.applicants.rejected}</span>
					</div>`;

				document.getElementById("hr-card-pipeline").innerHTML = `
					<div class="hr-card-hd">
						<div class="hr-card-title">Full Hiring Funnel — Requisition to Hire</div>
						<small style="color:var(--muted);font-size:10px;">Kanban view: Job Applicant list view</small>
					</div>
					<div class="hr-funnel">${funnelHtml}</div>
					${appBadges}`;

				// ── Requisition status bar chart
				const reqD = d.requisitions.by_status;
				this._make_chart("chart-req-status", {
					type: "bar",
					data: {
						labels: Object.keys(reqD),
						datasets: [{
							label: "Count",
							data: Object.values(reqD),
							backgroundColor: ["#f59e0b","#2563eb","#16a34a","#dc2626","#9ca3af","#6b7280"],
							borderRadius: 5,
							borderSkipped: false,
						}]
					},
					options: {
						responsive: true, maintainAspectRatio: true,
						plugins: { legend: { display: false } },
						scales: {
							y: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { font: { size: 10 } } },
							x: { grid: { display: false }, ticks: { font: { size: 10 } } }
						}
					}
				});
			}
		});
	}

	// ── 6. STAFFING PLAN ──────────────────────────────────────────
	load_staffing_plan() {
		frappe.call({
			method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_staffing_vs_actuals",
			args: { company: this.filters.company, department: this.filters.department },
			callback: (r) => {
				if (!r.message) return;
				const rows = r.message.data;

				if (!rows || rows.length === 0) {
					document.getElementById("hr-card-staffingplan").innerHTML = `
						<div class="hr-card-hd"><div class="hr-card-title">Headcount vs Staffing Plan</div></div>
						<div style="color:var(--muted);font-size:12px;padding:20px 0;text-align:center;">
							No active staffing plans found.<br>
							<small>Create a Staffing Plan with a future end date to see comparisons.</small>
						</div>`;
					return;
				}

				const tableRows = rows.map(row => {
					const actual = row.actual || 0;
					const pct    = row.planned > 0 ? Math.min(Math.round((actual / row.planned) * 100), 100) : 0;
					const barColor = pct >= 100 ? "var(--green)" : pct >= 70 ? "var(--blue)" : "var(--amber)";
					return `<tr>
						<td><b>${row.designation}</b></td>
						<td class="mono center">${row.planned}</td>
						<td class="mono center">${actual}</td>
						<td style="min-width:130px;">
							<div style="font-size:10px;color:var(--muted);margin-bottom:3px;">${pct}%</div>
							<div class="hr-prog-wrap"><div class="hr-prog-fill" style="width:${pct}%;background:${barColor};"></div></div>
						</td>
						<td>${row.open_positions > 0 ? `<span class="hb hb-red">−${row.open_positions} open</span>` : `<span class="hb hb-green">Filled</span>`}</td>
					</tr>`;
				}).join("");

				document.getElementById("hr-card-staffingplan").innerHTML = `
					<div class="hr-card-hd">
						<div class="hr-card-title">Headcount vs Staffing Plan</div>
						<small style="color:var(--muted);font-size:10px;">Company & Dept level · School-level not supported in Staffing Plan</small>
					</div>
					<table class="hr-tbl">
						<thead><tr><th>Designation</th><th class="center">Planned</th><th class="center">Actual</th><th>Fill Rate</th><th>Status</th></tr></thead>
						<tbody>${tableRows}</tbody>
					</table>`;
			}
		});
	}

	// ── 7. SCHOOL DATA + RATIOS ───────────────────────────────────
	load_school_ratios() {
		frappe.call({
			method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_faculty_ratio",
			args: { student_counts: JSON.stringify(this.student_counts), company: this.filters.company, school: this.filters.school },
			callback: (r) => {
				if (!r.message) return;
				const data = r.message;

				// School headcount table
				const tableRows = data.map(row => `
					<tr>
						<td><b>${row.school}</b></td>
						<td class="center">${row.faculty}</td>
						<td class="center">${row.staff}</td>
						<td class="center mono"><b>${row.total_employees}</b></td>
					</tr>`).join("");

				document.getElementById("hr-card-schooldata").innerHTML = `
					<div class="hr-card-hd"><div class="hr-card-title">School-wise Headcount</div></div>
					<table class="hr-tbl">
						<thead><tr><th>School</th><th class="center">Teaching</th><th class="center">Non-Teaching</th><th class="center">Total</th></tr></thead>
						<tbody>${tableRows}</tbody>
					</table>`;

				// Ratio table with manual student input
				const ratioRows = data.map(row => `
					<tr>
						<td><b>${row.school}</b></td>
						<td class="center">${row.faculty}</td>
						<td class="center">${row.staff}</td>
						<td>
							<input class="hr-stu-input" type="number" min="0"
								value="${this.student_counts[row.school] || ""}"
								placeholder="0" data-school="${row.school}"
								onchange="window._hrDash.update_student_count('${row.school}', this.value)" />
						</td>
						<td class="center mono">${row.faculty_ratio ? `1 : ${row.faculty_ratio}` : `<span style="color:var(--light)">—</span>`}</td>
						<td class="center mono">${row.staff_ratio   ? `1 : ${row.staff_ratio}`   : `<span style="color:var(--light)">—</span>`}</td>
					</tr>`).join("");

				document.getElementById("hr-card-ratios").innerHTML = `
					<div class="hr-card-hd">
						<div class="hr-card-title">Faculty-Student & Staff-Student Ratio</div>
						<small style="color:var(--muted);font-size:10px;">Enter student counts · SIS API integration pending</small>
					</div>
					<table class="hr-tbl">
						<thead><tr><th>School</th><th class="center">Faculty</th><th class="center">Staff</th><th>Students</th><th class="center">Faculty Ratio</th><th class="center">Staff Ratio</th></tr></thead>
						<tbody>${ratioRows}</tbody>
					</table>
					<div style="font-size:10px;color:var(--light);margin-top:10px;">Ratio = Students per Faculty/Staff member</div>`;
			}
		});
	}

	update_student_count(school, value) {
		this.student_counts[school] = parseInt(value) || 0;
		this.load_school_ratios();
	}

	// ── 8. RECENT MOVEMENTS ───────────────────────────────────────
	load_recent_movements() {
		frappe.call({
			method: "custom_app.custom_app.page.hr_dashboard.hr_dashboard.get_recent_movements",
			args: { company: this.filters.company, department: this.filters.department, school: this.filters.school },
			callback: (r) => {
				if (!r.message) return;
				const colors = ["#2563eb","#7c3aed","#16a34a","#d97706","#dc2626"];

				const render_list = (list, date_field) => list.map((emp, i) => {
					const initials = (emp.employee_name || "?").split(" ").map(n => n[0]).slice(0,2).join("").toUpperCase();
					const color = colors[i % colors.length];
					const date = emp[date_field] ? frappe.datetime.str_to_user(emp[date_field]) : "—";
					return `<div class="hr-mv-item">
						<div class="hr-mv-avatar" style="background:${color}18;color:${color};">${initials}</div>
						<div class="hr-mv-info">
							<div class="hr-mv-name">${emp.employee_name}</div>
							<div class="hr-mv-meta">${emp.designation || "—"} · ${emp.custom_school || emp.department || "—"}</div>
						</div>
						<div class="hr-mv-date">${date}</div>
					</div>`;
				}).join("") || `<div style="color:var(--light);font-size:12px;padding:16px 0;text-align:center;">No records</div>`;

				document.getElementById("hr-card-joiners").innerHTML = `
					<div class="hr-card-hd"><div class="hr-card-title">Recent Joiners</div><span class="hb hb-green">↑ New</span></div>
					${render_list(r.message.joiners, "date_of_joining")}`;

				document.getElementById("hr-card-leavers").innerHTML = `
					<div class="hr-card-hd"><div class="hr-card-title">Recent Leavers</div><span class="hb hb-red">↓ Left</span></div>
					${render_list(r.message.leavers, "relieving_date")}`;
			}
		});
	}
}