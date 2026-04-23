frappe.pages['asset-dashboard'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Asset Dashboard',
		single_column: true
	});

	// ── Load Chart.js from CDN ────────────────────────────────────────────────
	const loadChartJs = () => new Promise((resolve) => {
		if (window.Chart) return resolve();
		const s = document.createElement('script');
		s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js';
		s.onload = resolve;
		document.head.appendChild(s);
	});

	// ── API module name — change to your app name ─────────────────────────────
	const API = 'custom_app.custom_app.page.asset_dashboard.asset_dashboard';

	// ── Helper: call whitelisted Python method ────────────────────────────────
	async function callApi(method, args = {}) {
		const res = await frappe.call({ method: `${API}.${method}`, args });
		return res.message;
	}

	// ── Colour palette ────────────────────────────────────────────────────────
	const PALETTE = [
		'#4F46E5','#7C3AED','#EC4899','#F59E0B','#10B981',
		'#3B82F6','#EF4444','#14B8A6','#F97316','#8B5CF6',
		'#06B6D4','#84CC16','#E11D48','#0EA5E9','#A855F7'
	];

	// ── Styles ────────────────────────────────────────────────────────────────
	const css = `
	.ad-root{font-family:var(--font-stack);padding:24px;background:var(--bg-color);}

	/* KPI */
	.ad-kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:16px;margin-bottom:28px;}
	.ad-kpi{background:var(--card-bg);border:1px solid var(--border-color);border-radius:12px;padding:20px 22px;display:flex;flex-direction:column;gap:5px;}
	.ad-kpi .ki{font-size:1.5rem;}
	.ad-kpi .kl{font-size:10px;font-weight:700;color:var(--text-muted);letter-spacing:.7px;text-transform:uppercase;}
	.ad-kpi .kv{font-size:1.65rem;font-weight:700;color:var(--text-color);line-height:1.1;}
	.ad-kpi .ks{font-size:11px;color:var(--text-muted);}

	/* Section title */
	.ad-section-title{font-size:13px;font-weight:700;color:var(--text-color);margin:0 0 14px;padding-bottom:8px;border-bottom:2px solid var(--border-color);}

	/* Chart grid */
	.ad-chart-row{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px;}
	.ad-chart-row.three{grid-template-columns:1fr 1fr 1fr;}
	@media(max-width:900px){.ad-chart-row,.ad-chart-row.three{grid-template-columns:1fr;}}
	.ad-card{background:var(--card-bg);border:1px solid var(--border-color);border-radius:12px;padding:20px 22px;}
	.ad-card canvas{width:100%!important;}

	/* Filters */
	.ad-filters{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px;align-items:flex-end;}
	.ad-fg{display:flex;flex-direction:column;gap:4px;}
	.ad-fg label{font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;}
	.ad-fg select,.ad-fg input{border:1px solid var(--border-color);border-radius:6px;padding:6px 10px;font-size:13px;background:var(--card-bg);color:var(--text-color);min-width:150px;}
	.ad-btn{padding:7px 18px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;}
	.ad-btn-primary{background:#4F46E5;color:#fff;}
	.ad-btn-primary:hover{background:#4338CA;}
	.ad-btn-ghost{background:var(--card-bg);color:var(--text-color);border:1px solid var(--border-color);}
	.ad-btn-ghost:hover{background:var(--bg-color);}

	/* Table */
	.ad-table-wrap{overflow-x:auto;}
	.ad-table{width:100%;border-collapse:collapse;font-size:12.5px;}
	.ad-table th{background:var(--control-bg);color:var(--text-muted);font-weight:600;text-align:left;padding:9px 12px;border-bottom:2px solid var(--border-color);white-space:nowrap;cursor:pointer;user-select:none;}
	.ad-table th:hover{color:var(--text-color);}
	.ad-table td{padding:8px 12px;border-bottom:1px solid var(--border-color);color:var(--text-color);}
	.ad-table tr:hover td{background:var(--bg-color);}
	.ad-badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600;}
	.ad-badge.Submitted{background:#d1fae5;color:#065f46;}
	.ad-badge.Draft{background:#fef3c7;color:#92400e;}
	.ad-badge.Cancelled,.ad-badge.Scrapped{background:#fee2e2;color:#991b1b;}
	.ad-badge.In-Maintenance{background:#dbeafe;color:#1e40af;}

	/* Pagination */
	.ad-pagination{display:flex;gap:8px;justify-content:flex-end;margin-top:14px;align-items:center;}
	.ad-page-info{font-size:12px;color:var(--text-muted);margin-right:auto;}

	/* Top bar list */
	.ad-top-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;}
	.ad-top-list li{display:flex;align-items:center;gap:10px;}
	.ad-top-list .bl{font-size:12px;color:var(--text-color);min-width:130px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
	.ad-top-list .bt{flex:1;height:8px;background:var(--border-color);border-radius:4px;overflow:hidden;}
	.ad-top-list .bf{height:100%;border-radius:4px;background:#4F46E5;transition:width .4s;}
	.ad-top-list .bv{font-size:12px;color:var(--text-muted);min-width:90px;text-align:right;}

	/* Loader */
	.ad-loader{display:flex;align-items:center;justify-content:center;padding:80px;flex-direction:column;gap:14px;color:var(--text-muted);font-size:14px;}
	.ad-spinner{width:36px;height:36px;border:3px solid var(--border-color);border-top-color:#4F46E5;border-radius:50%;animation:ad-spin .7s linear infinite;}
	@keyframes ad-spin{to{transform:rotate(360deg);}}
	`;
	$('<style>').text(css).appendTo('head');

	// ── Root ──────────────────────────────────────────────────────────────────
	const $root = $('<div class="ad-root">').appendTo(page.main);

	// ── State ─────────────────────────────────────────────────────────────────
	let currentPage = 1;
	let currentOrder = 'creation_desc';
	let totalRows    = 0;
	const PAGE_SIZE  = 20;
	let charts = {};

	// ── Formatters ────────────────────────────────────────────────────────────
	const fmtCur = v => '₹ ' + Number(v||0).toLocaleString('en-IN', { maximumFractionDigits:0 });
	const fmtNum = v => Number(v||0).toLocaleString('en-IN');

	// ── Chart helpers ─────────────────────────────────────────────────────────
	function destroyChart(key) {
		if (charts[key]) { charts[key].destroy(); delete charts[key]; }
	}

	function makeDonut(id, key, labels, data) {
		destroyChart(key);
		const ctx = document.getElementById(id)?.getContext('2d');
		if (!ctx) return;
		charts[key] = new Chart(ctx, {
			type: 'doughnut',
			data: { labels, datasets: [{ data, backgroundColor: PALETTE.slice(0, labels.length), borderWidth: 2, hoverOffset: 6 }] },
			options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } } } }
		});
	}

	function makeBar(id, key, labels, data, label, horizontal = false) {
		destroyChart(key);
		const ctx = document.getElementById(id)?.getContext('2d');
		if (!ctx) return;
		charts[key] = new Chart(ctx, {
			type: 'bar',
			data: { labels, datasets: [{ label, data, backgroundColor: PALETTE.slice(0, labels.length), borderRadius: 4 }] },
			options: {
				indexAxis: horizontal ? 'y' : 'x', responsive: true, maintainAspectRatio: true,
				plugins: { legend: { display: false } },
				scales: { x: { grid: { display: !horizontal }, ticks: { font: { size: 10 } } }, y: { grid: { display: horizontal }, ticks: { font: { size: 10 } } } }
			}
		});
	}

	function makeLine(id, key, labels, data) {
		destroyChart(key);
		const ctx = document.getElementById(id)?.getContext('2d');
		if (!ctx) return;
		charts[key] = new Chart(ctx, {
			type: 'line',
			data: { labels, datasets: [{ label: 'Assets Added', data, borderColor: '#4F46E5', backgroundColor: 'rgba(79,70,229,.12)', borderWidth: 2, pointRadius: 3, fill: true, tension: .35 }] },
			options: { responsive: true, maintainAspectRatio: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { font: { size: 10 } } }, y: { beginAtZero: true, ticks: { font: { size: 10 } } } } }
		});
	}

	// ── Collect active filters ────────────────────────────────────────────────
	function getFilters() {
		return {
			company:        $root.find('#f-company').val()    || '',
			asset_category: $root.find('#f-category').val()  || '',
			status:         $root.find('#f-status').val()    || '',
			location:       $root.find('#f-location').val()  || '',
			department:     $root.find('#f-dept').val()      || '',
			from_date:      $root.find('#f-from').val()      || '',
			to_date:        $root.find('#f-to').val()        || ''
		};
	}

	// ── Render KPIs ───────────────────────────────────────────────────────────
	function renderKPIs(d) {
		const kpis = [
			{ icon: '📦', label: 'Total Assets',      value: fmtNum(d.total_assets),          sub: 'All records' },
			{ icon: '💰', label: 'Purchase Value',     value: fmtCur(d.total_purchase_value),  sub: 'Gross value' },
			{ icon: '📒', label: 'Book Value',         value: fmtCur(d.total_book_value),      sub: 'After depreciation' },
			{ icon: '📉', label: 'Total Depreciation', value: fmtCur(d.total_depreciation),    sub: 'Accumulated' },
			{ icon: '✅', label: 'Submitted',          value: fmtNum(d.submitted_count),       sub: 'Active assets' },
			{ icon: '🏷️', label: 'Categories',         value: fmtNum(d.total_categories),      sub: 'Unique types' },
			{ icon: '🏢', label: 'Companies',          value: fmtNum(d.total_companies),       sub: 'Entities' },
			{ icon: '📍', label: 'Locations',          value: fmtNum(d.total_locations),       sub: 'Sites' },
		];
		$root.find('.ad-kpi-row').html(
			kpis.map(k => `<div class="ad-kpi"><span class="ki">${k.icon}</span><span class="kl">${k.label}</span><span class="kv">${k.value}</span><span class="ks">${k.sub}</span></div>`).join('')
		);
	}

	// ── Render all charts ─────────────────────────────────────────────────────
	function renderCharts(byCategory, byCompany, byStatus, byLocation, trend, byDept, byItem, byVendor) {

		// Category count donut
		makeDonut('chart-cat-count', 'cat-count',
			byCategory.map(r => r.category || 'Unknown'),
			byCategory.map(r => r.count));

		// Category value bar
		const topCat = [...byCategory].sort((a, b) => b.total_value - a.total_value).slice(0, 10);
		makeBar('chart-cat-value', 'cat-value',
			topCat.map(r => r.category || 'Unknown'),
			topCat.map(r => r.total_value),
			'Value (₹)', true);

		// Company donut
		makeDonut('chart-company', 'company',
			byCompany.map(r => r.company || 'Unknown'),
			byCompany.map(r => r.count));

		// Status bar
		makeBar('chart-status', 'status',
			byStatus.map(r => r.status || 'Unknown'),
			byStatus.map(r => r.count),
			'Count');

		// Monthly trend line
		makeLine('chart-trend', 'trend',
			trend.map(r => r.month),
			trend.map(r => r.count));

		// Location bar
		makeBar('chart-location', 'location',
			byLocation.map(r => r.location || 'Unassigned'),
			byLocation.map(r => r.count),
			'Count', true);

		// Department donut
		makeDonut('chart-dept', 'dept',
			byDept.map(r => r.department),
			byDept.map(r => r.count));

		// Vendor value bar
		makeBar('chart-vendor', 'vendor',
			byVendor.map(r => r.supplier_name || r.vendor || 'Unknown'),
			byVendor.map(r => r.total_value),
			'Spend (₹)', true);

		// Top items by value — inline bar list
		const maxVal = byItem[0]?.total_value || 1;
		$root.find('.ad-top-list').html(
			byItem.map(r => `
			<li>
				<span class="bl" title="${r.item_name}">${r.item_name || r.item_code || '-'}</span>
				<span class="bt"><span class="bf" style="width:${(r.total_value / maxVal * 100).toFixed(1)}%"></span></span>
				<span class="bv">${fmtCur(r.total_value)}</span>
			</li>`).join('')
		);
	}

	// ── Render paginated table ────────────────────────────────────────────────
	function renderTable(result) {
		const { data, total, page, page_size } = result;
		const start = (page - 1) * page_size;
		totalRows   = total;

		const sortArrow = (col) => currentOrder.startsWith(col)
			? (currentOrder.endsWith('asc') ? ' ↑' : ' ↓') : '';

		$root.find('.ad-table-wrap').html(`
		<table class="ad-table">
			<thead><tr>
				<th>#</th>
				<th data-col="name"    >Asset ID${sortArrow('name')}</th>
				<th data-col="name_asc">Asset Name${sortArrow('name')}</th>
				<th data-col="category_asc">Category${sortArrow('category')}</th>
				<th>Item Group</th>
				<th>Company</th>
				<th>Location</th>
				<th>Department</th>
				<th>Supplier</th>
				<th>Status</th>
				<th data-col="purchase_date">Purchase Date${sortArrow('purchase_date')}</th>
				<th data-col="value">Purchase Value${sortArrow('value')}</th>
				<th>Book Value</th>
			</tr></thead>
			<tbody>
			${data.map((r, i) => `
				<tr>
					<td>${start + i + 1}</td>
					<td><a href="/app/asset/${r.id}" target="_blank">${r.id || '-'}</a></td>
					<td>${r.asset_name || '-'}</td>
					<td>${r.asset_category || '-'}</td>
					<td>${r.item_group || '-'}</td>
					<td>${r.company || '-'}</td>
					<td>${r.location || '-'}</td>
					<td>${r.department || '-'}</td>
					<td>${r.supplier_name || r.vendor || '-'}</td>
					<td><span class="ad-badge ${(r.status||'').replace(' ','-')}">${r.status || '-'}</span></td>
					<td>${r.purchase_date || '-'}</td>
					<td>${fmtCur(r.purchase_value)}</td>
					<td>${fmtCur(r.book_value)}</td>
				</tr>`).join('')}
			</tbody>
		</table>`);

		const pages = Math.ceil(total / page_size);
		$root.find('.ad-page-info').text(`Showing ${start + 1}–${Math.min(start + page_size, total)} of ${fmtNum(total)}`);

		const $pg = $root.find('.ad-pagination');
		$pg.find('.pg-btn').remove();
		const mkBtn = (label, p, disabled = false) =>
			`<button class="ad-btn ad-btn-ghost pg-btn" data-page="${p}" ${disabled ? 'disabled' : ''}>${label}</button>`;
		$pg.append(mkBtn('‹', page - 1, page <= 1));
		[...new Set([1, page - 1, page, page + 1, pages])].filter(p => p >= 1 && p <= pages).sort((a, b) => a - b)
			.forEach(p => $pg.append(mkBtn(p, p, p === page)));
		$pg.append(mkBtn('›', page + 1, page >= pages));
	}

	// ── Build DOM skeleton ────────────────────────────────────────────────────
	$root.html(`
	<div class="ad-loader" id="ad-loader"><div class="ad-spinner"></div><span>Loading…</span></div>
	<div id="ad-content" style="display:none">

		<!-- Filters -->
		<div class="ad-filters">
			<div class="ad-fg"><label>Company</label>
				<select id="f-company"><option value="">All Companies</option></select></div>
			<div class="ad-fg"><label>Category</label>
				<select id="f-category"><option value="">All Categories</option></select></div>
			<div class="ad-fg"><label>Status</label>
				<select id="f-status"><option value="">All Statuses</option></select></div>
			<div class="ad-fg"><label>Location</label>
				<select id="f-location"><option value="">All Locations</option></select></div>
			<div class="ad-fg"><label>Department</label>
				<select id="f-dept"><option value="">All Departments</option></select></div>
			<div class="ad-fg"><label>From Date</label>
				<input id="f-from" type="date"></div>
			<div class="ad-fg"><label>To Date</label>
				<input id="f-to" type="date"></div>
			<button class="ad-btn ad-btn-primary" id="btn-apply">Apply</button>
			<button class="ad-btn ad-btn-ghost"   id="btn-reset">Reset</button>
		</div>

		<!-- KPIs -->
		<div class="ad-kpi-row"></div>

		<!-- Row 1: Category -->
		<div class="ad-chart-row">
			<div class="ad-card">
				<div class="ad-section-title">Assets by Category (Count)</div>
				<canvas id="chart-cat-count" height="220"></canvas></div>
			<div class="ad-card">
				<div class="ad-section-title">Category Value Breakdown (Top 10)</div>
				<canvas id="chart-cat-value" height="220"></canvas></div>
		</div>

		<!-- Row 2: Company / Status / Trend -->
		<div class="ad-chart-row three">
			<div class="ad-card">
				<div class="ad-section-title">Assets by Company</div>
				<canvas id="chart-company" height="200"></canvas></div>
			<div class="ad-card">
				<div class="ad-section-title">Status Distribution</div>
				<canvas id="chart-status" height="200"></canvas></div>
			<div class="ad-card">
				<div class="ad-section-title">Monthly Addition Trend</div>
				<canvas id="chart-trend" height="200"></canvas></div>
		</div>

		<!-- Row 3: Location / Department -->
		<div class="ad-chart-row">
			<div class="ad-card">
				<div class="ad-section-title">Assets by Location (Top 20)</div>
				<canvas id="chart-location" height="220"></canvas></div>
			<div class="ad-card">
				<div class="ad-section-title">Assets by Department</div>
				<canvas id="chart-dept" height="220"></canvas></div>
		</div>

		<!-- Row 4: Vendor / Top Items -->
		<div class="ad-chart-row">
			<div class="ad-card">
				<div class="ad-section-title">Vendor Spend (Top 15)</div>
				<canvas id="chart-vendor" height="220"></canvas></div>
			<div class="ad-card">
				<div class="ad-section-title">Top Items by Total Value</div>
				<ul class="ad-top-list"></ul>
			</div>
		</div>

		<!-- Asset Register Table -->
		<div class="ad-card" style="margin-bottom:0">
			<div class="ad-section-title">Asset Register</div>
			<div class="ad-table-wrap"></div>
			<div class="ad-pagination">
				<span class="ad-page-info"></span>
			</div>
		</div>
	</div>`);

	// ── Events ────────────────────────────────────────────────────────────────
	$root.on('click', '.pg-btn', function () {
		currentPage = parseInt($(this).data('page'));
		loadTable();
	});

	$root.on('click', '.ad-table th[data-col]', function () {
		const col = $(this).data('col');
		if (currentOrder === col + '_desc') currentOrder = col + '_asc';
		else currentOrder = col + '_desc';
		currentPage = 1;
		loadTable();
	});

	$root.on('click', '#btn-apply', () => { currentPage = 1; loadAll(); });
	$root.on('click', '#btn-reset', () => {
		$root.find('#f-company,#f-category,#f-status,#f-location,#f-dept').val('');
		$root.find('#f-from,#f-to').val('');
		currentPage = 1;
		loadAll();
	});

	// ── Populate dropdowns from API ───────────────────────────────────────────
	async function populateFilters() {
		const opts = await callApi('get_filter_options');
		const fill = (sel, arr) => {
			const $s = $root.find(sel);
			arr.forEach(v => $s.append(`<option value="${v}">${v}</option>`));
		};
		fill('#f-company',  opts.companies);
		fill('#f-category', opts.categories);
		fill('#f-status',   opts.statuses);
		fill('#f-location', opts.locations);
		fill('#f-dept',     opts.departments);
	}

	// ── Load only table (sort / page change) ─────────────────────────────────
	async function loadTable() {
		const filters = getFilters();
		const result  = await callApi('get_asset_register', {
			filters: JSON.stringify(filters),
			page:    currentPage,
			page_size: PAGE_SIZE,
			order_by: currentOrder
		});
		renderTable(result);
	}

	// ── Load everything ───────────────────────────────────────────────────────
	async function loadAll() {
		$root.find('#ad-loader').show();
		$root.find('#ad-content').hide();
		const filters = getFilters();
		const fj = JSON.stringify(filters);

		try {
			await loadChartJs();

			const [kpi, byCat, byComp, byStatus, byLoc, trend, byDept, byItem, byVendor, register] = await Promise.all([
				callApi('get_kpi_summary',        { filters: fj }),
				callApi('get_assets_by_category', { filters: fj }),
				callApi('get_assets_by_company',  { filters: fj }),
				callApi('get_assets_by_status',   { filters: fj }),
				callApi('get_assets_by_location', { filters: fj }),
				callApi('get_monthly_trend',      { filters: fj }),
				callApi('get_assets_by_department',{ filters: fj }),
				callApi('get_assets_by_item',     { filters: fj }),
				callApi('get_assets_by_vendor',   { filters: fj }),
				callApi('get_asset_register',     { filters: fj, page: currentPage, page_size: PAGE_SIZE, order_by: currentOrder })
			]);

			$root.find('#ad-loader').hide();
			$root.find('#ad-content').show();

			renderKPIs(kpi);
			renderCharts(byCat, byComp, byStatus, byLoc, trend, byDept, byItem, byVendor);
			renderTable(register);

		} catch (e) {
			$root.find('#ad-loader').html(`<span style="color:var(--red)">⚠ Failed to load. Check console.</span>`);
			console.error('Asset Dashboard Error:', e);
		}
	}

	// ── Init ──────────────────────────────────────────────────────────────────
	populateFilters().then(() => loadAll());
};