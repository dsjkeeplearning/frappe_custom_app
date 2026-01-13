# Copyright (c) 2026, . and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MasterBudget(Document):
	def validate(self):
		self.validate_duplicate_departments()
		self.validate_budget_total()

	def validate_duplicate_departments(self):
		"""Check if any department is repeated in the department_budget table"""
		departments = []
		
		for row in self.department_budget:
			if row.department:
				if row.department in departments:
					frappe.throw(
						_("Department {0} is repeated in row {1}. Each department should appear only once.").format(
							frappe.bold(row.department), 
							row.idx
						)
					)
				departments.append(row.department)

	def validate_budget_total(self):
		"""Check if total of department budgets does not exceed total_budget"""
		total_department_budget = 0
		
		for row in self.department_budget:
			if row.budget:
				total_department_budget += row.budget
		
		if self.total_budget and total_department_budget > self.total_budget:
			frappe.throw(
				_("Total of department budgets ({0}) cannot be greater than Total Budget ({1})").format(
					frappe.bold(frappe.format_value(total_department_budget, {'fieldtype': 'Currency'})),
					frappe.bold(frappe.format_value(self.total_budget, {'fieldtype': 'Currency'}))
				)
			)