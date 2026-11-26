"""EOMS Docs: who reads and changes them, the upload, the page viewer and its sidebar entry (RULES.md ED).

No site or database is needed, see fake_site. The viewer tests draw a real PDF, so they need
pypdfium2, as the site does:

	python -m unittest custom_app.tests.test_rules_eoms
	bench --site <site> run-tests --skip-before-tests --module custom_app.tests.test_rules_eoms
"""

import inspect
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from frappe.core.doctype.file.file import File

from custom_app import hooks, sidebar
from custom_app.custom_app.doctype.eoms_docs import eoms_docs
from custom_app.overrides import file as file_override
from custom_app.tests.fake_site import Doc, SiteTest

DOCTYPES = Path(eoms_docs.__file__).parent.parent
EOMS = "EOMS Docs"
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


def meta(folder):
	return json.loads((DOCTYPES / folder / f"{folder}.json").read_text(encoding="utf-8"))


def fields(folder):
	return {f["fieldname"]: f for f in meta(folder)["fields"]}


def readers(folder="eoms_docs"):
	return {p["role"] for p in meta(folder)["permissions"] if p.get("read") and not p.get("permlevel")}


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


def a_pdf(*sizes):
	import pypdfium2

	pdf = pypdfium2.PdfDocument.new()
	for width, height in sizes:
		pdf.new_page(width, height)
	out = io.BytesIO()
	pdf.save(out)
	return out.getvalue()


class Record(Doc):
	"""An EOMS Docs record on the fake site, with the controller's own methods."""

	validate = eoms_docs.EOMSDocs.validate
	on_update = eoms_docs.EOMSDocs.on_update
	check_upload = eoms_docs.EOMSDocs.check_upload
	make_preview = eoms_docs.EOMSDocs.make_preview
	drop_preview = eoms_docs.EOMSDocs.drop_preview


class EomsTest(SiteTest):
	def setUp(self):
		super().setUp()
		folder = tempfile.TemporaryDirectory()
		self.addCleanup(folder.cleanup)
		self.folder = Path(folder.name)
		self.stored = {}
		self.patch(f"{eoms_docs.__name__}.file_of", lambda url: self.stored.get(url))

	def store(self, name, content, private=True):
		"""A file on disk, and its URL."""
		path = self.folder / name
		path.write_bytes(content)
		url = f"/{'private/' if private else ''}files/{name}"
		self.stored[url] = StoredFile(path)
		return url

	def read_as(self, user, *roles):
		"""Log in, with Frappe's read check following the roles of eoms_docs.json."""
		self.log_in(user, *roles)

		def has_permission(doctype, ptype="read", doc=None, user=None, throw=False, **kwargs):
			allowed = bool(readers() & set(frappe.get_roles()))
			if not allowed and throw:
				raise frappe.PermissionError
			return allowed

		self.patch("frappe.has_permission", has_permission)


class TestWhoChanges(unittest.TestCase):
	def test_everyone_reads_and_only_system_managers_change(self):
		for folder in ("eoms_docs", "eoms_department", "eoms_sub_department"):
			rows = meta(folder)["permissions"]
			self.assertIn("Desk User", readers(folder), folder)
			for row in rows:
				changes = [right for right in CHANGES if row.get(right)]
				if row["role"] != "System Manager":
					self.assertEqual(changes, [], f"{folder}: {row['role']} may only read")
			self.assertTrue(
				any(
					r["role"] == "System Manager" and r.get("create") and r.get("write") and r.get("delete")
					for r in rows
				),
				folder,
			)
		# Frappe shows the New button only to roles that may create.
		self.assertEqual(
			{r["role"] for r in meta("eoms_docs")["permissions"] if r.get("create")}, {"System Manager"}
		)

	def test_only_system_managers_see_the_file_field(self):
		self.assertEqual(fields("eoms_docs")["upload_doc"]["permlevel"], 1)
		self.assertEqual(fields("eoms_docs")["preview_pdf"]["permlevel"], 1)
		self.assertEqual(
			{r["role"] for r in meta("eoms_docs")["permissions"] if r.get("permlevel") == 1},
			{"System Manager"},
		)

	def test_company_and_department_are_mandatory(self):
		f = fields("eoms_docs")
		self.assertEqual(
			{
				name: (f[name]["fieldtype"], f[name].get("options"), bool(f[name].get("reqd")))
				for name in ("company", "department", "sub_department", "upload_doc")
			},
			{
				"company": ("Link", "Company", True),
				"department": ("Link", "EOMS Department", True),
				"sub_department": ("Link", "EOMS Sub Department", False),
				"upload_doc": ("Attach", None, True),
			},
		)

	def test_departments_hold_only_a_name(self):
		for folder, name, field in (
			("eoms_department", "EOMS Department", "department_name"),
			("eoms_sub_department", "EOMS Sub Department", "sub_department_name"),
		):
			doctype = meta(folder)
			self.assertEqual((doctype["name"], doctype["autoname"]), (name, f"field:{field}"))
			self.assertEqual([f["fieldname"] for f in doctype["fields"]], [field])
			self.assertTrue(doctype["fields"][0]["reqd"] and doctype["fields"][0]["unique"])


class TestUpload(EomsTest):
	def doc(self, url, **values):
		return Record(EOMS, name="EOMS-DOC-00001", upload_doc=url, **values)

	def test_only_pdf_doc_or_docx_is_accepted(self):
		for name, content in (
			("a.pdf", b"%PDF-1.7"),
			("b.docx", b"PK\x03\x04rest"),
			("c.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"),
		):
			doc = self.doc(self.store(name, content))
			doc.validate()
			self.assertEqual(doc.document_name, name)
		for name in ("d.txt", "e.xlsx", "f.png", "g.pdf.exe", "no_extension"):
			self.assertRefused("must be a PDF, DOC or DOCX", self.doc(self.store(name, b"%PDF-")).validate)
		self.assertRefused("must be a PDF, DOC or DOCX", self.doc(None).validate)

	def test_the_file_must_be_private(self):
		doc = self.doc(self.store("a.pdf", b"%PDF-1.7", private=False))
		self.assertRefused("must be a private file", doc.validate)

	def test_a_renamed_file_is_refused(self):
		for name, content in (
			("a.pdf", b"PK\x03\x04"),
			("b.docx", b"%PDF-1.7"),
			("c.doc", b"PK\x03\x04"),
			("d.pdf", b""),
		):
			self.assertRefused("is not a real", self.doc(self.store(name, content)).validate)

	def making_files(self):
		"""File records get the URL Frappe would give them on insert."""
		get_doc = self.site.get_doc

		def made(doctype, name=None, *args, **kwargs):
			doc = get_doc(doctype, name, *args, **kwargs)
			if isinstance(doctype, dict) and doctype.get("doctype") == "File":
				doc.file_url = f"/private/files/{doc.file_name}"
			return doc

		self.patch("frappe.get_doc", made)

	def office(self, found=True, works=True):
		"""LibreOffice, as it answers on the server."""
		self.patch("shutil.which", lambda name: f"/usr/bin/{name}" if found and name == "soffice" else None)
		self.calls = []

		def run(command, **kwargs):
			self.calls.append(command)
			out = Path(command[command.index("--outdir") + 1])
			if works:
				(out / "document.pdf").write_bytes(b"%PDF-1.7 from Word")
			return subprocess.CompletedProcess(
				command, 0 if works else 1, b"", b"" if works else b"broken file"
			)

		self.patch("subprocess.run", run)

	def test_a_word_file_gets_a_pdf_to_show(self):
		self.making_files()
		self.office()
		old = "/private/files/old.pdf"
		self.site.add(
			"File", "old", file_url=old, attached_to_doctype=EOMS, attached_to_name="EOMS-DOC-00001"
		)
		doc = self.doc(self.store("Policy.docx", b"PK\x03\x04"), preview_pdf=old)
		doc.on_update()

		[preview] = [d for d in self.site.made if d.doctype == "File"]
		self.assertEqual(
			(
				preview.file_name,
				preview.is_private,
				preview.attached_to_doctype,
				preview.attached_to_field,
				preview.content,
			),
			("Policy.pdf", 1, EOMS, "preview_pdf", b"%PDF-1.7 from Word"),
		)
		self.assertEqual((preview.calls, doc.preview_pdf), (["insert"], "/private/files/Policy.pdf"))
		self.assertIn("--headless", self.calls[0])
		self.assertEqual(self.site.deleted, [("File", "old")])

	def test_without_libreoffice_a_word_file_is_refused(self):
		self.office(found=False)
		self.assertRefused("LibreOffice", self.doc(self.store("a.docx", b"PK\x03\x04")).on_update)
		self.office(works=False)
		self.assertRefused(
			"could not be turned into PDF", self.doc(self.store("b.doc", b"\xd0\xcf")).on_update
		)
		self.assertEqual(len(self.site.errors), 1)

	def test_a_pdf_is_shown_as_it_is(self):
		self.office()
		self.site.add(
			"File",
			"old",
			file_url="/private/files/old.pdf",
			attached_to_doctype=EOMS,
			attached_to_name="EOMS-DOC-00001",
		)
		doc = self.doc(self.store("a.pdf", b"%PDF-1.7"), preview_pdf="/private/files/old.pdf")
		doc.on_update()
		self.assertEqual((self.calls, doc.preview_pdf, self.site.deleted), ([], None, [("File", "old")]))


class TestViewer(EomsTest):
	def setUp(self):
		super().setUp()
		self.url = self.store("a.pdf", a_pdf((595, 842), (842, 595)))
		self.site.add(EOMS, "EOMS-DOC-00001", upload_doc=self.url)

	def test_pages_are_laid_out_before_they_are_drawn(self):
		self.read_as("reader@example.com", "Desk User")
		pages = eoms_docs.get_pages("EOMS-DOC-00001")
		self.assertEqual(pages["pages"], [[595, 842], [842, 595]])
		self.assertEqual(list(pages["widths"]), list(eoms_docs.WIDTHS))
		self.assertRegex(pages["version"], r"^[0-9a-f]{12}$")

	def test_a_page_is_sent_as_an_image_never_the_file(self):
		self.read_as("reader@example.com", "Desk User")
		response = eoms_docs.get_page("EOMS-DOC-00001", 1, 700)
		body = response.get_data()
		self.assertEqual(response.mimetype, "image/webp")
		self.assertEqual((body[:4], body[8:12]), (b"RIFF", b"WEBP"))
		self.assertNotIn(b"%PDF", body)
		self.assertIn("private", response.headers["Cache-Control"])
		from PIL import Image

		self.assertEqual(Image.open(io.BytesIO(body)).size, (720, 509))  # 595 x 842 points, 720 wide

	def test_page_widths_are_rounded_up_to_a_few(self):
		self.assertEqual(
			[eoms_docs.fit(w) for w in (1, 480, 481, 961, "1300", 99999)], [480, 480, 720, 1280, 1600, 1600]
		)

	def test_someone_who_cannot_read_the_record_sees_no_page(self):
		self.read_as("guest@example.com", "Guest")
		with self.assertRaises(frappe.PermissionError):
			eoms_docs.get_pages("EOMS-DOC-00001")
		with self.assertRaises(frappe.PermissionError):
			eoms_docs.get_page("EOMS-DOC-00001", 0)

	def test_a_page_that_is_not_there(self):
		self.read_as("reader@example.com", "Desk User")
		with self.assertRaises(frappe.DoesNotExistError):
			eoms_docs.get_page("EOMS-DOC-00001", 2)

	def test_a_word_file_is_shown_from_its_pdf(self):
		self.read_as("reader@example.com", "Desk User")
		self.site.add(
			EOMS, "EOMS-DOC-00002", upload_doc=self.store("b.docx", b"PK\x03\x04"), preview_pdf=self.url
		)
		self.assertEqual(len(eoms_docs.get_pages("EOMS-DOC-00002")["pages"]), 2)
		self.site.records[EOMS]["EOMS-DOC-00002"].preview_pdf = None
		with self.assertRaises(frappe.DoesNotExistError):
			eoms_docs.get_pages("EOMS-DOC-00002")

	def test_pages_load_only_when_scrolled_near(self):
		js = (DOCTYPES / "eoms_docs" / "eoms_docs.js").read_text(encoding="utf-8")
		self.assertIn("new IntersectionObserver", js)
		self.assertIn('attr("data-src"', js)
		# The only place a page's image is fetched is draw(), called when it scrolls near.
		self.assertEqual(js.count("img.src ="), 1)
		self.assertIn("get_page?", js)
		self.assertNotIn("upload_doc}", js)


class TestDownloads(SiteTest):
	def file(self, attached_to):
		file = object.__new__(file_override.CustomFile)
		file.__dict__.update(doctype="File", attached_to_doctype=attached_to, is_private=1)
		return file

	def test_readers_cannot_download_an_eoms_file(self):
		self.patch(f"{File.__module__}.File.is_downloadable", lambda self: True)
		for user, roles, may in (
			("reader@example.com", ("Desk User", "HR Manager", "Accounts Manager"), False),
			("manager@example.com", ("System Manager",), True),
		):
			self.log_in(user, *roles)
			self.assertEqual(self.file(EOMS).is_downloadable(), may, user)
		frappe.local.session.user = "Administrator"
		self.assertTrue(self.file(EOMS).is_downloadable())

	def test_files_of_other_records_follow_frappe(self):
		self.log_in("reader@example.com", "Desk User")
		for answer in (True, False):
			self.patch(f"{File.__module__}.File.is_downloadable", lambda self, a=answer: a)
			self.assertEqual(self.file("Material Request").is_downloadable(), answer)
		self.assertIsNone(
			file_override.has_permission(Doc("File", attached_to_doctype="Material Request"), "read")
		)

	def test_the_file_record_is_closed_to_readers(self):
		eoms_file = Doc("File", attached_to_doctype=EOMS)
		self.log_in("reader@example.com", "Desk User")
		for ptype in ("read", "write", "create", "delete", "share"):
			# False closes the record. None would leave it to Frappe, which opens it to readers.
			self.assertIs(file_override.has_permission(eoms_file, ptype), False)
		self.log_in("manager@example.com", "System Manager")
		self.assertIsNone(file_override.has_permission(eoms_file, "read"))

	def test_a_zip_leaves_out_eoms_files(self):
		zipped = []
		self.patch(
			f"{file_override.__name__}.frappe_zip_files", lambda files: zipped.append(json.loads(files))
		)
		self.site.add("File", "eoms", attached_to_doctype=EOMS)
		self.site.add("File", "other", attached_to_doctype="Material Request")
		self.log_in("reader@example.com", "Desk User")
		file_override.zip_files(json.dumps(["eoms", "other"]))
		self.log_in("manager@example.com", "System Manager")
		file_override.zip_files(json.dumps(["eoms", "other"]))
		self.assertEqual(zipped, [["other"], ["eoms", "other"]])

	def test_every_way_frappe_hands_out_a_file_is_covered(self):
		"""If Frappe changes how it hands out files, this fails, and overrides/file.py needs a look."""
		from frappe import handler
		from frappe.core.api import file as file_api
		from frappe.core.doctype.file import utils
		from frappe.utils import response

		self.assertIn("file.is_downloadable()", inspect.getsource(utils.find_file_by_url))
		self.assertIn("find_file_by_url(", inspect.getsource(response.download_private_file))
		self.assertIn("find_file_by_url(", inspect.getsource(handler.download_file))
		self.assertIn("File.zip_files(", inspect.getsource(file_api.zip_files))
		self.assertEqual(hooks.override_doctype_class["File"], "custom_app.overrides.file.CustomFile")
		self.assertEqual(
			hooks.override_whitelisted_methods["frappe.core.api.file.zip_files"],
			"custom_app.overrides.file.zip_files",
		)
		self.assertEqual(hooks.has_permission["File"], "custom_app.overrides.file.has_permission")
		self.assertTrue(issubclass(file_override.CustomFile, File))


class TestSidebar(SiteTest):
	ENTRY = "EOMS Docs Sidebar"

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

	def test_eoms_docs_goes_between_hr_and_vendor_and_assets(self):
		# As on the site: HR and Vendor & Assets share place 7.
		self.sidebar(
			("Accounting", 4, ""),
			("Payables", 5, "Accounting"),
			("HR", 7, ""),
			("Receivables", 7, "Accounting"),
			("Vendor & Assets", 7, ""),
			("Buying", 9, ""),
			("Recruitment", 14, "HR"),
			("Config Email", 35, ""),
		)
		sidebar.add_entries()
		entry = self.made()
		self.assertEqual(entry.calls, ["save"])
		self.assertEqual(self.top(entry)[:5], ["Accounting", "HR", self.ENTRY, "Vendor & Assets", "Buying"])
		self.assertEqual(
			(entry.sequence_id, self.site.records["Workspace"]["Vendor & Assets"].sequence_id), (7.5, 8)
		)

	def test_the_eoms_entry_opens_the_list_for_everyone(self):
		self.sidebar(("HR", 7, ""), ("Vendor & Assets", 8, ""))
		sidebar.add_entries()
		entry = self.made()
		# The sidebar links to the address of the title, the EOMS Docs list; the entry's own name has another.
		self.assertEqual(address(entry.title), address(meta("eoms_docs")["name"]))
		self.assertNotEqual(address(entry.label), address(entry.title))
		self.assertEqual((entry.roles or [], entry.module, entry.public), ([], None, 1))
		self.assertEqual(
			[(s.type, s.link_to, s.doc_view) for s in entry.shortcuts], [("DocType", EOMS, "List")]
		)

	def test_an_eoms_entry_in_place_moves_nothing(self):
		self.sidebar(("HR", 7, ""), ("Vendor & Assets", 7, ""), ("Buying", 9, ""))
		entry = self.site.add("Workspace", self.ENTRY, public=1, label=self.ENTRY)
		sidebar.add_entries()
		moved = self.site.records["Workspace"]["Vendor & Assets"].sequence_id
		cache = MagicMock()
		with patch("frappe.cache", cache):
			sidebar.add_entries()
		self.assertEqual((entry.calls, entry.sequence_id, moved), (["save"], 7.5, 8))
		cache.delete_key.assert_not_called()

		# Vendor & Assets dragged back up to HR's place: moved down again, the entry kept.
		self.site.records["Workspace"]["Vendor & Assets"].sequence_id = 7
		with patch("frappe.cache", cache):
			sidebar.add_entries()
		self.assertEqual(
			(entry.calls, self.site.records["Workspace"]["Vendor & Assets"].sequence_id), (["save"], 8)
		)
		cache.delete_key.assert_called_once_with("bootinfo")

	def test_without_hr_the_eoms_entry_goes_last(self):
		self.sidebar(("Buying", 9, ""), ("Vendor & Assets", 7, ""))
		sidebar.add_entries()
		self.assertEqual(self.made().sequence_id, 10)


if __name__ == "__main__":
	unittest.main()
