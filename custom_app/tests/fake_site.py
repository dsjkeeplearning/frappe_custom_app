"""A made-up site in memory, so the business rules can be tested without a database.

The rules' own code runs unchanged on the real Frappe library. Only what would
reach the database, send an email or ask who is logged in is replaced for the
length of one test, then put back. On a bench nothing is read from the site and
nothing is written to it, so these tests are safe on any site.
"""

import unittest
from datetime import date
from unittest.mock import patch

import frappe
from frappe.utils import getdate

MISSING = object()


class Doc:
	"""A document whose empty fields read as None, as they do on a form."""

	def __init__(self, doctype=None, **values):
		self.__dict__.update(values)
		self.doctype = doctype
		self.flags = frappe._dict()
		self.calls = []
		self.before = values.get("before")
		self.new = values.get("new", False)

	def __getattr__(self, field):
		if field.startswith("__"):
			raise AttributeError(field)
		return None

	def get(self, field, default=None):
		value = self.__dict__.get(field)
		return default if value is None else value

	def set(self, field, value):
		setattr(self, field, value)

	def append(self, field, row):
		rows = self.__dict__.setdefault(field, [])
		rows.append(Doc(**row))
		return rows[-1]

	def update(self, values):
		self.__dict__.update(values)

	def is_new(self):
		return self.new

	def get_doc_before_save(self):
		return self.before

	def has_value_changed(self, field):
		return self.before is None or self.before.get(field) != self.get(field)

	def add_comment(self, kind, text):
		self.calls.append(("comment", text))

	def db_set(self, field, value, **kwargs):
		setattr(self, field, value)

	def _did(self, what):
		self.calls.append(what)
		return self

	def insert(self, **kwargs):
		self.new = False
		return self._did("insert")

	def save(self, **kwargs):
		return self._did("save")

	def submit(self, **kwargs):
		self.docstatus = 1
		return self._did("submit")

	def cancel(self, **kwargs):
		self.docstatus = 2
		return self._did("cancel")


class FakeSite:
	"""Stands in for frappe.db and the frappe functions that read or write records."""

	def __init__(self):
		self.records = {}
		self.emails = []
		self.errors = []
		self.made = []
		self.deleted = []
		self.shares = []
		self.removed_shares = []
		self.queries = []
		self.answers = []
		self.roles = {}
		self.commits = 0

	# Set-up -----------------------------------------------------------------

	def add(self, doctype, name, **values):
		doc = Doc(doctype, **{"docstatus": 0, "name": name, **values})
		self.records.setdefault(doctype, {})[name] = doc
		return doc

	def answer(self, part_of_query, rows):
		"""What a SQL query that contains these words returns: rows, or a function of its values."""
		self.answers.append((part_of_query, rows))

	# frappe.db --------------------------------------------------------------

	def matching(self, doctype, filters):
		found = list(self.records.get(doctype, {}).values())
		if filters is None or filters == {}:
			return found
		if isinstance(filters, str):
			return [doc for doc in found if doc.name == filters]
		return [doc for doc in found if all(fits(doc.get(f), test) for f, test in filters.items())]

	def get_value(self, doctype, filters=None, fieldname="name", as_dict=False, **kwargs):
		docs = self.matching(doctype, filters)
		if not docs:
			return None
		if isinstance(fieldname, str):
			return docs[0].get(fieldname)
		row = [docs[0].get(field) for field in fieldname]
		return frappe._dict(zip(fieldname, row, strict=True)) if as_dict else tuple(row)

	def exists(self, doctype, filters=None, **kwargs):
		if isinstance(doctype, dict):
			filters = {f: v for f, v in doctype.items() if f != "doctype"}
			doctype = doctype["doctype"]
		return self.get_value(doctype, filters, "name")

	def set_value(self, doctype, name, field, value=None, **kwargs):
		values = field if isinstance(field, dict) else {field: value}
		for doc in self.matching(doctype, name):
			doc.update(values)

	def delete(self, doctype, filters=None):
		for doc in self.matching(doctype, filters):
			self.deleted.append((doctype, doc.name))
			del self.records[doctype][doc.name]

	def sql(self, query, values=None, as_dict=False, **kwargs):
		self.queries.append((query, values))
		for part, rows in self.answers:
			if part in query:
				rows = rows(values) if callable(rows) else rows
				return [frappe._dict(r) for r in rows] if as_dict else rows
		raise AssertionError(f"no answer for this query: {' '.join(query.split())}")

	def escape(self, value, percent=True):
		return "'" + str(value).replace("'", "\\'") + "'"

	def commit(self):
		self.commits += 1

	def rollback(self, **kwargs):
		pass

	def get_default(self, key):
		return None

	def has_column(self, doctype, column):
		return True

	# frappe.* ---------------------------------------------------------------

	def get_all(self, doctype, filters=None, fields=None, pluck=None, limit=None, **kwargs):
		if isinstance(filters, list):
			filters = {f: [op, v] for f, op, v in filters}
		docs = self.matching(doctype, filters)[:limit]
		if pluck:
			return [doc.get(pluck) for doc in docs]
		return [frappe._dict({field: doc.get(field) for field in fields or ["name"]}) for doc in docs]

	def get_doc(self, doctype, name=None, *args, **kwargs):
		if isinstance(doctype, dict):
			values = dict(doctype)
			doc = Doc(values.pop("doctype"), new=True, **values)
			self.made.append(doc)
			return doc
		docs = self.matching(doctype, name if name is not None else doctype)
		if not docs:
			raise frappe.DoesNotExistError(f"{doctype} {name} not found")
		return docs[0]

	def new_doc(self, doctype, **kwargs):
		doc = Doc(doctype, new=True, name=f"new {doctype}")
		self.made.append(doc)
		return doc

	def copy_doc(self, doc, **kwargs):
		copy = Doc(doc.doctype, **{k: v for k, v in doc.__dict__.items() if k not in ("calls", "flags", "doctype")})
		copy.new = True
		self.made.append(copy)
		return copy

	def get_cached_value(self, doctype, name, fieldname="name", **kwargs):
		return self.get_value(doctype, name, fieldname)

	def delete_doc(self, doctype, name, **kwargs):
		self.delete(doctype, name)

	def sendmail(self, **kwargs):
		self.emails.append(frappe._dict(kwargs))

	def log_error(self, *args, **kwargs):
		self.errors.append((args, kwargs))

	def get_roles(self, user=None):
		return self.roles.get(user or frappe.session.user, [])

	def add_docshare(self, doctype, name, user, **kwargs):
		self.shares.append((doctype, name, user, kwargs))

	def remove_share(self, doctype, name, user):
		self.removed_shares.append((doctype, name, user))


def fits(value, test):
	"""Whether a field's value passes a Frappe filter."""
	if not isinstance(test, list | tuple):
		return (value or "") == (test or "")
	op, wanted = test
	op = op.lower()
	if op == "in":
		return value in wanted
	if op == "not in":
		return value not in wanted
	if op == "!=":
		return value != wanted
	if op == "is":
		return bool(value) == (wanted == "set")
	if op == "like":
		return wanted.strip("%").lower() in str(value or "").lower()
	if op == "between":
		return value is not None and day(wanted[0]) <= day(value) <= day(wanted[1])
	if op in ("<", "<=", ">", ">="):
		if value is None:
			return False
		value, wanted = day(value), day(wanted)
		return {"<": value < wanted, "<=": value <= wanted, ">": value > wanted, ">=": value >= wanted}[op]
	if op == "=":
		return value == wanted
	raise AssertionError(f"the fake site does not know the filter {op}")


def day(value):
	return getdate(value) if isinstance(value, str | date) else value


class SiteTest(unittest.TestCase):
	"""One test on a site of its own, logged in as a made-up user."""

	user = "someone@example.com"

	def setUp(self):
		self.site = FakeSite()
		for name, value in {
			"db": self.site,
			"session": frappe._dict(user=self.user, data=frappe._dict()),
			"flags": frappe._dict(in_test=True, mute_messages=True),
			"lang": "en",
			"conf": frappe._dict(),
			"system_settings": frappe._dict(time_zone="Asia/Kolkata"),
			"message_log": [],
			"user_date_format": "dd-mm-yyyy",
			"request": None,
		}.items():
			self.set_local(name, value)

		for name in (
			"get_all",
			"get_doc",
			"new_doc",
			"copy_doc",
			"get_cached_value",
			"delete_doc",
			"sendmail",
			"log_error",
			"get_roles",
		):
			self.patch(f"frappe.{name}", getattr(self.site, name))
		self.patch("frappe.translate.get_all_translations", lambda lang: {})
		self.patch("frappe.get_value", self.site.get_value)
		self.patch("frappe.get_cached_doc", self.site.get_doc)
		self.patch("frappe.share.add_docshare", self.site.add_docshare)
		self.patch("frappe.share.remove", self.site.remove_share)
		self.patch("frappe.format", lambda value, *a, **k: str(value))
		self.patch("frappe.utils.get_url_to_form", lambda doctype, name: f"/app/{doctype}/{name}")
		self.patch("frappe.logger", lambda *a, **k: unittest.mock.MagicMock())

	def set_local(self, name, value):
		before = getattr(frappe.local, name, MISSING)
		setattr(frappe.local, name, value)
		self.addCleanup(
			lambda: delattr(frappe.local, name) if before is MISSING else setattr(frappe.local, name, before)
		)

	def patch(self, target, replacement):
		patcher = patch(target, replacement)
		patcher.start()
		self.addCleanup(patcher.stop)

	def log_in(self, user, *roles):
		frappe.local.session.user = user
		self.site.roles[user] = list(roles)

	def assertRefused(self, part_of_message, function, *args, **kwargs):
		"""The call is refused, with a message that contains these words."""
		with self.assertRaises(frappe.ValidationError) as refused:
			function(*args, **kwargs)
		self.assertIn(part_of_message, str(refused.exception))
