# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

"""Training Videos and User Manual: one topic each, with a video, a user manual or both.

Everyone who reads a topic watches its video and reads its manual on the form, and only
System Managers add, change or delete a topic (RULES.md TR). Roles Applicable names whom a
topic is for, so the list can be filtered by it. It does not limit who reads the topic.

Both files are private. Frappe hands a private file only to someone signed in who may read
the record it is attached to, and answers range requests, so a video can be skipped through.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from custom_app.custom_app.doctype.eoms_docs.eoms_docs import extension, file_of

# Each file field: its label, what it takes, and where and how a file of each kind starts,
# so a file renamed to look like one is refused.
FILES = {
	"video": ("Video", "an MP4 or WebM", {".mp4": (4, b"ftyp"), ".webm": (0, b"\x1a\x45\xdf\xa3")}),
	"manual": ("User Manual", "a PDF", {".pdf": (0, b"%PDF-")}),
}


class TrainingVideosandUserManual(Document):
	def validate(self):
		if not (self.video or self.manual):
			frappe.throw(_("Attach a video, a user manual or both."), title=_("Nothing to show"))
		for fieldname in FILES:
			if self.get(fieldname):
				check_file(self, fieldname)


def check_file(doc, fieldname):
	"""A private file of a kind the field takes, whose content is of that kind."""
	label, takes, kinds = FILES[fieldname]
	url = doc.get(fieldname)
	kind = extension(url)
	if kind not in kinds:
		frappe.throw(_("{0} must be {1} file.").format(_(label), _(takes)), title=_("File type not allowed"))
	if not url.startswith("/private/files/"):
		frappe.throw(
			_("{0} must be a private file. Remove it and upload it again with Private ticked.").format(
				_(label)
			),
			title=_("File is public"),
		)
	file = file_of(url)
	if not file:
		frappe.throw(_("The {0} file was not found. Upload it again.").format(_(label)))
	offset, start = kinds[kind]
	with open(file.get_full_path(), "rb") as stored:
		head = stored.read(offset + len(start))
	if head[offset:] != start:
		frappe.throw(
			_("{0} is not a real {1} file.").format(file.file_name, kind[1:].upper()),
			title=_("File type not allowed"),
		)
