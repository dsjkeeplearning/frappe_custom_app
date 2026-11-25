"""The Business Rules page: who reads it, and what it shows of the site (RULES.md XX-06, XX-07).

No site or database is needed, see fake_site:

	python -m unittest custom_app.tests.test_rules_page
	bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_page
"""

import json
import unittest
from pathlib import Path

import frappe

from custom_app.business_rules import catalogue, site
from custom_app.custom_app.page.business_rules import business_rules
from custom_app.tests.fake_site import SiteTest

PAGE = Path(business_rules.__file__).parent / "business_rules.json"


class TestReaders(SiteTest):
	def setUp(self):
		super().setUp()
		self.site.add("Budget Settings", "Budget Settings")

	def test_only_a_system_manager_reads_the_rules(self):
		self.log_in("manager@example.com", "System Manager")
		self.assertIn("rules", business_rules.get())
		others = [
			"Employee",
			"Auditor",
			"Accounts Manager",
			"Finance Approver",
			"Finance User",
			"Procurement Approver",
			"AP Manager",
			"HR Manager",
			"Institution Head",
			"Expense Approver",
			"Guest",
		]
		for role in others:
			self.log_in("other@example.com", role)
			with self.assertRaises(frappe.PermissionError, msg=role):
				business_rules.get()
		self.log_in("all.of.them@example.com", *others)
		with self.assertRaises(frappe.PermissionError):
			business_rules.get()

	def test_the_page_opens_only_for_system_managers(self):
		page = json.loads(PAGE.read_text(encoding="utf-8"))
		self.assertEqual([row["role"] for row in page["roles"]], ["System Manager"])
		self.assertEqual(business_rules.READERS, ["System Manager"])

	def test_the_page_shows_every_rule(self):
		self.log_in("manager@example.com", "System Manager")
		page = business_rules.get()
		self.assertEqual([r["id"] for r in page["rules"]], [r["id"] for r in catalogue.rules()])
		self.assertTrue(all(r["title"] and r["plain"] for r in page["rules"]))
		self.assertEqual({r["proof"] for r in page["rules"]}, {"tested", "untested", "site"})


class TestSite(SiteTest):
	def workflow(self, name, steps):
		self.site.add("Workflow", name, is_active=1, document_type=name.split(" Flow")[0])
		for i, (state, action, next_state) in enumerate(steps):
			self.site.add(
				"Workflow Transition",
				f"{name} {i}",
				parent=name,
				parenttype="Workflow",
				state=state,
				action=action,
				next_state=next_state,
				allowed="Approver",
				allow_self_approval=0,
			)

	def test_a_workflow_is_compared_with_the_app(self):
		step = ("Draft", "Approve", "Approved")
		for name in ("Same Flow", "Changed Flow", "New Flow"):
			self.workflow(name, [step])
		of_app = {
			"Same Flow": [(*step, "Approver", False, "")],
			"Changed Flow": [(*step, "Someone Else", False, "")],
		}
		self.patch("custom_app.business_rules.site.app_workflows", lambda: of_app)
		self.assertEqual(
			{w["name"]: w["source"] for w in site.workflows()},
			{"Same Flow": "app", "Changed Flow": "changed", "New Flow": "site"},
		)

	def script(self, name, **values):
		self.site.add("Server Script", name, **{"disabled": 0, "script_type": "Scheduler Event", **values})

	def job(self, script, stopped=0, last=None):
		self.site.add("Scheduled Job Type", f"job {script}", server_script=script, stopped=stopped)
		if last:
			self.site.add("Scheduled Job Log", f"log {script}", scheduled_job_type=f"job {script}", status=last)

	def test_a_stopped_or_failing_job_is_shown(self):
		for name in ("Stopped", "Failing", "Fine"):
			self.script(name, event_frequency="Hourly")
		self.job("Stopped", stopped=1)
		self.job("Failing", last="Failed")
		self.job("Fine", last="Complete")
		self.assertEqual(
			{s["name"]: s["state"] for s in site.server_scripts()},
			{"Stopped": "stopped", "Failing": "failing", "Fine": "on"},
		)

	def test_switched_off_scripts_are_not_shown(self):
		self.script("On", script_type="DocType Event", reference_doctype="Budget", doctype_event="Before Save")
		self.script("Off", disabled=1)
		self.site.add("Client Script", "Form", enabled=1, dt="Budget", view="Form")
		self.site.add("Client Script", "Old form", enabled=0, dt="Budget", view="Form")
		self.site.add("Notification", "Own", enabled=1, is_standard=0, document_type="Budget", event="Save")
		self.site.add("Notification", "Standard", enabled=1, is_standard=1)
		self.assertEqual([(s["name"], s["runs"]) for s in site.server_scripts()], [("On", "Budget, Before Save")])
		self.assertEqual([s["name"] for s in site.client_scripts()], ["Form"])
		self.assertEqual([n["name"] for n in site.notifications()], ["Own"])

	def test_fields_the_app_does_not_hold_are_shown_without_their_value(self):
		self.patch(
			"custom_app.business_rules.site.app_customisations",
			lambda: ({("Budget", "known")}, {("Budget", "a", "reqd"): "1", ("Budget", "b", "reqd"): "1"}),
		)
		for field in ("known", "new"):
			self.site.add("Custom Field", field, dt="Budget", fieldname=field, reqd=1, is_system_generated=0)
		for field, prop, value in (
			("a", "reqd", "1"),
			("b", "reqd", "0"),
			("c", "default", "secret"),
			("d", "label", "x"),
		):
			self.site.add(
				"Property Setter",
				f"{field} {prop}",
				doc_type="Budget",
				field_name=field,
				property=prop,
				value=value,
				is_system_generated=0,
			)
		self.assertEqual([f["field"] for f in site.mandatory_fields()], ["new"])
		self.assertEqual(
			[(f["field"], f["change"]) for f in site.property_setters()],
			[("b", "reqd differs from the app"), ("c", "default set on the site")],
		)
		self.assertNotIn("secret", json.dumps(site.property_setters()))

	def test_settings_are_shown_as_they_are(self):
		self.site.add("Budget Settings", "Budget Settings", restrict_backdated_pr=1)
		self.site.add("Verifier PR Details", "v", parent="Verifier PR Settings")
		self.assertEqual([s["value"] for s in site.settings()], ["On", "Off", "Off", "1"])


if __name__ == "__main__":
	unittest.main()
