"""Mark the reallocations made with the earlier form as Single Account.

The earlier form set one account's month to a new amount, so it had no Transfer
Type. Marking them keeps them readable and lets a draft among them still be
approved or rejected as before.
"""

import frappe


def execute():
	frappe.db.sql(
		"""
		update `tabBudget Reallocation`
		set reallocation_type = 'Single Account'
		where ifnull(reallocation_type, '') = ''
		"""
	)
