"""Puts Business Rules on the Home workspace and in the sidebar, after every migrate.

Home: a shortcut after Home's last shortcut. Frappe shows a shortcut to a page only to
those who may open the page, so only System Managers see it (business_rules.json).

Sidebar: an entry right below Config Email that opens the page. The v15 sidebar lists
only workspaces, so the entry is a small workspace for System Managers, titled Business
Rules. Its own name is different: a workspace named Business Rules would take the page's
address, while the sidebar links to the address of the title, which is the page. It has no
module, or that module's forms would lead to it in their breadcrumbs. Frappe also lists
every entry for Workspace Managers; the page still refuses them if they are not System
Managers. Frappe checks the title against the page's name only outside a migrate.

ERPNext may replace Home when it updates, and the sidebar can be reordered, so both are
put back after each migrate. Neither ever stops a migrate.
"""

import json

import frappe
from frappe.utils import flt

from custom_app.custom_app.page.business_rules.business_rules import READERS

WORKSPACE = "Home"
LABEL = "Business Rules"
PAGE = "business-rules"
BLOCK_ID = "bizrules01"

SIDEBAR = "Business Rules Sidebar"
AFTER = "Config Email"
ICON = "list-alt"


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


def add_to_sidebar():
	"""after_migrate: the sidebar entry, right below Config Email. Saved only when something changed."""
	try:
		if frappe.db.exists("Workspace", SIDEBAR):
			entry = frappe.get_doc("Workspace", SIDEBAR)
		else:
			entry = frappe.new_doc("Workspace")
			entry.label = SIDEBAR
			entry.is_hidden = 0
		others = frappe.get_all(
			"Workspace",
			filters={"public": 1, "name": ["!=", SIDEBAR]},
			fields=["name", "parent_page", "sequence_id"],
		)
		if set_entry(entry, others):
			entry.flags.ignore_permissions = True
			entry.save()
	except Exception:
		frappe.log_error(title="Business Rules not added to the sidebar")


def set_entry(entry, others):
	"""Make the entry open the page, for System Managers, below Config Email. False when it already does."""
	parent, sequence = place(others)
	changed = False
	for field, value in {
		"title": LABEL,
		"public": 1,
		"module": None,
		"parent_page": parent,
		"sequence_id": sequence,
	}.items():
		if (entry.get(field) or None) != (value or None):
			entry.set(field, value)
			changed = True

	if not entry.icon:
		entry.icon = ICON
		changed = True

	if sorted(r.role for r in entry.roles or []) != sorted(READERS):
		entry.set("roles", [])
		for role in READERS:
			entry.append("roles", {"role": role})
		changed = True

	return add_shortcut(entry) or changed


def place(others):
	"""(parent, sequence id) right after Config Email among its siblings; last at the top when it is gone."""
	after = next((w for w in others if w.name == AFTER), None)
	parent = (after.parent_page or "") if after else ""
	siblings = [flt(w.sequence_id) for w in others if (w.parent_page or "") == parent]
	if not after:
		return parent, max(siblings, default=0) + 1
	start = flt(after.sequence_id)
	later = [s for s in siblings if s > start]
	return parent, (start + min(later)) / 2 if later else start + 1
