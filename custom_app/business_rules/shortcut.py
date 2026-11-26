"""Puts a Business Rules shortcut on the Home workspace, after every migrate.

Frappe shows a shortcut to a page only to those who may open the page, so only
System Managers see this one (business_rules.json). ERPNext may replace Home when
it updates, so the shortcut is put back after each migrate. It never stops a migrate.
"""

import json

import frappe

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
	changed = False
	if not any(s.type == "Page" and s.link_to == PAGE for s in home.shortcuts or []):
		home.append("shortcuts", {"type": "Page", "link_to": PAGE, "label": LABEL, "color": "Grey"})
		changed = True

	blocks = json.loads(home.content or "[]")
	if not any(b.get("type") == "shortcut" and b.get("data", {}).get("shortcut_name") == LABEL for b in blocks):
		shortcuts = [i for i, b in enumerate(blocks) if b.get("type") == "shortcut"]
		at = shortcuts[-1] + 1 if shortcuts else len(blocks)
		blocks.insert(at, {"id": BLOCK_ID, "type": "shortcut", "data": {"shortcut_name": LABEL, "col": 3}})
		home.content = json.dumps(blocks)
		changed = True

	return changed
