# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class BudgetSettings(Document):
	def validate(self):
		self.check_who_changes_inter_department_transfer()

	def check_who_changes_inter_department_transfer(self):
		"""Only a System Manager turns Inter Department Transfer on or off.

		Finance Approvers edit the other settings, so the rule is on this one field.
		"""
		before = self.get_doc_before_save()
		was_allowed = bool(before and before.get("allow_inter_department_transfer"))
		if bool(self.get("allow_inter_department_transfer")) == was_allowed:
			return
		if "System Manager" not in frappe.get_roles():
			frappe.throw(
				_("Only a System Manager can turn Inter Department Transfer on or off."),
				frappe.PermissionError,
				title=_("Not Allowed"),
			)
