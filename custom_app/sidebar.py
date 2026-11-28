"""The entries this app puts in the Desk sidebar, after every migrate.

The v15 sidebar lists only workspaces, so each entry is a small workspace whose title is
the entry's label. The sidebar links to the address of the title, so the entry opens what
its title names: the Business Rules page, the Training Videos and User Manual list, the
EOMS Docs list. The workspace's own name is different, because a workspace with that name
would take the address over. Frappe checks the title against other names only outside a
migrate.

An entry has no module, or that module's forms would lead to it in their breadcrumbs. Its
roles hide it from other users; Frappe still lists every entry for Workspace Managers.

The sidebar can be reordered, so each entry is put back in its place after each migrate,
and saved only when something changed. When the two entries it goes between share one
place, the second is moved down to make room. An entry's place is worked out from the rest
of the sidebar, not from this app's other entries, so an entry right below another neither
pushes it along nor is pushed on each migrate. None of this ever stops a migrate.
"""

import json

import frappe
from frappe.utils import flt

from custom_app.custom_app.page.business_rules.business_rules import READERS

ENTRIES = (
	frappe._dict(
		name="Business Rules Sidebar",
		title="Business Rules",
		link_type="Page",
		link_to="business-rules",
		icon="list-alt",
		roles=tuple(READERS),
		after="Config Email",
		before=None,
		block="bizrules01",
	),
	frappe._dict(
		name="Training Videos Sidebar",
		title="Training Videos and User Manual",
		link_type="DocType",
		link_to="Training Videos and User Manual",
		icon="education",
		roles=(),  # every employee watches and reads them
		after="Business Rules Sidebar",
		before=None,
		block="training01",
	),
	frappe._dict(
		name="EOMS Docs Sidebar",
		title="EOMS Docs",
		link_type="DocType",
		link_to="EOMS Docs",
		icon="file",
		roles=(),  # everyone reads EOMS Docs
		after="HR",
		before="Vendor & Assets",
		block="eomsdocs01",
	),
)


def add_entries():
	"""after_migrate: every entry, in its place."""
	for spec in ENTRIES:
		try:
			put(spec)
		except Exception:
			frappe.log_error(title=f"{spec.title} not added to the sidebar")


def put(spec):
	if frappe.db.exists("Workspace", spec.name):
		entry = frappe.get_doc("Workspace", spec.name)
	else:
		entry = frappe.new_doc("Workspace")
		entry.label = spec.name
		entry.is_hidden = 0
	# Placed among the rest of the sidebar, not among this app's other entries, except the one it
	# goes after: otherwise an entry placed after another pushes it along on every migrate.
	ours = {other.name for other in ENTRIES} - {spec.after}
	others = [
		w
		for w in frappe.get_all(
			"Workspace",
			filters={"public": 1, "name": ["!=", spec.name]},
			fields=["name", "parent_page", "sequence_id"],
		)
		if w.name not in ours
	]
	parent, sequence, moves = place(others, spec.after, spec.before)
	for name, moved_to in moves.items():
		frappe.db.set_value("Workspace", name, "sequence_id", moved_to, update_modified=False)
	if set_entry(entry, spec, parent, sequence):
		entry.flags.ignore_permissions = True
		entry.save()  # also clears the sidebar's cache
	elif moves:
		frappe.cache.delete_key("bootinfo")


def set_entry(entry, spec, parent, sequence):
	"""Make the entry open its link, for its roles, at its place. False when it already does."""
	changed = False
	for field, value in {
		"title": spec.title,
		"public": 1,
		"module": None,
		"parent_page": parent,
		"sequence_id": sequence,
	}.items():
		if (entry.get(field) or None) != (value or None):
			entry.set(field, value)
			changed = True

	if not entry.icon:
		entry.icon = spec.icon
		changed = True

	if sorted(r.role for r in entry.roles or []) != sorted(spec.roles):
		entry.set("roles", [])
		for role in spec.roles:
			entry.append("roles", {"role": role})
		changed = True

	return add_shortcut(entry, spec.link_type, spec.link_to, spec.title, spec.block) or changed


def place(others, after, before=None):
	"""(parent, sequence id, {entry: new sequence id}): right after `after`, before `before`.

	Without `after`, last at the top. When `before` shares the place of `after`, or is above
	it, `before` is moved down to just before whatever followed it.
	"""
	anchor = find(others, after)
	parent = (anchor.parent_page or "") if anchor else ""
	siblings = [w for w in others if (w.parent_page or "") == parent]
	if not anchor:
		return parent, max((flt(w.sequence_id) for w in siblings), default=0) + 1, {}

	start = flt(anchor.sequence_id)
	following = find(siblings, before) if before else None
	if following and flt(following.sequence_id) <= start:
		later = [flt(w.sequence_id) for w in siblings if flt(w.sequence_id) > start and w is not following]
		moved = (start + min(later)) / 2 if later else start + 1
		return parent, (start + moved) / 2, {following.name: moved}

	later = [flt(w.sequence_id) for w in siblings if flt(w.sequence_id) > start]
	return parent, (start + min(later)) / 2 if later else start + 1, {}


def find(workspaces, name):
	return next((w for w in workspaces if w.name == name), None) if name else None


def add_shortcut(workspace, link_type, link_to, label, block_id):
	"""Add a shortcut and its block after the workspace's last shortcut. False when both are there."""
	changed = False
	if not any(s.type == link_type and s.link_to == link_to for s in workspace.shortcuts or []):
		workspace.append(
			"shortcuts",
			{
				"type": link_type,
				"link_to": link_to,
				"label": label,
				"color": "Grey",
				"doc_view": "List" if link_type == "DocType" else "",
			},
		)
		changed = True

	blocks = json.loads(workspace.content or "[]")
	if not any(
		b.get("type") == "shortcut" and b.get("data", {}).get("shortcut_name") == label for b in blocks
	):
		shortcuts = [i for i, b in enumerate(blocks) if b.get("type") == "shortcut"]
		at = shortcuts[-1] + 1 if shortcuts else len(blocks)
		blocks.insert(at, {"id": block_id, "type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
		workspace.content = json.dumps(blocks)
		changed = True

	return changed
