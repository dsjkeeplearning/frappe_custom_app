"""A file attached to EOMS Docs is downloaded only by System Managers.

Frappe lets anyone who can read a record download its private files. Everyone reads EOMS
Docs, so for its files this is narrowed on each way Frappe hands a file out:
- /private/files/... and download_file, which ask File.is_downloadable (CustomFile)
- the zip of several files (zip_files)
- the File record itself (has_permission)
Readers see the pages as images instead (eoms_docs.py::get_page).
"""

import frappe
from frappe.core.api.file import zip_files as frappe_zip_files
from frappe.core.doctype.file.file import File

PROTECTED = ("EOMS Docs",)
DOWNLOADERS = ["System Manager"]


def may_download(file, user=None):
	"""False for a file attached to EOMS Docs, unless the user is a System Manager."""
	user = user or frappe.session.user
	if file.get("attached_to_doctype") not in PROTECTED:
		return True
	return user == "Administrator" or bool(set(DOWNLOADERS) & set(frappe.get_roles(user)))


class CustomFile(File):
	def is_downloadable(self):
		return may_download(self) and super().is_downloadable()


def has_permission(doc, ptype=None, user=None, debug=False):
	"""hooks.py has_permission for File. None leaves the answer to Frappe."""
	return None if may_download(doc, user) else False


@frappe.whitelist()
def zip_files(files):
	"""Frappe's zip of several files, without the EOMS Docs files the user may not download."""
	kept = [
		name
		for name in frappe.parse_json(files)
		if isinstance(name, str)
		and may_download(
			frappe._dict(attached_to_doctype=frappe.db.get_value("File", name, "attached_to_doctype"))
		)
	]
	return frappe_zip_files(frappe.as_json(kept))
