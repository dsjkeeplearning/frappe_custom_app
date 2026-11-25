"""What was set up on the site itself, read as it is now for the Business Rules page.

Much of the logic on this site was made in the Desk and is not in the app: scripts,
a workflow, mandatory fields and settings. This reads their names and compares
them with the app, so a change made on the site shows on the page at once.
It reads set-up only, never a transaction or a person, and returns no field's value.
"""

import json
from pathlib import Path

import frappe

APP = Path(__file__).resolve().parents[1]

# Overrides that change what a user must, may or cannot enter. Labels and layout are left out.
RULE_PROPERTIES = [
	"reqd",
	"mandatory_depends_on",
	"read_only",
	"read_only_depends_on",
	"options",
	"default",
	"permlevel",
	"allow_on_submit",
	"unique",
	"autoname",
]
STEP_FIELDS = ["state", "action", "next_state", "allowed", "allow_self_approval", "condition"]


def live():
	return {
		"settings": settings(),
		"workflows": workflows(),
		"scripts": server_scripts() + client_scripts(),
		"notifications": notifications(),
		"fields": mandatory_fields() + property_setters(),
	}


# Settings ------------------------------------------------------------------


def settings():
	budget = frappe.get_cached_doc("Budget Settings", "Budget Settings")
	verifiers = frappe.get_all(
		"Verifier PR Details", filters={"parent": "Verifier PR Settings"}, fields=["name"]
	)
	return [
		setting("Backdated purchase requests are refused", budget.get("restrict_backdated_pr")),
		setting("A request uses only its own month's budget", budget.get("restrict_pr_to_current_month_budget")),
		setting("A request uses the month it is raised in", budget.get("use_transaction_date_for_pr_budget")),
		{"label": "Cost centers that need a verifier", "value": str(len(verifiers))},
	]


def setting(label, on):
	return {"label": label, "value": "On" if on else "Off"}


# Workflows -----------------------------------------------------------------


def app_workflows():
	found = json.loads((APP / "fixtures" / "workflow.json").read_text(encoding="utf-8"))
	return {workflow["name"]: steps(workflow["transitions"]) for workflow in found}


def steps(transitions):
	return sorted(
		(t["state"], t["action"], t["next_state"], t["allowed"], bool(t.get("allow_self_approval")), condition(t))
		for t in transitions
	)


def condition(transition):
	return " ".join((transition.get("condition") or "").split())


def workflows():
	in_app, found = app_workflows(), []
	for workflow in frappe.get_all(
		"Workflow", filters={"is_active": 1}, fields=["name", "document_type"], order_by="document_type"
	):
		of_this = {"parent": workflow.name, "parenttype": "Workflow"}
		transitions = frappe.get_all(
			"Workflow Transition", filters=of_this, fields=STEP_FIELDS, order_by="idx"
		)
		found.append(
			{
				"name": workflow.name,
				"document_type": workflow.document_type,
				"source": source(steps(transitions), in_app.get(workflow.name)),
				"steps": [{key: t[key] for key in STEP_FIELDS[:4]} for t in transitions],
			}
		)
	return found


def source(on_site, in_app):
	"""Whether the app holds this workflow, holds another version of it, or does not know it."""
	if in_app is None:
		return "site"
	return "app" if on_site == in_app else "changed"


# Scripts and notifications -------------------------------------------------


def server_scripts():
	jobs = {
		job.server_script: job
		for job in frappe.get_all(
			"Scheduled Job Type",
			filters={"server_script": ["is", "set"]},
			fields=["name", "server_script", "stopped"],
		)
	}
	return [
		{"name": script.name, "runs": when(script), "state": job_state(jobs.get(script.name))}
		for script in frappe.get_all(
			"Server Script",
			filters={"disabled": 0},
			fields=["name", "script_type", "reference_doctype", "doctype_event", "event_frequency", "cron_format"],
			order_by="script_type, name",
		)
	]


def when(script):
	if script.script_type == "DocType Event":
		return f"{script.reference_doctype}, {script.doctype_event}"
	if script.script_type == "Scheduler Event":
		return f"Scheduled, {script.cron_format or script.event_frequency}"
	return script.script_type


def job_state(job):
	"""A scheduled script can be switched on while its job is stopped, or fail every time it runs."""
	if not job:
		return "on"
	if job.stopped:
		return "stopped"
	last = frappe.get_all(
		"Scheduled Job Log",
		filters={"scheduled_job_type": job.name},
		fields=["status"],
		order_by="creation desc",
		limit=1,
	)
	return "failing" if last and last[0].status == "Failed" else "on"


def client_scripts():
	return [
		{"name": script.name, "runs": f"{script.dt}, {script.view}", "state": "on"}
		for script in frappe.get_all(
			"Client Script", filters={"enabled": 1}, fields=["name", "dt", "view"], order_by="dt, name"
		)
	]


def notifications():
	return [
		{"name": n.name, "runs": f"{n.document_type}, {n.event}", "state": "on"}
		for n in frappe.get_all(
			"Notification",
			filters={"enabled": 1, "is_standard": 0},
			fields=["name", "document_type", "event"],
			order_by="document_type",
		)
	]


# Fields --------------------------------------------------------------------


def app_customisations():
	"""The fields and overrides the app holds: {(doctype, field)} and {(doctype, field, property): value}."""
	fields, overrides = set(), {}
	for path in sorted((APP / "custom_app" / "custom").glob("*.json")):
		custom = json.loads(path.read_text(encoding="utf-8"))
		fields |= {(custom["doctype"], f["fieldname"]) for f in custom.get("custom_fields", [])}
		for s in custom.get("property_setters", []):
			overrides[(custom["doctype"], s.get("field_name"), s["property"])] = str(s.get("value") or "")
	return fields, overrides


def mandatory_fields():
	"""Mandatory fields added on the site that the app does not hold."""
	in_app, _overrides = app_customisations()
	return [
		{"doctype": f.dt, "field": f.label or f.fieldname, "change": "added, mandatory"}
		for f in frappe.get_all(
			"Custom Field",
			filters={"is_system_generated": 0, "reqd": 1},
			fields=["dt", "fieldname", "label"],
			order_by="dt",
		)
		if (f.dt, f.fieldname) not in in_app
	]


def property_setters():
	"""Overrides made on the site that the app does not hold, or holds with another value."""
	_fields, in_app = app_customisations()
	found = []
	for s in frappe.get_all(
		"Property Setter",
		filters={"is_system_generated": 0, "property": ["in", RULE_PROPERTIES]},
		fields=["doc_type", "field_name", "property", "value"],
		order_by="doc_type",
	):
		key = (s.doc_type, s.field_name, s.property)
		if key not in in_app:
			change = f"{s.property} set on the site"
		elif in_app[key] != str(s.value or ""):
			change = f"{s.property} differs from the app"
		else:
			continue
		found.append({"doctype": s.doc_type, "field": s.field_name or "", "change": change})
	return found
