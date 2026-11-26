"""Puts a Business Rules shortcut on the Home workspace, after every migrate.

Frappe shows a shortcut to a page only to those who may open the page, so only System
Managers see it (business_rules.json). ERPNext may replace Home when it updates, so the
shortcut is put back after each migrate. It never stops a migrate.

The sidebar entry is in custom_app/sidebar.py, with the app's other entries.
"""

import frappe

from custom_app import sidebar

WORKSPACE = "Home"
LABEL = "Business Rules"
PAGE = "business-rules"
BLOCK_ID = "bizrules01"


def add_to_home():
	"""after_migrate: the shortcut on Home, once."""
	try:
		if not frappe.db.exists("Workspace", WORKSPACE):
			return
		home = frappe.get_doc("Workspace", WORKSPACE)
		if add_shortcut(home):
			home.flags.ignore_permissions = True
			home.save()
	except Exception:
		frappe.log_error(title="Business Rules shortcut not added to Home")


def add_shortcut(home):
	"""Add the shortcut and its block after Home's last shortcut. False when both are there already."""
	return sidebar.add_shortcut(home, "Page", PAGE, LABEL, BLOCK_ID)
