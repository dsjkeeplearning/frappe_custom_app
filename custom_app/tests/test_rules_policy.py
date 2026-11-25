"""The rules, their plain words, the code and the tests agree (RULES.md XX).

These read the repository only, so they run anywhere:

	python -m unittest custom_app.tests.test_rules_policy
"""

import ast
import json
import re
import unittest
from pathlib import Path

from custom_app.business_rules import catalogue

APP = Path(__file__).resolve().parents[1]
PAGE_SCRIPT = APP / "custom_app" / "page" / "business_rules" / "business_rules.js"
HOOKED = re.compile(r"custom_app(?:\.\w+){2,}")

# What plain words may not hold: code names, marks, and another rule's ID except as "(see XX-00)".
CODE = re.compile(r"`|\b[a-z]+_[a-z_]+\b|::|\.py\b")
BARE_ID = re.compile(r"(?<!see )\b[A-Z]{2}-\d{2}\b")
MARKS = [";", "—", "–", "→", "!"]

PERSONAL = {
	"email": re.compile(r"[\w.+-]+@[\w-]+\.\w+"),
	"PAN": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
	"GSTIN": re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b"),
	"phone number": re.compile(r"\b[6-9]\d{9}\b"),
	"key": re.compile(r"\b(ghp_|github_pat_|sk-ant-|AKIA)\w+"),
}


def repeated(ids):
	return sorted({i for i in ids if ids.count(i) > 1})


def defined_tests():
	"""Every test of the app as file::test."""
	found = set()
	for path in APP.rglob("test_*.py"):
		for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
			if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
				found.add(f"{path.stem}::{node.name}")
	return found


def cited_tests():
	return {t for row in catalogue.rules() for t in catalogue.test_names(row["test"])}


def missing_code(home):
	"""Whether a Home names a file that is not there, or a name its file does not define."""
	file, _, name = home.partition("::")
	path = APP / file
	if not path.is_file():
		return True
	return bool(name) and name not in defined_names(path)


def defined_names(path):
	names = set()
	for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
		if isinstance(node, ast.FunctionDef | ast.ClassDef):
			names.add(node.name)
		elif isinstance(node, ast.Assign):
			names |= {target.id for target in node.targets if isinstance(target, ast.Name)}
	return names


def hooked(text):
	"""The app's own code that hooks.py names, as Homes. Comments and examples do not count."""
	found = set()
	for node in ast.walk(ast.parse(text)):
		if isinstance(node, ast.Constant) and isinstance(node.value, str) and HOOKED.fullmatch(node.value):
			module, name = node.value.removeprefix("custom_app.").rsplit(".", 1)
			found.add(f"{module.replace('.', '/')}.py::{name}")
	return found


def faults(words):
	return [mark for mark in MARKS if mark in words] + CODE.findall(words) + BARE_ID.findall(words)


def stale(rows, words):
	return {
		row["id"]: catalogue.fingerprint(row["text"])
		for row in rows
		if words.get(row["id"], {}).get("source") != catalogue.fingerprint(row["text"])
	}


class TestCatalogue(unittest.TestCase):
	def test_ids_are_unique(self):
		self.assertEqual(repeated([row["id"] for row in catalogue.rules()]), [])
		self.assertEqual(repeated(["A-01", "B-01", "A-01"]), ["A-01"])

	def test_every_group_is_on_one_tab(self):
		groups = [group for tab in catalogue.TABS for group in tab["groups"]]
		self.assertEqual(repeated(groups), [])
		self.assertEqual(sorted(groups), sorted({rule["group"] for rule in catalogue.rules()}))
		self.assertEqual(sorted(groups), sorted(catalogue.plain_words()["groups"]))
		misplaced = [rule["id"] for rule in catalogue.rules() if not rule["id"].startswith(rule["group"])]
		self.assertEqual(misplaced, [])
		script = PAGE_SCRIPT.read_text(encoding="utf-8")
		flows = script.split("const FLOWS = {", 1)[1].split("\n};", 1)[0]
		drawn = re.findall(r"^\t(\w+): \{$", flows, re.M)
		self.assertEqual(drawn, [tab["key"] for tab in catalogue.TABS])

	def test_every_rule_names_tests_that_exist(self):
		self.assertEqual(sorted(cited_tests() - defined_tests()), [])

	def test_every_test_belongs_to_a_rule(self):
		self.assertEqual(sorted(defined_tests() - cited_tests()), [], "name each in RULES.md")

	def test_the_code_a_rule_names_exists(self):
		missing = [f"{r['id']}: {home}" for r in catalogue.rules() for home in r["home"] if missing_code(home)]
		self.assertEqual(missing, [])
		self.assertTrue(missing_code("api/nowhere.py"))
		self.assertTrue(missing_code("api/supplier.py::no_such_function"))

	def test_every_hook_is_a_rule(self):
		homes = {home for rule in catalogue.rules() for home in rule["home"]}
		found = hooked((APP / "hooks.py").read_text(encoding="utf-8"))
		self.assertGreater(len(found), 30)
		self.assertEqual(sorted(found - homes), [], "write a rule for each")
		self.assertEqual(
			hooked("# custom_app.a.b\nx = {'on_submit': 'custom_app.api.x.go'}"), {"api/x.py::go"}
		)

	def test_plain_words_are_written_from_the_present_rule(self):
		rules, words = catalogue.rules(), catalogue.plain_words()["rules"]
		self.assertEqual(stale(rules, words), {}, "rewrite their plain words, then set each source")
		self.assertEqual(sorted(words), sorted(rule["id"] for rule in rules))
		made_up = [{"id": "AA-01", "text": "As it is now."}]
		self.assertIn("AA-01", stale(made_up, {"AA-01": {"source": catalogue.fingerprint("As it was.")}}))

	def test_plain_words_name_no_code(self):
		words = catalogue.plain_words()
		texts = {f"{i} {k}": e[k] for i, e in words["rules"].items() for k in ("title", "plain")}
		texts |= {f"{i} {k}": e[k] for i, e in words["groups"].items() for k in ("name", "summary")}
		self.assertEqual({where: faults(text) for where, text in texts.items() if faults(text)}, {})
		for bad in ("Set by `x`.", "Runs set_shift.", "One; two.", "As PR-06 says.", "Stops!", "A — B."):
			self.assertTrue(faults(bad), bad)
		self.assertEqual(faults("Refused already (see PR-06)."), [])
		text = catalogue.PLAIN.read_text(encoding="utf-8")
		self.assertEqual(text, json.dumps(json.loads(text), indent=1, ensure_ascii=False) + "\n")

	def test_the_rules_hold_no_personal_data(self):
		words = re.sub(r'"source": "\w+"', "", catalogue.PLAIN.read_text(encoding="utf-8"))
		text = catalogue.RULES.read_text(encoding="utf-8") + words
		self.assertEqual({kind: p.findall(text) for kind, p in PERSONAL.items() if p.search(text)}, {})
		for kind, example in {"email": "a@example.com", "PAN": "AAAAA0000A", "phone number": "9" * 10}.items():
			self.assertTrue(PERSONAL[kind].search(example), kind)


if __name__ == "__main__":
	unittest.main()
