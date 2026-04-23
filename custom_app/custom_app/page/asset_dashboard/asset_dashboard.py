import frappe
from frappe import _


def get_filters_conditions(filters):
	"""Build WHERE conditions from filters dict."""
	conditions = []
	values = {}

	if filters.get("company"):
		conditions.append("a.company = %(company)s")
		values["company"] = filters["company"]

	if filters.get("asset_category"):
		conditions.append("a.asset_category = %(asset_category)s")
		values["asset_category"] = filters["asset_category"]

	if filters.get("status"):
		conditions.append("a.status = %(status)s")
		values["status"] = filters["status"]

	if filters.get("location"):
		conditions.append("a.location LIKE %(location)s")
		values["location"] = f"%{filters['location']}%"

	if filters.get("department"):
		conditions.append("a.department = %(department)s")
		values["department"] = filters["department"]

	if filters.get("from_date"):
		conditions.append("a.purchase_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("a.purchase_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
	return where, values


# ─────────────────────────────────────────────────────────────
# 1. KPI Summary
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_kpi_summary(filters=None):
	"""Returns top-level KPI numbers."""
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	data = frappe.db.sql(f"""
		SELECT
			COUNT(*)                                                        AS total_assets,
			SUM(a.gross_purchase_amount)                                    AS total_purchase_value,
			SUM(a.value_after_depreciation)                                 AS total_book_value,
			SUM(a.gross_purchase_amount - a.value_after_depreciation)       AS total_depreciation,
			COUNT(DISTINCT a.company)                                       AS total_companies,
			COUNT(DISTINCT a.asset_category)                                AS total_categories,
			COUNT(DISTINCT a.location)                                      AS total_locations,
			SUM(CASE WHEN a.status = 'Submitted'       THEN 1 ELSE 0 END)  AS submitted_count,
			SUM(CASE WHEN a.status = 'Draft'           THEN 1 ELSE 0 END)  AS draft_count,
			SUM(CASE WHEN a.status = 'In Maintenance'  THEN 1 ELSE 0 END)  AS in_maintenance_count,
			SUM(CASE WHEN a.status = 'Scrapped'        THEN 1 ELSE 0 END)  AS scrapped_count,
			SUM(CASE WHEN a.calculate_depreciation = 1 THEN 1 ELSE 0 END)  AS depreciating_count,
			SUM(CASE WHEN a.is_fully_depreciated = 1   THEN 1 ELSE 0 END)  AS fully_depreciated_count
		FROM `tabAsset` a
		{where}
	""", values, as_dict=True)

	return data[0] if data else {}


# ─────────────────────────────────────────────────────────────
# 2. Assets by Category (count + value)
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_assets_by_category(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	return frappe.db.sql(f"""
		SELECT
			COALESCE(NULLIF(TRIM(a.asset_category), ''), 'Unassigned') AS category,
			COUNT(*)                                                    AS count,
			SUM(a.gross_purchase_amount)                                AS total_value,
			SUM(a.value_after_depreciation)                             AS book_value,
			AVG(a.gross_purchase_amount)                                AS avg_value
		FROM `tabAsset` a
		{where}
		GROUP BY COALESCE(NULLIF(TRIM(a.asset_category), ''), 'Unassigned')
		ORDER BY count DESC
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 3. Assets by Company
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_assets_by_company(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	return frappe.db.sql(f"""
		SELECT
			COALESCE(NULLIF(TRIM(a.company), ''), 'Unassigned') AS company,
			COUNT(*)                                            AS count,
			SUM(a.gross_purchase_amount)                        AS total_value,
			COUNT(DISTINCT a.asset_category)                    AS categories,
			COUNT(DISTINCT a.location)                          AS locations
		FROM `tabAsset` a
		{where}
		GROUP BY COALESCE(NULLIF(TRIM(a.company), ''), 'Unassigned')
		ORDER BY count DESC
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 4. Assets by Status
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_assets_by_status(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	return frappe.db.sql(f"""
		SELECT
			COALESCE(NULLIF(TRIM(a.status), ''), 'Unknown') AS status,
			COUNT(*)                                         AS count,
			SUM(a.gross_purchase_amount)                     AS total_value
		FROM `tabAsset` a
		{where}
		GROUP BY COALESCE(NULLIF(TRIM(a.status), ''), 'Unknown')
		ORDER BY count DESC
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 5. Assets by Location (with company)
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_assets_by_location(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	return frappe.db.sql(f"""
		SELECT
			COALESCE(NULLIF(TRIM(a.location), ''), 'Unassigned') AS location,
			COUNT(*)                                              AS count,
			SUM(a.gross_purchase_amount)                          AS total_value,
			COUNT(DISTINCT a.asset_category)                      AS categories,
			COUNT(DISTINCT a.company)                             AS companies
		FROM `tabAsset` a
		{where}
		GROUP BY COALESCE(NULLIF(TRIM(a.location), ''), 'Unassigned')
		ORDER BY count DESC
		LIMIT 20
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 6. Monthly Addition Trend
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_monthly_trend(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	# Need to handle the extra AND when there's already a WHERE clause
	date_condition = "AND a.purchase_date IS NOT NULL" if where else "WHERE a.purchase_date IS NOT NULL"

	return frappe.db.sql(f"""
		SELECT
			DATE_FORMAT(a.purchase_date, '%%Y-%%m')  AS month,
			COUNT(*)                                 AS count,
			SUM(a.gross_purchase_amount)             AS total_value
		FROM `tabAsset` a
		{where}
		{date_condition}
		GROUP BY DATE_FORMAT(a.purchase_date, '%%Y-%%m')
		ORDER BY month ASC
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 7. Department-wise breakdown
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_assets_by_department(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	return frappe.db.sql(f"""
		SELECT
			COALESCE(NULLIF(TRIM(a.department), ''), 'Unassigned') AS department,
			COUNT(*)                                                AS count,
			SUM(a.gross_purchase_amount)                            AS total_value,
			COUNT(DISTINCT a.asset_category)                        AS categories
		FROM `tabAsset` a
		{where}
		GROUP BY COALESCE(NULLIF(TRIM(a.department), ''), 'Unassigned')
		ORDER BY count DESC
		LIMIT 15
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 8. Asset Item breakdown (JOIN with tabItem)
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_assets_by_item(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	return frappe.db.sql(f"""
		SELECT
			a.item_code                             AS item_code,
			a.item_name                             AS item_name,
			i.item_group                            AS item_group,
			COUNT(*)                                AS count,
			SUM(a.gross_purchase_amount)            AS total_value,
			AVG(a.gross_purchase_amount)            AS avg_value
		FROM `tabAsset` a
		LEFT JOIN `tabItem` i ON i.name = a.item_code
		{where}
		GROUP BY a.item_code, a.item_name, i.item_group
		ORDER BY total_value DESC
		LIMIT 20
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 9. Vendor-wise spend (JOIN with tabSupplier)
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_assets_by_vendor(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	vendor_condition = "AND a.supplier IS NOT NULL AND a.supplier != ''" if where else "WHERE a.supplier IS NOT NULL AND a.supplier != ''"

	return frappe.db.sql(f"""
		SELECT
			a.supplier                                AS vendor,
			s.supplier_name                         AS supplier_name,
			s.supplier_group                        AS supplier_group,
			COUNT(*)                                AS count,
			SUM(a.gross_purchase_amount)            AS total_value
		FROM `tabAsset` a
		LEFT JOIN `tabSupplier` s ON s.name = a.supplier
		{where}
		{vendor_condition}
		GROUP BY a.supplier
		ORDER BY total_value DESC
		LIMIT 15
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 10. Depreciation Summary (JOIN with Finance Books child table)
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_depreciation_summary(filters=None):
	filters = frappe.parse_json(filters or {})
	where, values = get_filters_conditions(filters)

	depr_condition = "AND a.calculate_depreciation = 1" if where else "WHERE a.calculate_depreciation = 1"

	return frappe.db.sql(f"""
		SELECT
			a.asset_category                                                    AS category,
			a.depreciation_method                                               AS method,
			COUNT(*)                                                            AS count,
			SUM(a.gross_purchase_amount)                                        AS purchase_value,
			SUM(a.value_after_depreciation)                                     AS book_value,
			SUM(a.gross_purchase_amount - a.value_after_depreciation)           AS accumulated_depreciation,
			SUM(CASE WHEN a.is_fully_depreciated = 1 THEN 1 ELSE 0 END)        AS fully_depreciated
		FROM `tabAsset` a
		{where}
		{depr_condition}
		GROUP BY a.asset_category, a.depreciation_method
		ORDER BY purchase_value DESC
	""", values, as_dict=True)


# ─────────────────────────────────────────────────────────────
# 11. Asset Register — paginated, with JOIN to Item + Supplier
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_asset_register(filters=None, page=1, page_size=20, order_by="creation_desc"):
	filters   = frappe.parse_json(filters or {})
	page      = int(page)
	page_size = int(page_size)
	offset    = (page - 1) * page_size

	# Safe order-by map (prevents SQL injection)
	order_map = {
		"creation_desc":       "a.creation DESC",
		"creation_asc":        "a.creation ASC",
		"purchase_date_desc":  "a.purchase_date DESC",
		"purchase_date_asc":   "a.purchase_date ASC",
		"value_desc":          "a.gross_purchase_amount DESC",
		"value_asc":           "a.gross_purchase_amount ASC",
		"name_asc":            "a.asset_name ASC",
		"name_desc":           "a.asset_name DESC",
		"category_asc":        "a.asset_category ASC",
	}
	sql_order = order_map.get(order_by, "a.creation DESC")

	where, values = get_filters_conditions(filters)
	values["page_size"] = page_size
	values["offset"]    = offset

	rows = frappe.db.sql(f"""
		SELECT
			a.name                                  AS id,
			a.asset_name                            AS asset_name,
			a.asset_category                        AS asset_category,
			a.item_code                             AS item_code,
			a.item_name                             AS item_name,
			i.item_group                            AS item_group,
			a.company                               AS company,
			a.location                              AS location,
			a.department                            AS department,
			a.status                                AS status,
			a.purchase_date                         AS purchase_date,
			a.gross_purchase_amount                 AS purchase_value,
			a.value_after_depreciation              AS book_value,
			a.supplier                                AS vendor,
			s.supplier_name                         AS supplier_name,
			a.custom_manufacturer                          AS manufacturer,
			a.is_fully_depreciated                  AS is_fully_depreciated,
			a.calculate_depreciation                AS calculate_depreciation,
			a.custodian                             AS custodian
		FROM `tabAsset` a
		LEFT JOIN `tabItem`     i ON i.name = a.item_code
		LEFT JOIN `tabSupplier` s ON s.name = a.supplier
		{where}
		ORDER BY {sql_order}
		LIMIT %(page_size)s OFFSET %(offset)s
	""", values, as_dict=True)

	count_data = frappe.db.sql(f"""
		SELECT COUNT(*) AS total
		FROM `tabAsset` a
		{where}
	""", values, as_dict=True)

	return {
		"data":      rows,
		"total":     count_data[0]["total"] if count_data else 0,
		"page":      page,
		"page_size": page_size
	}


# ─────────────────────────────────────────────────────────────
# 12. Filter Options (dynamic dropdowns populated from DB)
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_filter_options():
	"""Returns distinct values for all filter dropdowns in one call."""

	companies = frappe.db.sql("""
		SELECT DISTINCT company FROM `tabAsset`
		WHERE company IS NOT NULL AND company != ''
		ORDER BY company
	""", as_dict=True)

	categories = frappe.db.sql("""
		SELECT DISTINCT asset_category FROM `tabAsset`
		WHERE asset_category IS NOT NULL AND asset_category != ''
		ORDER BY asset_category
	""", as_dict=True)

	locations = frappe.db.sql("""
		SELECT DISTINCT location FROM `tabAsset`
		WHERE location IS NOT NULL AND location != ''
		ORDER BY location
	""", as_dict=True)

	departments = frappe.db.sql("""
		SELECT DISTINCT department FROM `tabAsset`
		WHERE department IS NOT NULL AND department != ''
		ORDER BY department
	""", as_dict=True)

	statuses = frappe.db.sql("""
		SELECT DISTINCT status FROM `tabAsset`
		WHERE status IS NOT NULL AND status != ''
		ORDER BY status
	""", as_dict=True)

	return {
		"companies":   [r["company"]        for r in companies],
		"categories":  [r["asset_category"] for r in categories],
		"locations":   [r["location"]       for r in locations],
		"departments": [r["department"]     for r in departments],
		"statuses":    [r["status"]         for r in statuses],
	}