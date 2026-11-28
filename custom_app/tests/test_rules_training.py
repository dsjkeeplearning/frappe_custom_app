"""Training Videos and User Manual: who reads and changes them, the files, the players and the
sidebar entry (RULES.md TR).

No site or database is needed, see fake_site:

	python -m unittest custom_app.tests.test_rules_training
	bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_training
"""

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from custom_app import hooks, sidebar
from custom_app.custom_app.doctype.training_videos_and_user_manual import (
	training_videos_and_user_manual as training,
)
from custom_app.overrides import file as file_override
from custom_app.tests.fake_site import Doc, SiteTest

DOCTYPES = Path(training.__file__).parent.parent
TRAINING = "Training Videos and User Manual"
CHANGES = (
	"create",
	"write",
	"delete",
	"submit",
	"cancel",
	"amend",
	"import",
	"export",
	"share",
	"email",
	"print",
	"report",
)
# How each kind of file starts.
MP4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00"
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81"
PDF = b"%PDF-1.7\n"


def meta(folder="training_videos_and_user_manual"):
	return json.loads((DOCTYPES / folder / f"{folder}.json").read_text(encoding="utf-8"))


def fields(folder="training_videos_and_user_manual"):
	return {f["fieldname"]: f for f in meta(folder)["fields"]}


def script():
	folder = DOCTYPES / "training_videos_and_user_manual"
	return (folder / "training_videos_and_user_manual.js").read_text(encoding="utf-8")


def address(name):
	"""The /app address Frappe gives a name, as frappe.router.slug does."""
	return name.lower().replace(" ", "-")


class StoredFile:
	"""A File record whose content is on disk."""

	def __init__(self, path):
		self.path = Path(path)
		self.file_name = self.path.name

	def get_full_path(self):
		return str(self.path)


class Topic(Doc):
	"""A training topic on the fake site, with the controller's own check."""

	validate = training.TrainingVideosandUserManual.validate


class TestWhoReads(unittest.TestCase):
	def test_everyone_reads_and_only_system_managers_change(self):
		rows = meta()["permissions"]
		self.assertEqual({r["role"] for r in rows if r.get("read")}, {"System Manager", "Desk User"})
		for row in rows:
			if row["role"] != "System Manager":
				changes = [right for right in CHANGES if row.get(right)]
				self.assertEqual(changes, [], f"{row['role']} may only read")
		# Frappe shows the New button only to roles that may create.
		self.assertEqual({r["role"] for r in rows if r.get("create")}, {"System Manager"})
		self.assertTrue(
			any(r["role"] == "System Manager" and r.get("write") and r.get("delete") for r in rows)
		)

	def test_roles_applicable_does_not_limit_who_reads(self):
		roles, child = fields()["roles"], meta("training_topic_role")
		self.assertEqual(
			(roles["fieldtype"], roles["label"], roles["options"]),
			("Table MultiSelect", "Roles Applicable", child["name"]),
		)
		self.assertEqual(child["istable"], 1)
		self.assertEqual(
			[(f["fieldname"], f["fieldtype"], f["options"]) for f in child["fields"]],
			[("role", "Link", "Role")],
		)
		# Who reads comes from the permissions alone: nothing narrows them to a topic's roles.
		self.assertFalse(any(r.get("if_owner") or r.get("permlevel") for r in meta()["permissions"]))
		self.assertNotIn(TRAINING, hooks.has_permission)
		self.assertNotIn(TRAINING, getattr(hooks, "permission_query_conditions", {}))
		self.assertFalse(roles.get("reqd"))


class FileTest(SiteTest):
	def setUp(self):
		super().setUp()
		folder = tempfile.TemporaryDirectory()
		self.addCleanup(folder.cleanup)
		self.folder = Path(folder.name)
		self.stored = {}
		self.patch(f"{training.__name__}.file_of", lambda url: self.stored.get(url))

	def store(self, name, content, private=True):
		"""A file on disk, and its URL."""
		path = self.folder / name
		path.write_bytes(content)
		url = f"/{'private/' if private else ''}files/{name}"
		self.stored[url] = StoredFile(path)
		return url

	def topic(self, **files):
		return Topic(
			TRAINING,
			name="TRN-00001",
			title="Raise a purchase request",
			sidebar_section="Expense & Request",
			**files,
		)


class TestFiles(FileTest):
	def test_a_topic_needs_a_video_or_a_manual(self):
		self.assertEqual({n for n, f in fields().items() if f.get("reqd")}, {"title", "sidebar_section"})
		self.assertRefused("Attach a video, a user manual or both", self.topic().validate)
		video, manual = self.store("a.mp4", MP4), self.store("a.pdf", PDF)
		for files in ({"video": video}, {"manual": manual}, {"video": video, "manual": manual}):
			self.topic(**files).validate()

	def test_only_mp4_or_webm_video_and_pdf_manual_are_accepted(self):
		self.topic(video=self.store("a.mp4", MP4)).validate()
		self.topic(video=self.store("b.webm", WEBM)).validate()
		self.topic(manual=self.store("c.PDF", PDF)).validate()
		for name in ("d.mov", "e.avi", "f.mkv", "g.mp4.exe", "h.pdf", "no_extension"):
			video = self.store(name, MP4)
			self.assertRefused("Video must be an MP4 or WebM file", self.topic(video=video).validate)
		for name in ("i.docx", "j.mp4", "k.pdf.exe"):
			manual = self.store(name, PDF)
			self.assertRefused("User Manual must be a PDF file", self.topic(manual=manual).validate)
		# The upload box offers the same kinds.
		kinds = {field: sorted(takes[2]) for field, takes in training.FILES.items()}
		self.assertEqual(kinds, {"video": [".mp4", ".webm"], "manual": [".pdf"]})
		self.assertIn('const UPLOADS = { video: [".mp4", ".webm"], manual: [".pdf"] };', script())

	def test_the_files_must_be_private(self):
		video = self.store("a.mp4", MP4, private=False)
		self.assertRefused("Video must be a private file", self.topic(video=video).validate)
		manual = self.store("a.pdf", PDF, private=False)
		self.assertRefused("User Manual must be a private file", self.topic(manual=manual).validate)
		self.assertEqual(meta()["make_attachments_public"], 0)
		self.assertIn("make_attachments_public: false,", script())
		self.assertIn("allow_toggle_private: false,", script())

	def test_a_renamed_file_is_refused(self):
		for field, name, content in (
			("video", "a.mp4", PDF),
			("video", "b.webm", MP4),
			("manual", "c.pdf", MP4),
			("video", "d.mp4", b"ftyp"),  # an MP4 says ftyp from its fifth byte
		):
			upload = self.store(name, content)
			self.assertRefused(f"{name} is not a real", self.topic(**{field: upload}).validate)
		self.assertRefused("file was not found", self.topic(video="/private/files/gone.mp4").validate)


class TestPlayers(SiteTest):
	def test_the_form_plays_the_video_and_shows_the_manual(self):
		js = script()
		self.assertIn('<video class="training-video" controls preload="metadata" playsinline>', js)
		self.assertIn('$(`<iframe class="training-manual"></iframe>`).attr({ src: url', js)
		self.assertIn("Open the manual in a new tab", js)
		# Only a file of the site is shown, and each player only when its file is there.
		self.assertIn("const FILE_URL = /^\\/(private\\/)?files\\//;", js)
		self.assertEqual(
			(fields()["video_player"]["depends_on"], fields()["manual_viewer"]["depends_on"]),
			("video", "manual"),
		)
		# A video left playing is paused when the user moves away.
		self.assertIn('frappe.router.on("change"', js)
		self.assertIn("video.pause()", js)

	def test_readers_get_the_files_of_a_topic(self):
		from frappe.core.doctype.file import file as frappe_file
		from frappe.utils import response

		self.assertNotIn(TRAINING, file_override.PROTECTED)
		topic_file = Doc("File", attached_to_doctype=TRAINING, attached_to_name="TRN-00001", is_private=1)
		self.log_in("reader@example.com", "Desk User")
		self.assertTrue(file_override.may_download(topic_file))
		# None leaves it to Frappe, which hands a private file to whoever may read its record.
		self.assertIsNone(file_override.has_permission(topic_file, "read"))
		self.assertIn('ref_doc.has_permission("read"', inspect.getsource(frappe_file.has_permission))
		# To nobody signed out, and in pieces, so a video can be skipped through.
		self.assertIn('frappe.session.user == "Guest"', inspect.getsource(response.download_private_file))
		self.assertIn('"Accept-Ranges"', inspect.getsource(response.send_private_file))


class TestSidebar(SiteTest):
	ENTRY = "Training Videos Sidebar"
	RULES = "Business Rules Sidebar"

	def sidebar(self, *entries):
		for name, sequence, parent in entries:
			self.site.add("Workspace", name, public=1, sequence_id=sequence, parent_page=parent)

	def made(self):
		[entry] = [doc for doc in self.site.made if doc.label == self.ENTRY]
		return entry

	def top(self, entry):
		"""The top of the sidebar in order, with the entry."""
		listed = [w for w in self.site.records["Workspace"].values() if not w.parent_page] + [entry]
		return [w.label or w.name for w in sorted(listed, key=lambda w: w.sequence_id)]

	def test_training_goes_right_below_business_rules(self):
		# As on the site: Business Rules right below Config Email.
		self.sidebar(
			("Build", 33, ""),
			("Config Email", 35, ""),
			(self.RULES, 35.5, ""),
			("Tax", 35.7, "Payroll"),
			("Later", 36, ""),
		)
		sidebar.add_entries()
		entry = self.made()
		self.assertEqual(entry.calls, ["save"])
		self.assertEqual(self.top(entry), ["Build", "Config Email", self.RULES, self.ENTRY, "Later"])
		self.assertEqual((entry.parent_page or "", entry.sequence_id), ("", 35.75))

	def test_the_training_entry_opens_the_list_for_everyone(self):
		self.sidebar(("Config Email", 35, ""), (self.RULES, 36, ""))
		sidebar.add_entries()
		entry = self.made()
		# The sidebar links to the address of the title, the list; the entry's own name has another.
		self.assertEqual(address(entry.title), address(meta()["name"]))
		self.assertNotEqual(address(entry.label), address(entry.title))
		self.assertEqual((entry.roles or [], entry.module, entry.public), ([], None, 1))
		self.assertEqual(
			[(s.type, s.link_to, s.doc_view) for s in entry.shortcuts], [("DocType", TRAINING, "List")]
		)
		self.assertIn(TRAINING, entry.content)

	def test_two_entries_in_a_row_stay_put(self):
		self.sidebar(("Config Email", 35, ""), ("Later", 36, ""))
		rules = self.site.add("Workspace", self.RULES, public=1, label=self.RULES)
		entry = self.site.add("Workspace", self.ENTRY, public=1, label=self.ENTRY)
		for _migrate in range(4):
			sidebar.add_entries()
		# Each is placed among the rest of the sidebar, not the other: neither pushes the other along.
		self.assertEqual((rules.sequence_id, entry.sequence_id), (35.5, 35.75))
		self.assertEqual((rules.calls, entry.calls), (["save"], ["save"]))

	def test_without_business_rules_the_training_entry_goes_last(self):
		self.sidebar(("Build", 33, ""), ("Tax", 38, "Payroll"))
		with patch.object(sidebar, "ENTRIES", tuple(e for e in sidebar.ENTRIES if e.name != self.RULES)):
			sidebar.add_entries()
		self.assertEqual((self.made().parent_page or "", self.made().sequence_id), ("", 34))


if __name__ == "__main__":
	unittest.main()
