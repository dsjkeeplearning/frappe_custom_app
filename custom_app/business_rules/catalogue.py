"""Reads the rules in RULES.md and their plain words in plain.json.

No Frappe import, so the checks in test_rules_policy run without a bench.
"""

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "RULES.md"
PLAIN = HERE / "plain.json"

# The page's tabs, in the order money and people move, each with its groups of RULES.md.
TABS = [
	{"key": "budget", "label": "Budget", "groups": ["BC", "BU", "BR", "RP"]},
	{"key": "purchase", "label": "Request to order", "groups": ["PR", "SQ", "PO"]},
	{"key": "payment", "label": "Invoice, payment, claims", "groups": ["PI", "PE", "EC"]},
	{"key": "people", "label": "Attendance and payroll", "groups": ["AT", "LV", "PY"]},
	{"key": "access", "label": "Approvals and access", "groups": ["WF", "AC", "ED"]},
	{"key": "vendor", "label": "Vendors, emails, dashboards", "groups": ["VN", "EM", "DB"]},
	{"key": "site", "label": "On this site", "groups": ["ST"]},
	{"key": "trust", "label": "Keeping rules true", "groups": ["XX"]},
]

# What the Test column of a rule may say instead of naming tests.
NO_TEST = "-"
SEEN_ON_SITE = re.compile(r"seen on the site, \d{4}-\d{2}-\d{2}$")

ROW = re.compile(r"^\| ([A-Z]{2}-\d{2}) \|")


def rows(text=None):
	"""Each table row of RULES.md as (id, group, the other cells)."""
	group = None
	for line in (RULES.read_text(encoding="utf-8") if text is None else text).splitlines():
		if line.startswith("## "):
			group = line[3:].split(" ", 1)[0]
		elif ROW.match(line):
			cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
			yield cells[0], group, cells[1:]


def rules(text=None):
	"""Every rule, in order: id, group, text, the code that keeps it and the tests that prove it."""
	return [
		{"id": rid, "group": group, "text": cells[0], "home": code_names(cells[1]), "test": cells[2]}
		for rid, group, cells in rows(text)
	]


def code_names(cell):
	return re.findall(r"`([^`]+)`", cell)


def test_names(cell):
	return [] if cell == NO_TEST or SEEN_ON_SITE.match(cell) else cell.split(", ")


def fingerprint(text):
	"""Ten digits that change whenever the rule's words change."""
	return hashlib.sha1(text.encode()).hexdigest()[:10]


def plain_words():
	return json.loads(PLAIN.read_text(encoding="utf-8"))


def page():
	"""The rules as the page shows them: tabs, groups, and each rule in plain words."""
	words = plain_words()
	return {
		"tabs": TABS,
		"groups": words["groups"],
		"rules": [
			{
				"id": rule["id"],
				"group": rule["group"],
				"title": words["rules"][rule["id"]]["title"],
				"plain": words["rules"][rule["id"]]["plain"],
			}
			for rule in rules()
		],
	}

