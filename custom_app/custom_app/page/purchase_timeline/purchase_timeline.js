frappe.pages["purchase-timeline"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Purchase Timeline",
		single_column: true,
	});
	new PurchaseTimeline(page, wrapper);
};

class PurchaseTimeline {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.filters = {};
		this.trees = [];
		this.controls = {};
		this._debounceTimer = null;
		this._selectedNodeId = null;
		this._injectStyles();
		this._injectPageHeader();
		this._buildLayout();
		this._loadFilterOptions();
	}

	// ─────────────────────────────────────────────────────────────
	// STYLES
	// ─────────────────────────────────────────────────────────────
	_injectStyles() {
		if (document.getElementById("pt-styles")) return;
		const style = document.createElement("style");
		style.id = "pt-styles";
		style.textContent = `
		/* ── Root ── */
		.pt-root {
			display: flex; flex-direction: column;
			height: calc(100vh - 110px); overflow: hidden;
			background: #f0f2f5; font-family: inherit;
		}

		/* ── Filter bar ── */
		.pt-bar {
			background: #fff;
			border-bottom: 1px solid #e4e7ec;
			padding: 10px 20px;
			flex-shrink: 0;
			box-shadow: 0 1px 4px rgba(0,0,0,.05);
		}
		.pt-bar-top {
			display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
		}
		.pt-search-by-wrap {
			display: flex; align-items: center; gap: 8px;
			background: #f7f8fa; border: 1px solid #e4e7ec;
			border-radius: 8px; padding: 6px 12px;
			cursor: pointer; transition: border-color .15s, background .15s;
			user-select: none;
		}
		.pt-search-by-wrap:hover { border-color: #7f56d9; background: #faf8ff; }
		.pt-search-by-label { font-size: 12px; font-weight: 600; color: #667085; }
		.pt-search-by-val { font-size: 12px; font-weight: 700; color: #7f56d9; }
		.pt-search-by-chevron { font-size: 10px; color: #98a2b3; margin-left: 2px; transition: transform .2s; }
		.pt-search-by-chevron.open { transform: rotate(180deg); }

		.pt-filters-expanded {
			display: none; margin-top: 10px;
			padding-top: 10px; border-top: 1px solid #f2f4f7;
		}
		.pt-filters-expanded.open { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }

		.pt-fg { display: flex; flex-direction: column; min-width: 140px; flex: 1 1 140px; max-width: 200px; }
		.pt-fg-sm { flex: 0 1 130px; max-width: 140px; }
		.pt-fg-date { flex: 0 1 130px; max-width: 140px; }
		.pt-fl { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px; color: #98a2b3; margin-bottom: 3px; }
		.pt-fg .form-control, .pt-fg select, .pt-fg input[type=date] {
			font-size: 12px; height: 30px; padding: 3px 8px;
			border: 1px solid #d0d5dd; border-radius: 6px;
			width: 100%; background: #fff; color: #101828;
			appearance: auto;
		}
		.pt-fg .form-control:focus, .pt-fg select:focus, .pt-fg input[type=date]:focus {
			outline: none; border-color: #7f56d9;
			box-shadow: 0 0 0 3px rgba(127,86,217,.1);
		}
		.pt-fg .frappe-control { margin-bottom: 0; }
		.pt-fg .frappe-control .control-input-wrapper { padding: 0; }
		.pt-fg .frappe-control label.control-label { display: none; }
		.pt-fg .awesomplete { width: 100%; }

		.pt-bar-actions { display: flex; gap: 8px; align-items: center; margin-left: auto; }
		.pt-btn {
			height: 30px; padding: 0 12px; border-radius: 6px;
			font-size: 12px; font-weight: 600; cursor: pointer;
			border: 1px solid #d0d5dd; background: #fff; color: #344054;
			display: inline-flex; align-items: center; gap: 5px;
			transition: background .15s, border-color .15s;
			white-space: nowrap;
		}
		.pt-btn:hover { background: #f5f7fa; }
		.pt-btn-primary {
			background: #7f56d9; border-color: #7f56d9; color: #fff;
		}
		.pt-btn-primary:hover { background: #6941c6; border-color: #6941c6; }

		.pt-active-dot {
			width: 7px; height: 7px; border-radius: 50%;
			background: #7f56d9; display: none;
		}
		.pt-active-dot.show { display: inline-block; }

		.pt-filter-tag {
			display: inline-flex; align-items: center; gap: 4px;
			background: #f4f0ff; border: 1px solid #d6bbfb;
			border-radius: 20px; padding: 2px 8px;
			font-size: 11px; font-weight: 600; color: #6941c6;
		}
		.pt-filter-tag button {
			background: none; border: none; cursor: pointer;
			color: #9e77ed; font-size: 12px; padding: 0; line-height: 1;
		}
		.pt-active-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }

		/* ── Main area ── */
		.pt-main {
			flex: 1; overflow: hidden; display: flex;
			flex-direction: row; position: relative;
		}

		/* ── Canvas area ── */
		.pt-canvas {
			flex: 1; overflow-y: auto; padding: 20px 24px;
			transition: margin-right .3s;
		}
		.pt-canvas.panel-open { margin-right: 360px; }

		/* ── Loading / empty ── */
		.pt-loading {
			display: flex; align-items: center; justify-content: center;
			gap: 10px; padding: 80px 20px; color: #667085; font-size: 14px;
		}
		.pt-spinner {
			width: 20px; height: 20px; border: 2.5px solid #e2e6ea;
			border-top-color: #7f56d9; border-radius: 50%;
			animation: pt-spin .7s linear infinite;
		}
		@keyframes pt-spin { to { transform: rotate(360deg); } }
		.pt-empty { text-align: center; padding: 80px 20px; color: #98a2b3; }
		.pt-empty h4 { font-size: 15px; color: #667085; margin-bottom: 6px; }
		.pt-empty p { font-size: 13px; }

		/* ── Result header ── */
		.pt-result-header {
			display: flex; align-items: center; justify-content: space-between;
			margin-bottom: 16px; flex-wrap: wrap; gap: 8px;
		}
		.pt-result-count { font-size: 13px; color: #667085; }
		.pt-result-count strong { color: #344054; }

		/* ── Graph cards ── */
		.pt-graph-card {
			background: #fff; border: 1px solid #e4e7ec; border-radius: 12px;
			margin-bottom: 20px; overflow: hidden;
			box-shadow: 0 1px 4px rgba(0,0,0,.04);
		}
		.pt-graph-card-header {
			padding: 12px 16px; border-bottom: 1px solid #f2f4f7;
			display: flex; align-items: center; gap: 10px;
			background: #fafbfc;
		}
		.pt-graph-card-icon {
			width: 30px; height: 30px; border-radius: 7px;
			display: flex; align-items: center; justify-content: center;
			font-size: 14px; background: #f4f0ff; color: #7f56d9; flex-shrink: 0;
		}
		.pt-graph-card-title { font-weight: 700; font-size: 13px; color: #101828; }
		.pt-graph-card-sub { font-size: 11px; color: #667085; margin-top: 1px; }
		.pt-graph-card-badges { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 4px; }
		.pt-graph-card-body { padding: 16px; overflow-x: auto; }

		/* ── SVG graph ── */
		.pt-gsvg { display: block; }
		.pt-gnode { cursor: pointer; }
		.pt-gnode rect {
			rx: 8; stroke-width: 1.5px;
			transition: filter .15s, opacity .2s;
		}
		.pt-gnode text { font-size: 11px; font-family: inherit; pointer-events: none; transition: opacity .2s; }
		.pt-gnode .pt-gsub { font-size: 9.5px; fill: #667085; }
		.pt-gedge { stroke: #d0d5dd; stroke-width: 1.5px; fill: none; transition: opacity .2s, stroke .2s; }

		/* Selection dim */
		.pt-gsvg.pt-sel .pt-gnode rect { opacity: .18; }
		.pt-gsvg.pt-sel .pt-gnode text { opacity: .18; }
		.pt-gsvg.pt-sel .pt-gedge { opacity: .08; }
		.pt-gsvg.pt-sel .pt-gnode.pt-gactive rect { opacity: 1; }
		.pt-gsvg.pt-sel .pt-gnode.pt-gactive text { opacity: 1; }
		.pt-gsvg.pt-sel .pt-gedge.pt-geactive { opacity: 1; stroke: #7f56d9; stroke-width: 2px; }

		/* Hover glow */
		.pt-gnode:hover rect { filter: brightness(.93); }
		.pt-gnode.pt-gactive rect { filter: drop-shadow(0 0 4px rgba(127,86,217,.4)); }

		.pt-graph-hint {
			font-size: 11px; color: #c0c7d0; text-align: right; padding: 4px 0 0; margin-top: 6px;
		}

		/* ── Detail panel ── */
		.pt-panel {
			position: absolute; right: 0; top: 0; bottom: 0;
			width: 360px; background: #fff;
			border-left: 1px solid #e4e7ec;
			box-shadow: -4px 0 20px rgba(0,0,0,.07);
			display: flex; flex-direction: column;
			transform: translateX(100%);
			transition: transform .3s cubic-bezier(.4,0,.2,1);
			z-index: 10;
		}
		.pt-panel.open { transform: translateX(0); }
		.pt-panel-header {
			padding: 14px 16px; border-bottom: 1px solid #f2f4f7;
			display: flex; align-items: flex-start; gap: 10px;
			background: #fafbfc; flex-shrink: 0;
		}
		.pt-panel-icon {
			width: 36px; height: 36px; border-radius: 8px;
			display: flex; align-items: center; justify-content: center;
			font-size: 18px; flex-shrink: 0;
		}
		.pt-panel-title { font-size: 13px; font-weight: 700; color: #101828; }
		.pt-panel-name { font-size: 12px; color: #7f56d9; font-weight: 600; margin-top: 1px; }
		.pt-panel-name a { color: inherit; text-decoration: none; }
		.pt-panel-name a:hover { text-decoration: underline; }
		.pt-panel-close {
			margin-left: auto; flex-shrink: 0; background: none; border: none;
			cursor: pointer; font-size: 18px; color: #98a2b3; padding: 2px 6px;
			border-radius: 5px; line-height: 1; transition: background .15s;
		}
		.pt-panel-close:hover { background: #f2f4f7; color: #344054; }
		.pt-panel-body { flex: 1; overflow-y: auto; padding: 14px 16px; }

		/* Badges */
		.pt-badge {
			display: inline-flex; align-items: center; gap: 4px;
			font-size: 11px; font-weight: 500; border-radius: 20px;
			padding: 2px 8px; white-space: nowrap;
		}
		.pt-badge-purple  { background: #f4f0ff; color: #7f56d9; }
		.pt-badge-blue    { background: #eff8ff; color: #1570ef; }
		.pt-badge-green   { background: #ecfdf3; color: #027a48; }
		.pt-badge-orange  { background: #fff6ed; color: #c4320a; }
		.pt-badge-gray    { background: #f2f4f7; color: #344054; }
		.pt-badge-red     { background: #fef3f2; color: #b42318; }
		.pt-badge-yellow  { background: #fffaeb; color: #b54708; }
		.pt-badge-teal    { background: #f0fdf4; color: #107569; }

		/* Detail grid in panel */
		.pt-dg { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; margin-bottom: 14px; }
		.pt-di .lbl { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: #98a2b3; display: block; }
		.pt-di .val { font-size: 12px; font-weight: 600; color: #101828; }
		.pt-di.full { grid-column: 1 / -1; }
		.pt-section-title {
			font-size: 10px; font-weight: 700; text-transform: uppercase;
			letter-spacing: .6px; color: #98a2b3; margin: 14px 0 6px;
			display: flex; align-items: center; gap: 6px;
		}
		.pt-section-title::after { content: ""; flex: 1; height: 1px; background: #f2f4f7; }

		/* Items table in panel */
		.pt-items-tbl { width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 4px; }
		.pt-items-tbl th { background: #f5f7fa; color: #667085; font-weight: 600; padding: 5px 6px; text-align: left; border-bottom: 1px solid #e2e6ea; }
		.pt-items-tbl td { padding: 4px 6px; border-bottom: 1px solid #f2f4f7; color: #344054; }
		.pt-items-tbl tr:last-child td { border-bottom: none; }
		.pt-items-toggle {
			font-size: 11px; color: #7f56d9; cursor: pointer; font-weight: 600;
			display: inline-flex; align-items: center; gap: 4px; margin-bottom: 5px;
		}
		.pt-items-table-wrap { display: none; }
		.pt-items-table-wrap.open { display: block; }

		/* Open link btn */
		.pt-open-link {
			display: flex; align-items: center; justify-content: center; gap: 6px;
			width: 100%; padding: 8px; margin-top: 12px;
			border: 1px solid #d6bbfb; border-radius: 8px;
			background: #faf5ff; color: #6941c6; font-size: 12px; font-weight: 600;
			text-decoration: none; cursor: pointer; transition: background .15s;
		}
		.pt-open-link:hover { background: #f4f0ff; }

		/* ── Tooltip ── */
		.pt-tooltip {
			position: fixed; background: #101828; color: #fff;
			font-size: 11px; padding: 6px 10px; border-radius: 6px;
			pointer-events: none; z-index: 9999; max-width: 220px;
			box-shadow: 0 4px 12px rgba(0,0,0,.2); line-height: 1.5;
			display: none;
		}

		/* Scrollbar */
		.pt-canvas::-webkit-scrollbar, .pt-panel-body::-webkit-scrollbar { width: 4px; }
		.pt-canvas::-webkit-scrollbar-thumb, .pt-panel-body::-webkit-scrollbar-thumb { background: #e2e6ea; border-radius: 4px; }

		/* ── Themed page header ── */
		.pt-header {
			background: #1a1d23;
			padding: 18px 24px;
			display: flex; align-items: center; justify-content: center;
			flex-shrink: 0;
		}
		.pt-header-left { text-align: center; }
		.pt-header-left h1 {
			font-size: 20px; font-weight: 700; color: #fff;
			letter-spacing: -.3px; margin: 0;
		}
		.pt-header-left h1 span { color: #9e77ed; }
		.pt-header-left p {
			font-size: 11px; color: rgba(255,255,255,.4);
			margin-top: 3px; letter-spacing: .4px; text-transform: uppercase;
		}

		/* ── Fix filter alignment ── */
		.pt-fg .frappe-control { margin-bottom: 0 !important; }
		.pt-fg .frappe-control .form-group { margin-bottom: 0 !important; }
		.pt-fg .frappe-control .control-input-wrapper {
			padding: 0 !important;
			height: 30px !important;
			display: flex; align-items: center;
		}
		.pt-fg .frappe-control .input-with-feedback,
		.pt-fg .frappe-control .awesomplete > input {
			height: 30px !important;
			font-size: 12px !important;
			padding: 3px 8px !important;
			border: 1px solid #d0d5dd !important;
			border-radius: 6px !important;
			margin: 0 !important;
			line-height: normal !important;
		}
		.pt-fg .frappe-control .input-with-feedback:focus,
		.pt-fg .frappe-control .awesomplete > input:focus {
			border-color: #7f56d9 !important;
			box-shadow: 0 0 0 3px rgba(127,86,217,.1) !important;
			outline: none !important;
		}
		.pt-fg .frappe-control .control-label { display: none !important; }
		.pt-fg .frappe-control .control-input { padding: 0 !important; }
		`;
		document.head.appendChild(style);
	}

	// ─────────────────────────────────────────────────────────────
	// PAGE HEADER
	// ─────────────────────────────────────────────────────────────
	_injectPageHeader() {
		if (!document.getElementById("pt-page-head-style")) {
			const s = document.createElement("style");
			s.id = "pt-page-head-style";
			s.textContent = `.page-head { display: none !important; }`;
			document.head.appendChild(s);
		}
	}

	// ─────────────────────────────────────────────────────────────
	// LAYOUT
	// ─────────────────────────────────────────────────────────────
	_buildLayout() {
		this.$root = $(`
			<div class="pt-root">
				<div class="pt-header">
					<div class="pt-header-left">
						<h1>Purchase <span>Timeline</span></h1>
						<p>End-to-end procurement · PR → RFQ → SQ → PO → Receipt / Invoice</p>
					</div>
				</div>
				<div class="pt-bar">
					<div class="pt-bar-top">
						<div class="pt-search-by-wrap" id="pt-search-by-toggle">
							<span class="pt-search-by-label">Search by</span>
							<span class="pt-search-by-val" id="pt-search-by-val">All</span>
							<span class="pt-search-by-chevron" id="pt-sb-chev">▼</span>
						</div>
						<div id="pt-active-tags" class="pt-active-tags" style="flex:1;"></div>
						<div class="pt-bar-actions">
							<span class="pt-active-dot" id="pt-dot"></span>
							<button class="pt-btn" id="pt-clear">✕ Clear</button>
							<button class="pt-btn pt-btn-primary" id="pt-search-btn">⌕ Search</button>
						</div>
					</div>
					<div class="pt-filters-expanded" id="pt-filters-expanded"></div>
				</div>
				<div class="pt-main" id="pt-main-wrap">
					<div class="pt-canvas" id="pt-canvas">
						<div class="pt-loading"><div class="pt-spinner"></div> Loading…</div>
					</div>
					<div class="pt-panel" id="pt-panel">
						<div class="pt-panel-header" id="pt-panel-header">
							<div class="pt-panel-icon" id="pt-panel-icon">📋</div>
							<div style="flex:1;min-width:0;">
								<div class="pt-panel-title" id="pt-panel-title">Document Details</div>
								<div class="pt-panel-name" id="pt-panel-name"></div>
							</div>
							<button class="pt-panel-close" id="pt-panel-close">×</button>
						</div>
						<div class="pt-panel-body" id="pt-panel-body"></div>
					</div>
				</div>
			</div>
			<div class="pt-tooltip" id="pt-tooltip"></div>
		`).appendTo($(this.wrapper).find(".page-content"));

		this.$canvas = this.$root.find("#pt-canvas");
		this.$panel = this.$root.find("#pt-panel");
		this.$filterRow = this.$root.find("#pt-filters-expanded");
		this.$dot = this.$root.find("#pt-dot");
		this.$activeTags = this.$root.find("#pt-active-tags");
		this.$tooltip = $("#pt-tooltip");

		// Toggle filter expand/collapse
		this.$root.find("#pt-search-by-toggle").on("click", () => {
			const $exp = this.$filterRow;
			const open = $exp.toggleClass("open").hasClass("open");
			this.$root.find("#pt-sb-chev").toggleClass("open", open);
		});

		this.$root.find("#pt-clear").on("click", () => this._clearFilters());
		this.$root.find("#pt-search-btn").on("click", () => this._fetchTree(true));
		this.$root.find("#pt-panel-close").on("click", () => this._closePanel());
	}

	// ─────────────────────────────────────────────────────────────
	// LOAD FILTER OPTIONS
	// ─────────────────────────────────────────────────────────────
	_loadFilterOptions() {
		frappe.call({
			method: "custom_app.custom_app.page.purchase_timeline.purchase_timeline.get_filter_options",
			callback: (r) => {
				if (r.message) {
					this.filterOptions = r.message;
					this._buildFilters(r.message);
					this._fetchTree();
				}
			},
		});
	}

	// ─────────────────────────────────────────────────────────────
	// BUILD FILTERS
	// ─────────────────────────────────────────────────────────────
	_buildFilters(opts) {
		let html = "";

		// "Search by" type selector
		html += `<div class="pt-fg pt-fg-sm">
			<label class="pt-fl">Type</label>
			<select class="pt-filter" id="pt-f-type">
				<option value="mr">Purchase Request</option>
				<option value="po">Purchase Order</option>
				<option value="pi">Purchase Invoice</option>
				<option value="pr">Purchase Receipt</option>
				<option value="sq">Supplier Quotation</option>
				<option value="rfq">Request for Quotation</option>
			</select>
		</div>`;

		// Dynamic doc link — shown/updated by type
		html += `<div class="pt-fg" id="pt-f-doc-wrap"><label class="pt-fl" id="pt-f-doc-label">Document</label><div id="pt-f-doc"></div></div>`;

		// Status — single "Status" field (MR status values cover both)
		const allStatuses = [
			"Draft", "Submitted", "Pending", "Open", "Ordered", "Issued",
			"Received", "Partially Ordered", "Partially Received",
			"To Receive and Bill", "To Receive", "To Bill",
			"Completed", "Cancelled", "Closed", "Overdue"
		];
		html += `<div class="pt-fg pt-fg-sm">
			<label class="pt-fl">Status</label>
			<select class="pt-filter" id="pt-f-status">
				<option value="">Any Status</option>
				${allStatuses.map(s => `<option value="${s}">${s}</option>`).join("")}
			</select>
		</div>`;

		if (!opts.lock_company) {
			html += `<div class="pt-fg pt-fg-sm"><label class="pt-fl">Company</label><div id="pt-f-company"></div></div>`;
		} else if (opts.companies.length === 1) {
			html += `<div class="pt-fg pt-fg-sm"><label class="pt-fl">Company</label><div style="font-size:12px;font-weight:600;color:#344054;padding:5px 0;">${opts.companies[0]}</div></div>`;
		}

		html += `<div class="pt-fg pt-fg-sm"><label class="pt-fl">Supplier</label><div id="pt-f-supplier"></div></div>`;
		html += `<div class="pt-fg pt-fg-sm"><label class="pt-fl">Cost Center</label><div id="pt-f-cost-center"></div></div>`;
		html += `<div class="pt-fg pt-fg-date"><label class="pt-fl">From</label><input type="date" class="pt-filter form-control" id="pt-f-date-from"></div>`;
		html += `<div class="pt-fg pt-fg-date"><label class="pt-fl">To</label><input type="date" class="pt-filter form-control" id="pt-f-date-to"></div>`;

		this.$filterRow.html(html);

		// Locked company
		if (opts.lock_company && opts.companies.length === 1) {
			this.filters.company = opts.companies[0];
		}

		// Build link controls
		if (!opts.lock_company) {
			this._makeLinkCtrl("pt-f-company", "Company", () => ({}));
		}
		this._makeLinkCtrl("pt-f-supplier", "Supplier", () => ({}));
		this._makeLinkCtrl("pt-f-cost-center", "Cost Center", () => ({ is_group: 0 }));

		// Build the doc link control for initial type (MR)
		this._buildDocControl("mr");

		// When type changes, rebuild doc control and update label
		this.$filterRow.find("#pt-f-type").on("change", (e) => {
			const type = e.target.value;
			const labels = {
				mr: "Purchase Request", po: "Purchase Order", pi: "Purchase Invoice",
				pr: "Purchase Receipt", sq: "Supplier Quotation", rfq: "Request for Quotation"
			};
			this.$filterRow.find("#pt-f-doc-label").text(labels[type] || "Document");
			this.$filterRow.find("#pt-f-doc").html("");
			this.$root.find("#pt-search-by-val").text(labels[type] || "All");
			this._buildDocControl(type);
		});

		// Auto-fetch on date/status change
		this.$filterRow.find("select.pt-filter, input[type=date].pt-filter").on("change", () => this._debouncedFetch());

		// Enter key
		this.$filterRow.on("keydown", "input", (e) => {
			if (e.key === "Enter") { e.preventDefault(); this._fetchTree(true); }
		});
	}

	_buildDocControl(type) {
		const map = {
			mr: "Material Request", po: "Purchase Order",
			pi: "Purchase Invoice", pr: "Purchase Receipt",
			sq: "Supplier Quotation", rfq: "Request for Quotation"
		};
		const doctype = map[type];
		if (!doctype) return;

		// Remove old doc control
		if (this.controls["pt-f-doc"]) {
			delete this.controls["pt-f-doc"];
			this.$filterRow.find("#pt-f-doc").html("");
		}
		this._makeLinkCtrl("pt-f-doc", doctype, () => {
			const f = { docstatus: ["!=", 2] };
			const co = this._getCompanyVal();
			if (co) f.company = co;
			return f;
		});
	}

	_makeLinkCtrl(containerId, doctype, getFilters) {
		const $container = this.$filterRow.find(`#${containerId}`);
		if (!$container.length) return;
		const ctrl = frappe.ui.form.make_control({
			parent: $container,
			df: {
				fieldtype: "Link", options: doctype, fieldname: containerId,
				placeholder: `Search…`,
				get_query: () => ({ filters: getFilters() || {} }),
				change: () => { this._debouncedFetch(); },
			},
			render_input: true,
		});
		ctrl.refresh();
		ctrl.$input.on("awesomplete-close", () => setTimeout(() => this._debouncedFetch(), 50));
		this.controls[containerId] = ctrl;
	}

	_getCompanyVal() {
		if (this.filterOptions?.lock_company && this.filterOptions.companies?.length === 1)
			return this.filterOptions.companies[0];
		return this.controls["pt-f-company"]?.get_value() || null;
	}

	// ─────────────────────────────────────────────────────────────
	// GATHER / CLEAR FILTERS
	// ─────────────────────────────────────────────────────────────
	_gatherFilters() {
		const getCtrl = (id) => (this.controls[id]?.get_value() || "").trim() || null;
		const getRaw = (id) => (this.$filterRow.find(`#${id}`).val() || "").trim() || null;

		const type = getRaw("pt-f-type") || "mr";
		const doc = getCtrl("pt-f-doc");
		const status = getRaw("pt-f-status");

		let company = getCtrl("pt-f-company");
		if (!company && this.filterOptions?.lock_company && this.filterOptions.companies?.length === 1)
			company = this.filterOptions.companies[0];

		// Map type + status to correct filter key
		const docKey = { mr: "material_request", po: "purchase_order", pi: "purchase_invoice", pr: "purchase_receipt", sq: "supplier_quotation", rfq: "rfq" }[type];
		const statusKey = (type === "mr") ? "mr_status" : (type === "po") ? "po_status" : null;

		return {
			[docKey]: doc,
			company,
			cost_center: getCtrl("pt-f-cost-center"),
			supplier: getCtrl("pt-f-supplier"),
			mr_status: (statusKey === "mr_status") ? status : null,
			po_status: (statusKey === "po_status") ? status : null,
			date_from: getRaw("pt-f-date-from"),
			date_to: getRaw("pt-f-date-to"),
			_type: type,
			_status: status, // for display
		};
	}

	_hasActive(f) {
		const locked = this.filterOptions?.lock_company && this.filterOptions.companies?.length === 1
			? this.filterOptions.companies[0] : null;
		return Object.entries(f).some(([k, v]) => {
			if (!v || k.startsWith("_")) return false;
			if (k === "company" && v === locked) return false;
			return true;
		});
	}

	_clearFilters() {
		Object.entries(this.controls).forEach(([id, ctrl]) => {
			if (id === "pt-f-company" && this.filterOptions?.lock_company) return;
			ctrl.set_value("");
		});
		this.$filterRow.find("select.pt-filter").val("");
		this.$filterRow.find("input[type=date].pt-filter").val("");
		this.$activeTags.html("");
		this.$dot.removeClass("show");
		this._fetchTree();
	}

	_updateActiveTags(f) {
		const typeLabels = { mr: "PR", po: "PO", pi: "PI", pr: "PR", sq: "SQ", rfq: "RFQ" };
		const tags = [];
		const type = f._type || "mr";
		const docKey = { mr: "material_request", po: "purchase_order", pi: "purchase_invoice", pr: "purchase_receipt", sq: "supplier_quotation", rfq: "rfq" }[type];
		if (f[docKey]) tags.push(`<span class="pt-filter-tag">${typeLabels[type]}: ${f[docKey]}</span>`);
		if (f.company && !(this.filterOptions?.lock_company)) tags.push(`<span class="pt-filter-tag">Co: ${f.company}</span>`);
		if (f.supplier) tags.push(`<span class="pt-filter-tag">Supplier: ${f.supplier}</span>`);
		if (f.cost_center) tags.push(`<span class="pt-filter-tag">CC: ${f.cost_center}</span>`);
		if (f.mr_status || f.po_status) tags.push(`<span class="pt-filter-tag">Status: ${f.mr_status || f.po_status}</span>`);
		if (f.date_from) tags.push(`<span class="pt-filter-tag">From: ${f.date_from}</span>`);
		if (f.date_to) tags.push(`<span class="pt-filter-tag">To: ${f.date_to}</span>`);
		this.$activeTags.html(tags.join(""));
		this.$dot.toggleClass("show", tags.length > 0);
	}

	// ─────────────────────────────────────────────────────────────
	// FETCH
	// ─────────────────────────────────────────────────────────────
	_debouncedFetch() {
		if (this._debounceTimer) clearTimeout(this._debounceTimer);
		this._debounceTimer = setTimeout(() => this._fetchTree(), 400);
	}

	_fetchTree(forceLoading = false) {
		const f = this._gatherFilters();
		this._updateActiveTags(f);
		this._closePanel();

		if (!this._loadedOnce || forceLoading) {
			this.$canvas.html(`<div class="pt-loading"><div class="pt-spinner"></div> Building procurement timeline…</div>`);
		}

		const args = { ...f };
		// Remove internal keys and nulls
		delete args._type; delete args._status;
		Object.keys(args).forEach(k => { if (!args[k]) delete args[k]; });

		frappe.call({
			method: "custom_app.custom_app.page.purchase_timeline.purchase_timeline.get_procurement_tree",
			args: { ...args, limit: 50 },
			callback: (r) => {
				this._loadedOnce = true;
				if (r.message) {
					this.trees = r.message.trees || [];
					this._renderAll(r.message);
				} else {
					this._renderError();
				}
			},
			error: () => { this._loadedOnce = true; this._renderError(); },
		});
	}

	// ─────────────────────────────────────────────────────────────
	// RENDER ALL
	// ─────────────────────────────────────────────────────────────
	_renderAll(data) {
		const { trees, total } = data;
		if (!trees || trees.length === 0) {
			this.$canvas.html(`
				<div class="pt-empty">
					<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom:10px;opacity:.4;"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/></svg>
					<h4>No records found</h4>
					<p>Try adjusting your filters.</p>
				</div>`);
			return;
		}

		let html = `<div class="pt-result-header">
			<div class="pt-result-count">Showing <strong>${trees.length}</strong> of <strong>${total}</strong></div>
		</div>`;

		trees.forEach((tree, i) => { html += this._buildGraphCard(tree, i); });
		this.$canvas.html(html);
		this._renderAllGraphs(trees);
		this._bindPanelEvents();
	}

	_renderError() {
		this.$canvas.html(`<div class="pt-empty"><h4>Failed to load</h4><p>Check console for details.</p></div>`);
	}

	// ─────────────────────────────────────────────────────────────
	// GRAPH CARD SHELL
	// ─────────────────────────────────────────────────────────────
	_buildGraphCard(tree, idx) {
		const isNoMR = tree.no_mr;
		const statusBadge = !isNoMR ? this._badge(tree.workflow_state || tree.status) : "";
		const tenderBadge = tree.tender_type ? `<span class="pt-badge pt-badge-teal">${tree.tender_type}</span>` : "";

		return `<div class="pt-graph-card" data-card-idx="${idx}">
			<div class="pt-graph-card-header">
				<div class="pt-graph-card-icon">📋</div>
				<div style="flex:1;min-width:0;">
					<div class="pt-graph-card-title">${isNoMR ? "No Purchase Request" : `Purchase Request · ${tree.name}`}</div>
					<div class="pt-graph-card-sub">${!isNoMR ? `${tree.transaction_date || "—"} · ${tree.company || ""} · ${tree.items_count || 0} item(s)` : "Purchase Order without PR"}</div>
					<div class="pt-graph-card-badges">${statusBadge}${tenderBadge}</div>
				</div>
			</div>
			<div class="pt-graph-card-body" id="pt-gcb-${idx}">
				<div class="pt-loading" style="padding:30px;"><div class="pt-spinner"></div></div>
			</div>
		</div>`;
	}

	// ─────────────────────────────────────────────────────────────
	// RENDER ALL GRAPHS
	// ─────────────────────────────────────────────────────────────
	_renderAllGraphs(trees) {
		trees.forEach((tree, idx) => {
			setTimeout(() => this._renderGraph(tree, idx), 0);
		});
	}

	_renderGraph(tree, idx) {
		const $body = this.$canvas.find(`#pt-gcb-${idx}`);
		if (!$body.length) return;

		const colW = 190, nodeW = 155, nodeH = 48, vGap = 16, padding = 16;
		const colNodes = [[], [], [], [], []];
		const nodes = [], edges = [];
		const push = (col, n) => { colNodes[col].push(n); nodes.push(n); };

		// Build node data
		if (!tree.no_mr) {
			push(0, {
				id: `node-mr-${tree.name}`, col: 0,
				label: tree.name, sub: "Purchase Request",
				color: "#7f56d9", bg: "#f4f0ff",
				data: { type: "mr", ...tree },
			});
		}
		(tree.rfqs || []).forEach(rfq => {
			push(1, { id: `node-rfq-${rfq.name}`, col: 1, label: rfq.name, sub: "RFQ", color: "#1570ef", bg: "#eff8ff", data: { type: "rfq", ...rfq } });
			if (!tree.no_mr) edges.push({ from: `node-mr-${tree.name}`, to: `node-rfq-${rfq.name}` });
		});
		(tree.supplier_quotations || []).forEach(sq => {
			push(2, { id: `node-sq-${sq.name}`, col: 2, label: sq.name, sub: sq.supplier_name || sq.supplier || "SQ", color: "#d97706", bg: "#fff7e6", data: { type: "sq", ...sq } });
			const fromRfq = (sq.items || []).find(it => it.request_for_quotation)?.request_for_quotation;
			if (fromRfq && (tree.rfqs || []).some(r => r.name === fromRfq)) {
				edges.push({ from: `node-rfq-${fromRfq}`, to: `node-sq-${sq.name}` });
			} else if (!tree.no_mr) {
				edges.push({ from: `node-mr-${tree.name}`, to: `node-sq-${sq.name}` });
			}
		});
		(tree.purchase_orders || []).forEach(po => {
			const poId = `node-po-${po.name}`;
			push(3, { id: poId, col: 3, label: po.name, sub: po.supplier_name || po.supplier || "PO", color: "#027a48", bg: "#ecfdf3", data: { type: "po", ...po } });
			const fromSq = (po.items || []).find(it => it.supplier_quotation)?.supplier_quotation;
			if (fromSq && (tree.supplier_quotations || []).some(s => s.name === fromSq)) {
				edges.push({ from: `node-sq-${fromSq}`, to: poId });
			} else if (!tree.no_mr) {
				edges.push({ from: `node-mr-${tree.name}`, to: poId });
			}
			(po.purchase_receipts || []).forEach(pr => {
				const prId = `node-pr-${pr.name}`;
				push(4, { id: prId, col: 4, label: pr.name, sub: "Receipt", color: "#107569", bg: "#f0fdf4", data: { type: "pr", ...pr } });
				edges.push({ from: poId, to: prId });
			});
			(po.purchase_invoices || []).forEach(pi => {
				const piId = `node-pi-${pi.name}`;
				push(4, { id: piId, col: 4, label: pi.name, sub: pi.is_return ? "Invoice (Return)" : "Invoice", color: "#b42318", bg: "#fef3f2", data: { type: "pi", ...pi } });
				edges.push({ from: poId, to: piId });
			});
		});

		if (!nodes.length) {
			$body.html(`<div style="padding:20px;color:#98a2b3;font-size:12px;text-align:center;">No documents to display.</div>`);
			return;
		}

		// Layout
		const usedCols = [0, 1, 2, 3, 4].filter(c => colNodes[c].length);
		const colMap = {};
		usedCols.forEach((c, i) => { colMap[c] = i; });
		const maxRows = Math.max(...colNodes.map(c => c.length), 1);
		const svgW = padding * 2 + usedCols.length * colW;
		const svgH = padding * 2 + maxRows * (nodeH + vGap) - vGap + 10;

		nodes.forEach(n => {
			const ci = colMap[n.col];
			const ri = colNodes[n.col].indexOf(n);
			const rowCount = colNodes[n.col].length;
			const totalH = rowCount * (nodeH + vGap) - vGap;
			const offsetY = (svgH - padding * 2 - totalH) / 2;
			n.x = padding + ci * colW;
			n.y = padding + offsetY + ri * (nodeH + vGap);
			n.cx = n.x + nodeW / 2;
			n.cy = n.y + nodeH / 2;
		});

		const nodeMap = {};
		nodes.forEach(n => { nodeMap[n.id] = n; });

		// Adjacency
		const adj = {};
		nodes.forEach(n => { adj[n.id] = new Set(); });
		edges.forEach(e => {
			if (adj[e.from]) adj[e.from].add(e.to);
			if (adj[e.to]) adj[e.to].add(e.from);
		});

		// Column labels
		const colLabels = { 0: "PR", 1: "RFQ", 2: "Quotation", 3: "PO", 4: "Receipt / Invoice" };
		let labelsSvg = "";
		usedCols.forEach((c, i) => {
			const x = padding + i * colW + nodeW / 2;
			labelsSvg += `<text x="${x}" y="12" text-anchor="middle" font-size="9" font-weight="700" fill="#c0c7d4" letter-spacing=".5" font-family="inherit" text-transform="uppercase">${colLabels[c] || ""}</text>`;
		});

		// Edges
		let edgeSvg = "";
		edges.forEach(e => {
			const a = nodeMap[e.from], b = nodeMap[e.to];
			if (!a || !b) return;
			const x1 = a.x + nodeW, y1 = a.cy;
			const x2 = b.x, y2 = b.cy;
			const mx = (x1 + x2) / 2;
			edgeSvg += `<path class="pt-gedge" data-ef="${a.id}" data-et="${b.id}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
		});

		// Nodes
		let nodeSvg = "";
		nodes.forEach(n => {
			const lbl = n.label.length > 17 ? n.label.slice(0, 16) + "…" : n.label;
			const sub = (n.sub || "").length > 22 ? n.sub.slice(0, 21) + "…" : (n.sub || "");
			nodeSvg += `<g class="pt-gnode" data-nid="${n.id}" data-tree-idx="${idx}">
				<rect x="${n.x}" y="${n.y}" width="${nodeW}" height="${nodeH}" rx="8" fill="${n.bg}" stroke="${n.color}"/>
				<circle cx="${n.x + 14}" cy="${n.y + 14}" r="4" fill="${n.color}" opacity=".5"/>
				<text x="${n.x + 26}" y="${n.y + 19}" fill="${n.color}" font-weight="700" font-family="inherit">${frappe.utils.escape_html(lbl)}</text>
				<text class="pt-gsub" x="${n.x + 26}" y="${n.y + 35}" font-family="inherit">${frappe.utils.escape_html(sub)}</text>
			</g>`;
		});

		const svgEl = `<svg class="pt-gsvg" viewBox="0 0 ${svgW} ${svgH + 20}" width="${svgW}" height="${svgH + 20}" xmlns="http://www.w3.org/2000/svg">
			<g transform="translate(0,16)">${edgeSvg}${nodeSvg}</g>
			${labelsSvg}
		</svg>
		<div class="pt-graph-hint">Click a node to inspect · Click background to deselect</div>`;

		$body.html(svgEl);

		const $svg = $body.find("svg");

		// Store node data for panel
		nodes.forEach(n => {
			$body.find(`[data-nid="${n.id}"]`).data("nodedata", n.data);
		});

		// Build adjacency store on svg element
		$svg.data("adj", adj);

		// Click node
		$svg.find(".pt-gnode").on("click", (e) => {
			e.stopPropagation();
			const $node = $(e.currentTarget);
			const nid = $node.attr("data-nid");
			const alreadySel = $svg.hasClass("pt-sel") && $node.hasClass("pt-gactive") && $svg.find(".pt-gactive").length === 1;

			$svg.find(".pt-gnode").removeClass("pt-gactive");
			$svg.find(".pt-gedge").removeClass("pt-geactive");

			if (alreadySel) {
				$svg.removeClass("pt-sel");
				this._closePanel();
				return;
			}

			$svg.addClass("pt-sel");
			$node.addClass("pt-gactive");
			const neighbors = (adj[nid] || new Set());
			neighbors.forEach(nbid => $svg.find(`[data-nid="${nbid}"]`).addClass("pt-gactive"));
			$svg.find(".pt-gedge").each(function () {
				const ef = $(this).attr("data-ef"), et = $(this).attr("data-et");
				if (ef === nid || et === nid) $(this).addClass("pt-geactive");
			});

			// Open panel
			const nd = $node.data("nodedata");
			if (nd) this._openPanel(nd);
		});

		// Click background to deselect
		$svg.on("click", (e) => {
			if ($(e.target).closest(".pt-gnode").length) return;
			$svg.removeClass("pt-sel");
			$svg.find(".pt-gnode").removeClass("pt-gactive");
			$svg.find(".pt-gedge").removeClass("pt-geactive");
			this._closePanel();
		});

		// Tooltip
		$svg.find(".pt-gnode").on("mouseenter", (e) => {
			const nd = $(e.currentTarget).data("nodedata");
			if (!nd) return;
			const lines = this._tooltipLines(nd);
			this.$tooltip.html(lines.join("<br>")).css("display", "block");
		}).on("mousemove", (e) => {
			this.$tooltip.css({ left: e.pageX + 14, top: e.pageY + 10 });
		}).on("mouseleave", () => {
			this.$tooltip.css("display", "none");
		});
	}

	_tooltipLines(nd) {
		const fmt = (v) => v ? frappe.format(v, { fieldtype: "Currency" }) : "—";
		const lines = [];
		if (nd.type === "mr") {
			lines.push(`<strong>Purchase Request</strong>`, nd.name, `Status: ${nd.workflow_state || nd.status || "—"}`, `Date: ${nd.transaction_date || "—"}`);
		} else if (nd.type === "rfq") {
			lines.push(`<strong>RFQ</strong>`, nd.name, `Status: ${nd.status || "—"}`);
		} else if (nd.type === "sq") {
			lines.push(`<strong>Supplier Quotation</strong>`, nd.name, `Supplier: ${nd.supplier_name || nd.supplier || "—"}`, `Total: ${fmt(nd.grand_total)}`);
		} else if (nd.type === "po") {
			lines.push(`<strong>Purchase Order</strong>`, nd.name, `Supplier: ${nd.supplier_name || nd.supplier || "—"}`, `Status: ${nd.workflow_state || nd.status || "—"}`, `Total: ${fmt(nd.grand_total)}`);
		} else if (nd.type === "pr") {
			lines.push(`<strong>Purchase Receipt</strong>`, nd.name, `Supplier: ${nd.supplier_name || nd.supplier || "—"}`, `Total: ${fmt(nd.grand_total)}`);
		} else if (nd.type === "pi") {
			lines.push(`<strong>Purchase Invoice</strong>`, nd.name, `Status: ${nd.workflow_state || nd.status || "—"}`, `Total: ${fmt(nd.grand_total)}`, `Due: ${fmt(nd.outstanding_amount)}`);
		}
		return lines;
	}

	// ─────────────────────────────────────────────────────────────
	// DETAIL PANEL
	// ─────────────────────────────────────────────────────────────
	_bindPanelEvents() {
		// Already bound in renderGraph
	}

	_openPanel(nd) {
		const typeMap = {
			mr: { icon: "📋", label: "Purchase Request", color: "#f4f0ff", linkBase: "/app/material-request" },
			rfq: { icon: "📨", label: "Request for Quotation", color: "#eff8ff", linkBase: "/app/request-for-quotation" },
			sq: { icon: "💬", label: "Supplier Quotation", color: "#fff7e6", linkBase: "/app/supplier-quotation" },
			po: { icon: "🛒", label: "Purchase Order", color: "#ecfdf3", linkBase: "/app/purchase-order" },
			pr: { icon: "📦", label: "Purchase Receipt", color: "#f0fdf4", linkBase: "/app/purchase-receipt" },
			pi: { icon: "🧾", label: "Purchase Invoice", color: "#fef3f2", linkBase: "/app/purchase-invoice" },
		};
		const meta = typeMap[nd.type] || typeMap.mr;

		this.$root.find("#pt-panel-icon").text(meta.icon).css("background", meta.color);
		this.$root.find("#pt-panel-title").text(meta.label);
		this.$root.find("#pt-panel-name").html(`<a href="${meta.linkBase}/${nd.name}" target="_blank">${nd.name} ↗</a>`);

		const body = this._buildPanelBody(nd, meta);
		this.$root.find("#pt-panel-body").html(body);

		// Bind items toggle in panel
		this.$root.find("#pt-panel-body").find(".pt-items-toggle").off("click").on("click", function () {
			const $wrap = $(this).next(".pt-items-table-wrap");
			const open = $wrap.toggleClass("open").hasClass("open");
			$(this).html((open ? "▾ Hide" : "▸ Show") + ` ${nd.items?.length || 0} item(s)`);
		});

		this.$panel.addClass("open");
		this.$canvas.addClass("panel-open");
	}

	_closePanel() {
		this.$panel.removeClass("open");
		this.$canvas.removeClass("panel-open");
	}

	_buildPanelBody(nd, meta) {
		const fmt = (v) => v ? frappe.format(v, { fieldtype: "Currency" }) : "—";
		let html = "";

		// Status badge(s)
		const statusVal = nd.status; // always use raw status, not workflow_state
		if (statusVal) {
			html += `<div style="margin-bottom:10px;">${this._badge(statusVal)}`;
			if (nd.is_return) html += ` <span class="pt-badge pt-badge-red">↩ Return</span>`;
			html += `</div>`;
		}

		// Detail grid
		const pairs = [];
		if (nd.type === "mr") {
			pairs.push(["Date", nd.transaction_date], ["Company", nd.company], ["Cost Center", nd.cost_center],
				["Created By", nd.creator_name || nd.owner], ["Employee", nd.employee_name || nd.employee],
				["Approved By", nd.approver_name || nd.approver], ["Verified By", nd.verifier_name || nd.verifier],
				["Total Value", nd.total_value ? fmt(nd.total_value) : null], ["Modified", nd.modified]);
			if (nd.tender_type) pairs.push(["Tender Type", nd.tender_type]);
			if (nd.notes) pairs.push(["Notes", nd.notes]);
		} else if (nd.type === "rfq") {
			const suppliers = Object.values(nd.supplier_names || {}).join(", ");
			pairs.push(["Date", nd.transaction_date], ["Company", nd.company], ["Suppliers", suppliers], ["Modified", nd.modified]);
		} else if (nd.type === "sq") {
			pairs.push(["Date", nd.transaction_date], ["Supplier", nd.supplier_name || nd.supplier],
				["Grand Total", fmt(nd.grand_total)], ["Currency", nd.currency], ["Company", nd.company], ["Modified", nd.modified]);
		} else if (nd.type === "po") {
			const recvPct = nd.per_received ? `${parseFloat(nd.per_received).toFixed(0)}%` : "0%";
			const billPct = nd.per_billed ? `${parseFloat(nd.per_billed).toFixed(0)}%` : "0%";
			pairs.push(["Date", nd.transaction_date], ["Supplier", nd.supplier_name || nd.supplier],
				["Grand Total", fmt(nd.grand_total)], ["Currency", nd.currency],
				["% Received", recvPct], ["% Billed", billPct],
				["Company", nd.company], ["Modified", nd.modified]);
		} else if (nd.type === "pr") {
			pairs.push(["Posting Date", nd.posting_date], ["Supplier", nd.supplier_name || nd.supplier],
				["Grand Total", fmt(nd.grand_total)], ["Company", nd.company], ["Modified", nd.modified]);
		} else if (nd.type === "pi") {
			pairs.push(["Posting Date", nd.posting_date], ["Supplier", nd.supplier_name || nd.supplier],
				["Grand Total", fmt(nd.grand_total)], ["Outstanding", fmt(nd.outstanding_amount)],
				["Company", nd.company], ["Modified", nd.modified]);
		}

		html += `<div class="pt-dg">`;
		pairs.filter(([, v]) => v).forEach(([k, v]) => {
			html += `<div class="pt-di"><span class="lbl">${k}</span><span class="val">${v}</span></div>`;
		});
		html += `</div>`;

		// Items
		if (nd.items && nd.items.length) {
			html += `<div class="pt-section-title">Items</div>`;
			html += `<div class="pt-items-toggle">▸ Show ${nd.items.length} item(s)</div>`;
			html += `<div class="pt-items-table-wrap">`;

			let headers = [], rowFn;
			if (nd.type === "mr") {
				headers = ["Item", "Qty", "UOM", "Rate"];
				rowFn = it => [it.item_name || it.item_code, it.qty, it.uom, it.rate ? fmt(it.rate) : "—"];
			} else if (nd.type === "po") {
				headers = ["Item", "Qty", "Rate", "Rcvd", "Billed"];
				rowFn = it => [it.item_name || it.item_code, it.qty, it.rate ? fmt(it.rate) : "—", it.received_qty ?? "—", it.billed_qty ?? "—"];
			} else if (nd.type === "pr") {
				headers = ["Item", "Qty", "Accepted", "Rejected"];
				rowFn = it => [it.item_name || it.item_code, it.qty, it.accepted_qty ?? "—", it.rejected_qty ?? "—"];
			} else {
				headers = ["Item", "Qty", "Rate", "Amount"];
				rowFn = it => [it.item_name || it.item_code, it.qty, it.rate ? fmt(it.rate) : "—", it.amount ? fmt(it.amount) : "—"];
			}

			html += `<table class="pt-items-tbl"><thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>`;
			nd.items.forEach(it => {
				html += `<tr>${rowFn(it).map(v => `<td>${v ?? "—"}</td>`).join("")}</tr>`;
			});
			html += `</tbody></table></div>`;
		}

		// Open link
		html += `<a class="pt-open-link" href="${meta.linkBase}/${nd.name}" target="_blank">Open in full view ↗</a>`;

		return html;
	}

	// ─────────────────────────────────────────────────────────────
	// HELPERS
	// ─────────────────────────────────────────────────────────────
	_badge(status) {
		if (!status) return "";
		const map = {
			"Draft": "pt-badge-gray", "Submitted": "pt-badge-blue",
			"Verified": "pt-badge-teal", "Approved": "pt-badge-green",
			"Approved by Manager": "pt-badge-green", "Pending": "pt-badge-yellow",
			"Rejected": "pt-badge-red", "Cancelled": "pt-badge-red",
			"Ordered": "pt-badge-purple", "Open": "pt-badge-blue",
			"To Receive": "pt-badge-orange", "To Receive and Bill": "pt-badge-orange",
			"To Bill": "pt-badge-yellow", "Completed": "pt-badge-green",
			"Received": "pt-badge-teal", "Overdue": "pt-badge-red",
			"Partially Received": "pt-badge-yellow", "Partially Ordered": "pt-badge-yellow",
			"Closed": "pt-badge-gray", "Issued": "pt-badge-blue",
		};
		return `<span class="pt-badge ${map[status] || "pt-badge-gray"}">${status}</span>`;
	}
}