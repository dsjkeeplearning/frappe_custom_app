import frappe

from custom_app.business_rules import catalogue, site

# Only a System Manager sees the rules. The page's own roles say the same (test_rules_page).
READERS = ["System Manager"]


@frappe.whitelist()
def get():
	"""Every rule in plain words, and what was set up on this site as it is now."""
	only_readers()
	return {**catalogue.page(), "site": site.live()}


def only_readers():
	"""Like frappe.only_for, but it also holds while tests run, so a test can prove it."""
	if frappe.session.user != "Administrator" and not set(READERS) & set(frappe.get_roles()):
		raise frappe.PermissionError
