import frappe
from frappe.utils import getdate, nowdate, add_months, get_first_day, get_last_day
from datetime import date


# ─────────────────────────────────────────────────────────────────
# ROLE / PERMISSION HELPERS
# ─────────────────────────────────────────────────────────────────

def _is_system_manager():
	return "System Manager" in frappe.get_roles(frappe.session.user)


def _get_permitted_companies():
    if _is_system_manager():
        rows = frappe.db.sql(
            "SELECT name FROM `tabCompany` ORDER BY name", as_dict=True
        )
        return [r.name for r in rows]

    from frappe.permissions import get_user_permissions
    permitted = get_user_permissions(frappe.session.user).get("Company", [])
    names = [p.get("doc") for p in permitted if p.get("doc")]

    if not names:
        return []

    placeholders = ", ".join(["%s"] * len(names))
    rows = frappe.db.sql(
        f"SELECT name FROM `tabCompany` WHERE name IN ({placeholders}) ORDER BY name",
        names,
        as_dict=True,
    )
    return [r.name for r in rows]


def _resolve_company(company_arg):
	"""
	Returns the company to filter on.
	- System Manager: returns company_arg as-is (None = all companies).
	- Institution Head: ignores company_arg, returns first permitted company
	  (or None if multiple permitted, or '__NONE__' if none permitted).
	"""
	if _is_system_manager():
		return company_arg
	permitted = _get_permitted_companies()
	if not permitted:
		return "__NONE__"
	return permitted[0]


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def _period_dates(period="month", date_from=None, date_to=None):
	if period == "custom" and date_from and date_to:
		return getdate(date_from), getdate(date_to)
	today = getdate(nowdate())
	if period == "month":
		return get_first_day(today), get_last_day(today)
	elif period == "quarter":
		qm    = ((today.month - 1) // 3) * 3 + 1
		start = date(today.year, qm, 1)
		return start, get_last_day(add_months(start, 2))
	else:  # year
		return date(today.year, 1, 1), date(today.year, 12, 31)


def _base_filters(company=None, department=None):
	clauses, args = [], {}
	if company:
		clauses.append("e.company = %(company)s")
		args["company"] = company
	if department:
		clauses.append("e.department = %(department)s")
		args["department"] = department
	return (" AND " + " AND ".join(clauses)) if clauses else "", args


# ─────────────────────────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_filter_options():
	companies   = _get_permitted_companies()
	departments = frappe.db.sql("SELECT name FROM `tabDepartment` ORDER BY name", as_dict=True)
	return {
		"companies":   companies,
		"departments": [r.name for r in departments],
		"lock_company": not _is_system_manager(),
	}


# ─────────────────────────────────────────────────────────────────
# 1. ATTRITION RATE
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_attrition_rate(period="month", company=None, department=None, date_from=None, date_to=None):
	start, end = _period_dates(period, date_from, date_to)
	extra_where, args = _base_filters(_resolve_company(company), department)
	ew = extra_where.replace("e.company", "company").replace("e.department", "department")

	start_count = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE date_of_joining <= %(start)s
		AND (relieving_date IS NULL OR relieving_date >= %(start)s) {ew}
	""", {**args, "start": start}, as_dict=True)[0].cnt or 0

	end_count = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE date_of_joining <= %(end)s
		AND (relieving_date IS NULL OR relieving_date >= %(end)s) {ew}
	""", {**args, "end": end}, as_dict=True)[0].cnt or 0

	separations = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE relieving_date BETWEEN %(start)s AND %(end)s {ew}
	""", {**args, "start": start, "end": end}, as_dict=True)[0].cnt or 0

	missing_date = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE status IN ('Left', 'Inactive')
		AND (relieving_date IS NULL OR relieving_date = '') {ew}
	""", args, as_dict=True)[0].cnt or 0

	avg_headcount = (start_count + end_count) / 2 if (start_count + end_count) > 0 else 1
	rate = round((separations / avg_headcount) * 100, 2)

	# Monthly trend (last 6 months — always shows rolling 6 months regardless of period)
	trend = []
	for i in range(5, -1, -1):
		m_start = get_first_day(add_months(getdate(nowdate()), -i))
		m_end   = get_last_day(m_start)
		s = frappe.db.sql(f"""
			SELECT COUNT(*) as cnt FROM `tabEmployee`
			WHERE relieving_date BETWEEN %(ms)s AND %(me)s {ew}
		""", {**args, "ms": m_start, "me": m_end}, as_dict=True)[0].cnt or 0
		trend.append({"label": m_start.strftime("%b %Y"), "value": s})

	return {
		"rate": rate,
		"separations": separations,
		"avg_headcount": round(avg_headcount, 1),
		"start_count": start_count,
		"end_count": end_count,
		"missing_relieving_date": missing_date,
		"period_label": f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}",
		"trend": trend,
	}


# ─────────────────────────────────────────────────────────────────
# 2. TIME TO HIRE
#    time_to_hire = Job Offer.offer_date - Job Opening.posted_on
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_time_to_hire(company=None, department=None, date_from=None, date_to=None):
	extra = []
	args  = {}
	resolved = _resolve_company(company)
	if resolved == "__NONE__":
		return {"avg_days": 0, "min_days": 0, "max_days": 0, "total_hires": 0,
				"first_opening_date": "", "first_applicant": "—", "excluded_count": 0, "trend": []}
	if resolved:
		extra.append("jo.company = %(company)s")
		args["company"] = resolved
	if date_from:
		extra.append("jof.offer_date >= %(date_from)s")
		args["date_from"] = date_from
	if date_to:
		extra.append("jof.offer_date <= %(date_to)s")
		args["date_to"] = date_to

	ew = (" AND " + " AND ".join(extra)) if extra else ""

	result = frappe.db.sql(f"""
		SELECT
			AVG(DATEDIFF(jof.offer_date, jo.posted_on))  AS avg_days,
			MIN(DATEDIFF(jof.offer_date, jo.posted_on))  AS min_days,
			MAX(DATEDIFF(jof.offer_date, jo.posted_on))  AS max_days,
			COUNT(*)                                      AS total_hires,
			MIN(jo.posted_on)                             AS first_opening_date,
			(SELECT ja2.applicant_name
			   FROM `tabJob Applicant` ja2
			   JOIN `tabJob Opening` jo2 ON ja2.job_title = jo2.name
			   WHERE jo2.posted_on = MIN(jo.posted_on)
			   LIMIT 1)                                   AS first_applicant
		FROM `tabJob Offer` jof
		JOIN `tabJob Applicant` jap ON jof.job_applicant = jap.name
		JOIN `tabJob Opening`   jo  ON jap.job_title = jo.name
		WHERE jof.docstatus = 1
		AND jof.offer_date IS NOT NULL
		AND jo.posted_on IS NOT NULL
		AND DATEDIFF(jof.offer_date, jo.posted_on) >= 0
		{ew}
	""", args, as_dict=True)

	# Monthly trend (rolling 6 months)
	trend = []
	for i in range(5, -1, -1):
		m_start = get_first_day(add_months(getdate(nowdate()), -i))
		m_end   = get_last_day(m_start)
		tr = frappe.db.sql("""
			SELECT AVG(DATEDIFF(jof.offer_date, jo.posted_on)) as avg_days
			FROM `tabJob Offer` jof
			JOIN `tabJob Applicant` jap ON jof.job_applicant = jap.name
			JOIN `tabJob Opening`   jo  ON jap.job_title = jo.name
			WHERE jof.docstatus = 1
			AND jof.offer_date BETWEEN %(ms)s AND %(me)s
			AND DATEDIFF(jof.offer_date, jo.posted_on) >= 0
		""", {"ms": m_start, "me": m_end}, as_dict=True)
		trend.append({
			"label": m_start.strftime("%b %Y"),
			"value": round(tr[0].avg_days or 0, 1) if tr else 0
		})

	excluded = frappe.db.sql("""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE (job_applicant IS NULL OR job_applicant = '')
		AND date_of_joining <= CURDATE()
		AND (relieving_date IS NULL OR relieving_date >= CURDATE())
	""", as_dict=True)[0].cnt or 0

	row = result[0] if result else {}
	return {
		"avg_days":           round(row.get("avg_days") or 0, 1),
		"min_days":           row.get("min_days") or 0,
		"max_days":           row.get("max_days") or 0,
		"total_hires":        row.get("total_hires") or 0,
		"first_opening_date": str(row.get("first_opening_date") or ""),
		"first_applicant":    row.get("first_applicant") or "—",
		"excluded_count":     excluded,
		"trend":              trend,
	}


# ─────────────────────────────────────────────────────────────────
# 3. OFFER ACCEPTANCE
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_offer_acceptance(company=None, date_from=None, date_to=None):
	ew, args = [], {}
	resolved = _resolve_company(company)
	if resolved == "__NONE__":
		return {"rate": 0, "accepted": 0, "rejected": 0, "awaiting": 0,
				"total": 0, "chart_data": [0, 0, 0]}
	if resolved:
		ew.append("company = %(company)s")
		args["company"] = resolved
	if date_from:
		ew.append("offer_date >= %(date_from)s")
		args["date_from"] = date_from
	if date_to:
		ew.append("offer_date <= %(date_to)s")
		args["date_to"] = date_to

	where = (" AND " + " AND ".join(ew)) if ew else ""

	result = frappe.db.sql(f"""
		SELECT status, COUNT(*) as cnt
		FROM `tabJob Offer`
		WHERE docstatus = 1 {where}
		GROUP BY status
	""", args, as_dict=True)

	counts = {"Accepted": 0, "Rejected": 0, "Awaiting Response": 0}
	for row in result:
		counts[row.status] = row.cnt

	total = sum(counts.values())
	rate  = round((counts["Accepted"] / total) * 100, 2) if total > 0 else 0
	return {
		"rate": rate, "accepted": counts["Accepted"],
		"rejected": counts["Rejected"], "awaiting": counts["Awaiting Response"],
		"total": total,
		"chart_data": [counts["Accepted"], counts["Rejected"], counts["Awaiting Response"]],
	}


# ─────────────────────────────────────────────────────────────────
# 4. HEADCOUNT SUMMARY
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_headcount_summary(period="month", company=None, department=None, date_from=None, date_to=None):
	start, end = _period_dates(period, date_from, date_to)

	resolved = _resolve_company(company)
	if resolved == "__NONE__":
		return {"total": 0, "teaching": 0, "non_teaching": 0, "unclassified": 0,
				"teaching_pct": 0, "dept_data": [], "join_trend": [], "period_label": ""}

	ew, args = [], {}
	if resolved:
		ew.append("company = %(company)s")
		args["company"] = resolved
	if department:
		ew.append("department = %(department)s")
		args["department"] = department

	where = (" AND " + " AND ".join(ew)) if ew else ""

	# Who was active during the selected period
	period_filter = """
		AND date_of_joining <= %(end)s
		AND (relieving_date IS NULL OR relieving_date >= %(start)s)
	"""
	args["start"] = start
	args["end"]   = end

	total = frappe.db.sql(f"""
		SELECT COUNT(*) as c FROM `tabEmployee`
		WHERE 1=1 {where} {period_filter}
	""", args, as_dict=True)[0].c or 0

	teaching = frappe.db.sql(f"""
		SELECT COUNT(*) as c FROM `tabEmployee`
		WHERE custom_type='Teaching' {where} {period_filter}
	""", args, as_dict=True)[0].c or 0

	non_teaching = frappe.db.sql(f"""
		SELECT COUNT(*) as c FROM `tabEmployee`
		WHERE custom_type='Non-Teaching' {where} {period_filter}
	""", args, as_dict=True)[0].c or 0

	unclassified = total - teaching - non_teaching

	dept_data = frappe.db.sql(f"""
		SELECT COALESCE(department,'Unassigned') as department, COUNT(*) as total
		FROM `tabEmployee`
		WHERE 1=1 {where} {period_filter}
		GROUP BY department ORDER BY total DESC LIMIT 10
	""", args, as_dict=True)

	# Monthly joining trend — rolling last 6 months (not affected by period filter)
	join_args = {}
	if resolved:
		join_args["company"] = resolved
	if department:
		join_args["department"] = department
	join_where = (" AND " + " AND ".join(ew)) if ew else ""

	join_trend = []
	for i in range(5, -1, -1):
		m_start = get_first_day(add_months(getdate(nowdate()), -i))
		m_end   = get_last_day(m_start)
		c = frappe.db.sql(f"""
			SELECT COUNT(*) as cnt FROM `tabEmployee`
			WHERE date_of_joining BETWEEN %(ms)s AND %(me)s {join_where}
		""", {**join_args, "ms": m_start, "me": m_end}, as_dict=True)[0].cnt or 0
		join_trend.append({"label": m_start.strftime("%b %Y"), "value": c})

	return {
		"total": total, "teaching": teaching,
		"non_teaching": non_teaching, "unclassified": unclassified,
		"teaching_pct": round((teaching / total) * 100, 1) if total > 0 else 0,
		"dept_data": dept_data,
		"join_trend": join_trend,
		"period_label": f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}",
	}


# ─────────────────────────────────────────────────────────────────
# 5. STAFFING PLAN vs ACTUALS
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_staffing_vs_actuals(company=None, department=None, date_from=None, date_to=None):
	resolved = _resolve_company(company)
	if resolved == "__NONE__":
		return {"data": [], "total_rows": 0}

	ew, args = [], {}
	if resolved:
		ew.append("sp.company = %(company)s")
		args["company"] = resolved
	if department:
		ew.append("sp.department = %(department)s")
		args["department"] = department

	# If custom date range: show plans active during that range
	# Otherwise: show currently active plans
	if date_from and date_to:
		ew.append("sp.from_date <= %(date_to)s AND sp.to_date >= %(date_from)s")
		args["date_from"] = date_from
		args["date_to"]   = date_to
	else:
		ew.append("sp.to_date >= CURDATE()")

	where = (" AND " + " AND ".join(ew)) if ew else ""

	result = frappe.db.sql(f"""
		SELECT spd.designation,
			spd.vacancies as planned,
			spd.current_count as actual,
			(spd.vacancies - COALESCE(spd.current_count,0)) as open_positions
		FROM `tabStaffing Plan Detail` spd
		JOIN `tabStaffing Plan` sp ON spd.parent = sp.name
		WHERE sp.docstatus = 1 {where}
		ORDER BY spd.designation
	""", args, as_dict=True)

	return {"data": result, "total_rows": len(result)}


# ─────────────────────────────────────────────────────────────────
# 6. FULL RECRUITMENT FUNNEL
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_recruitment_pipeline(company=None, department=None, date_from=None, date_to=None):
	resolved = _resolve_company(company)
	if resolved == "__NONE__":
		empty = {"total": 0, "pending": 0, "approved": 0, "filled": 0, "rejected": 0, "by_status": {}}
		return {"requisitions": empty, "openings": {"total": 0, "open": 0, "closed": 0},
				"applicants": {"total": 0, "open": 0, "replied": 0, "hold": 0, "accepted": 0, "rejected": 0},
				"offers": {"sent": 0, "accepted": 0, "rejected": 0, "awaiting": 0}, "hired": 0}

	# ── Requisition filters
	req_ew, req_args = [], {}
	if resolved:
		req_ew.append("jreq.company = %(company)s")
		req_args["company"] = resolved
	if department:
		req_ew.append("jreq.department = %(department)s")
		req_args["department"] = department
	if date_from:
		req_ew.append("jreq.posting_date >= %(date_from)s")
		req_args["date_from"] = date_from
	if date_to:
		req_ew.append("jreq.posting_date <= %(date_to)s")
		req_args["date_to"] = date_to
	req_where = (" AND " + " AND ".join(req_ew)) if req_ew else ""

	# ── Job Opening filters
	jo_ew, jo_args = [], {}
	if resolved:
		jo_ew.append("jo.company = %(company)s")
		jo_args["company"] = resolved
	if department:
		jo_ew.append("jo.department = %(department)s")
		jo_args["department"] = department
	if date_from:
		jo_ew.append("jo.posted_on >= %(date_from)s")
		jo_args["date_from"] = date_from
	if date_to:
		jo_ew.append("jo.posted_on <= %(date_to)s")
		jo_args["date_to"] = date_to
	jo_where = (" AND " + " AND ".join(jo_ew)) if jo_ew else ""

	# ── Offer date filters
	jof_ew, jof_args = [], {}
	if resolved:
		jof_ew.append("jo.company = %(company)s")
		jof_args["company"] = resolved
	if department:
		jof_ew.append("jo.department = %(department)s")
		jof_args["department"] = department
	if date_from:
		jof_ew.append("jof.offer_date >= %(date_from)s")
		jof_args["date_from"] = date_from
	if date_to:
		jof_ew.append("jof.offer_date <= %(date_to)s")
		jof_args["date_to"] = date_to
	jof_where = (" AND " + " AND ".join(jof_ew)) if jof_ew else ""

	req_statuses = frappe.db.sql(f"""
		SELECT jreq.status, COUNT(*) as cnt FROM `tabJob Requisition` jreq
		WHERE 1=1 {req_where} GROUP BY jreq.status
	""", req_args, as_dict=True)
	req_map = {r.status: r.cnt for r in req_statuses}

	jo_statuses = frappe.db.sql(f"""
		SELECT jo.status, COUNT(*) as cnt FROM `tabJob Opening` jo
		WHERE 1=1 {jo_where} GROUP BY jo.status
	""", jo_args, as_dict=True)
	jo_map = {r.status: r.cnt for r in jo_statuses}

	ja_statuses = frappe.db.sql(f"""
		SELECT ja.status, COUNT(*) as cnt
		FROM `tabJob Applicant` ja
		JOIN `tabJob Opening` jo ON ja.job_title = jo.name
		WHERE 1=1 {jo_where}
		GROUP BY ja.status
	""", jo_args, as_dict=True)
	ja_map = {r.status: r.cnt for r in ja_statuses}

	jof_statuses = frappe.db.sql(f"""
		SELECT jof.status, COUNT(*) as cnt
		FROM `tabJob Offer` jof
		JOIN `tabJob Applicant` ja  ON jof.job_applicant = ja.name
		JOIN `tabJob Opening`   jo  ON ja.job_title = jo.name
		WHERE jof.docstatus = 1 {jof_where}
		GROUP BY jof.status
	""", jof_args, as_dict=True)
	jof_map = {r.status: r.cnt for r in jof_statuses}

	hired_ew, hired_args = [], {}
	if resolved:
		hired_ew.append("e.company = %(company)s")
		hired_args["company"] = resolved
	if date_from:
		hired_ew.append("e.date_of_joining >= %(date_from)s")
		hired_args["date_from"] = date_from
	if date_to:
		hired_ew.append("e.date_of_joining <= %(date_to)s")
		hired_args["date_to"] = date_to
	hired_where = (" AND " + " AND ".join(hired_ew)) if hired_ew else ""

	hired = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee` e
		WHERE e.job_applicant IS NOT NULL AND e.job_applicant != '' {hired_where}
	""", hired_args, as_dict=True)[0].cnt or 0

	req_chart = {
		"Pending":         req_map.get("Pending", 0),
		"Open & Approved": req_map.get("Open & Approved", 0),
		"Filled":          req_map.get("Filled", 0),
		"Rejected":        req_map.get("Rejected", 0),
		"On Hold":         req_map.get("On Hold", 0),
		"Cancelled":       req_map.get("Cancelled", 0),
	}

	return {
		"requisitions": {
			"total":    sum(req_map.values()),
			"pending":  req_map.get("Pending", 0),
			"approved": req_map.get("Open & Approved", 0),
			"filled":   req_map.get("Filled", 0),
			"rejected": req_map.get("Rejected", 0),
			"by_status": req_chart,
		},
		"openings": {
			"total":  sum(jo_map.values()),
			"open":   jo_map.get("Open", 0),
			"closed": jo_map.get("Closed", 0),
		},
		"applicants": {
			"total":    sum(ja_map.values()),
			"open":     ja_map.get("Open", 0),
			"replied":  ja_map.get("Replied", 0),
			"hold":     ja_map.get("Hold", 0),
			"accepted": ja_map.get("Accepted", 0),
			"rejected": ja_map.get("Rejected", 0),
		},
		"offers": {
			"sent":     sum(jof_map.values()),
			"accepted": jof_map.get("Accepted", 0),
			"rejected": jof_map.get("Rejected", 0),
			"awaiting": jof_map.get("Awaiting Response", 0),
		},
		"hired": hired,
	}


# ─────────────────────────────────────────────────────────────────
# 7. RECENT MOVEMENTS
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_recent_movements(company=None, department=None, date_from=None, date_to=None):
	resolved = _resolve_company(company)
	if resolved == "__NONE__":
		return {"joiners": [], "leavers": []}

	ew, args = [], {}
	if resolved:
		ew.append("company = %(company)s")
		args["company"] = resolved
	if department:
		ew.append("department = %(department)s")
		args["department"] = department

	where = (" AND " + " AND ".join(ew)) if ew else ""

	# Joiners: joined within date range (or most recent if no range)
	if date_from and date_to:
		joiner_filter = "AND date_of_joining BETWEEN %(date_from)s AND %(date_to)s"
		args["date_from"] = date_from
		args["date_to"]   = date_to
	else:
		joiner_filter = "AND date_of_joining <= CURDATE() AND (relieving_date IS NULL OR relieving_date >= CURDATE())"

	joiners = frappe.db.sql(f"""
		SELECT employee_name, designation, department, date_of_joining
		FROM `tabEmployee`
		WHERE 1=1 {where} {joiner_filter}
		ORDER BY date_of_joining DESC LIMIT 5
	""", args, as_dict=True)

	# Leavers: left within date range (or most recent if no range)
	if date_from and date_to:
		leaver_filter = "AND relieving_date BETWEEN %(date_from)s AND %(date_to)s"
	else:
		leaver_filter = "AND relieving_date IS NOT NULL"

	leavers = frappe.db.sql(f"""
		SELECT employee_name, designation, department, relieving_date
		FROM `tabEmployee`
		WHERE 1=1 {where} {leaver_filter}
		ORDER BY relieving_date DESC LIMIT 5
	""", args, as_dict=True)

	return {"joiners": joiners, "leavers": leavers}