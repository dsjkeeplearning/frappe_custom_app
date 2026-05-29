import frappe
from frappe.utils import getdate, nowdate, add_months, get_first_day, get_last_day
from datetime import date


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def _period_dates(period="month"):
	today = getdate(nowdate())
	if period == "month":
		start = get_first_day(today)
		end   = get_last_day(today)
	elif period == "quarter":
		qm    = ((today.month - 1) // 3) * 3 + 1
		start = date(today.year, qm, 1)
		end   = get_last_day(add_months(start, 2))
	else:  # year
		start = date(today.year, 1, 1)
		end   = date(today.year, 12, 31)
	return start, end


def _base_filters(company=None, department=None, school=None):
	"""Return a dict of common WHERE clauses for Employee queries."""
	clauses, args = [], {}
	if company:
		clauses.append("e.company = %(company)s")
		args["company"] = company
	if department:
		clauses.append("e.department = %(department)s")
		args["department"] = department
	if school:
		clauses.append("e.custom_school = %(school)s")
		args["school"] = school
	return (" AND " + " AND ".join(clauses)) if clauses else "", args


# ─────────────────────────────────────────────────────────────────
# FILTER OPTIONS
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_filter_options():
	companies    = frappe.db.sql("SELECT name FROM `tabCompany` ORDER BY name", as_dict=True)
	departments  = frappe.db.sql("SELECT name FROM `tabDepartment` ORDER BY name", as_dict=True)
	schools      = frappe.db.sql(
		"SELECT DISTINCT custom_school as name FROM `tabEmployee` "
		"WHERE custom_school IS NOT NULL AND custom_school != '' ORDER BY custom_school",
		as_dict=True
	)
	designations = frappe.db.sql("SELECT name FROM `tabDesignation` ORDER BY name", as_dict=True)
	return {
		"companies":    [r.name for r in companies],
		"departments":  [r.name for r in departments],
		"schools":      [r.name for r in schools],
		"designations": [r.name for r in designations],
	}


# ─────────────────────────────────────────────────────────────────
# 1. ATTRITION RATE
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_attrition_rate(period="month", company=None, department=None, school=None):
	start, end = _period_dates(period)
	extra_where, args = _base_filters(company, department, school)

	# Replace 'e.' prefix since these queries use tabEmployee directly
	ew = extra_where.replace("e.company", "company").replace("e.department", "department").replace("e.custom_school", "custom_school")

	start_count = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE date_of_joining <= %(start)s
		AND (relieving_date IS NULL OR relieving_date >= %(start)s)
		AND status != 'Left' {ew}
	""", {**args, "start": start}, as_dict=True)[0].cnt or 0

	end_count = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE date_of_joining <= %(end)s
		AND (relieving_date IS NULL OR relieving_date >= %(end)s)
		AND status != 'Left' {ew}
	""", {**args, "end": end}, as_dict=True)[0].cnt or 0

	separations = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE status IN ('Left', 'Inactive')
		AND relieving_date BETWEEN %(start)s AND %(end)s {ew}
	""", {**args, "start": start, "end": end}, as_dict=True)[0].cnt or 0

	missing_date = frappe.db.sql(f"""
		SELECT COUNT(*) as cnt FROM `tabEmployee`
		WHERE status IN ('Left', 'Inactive')
		AND (relieving_date IS NULL OR relieving_date = '') {ew}
	""", args, as_dict=True)[0].cnt or 0

	avg_headcount = (start_count + end_count) / 2 if (start_count + end_count) > 0 else 1
	rate = round((separations / avg_headcount) * 100, 2)

	# Monthly trend (last 6 months)
	trend = []
	for i in range(5, -1, -1):
		m_start = get_first_day(add_months(getdate(nowdate()), -i))
		m_end   = get_last_day(m_start)
		s = frappe.db.sql(f"""
			SELECT COUNT(*) as cnt FROM `tabEmployee`
			WHERE status IN ('Left','Inactive')
			AND relieving_date BETWEEN %(ms)s AND %(me)s {ew}
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
def get_time_to_hire(company=None, department=None, school=None, date_from=None, date_to=None):
	extra = []
	args  = {}
	if company:
		extra.append("jo.company = %(company)s")
		args["company"] = company
	if department:
		extra.append("jop.designation IN (SELECT name FROM `tabDesignation` WHERE name = %(dept_desg)s)")
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

	# Monthly trend
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
		AND status = 'Active'
	""", as_dict=True)[0].cnt or 0

	row = result[0] if result else {}
	return {
		"avg_days":         round(row.get("avg_days") or 0, 1),
		"min_days":         row.get("min_days") or 0,
		"max_days":         row.get("max_days") or 0,
		"total_hires":      row.get("total_hires") or 0,
		"first_opening_date": str(row.get("first_opening_date") or ""),
		"first_applicant":  row.get("first_applicant") or "—",
		"excluded_count":   excluded,
		"trend":            trend,
	}


# ─────────────────────────────────────────────────────────────────
# 3. OFFER ACCEPTANCE
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_offer_acceptance(company=None, date_from=None, date_to=None):
	ew, args = [], {}
	if company:
		ew.append("company = %(company)s")
		args["company"] = company
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
def get_headcount_summary(company=None, department=None, school=None):
	ew, args = [], {}
	if company:
		ew.append("company = %(company)s")
		args["company"] = company
	if department:
		ew.append("department = %(department)s")
		args["department"] = department
	if school:
		ew.append("custom_school = %(school)s")
		args["school"] = school

	where = (" AND " + " AND ".join(ew)) if ew else ""

	total       = frappe.db.sql(f"SELECT COUNT(*) as c FROM `tabEmployee` WHERE status='Active' {where}", args, as_dict=True)[0].c or 0
	teaching    = frappe.db.sql(f"SELECT COUNT(*) as c FROM `tabEmployee` WHERE status='Active' AND custom_type='Teaching' {where}", args, as_dict=True)[0].c or 0
	non_teaching= frappe.db.sql(f"SELECT COUNT(*) as c FROM `tabEmployee` WHERE status='Active' AND custom_type='Non-Teaching' {where}", args, as_dict=True)[0].c or 0
	unclassified= total - teaching - non_teaching

	school_data = frappe.db.sql(f"""
		SELECT COALESCE(custom_school,'Unassigned') as school,
			SUM(CASE WHEN custom_type='Teaching' THEN 1 ELSE 0 END) as teaching,
			SUM(CASE WHEN custom_type='Non-Teaching' THEN 1 ELSE 0 END) as non_teaching,
			COUNT(*) as total
		FROM `tabEmployee` WHERE status='Active' {where}
		GROUP BY custom_school ORDER BY total DESC
	""", args, as_dict=True)

	dept_data = frappe.db.sql(f"""
		SELECT COALESCE(department,'Unassigned') as department, COUNT(*) as total
		FROM `tabEmployee` WHERE status='Active' {where}
		GROUP BY department ORDER BY total DESC LIMIT 10
	""", args, as_dict=True)

	# Monthly joining trend last 6 months
	join_trend = []
	for i in range(5, -1, -1):
		m_start = get_first_day(add_months(getdate(nowdate()), -i))
		m_end   = get_last_day(m_start)
		c = frappe.db.sql(f"""
			SELECT COUNT(*) as cnt FROM `tabEmployee`
			WHERE date_of_joining BETWEEN %(ms)s AND %(me)s {where}
		""", {**args, "ms": m_start, "me": m_end}, as_dict=True)[0].cnt or 0
		join_trend.append({"label": m_start.strftime("%b %Y"), "value": c})

	return {
		"total": total, "teaching": teaching,
		"non_teaching": non_teaching, "unclassified": unclassified,
		"teaching_pct": round((teaching / total) * 100, 1) if total > 0 else 0,
		"school_data": school_data, "dept_data": dept_data,
		"join_trend": join_trend,
	}


# ─────────────────────────────────────────────────────────────────
# 5. STAFFING PLAN vs ACTUALS
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_staffing_vs_actuals(company=None, department=None):
	ew, args = [], {}
	if company:
		ew.append("sp.company = %(company)s")
		args["company"] = company
	if department:
		ew.append("sp.department = %(department)s")
		args["department"] = department

	where = (" AND " + " AND ".join(ew)) if ew else ""

	result = frappe.db.sql(f"""
		SELECT spd.designation,
			spd.vacancies as planned,
			spd.current_count as actual,
			(spd.vacancies - COALESCE(spd.current_count,0)) as open_positions
		FROM `tabStaffing Plan Detail` spd
		JOIN `tabStaffing Plan` sp ON spd.parent = sp.name
		WHERE sp.docstatus = 1 AND sp.to_date >= CURDATE() {where}
		ORDER BY spd.designation
	""", args, as_dict=True)

	return {"data": result, "total_rows": len(result)}


# ─────────────────────────────────────────────────────────────────
# 6. FULL RECRUITMENT FUNNEL
#    Job Requisition → Job Opening → Job Applicant → Job Offer → Hired
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_recruitment_pipeline(company=None, department=None, date_from=None, date_to=None):
	# ── Requisition filters (single table, no alias needed)
	req_ew, req_args = [], {}
	if company:
		req_ew.append("jreq.company = %(company)s")
		req_args["company"] = company
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

	# ── Job Opening filters (prefixed jo.)
	jo_ew, jo_args = [], {}
	if company:
		jo_ew.append("jo.company = %(company)s")
		jo_args["company"] = company
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

	# ── Offer date filters (prefixed jof.)
	jof_ew, jof_args = [], {}
	if company:
		jof_ew.append("jo.company = %(company)s")
		jof_args["company"] = company
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

	# Job Requisitions
	req_statuses = frappe.db.sql(f"""
		SELECT jreq.status, COUNT(*) as cnt FROM `tabJob Requisition` jreq
		WHERE 1=1 {req_where} GROUP BY jreq.status
	""", req_args, as_dict=True)
	req_map = {r.status: r.cnt for r in req_statuses}

	# Job Openings
	jo_statuses = frappe.db.sql(f"""
		SELECT jo.status, COUNT(*) as cnt FROM `tabJob Opening` jo
		WHERE 1=1 {jo_where} GROUP BY jo.status
	""", jo_args, as_dict=True)
	jo_map = {r.status: r.cnt for r in jo_statuses}

	# Job Applicants — join through job_title → Job Opening for company/dept filter
	ja_statuses = frappe.db.sql(f"""
		SELECT ja.status, COUNT(*) as cnt
		FROM `tabJob Applicant` ja
		JOIN `tabJob Opening` jo ON ja.job_title = jo.name
		WHERE 1=1 {jo_where}
		GROUP BY ja.status
	""", jo_args, as_dict=True)
	ja_map = {r.status: r.cnt for r in ja_statuses}

	# Job Offers — use jof_where which prefixes all columns correctly
	jof_statuses = frappe.db.sql(f"""
		SELECT jof.status, COUNT(*) as cnt
		FROM `tabJob Offer` jof
		JOIN `tabJob Applicant` ja  ON jof.job_applicant = ja.name
		JOIN `tabJob Opening`   jo  ON ja.job_title = jo.name
		WHERE jof.docstatus = 1 {jof_where}
		GROUP BY jof.status
	""", jof_args, as_dict=True)
	jof_map = {r.status: r.cnt for r in jof_statuses}

	# Hired (employees with applicant link, filtered by joining date)
	hired_ew, hired_args = [], {}
	if company:
		hired_ew.append("e.company = %(company)s")
		hired_args["company"] = company
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

	# Requisition status breakdown for chart
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
def get_recent_movements(company=None, department=None, school=None):
	ew, args = [], {}
	if company:
		ew.append("company = %(company)s")
		args["company"] = company
	if department:
		ew.append("department = %(department)s")
		args["department"] = department
	if school:
		ew.append("custom_school = %(school)s")
		args["school"] = school

	where = (" AND " + " AND ".join(ew)) if ew else ""

	joiners = frappe.db.sql(f"""
		SELECT employee_name, designation, department, custom_school, date_of_joining
		FROM `tabEmployee`
		WHERE status = 'Active' {where}
		ORDER BY date_of_joining DESC LIMIT 5
	""", args, as_dict=True)

	leavers = frappe.db.sql(f"""
		SELECT employee_name, designation, department, custom_school, relieving_date
		FROM `tabEmployee`
		WHERE status = 'Left' AND relieving_date IS NOT NULL {where}
		ORDER BY relieving_date DESC LIMIT 5
	""", args, as_dict=True)

	return {"joiners": joiners, "leavers": leavers}


# ─────────────────────────────────────────────────────────────────
# 8. FACULTY-STUDENT RATIO
# ─────────────────────────────────────────────────────────────────
@frappe.whitelist()
def get_faculty_ratio(student_counts=None, company=None, school=None):
	import json
	if student_counts and isinstance(student_counts, str):
		student_counts = json.loads(student_counts)
	else:
		student_counts = {}

	ew, args = [], {}
	if company:
		ew.append("company = %(company)s")
		args["company"] = company
	if school:
		ew.append("custom_school = %(school)s")
		args["school"] = school

	where = (" AND " + " AND ".join(ew)) if ew else ""

	school_data = frappe.db.sql(f"""
		SELECT COALESCE(custom_school,'Unassigned') as school,
			SUM(CASE WHEN custom_type='Teaching' THEN 1 ELSE 0 END) as faculty,
			SUM(CASE WHEN custom_type='Non-Teaching' THEN 1 ELSE 0 END) as staff,
			COUNT(*) as total
		FROM `tabEmployee`
		WHERE status = 'Active' {where}
		GROUP BY custom_school ORDER BY school
	""", args, as_dict=True)

	result = []
	for row in school_data:
		students     = student_counts.get(row.school, 0)
		faculty_ratio= round(students / row.faculty, 1) if row.faculty > 0 and students > 0 else None
		staff_ratio  = round(students / row.staff,   1) if row.staff   > 0 and students > 0 else None
		result.append({
			"school": row.school, "faculty": row.faculty,
			"staff": row.staff, "total_employees": row.total,
			"students": students,
			"faculty_ratio": faculty_ratio, "staff_ratio": staff_ratio,
		})
	return result