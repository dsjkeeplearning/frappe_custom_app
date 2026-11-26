# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

"""EOMS Docs: documents everyone reads in the Desk, page by page, and only System Managers change.

The file never reaches a reader. The server draws each page as an image when the reader
scrolls to it (get_pages, get_page), and only System Managers may download a file attached
to EOMS Docs (overrides/file.py). A Word file is turned into a PDF on save, by LibreOffice,
and its pages are drawn from that PDF.

Drawing needs pypdfium2 (pyproject.toml). Word files also need LibreOffice on the server.
"""

import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint
from werkzeug.wrappers import Response

# How each allowed file starts, so a file renamed to look like one is refused.
KINDS = {
	".pdf": b"%PDF-",
	".docx": b"PK\x03\x04",
	".doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
}
WORD = (".doc", ".docx")

# The widths a page is drawn at, in pixels. A request is rounded up to one of them, so the
# browser can keep a drawn page, and the server never draws a page wider than the last.
WIDTHS = (480, 720, 960, 1280, 1600)
TALLEST = 4000  # pixels: a very long page is drawn narrower rather than taller
QUALITY = 70  # WebP quality: text stays sharp at a fraction of the size of PNG
KEEP_FOR = 86400  # seconds the browser keeps a page

# PDFium may not run in two threads of one process at once.
PDFIUM = threading.Lock()


class EOMSDocs(Document):
	def validate(self):
		self.check_upload()

	def on_update(self):
		if extension(self.upload_doc) in WORD:
			if self.has_value_changed("upload_doc") or not self.preview_pdf:
				self.make_preview()
		elif self.preview_pdf:
			self.drop_preview()

	def check_upload(self):
		"""A private PDF, DOC or DOCX file, whose content is of that kind. Its name becomes the title."""
		url = self.upload_doc or ""
		kind = extension(url)
		if kind not in KINDS:
			frappe.throw(_("Upload Doc must be a PDF, DOC or DOCX file."), title=_("File type not allowed"))
		if not url.startswith("/private/files/"):
			frappe.throw(
				_("Upload Doc must be a private file. Remove it and upload it again with Private ticked."),
				title=_("File is public"),
			)
		file = file_of(url)
		if not file:
			frappe.throw(_("The uploaded file was not found. Upload it again."))
		with open(file.get_full_path(), "rb") as stored:
			start = stored.read(len(KINDS[kind]))
		if start != KINDS[kind]:
			frappe.throw(
				_("{0} is not a real {1} file.").format(file.file_name, kind[1:].upper()),
				title=_("File type not allowed"),
			)
		self.document_name = file.file_name

	def make_preview(self):
		"""The PDF that the pages of a Word file are drawn from, kept as a private file of this record."""
		source = file_of(self.upload_doc)
		old = self.preview_pdf
		preview = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{Path(source.file_name).stem}.pdf",
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"attached_to_field": "preview_pdf",
				"is_private": 1,
				"content": to_pdf(source.get_full_path()),
			}
		)
		preview.insert(ignore_permissions=True)
		self.db_set("preview_pdf", preview.file_url, update_modified=False)
		if old and old != preview.file_url:
			delete_files(self, old)

	def drop_preview(self):
		delete_files(self, self.preview_pdf)
		self.db_set("preview_pdf", None, update_modified=False)


def extension(url):
	return os.path.splitext((url or "").split("?")[0])[1].lower()


def file_of(url):
	"""The File record of a file URL, or None."""
	name = frappe.db.get_value("File", {"file_url": url}, "name") if url else None
	return frappe.get_doc("File", name) if name else None


def delete_files(doc, url):
	for name in frappe.get_all(
		"File",
		filters={"file_url": url, "attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
		pluck="name",
	):
		frappe.delete_doc("File", name, ignore_permissions=True)


def to_pdf(path):
	"""A Word file as PDF bytes, made by LibreOffice. Refused with a message when it cannot be made."""
	office = shutil.which("soffice") or shutil.which("libreoffice")
	if not office:
		frappe.throw(
			_(
				"Word files are shown through a PDF made by LibreOffice, which is not installed on the "
				"server. Upload the document as PDF, or ask for LibreOffice to be installed."
			),
			title=_("LibreOffice needed"),
		)
	with tempfile.TemporaryDirectory() as folder:
		folder = Path(folder)
		source = folder / f"document{Path(path).suffix.lower()}"
		shutil.copyfile(path, source)
		command = [
			office,
			f"-env:UserInstallation={(folder / 'profile').as_uri()}",
			"--headless",
			"--norestore",
			"--convert-to",
			"pdf",
			"--outdir",
			str(folder),
			str(source),
		]
		try:
			done = subprocess.run(command, capture_output=True, timeout=180)
			failed = done.returncode != 0
			detail = done.stderr
		except subprocess.TimeoutExpired:
			failed, detail = True, b"LibreOffice took longer than 180 seconds"
		pdf = folder / "document.pdf"
		if failed or not pdf.is_file():
			frappe.log_error(
				title="EOMS Docs: Word file not turned into PDF",
				message=(detail or b"").decode(errors="replace")[-2000:],
			)
			frappe.throw(
				_("The Word file could not be turned into PDF. Check that it opens, or upload a PDF.")
			)
		return pdf.read_bytes()


# The viewer -----------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_pages(name):
	"""The size of each page in points, so the viewer can lay out every page before drawing any."""
	path = readable_pdf(name)
	with PDFIUM:
		pdf = open_pdf(path)
		try:
			sizes = [pdf.get_page_size(i) for i in range(len(pdf))]
		finally:
			pdf.close()
	return {
		"pages": [[round(width, 2), round(height, 2)] for width, height in sizes],
		"widths": WIDTHS,
		"version": version(path),
	}


@frappe.whitelist(methods=["GET"])
def get_page(name, page, width=WIDTHS[2], v=None):
	"""One page as a WebP image. Never the file. `v` only tells the browser when the file changed."""
	path = readable_pdf(name)
	page, width = cint(page), fit(width)
	with PDFIUM:
		pdf = open_pdf(path)
		try:
			if not 0 <= page < len(pdf):
				raise frappe.DoesNotExistError(_("Page {0} not found").format(page + 1))
			sheet = pdf[page]
			try:
				points_wide, points_high = sheet.get_size()
				scale = min(width / points_wide, TALLEST / points_high)
				image = sheet.render(scale=scale).to_pil()
			finally:
				sheet.close()
		finally:
			pdf.close()
	out = io.BytesIO()
	image.convert("RGB").save(out, "WEBP", quality=QUALITY)
	return Response(
		out.getvalue(),
		mimetype="image/webp",
		headers={"Cache-Control": f"private, max-age={KEEP_FOR}", "Content-Disposition": "inline"},
	)


def readable_pdf(name):
	"""The path of the PDF to draw from, after checking the user may read the record."""
	frappe.has_permission("EOMS Docs", "read", doc=name, throw=True)
	doc = frappe.get_doc("EOMS Docs", name)
	url = doc.preview_pdf if extension(doc.upload_doc) in WORD else doc.upload_doc
	file = file_of(url)
	if not file:
		raise frappe.DoesNotExistError(_("This document has no pages to show yet."))
	return file.get_full_path()


def open_pdf(path):
	try:
		import pypdfium2
	except ImportError:
		frappe.throw(_("The document viewer needs pypdfium2 on the server. Run: bench setup requirements"))
	return pypdfium2.PdfDocument(path)


def fit(width):
	"""The drawn width for a requested one: the next of WIDTHS up, at most the widest."""
	return next((w for w in WIDTHS if w >= cint(width)), WIDTHS[-1])


def version(path):
	"""Changes when the file changes, so the browser does not show pages it kept from the old file."""
	stat = os.stat(path)
	return hashlib.sha1(f"{path}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:12]
