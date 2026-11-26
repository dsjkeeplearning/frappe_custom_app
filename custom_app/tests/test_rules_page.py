"""The Business Rules page: who reads it, and what it shows of the site (RULES.md XX-06, XX-07).

No site or database is needed, see fake_site:

	python -m unittest custom_app.tests.test_rules_page
	bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_page
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from custom_app import sidebar
from custom_app.business_rules import catalogue, shortcut, site
from custom_app.custom_app.page.business_rules import business_rules
from custom_app.tests.fake_site import Doc, SiteTest

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


class TestShortcut(SiteTest):
	def home(self):
		blocks = [
			{"id": "a", "type": "header", "data": {"text": "Your Shortcuts"}},
			{"id": "b", "type": "shortcut", "data": {"shortcut_name": "Item", "col": 3}},
			{"id": "c", "type": "shortcut", "data": {"shortcut_name": "Customer", "col": 3}},
			{"id": "d", "type": "header", "data": {"text": "Reports & Masters"}},
			{"id": "e", "type": "card", "data": {"card_name": "Accounting", "col": 4}},
		]
		return self.site.add(
			"Workspace",
			"Home",
			shortcuts=[Doc(type="DocType", link_to="Item", label="Item")],
			content=json.dumps(blocks),
		)

	def test_the_shortcut_goes_after_homes_last_shortcut(self):
		home = self.home()
		shortcut.add_to_home()
		self.assertEqual(home.calls, ["save"])
		added = home.shortcuts[-1]
		self.assertEqual((added.type, added.link_to, added.label), ("Page", "business-rules", "Business Rules"))
		self.assertEqual(json.loads(PAGE.read_text(encoding="utf-8"))["name"], added.link_to)
		names = [b["data"].get("shortcut_name") for b in json.loads(home.content)]
		self.assertEqual(names, [None, "Item", "Customer", "Business Rules", None, None])

	def test_a_shortcut_already_there_is_not_added_again(self):
		home = self.home()
		shortcut.add_to_home()
		shortcut.add_to_home()
		self.assertEqual((home.calls, len(home.shortcuts)), (["save"], 2))
		self.assertEqual(home.content.count("Business Rules"), 1)

	def test_the_shortcut_never_stops_a_migrate(self):
		shortcut.add_to_home()
		self.assertEqual(self.site.errors, [])
		self.home()
		with patch("frappe.get_doc", side_effect=RuntimeError("Home is broken")):
			shortcut.add_to_home()
		self.assertEqual(len(self.site.errors), 1)


def address(name):
	"""The /app address Frappe gives a name, as frappe.router.slug does."""
	return name.lower().replace(" ", "-")


class TestSidebar(SiteTest):
	"""The Business Rules entry of sidebar.py. The EOMS Docs entry is in test_rules_eoms."""

	SIDEBAR = "Business Rules Sidebar"

	def sidebar(self, *entries):
		for name, sequence, parent in entries:
			self.site.add("Workspace", name, public=1, sequence_id=sequence, parent_page=parent)

	def made(self):
		[entry] = [doc for doc in self.site.made if doc.label == self.SIDEBAR]
		self.assertEqual(entry.calls, ["save"])
		return entry

	def test_the_sidebar_entry_opens_the_page_for_system_managers(self):
		self.sidebar(("Build", 33, ""), ("Config Email", 35, ""))
		sidebar.add_entries()
		entry = self.made()
		page = json.loads(PAGE.read_text(encoding="utf-8"))
		# The sidebar links to the address of the title, the page; the entry's own name has another.
		self.assertEqual(address(entry.title), page["name"])
		self.assertNotEqual(address(entry.label), page["name"])
		self.assertEqual([r.role for r in entry.roles], [row["role"] for row in page["roles"]])
		self.assertEqual((entry.public, entry.is_hidden, entry.module), (1, 0, None))
		self.assertEqual([(s.type, s.link_to) for s in entry.shortcuts], [("Page", page["name"])])
		self.assertIn("Business Rules", entry.content)

	def test_the_entry_goes_right_below_config_email(self):
		self.sidebar(("Build", 33, ""), ("Config Email", 35, ""), ("Tax", 36, "Payroll"), ("Later", 40, ""))
		sidebar.add_entries()
		self.assertEqual((self.made().parent_page or "", self.made().sequence_id), ("", 37.5))

		self.site.made.clear()
		self.site.records["Workspace"]["Config Email"].parent_page = "Payroll"
		sidebar.add_entries()
		self.assertEqual((self.made().parent_page or "", self.made().sequence_id), ("Payroll", 35.5))

	def test_without_config_email_the_entry_goes_last(self):
		self.sidebar(("Build", 33, ""), ("Tax", 38, "Payroll"))
		sidebar.add_entries()
		self.assertEqual((self.made().parent_page or "", self.made().sequence_id), ("", 34))

	def test_an_entry_already_in_place_is_not_saved_again(self):
		self.sidebar(("Config Email", 35, ""))
		entry = self.site.add("Workspace", self.SIDEBAR, public=1, label=self.SIDEBAR)
		sidebar.add_entries()
		sidebar.add_entries()
		self.assertEqual((entry.calls, entry.sequence_id, entry.title), (["save"], 36, "Business Rules"))

		# Moved, or opened to another role on the site: put back on the next migrate.
		entry.sequence_id = 3
		entry.append("roles", {"role": "Employee"})
		sidebar.add_entries()
		self.assertEqual((entry.calls, entry.sequence_id), (["save", "save"], 36))
		self.assertEqual([r.role for r in entry.roles], ["System Manager"])
		self.assertEqual((len(entry.shortcuts), entry.content.count("Business Rules")), (1, 1))

	def test_the_sidebar_entry_never_stops_a_migrate(self):
		self.sidebar(("Config Email", 35, ""))
		with patch("frappe.get_all", side_effect=RuntimeError("Workspace is broken")):
			sidebar.add_entries()
		self.assertEqual(len(self.site.errors), len(sidebar.ENTRIES))
		self.assertEqual([doc.calls for doc in self.site.made], [[]] * len(sidebar.ENTRIES))


if __name__ == "__main__":
	unittest.main()
