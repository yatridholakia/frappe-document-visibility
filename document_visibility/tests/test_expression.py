"""
Unit tests for the expression compiler.

No database: `allowed_fields` is injected, so these run anywhere.
"""

import unittest

from document_visibility.permissions.dvr_expression import compile_dvr_expression

FIELDS = {"status", "department", "amount", "closed_on", "owner", "name"}


def compile_expr(expr):
	return compile_dvr_expression(expr, "Task", allowed_fields=FIELDS)


class TestExpressionCompiler(unittest.TestCase):
	def test_comparisons(self):
		cases = [
			('doc.status == "Open"', "`tabTask`.`status` = 'Open'"),
			('doc.status != "Open"', "`tabTask`.`status` != 'Open'"),
			("doc.amount > 100", "`tabTask`.`amount` > 100"),
			("doc.amount >= 100", "`tabTask`.`amount` >= 100"),
			("doc.amount < 100", "`tabTask`.`amount` < 100"),
			("doc.amount <= 100", "`tabTask`.`amount` <= 100"),
			("doc.amount == 1.5", "`tabTask`.`amount` = 1.5"),
		]
		for expr, expected in cases:
			with self.subTest(expr=expr):
				self.assertEqual(compile_expr(expr), expected)

	def test_membership(self):
		self.assertEqual(
			compile_expr('doc.status in ("Open", "Working")'),
			"`tabTask`.`status` IN ('Open', 'Working')",
		)
		self.assertEqual(
			compile_expr('doc.status not in ["Cancelled"]'),
			"`tabTask`.`status` NOT IN ('Cancelled')",
		)

	def test_boolean_operators(self):
		self.assertEqual(
			compile_expr('doc.status == "Open" and doc.amount > 10'),
			"(`tabTask`.`status` = 'Open' AND `tabTask`.`amount` > 10)",
		)
		self.assertEqual(
			compile_expr('doc.status == "Open" or doc.status == "Working"'),
			"(`tabTask`.`status` = 'Open' OR `tabTask`.`status` = 'Working')",
		)

	def test_nested_boolean_operators(self):
		self.assertEqual(
			compile_expr('(doc.status == "Open" or doc.status == "Working") and doc.amount > 10'),
			"((`tabTask`.`status` = 'Open' OR `tabTask`.`status` = 'Working') AND `tabTask`.`amount` > 10)",
		)

	def test_null_comparison_uses_is_null(self):
		"""`= NULL` never matches in SQL, so `is None` must not compile to it."""
		self.assertEqual(compile_expr("doc.closed_on is None"), "`tabTask`.`closed_on` IS NULL")
		self.assertEqual(compile_expr("doc.closed_on is not None"), "`tabTask`.`closed_on` IS NOT NULL")

	def test_equality_against_none_is_rejected(self):
		with self.assertRaises(ValueError) as ctx:
			compile_expr("doc.closed_on == None")
		self.assertIn("is None", str(ctx.exception))

	def test_string_literals_are_escaped(self):
		self.assertEqual(
			compile_expr("""doc.department == "O'Brien" """), "`tabTask`.`department` = 'O''Brien'"
		)
		self.assertEqual(compile_expr(r'doc.department == "a\\b"'), "`tabTask`.`department` = 'a\\\\b'")

	def test_booleans_compile_to_integers(self):
		self.assertEqual(compile_expr("doc.status == True"), "`tabTask`.`status` = 1")
		self.assertEqual(compile_expr("doc.status == False"), "`tabTask`.`status` = 0")

	def test_unknown_field_is_rejected(self):
		with self.assertRaises(ValueError) as ctx:
			compile_expr('doc.no_such_field == "x"')
		self.assertIn("no_such_field", str(ctx.exception))

	def test_user_identifier_is_rejected(self):
		"""It used to compile to an unbound placeholder that reached SQL."""
		with self.assertRaises(ValueError) as ctx:
			compile_expr("doc.owner == user")
		self.assertIn("user", str(ctx.exception))

	def test_rejected_expressions(self):
		cases = [
			"len(doc.status)",  # function call
			"doc.status.lower()",  # method access
			'other.status == "x"',  # not a doc attribute
			'doc.status == "Open" == "Working"',  # chained comparison
			'doc.status is "Open"',  # is against a non-None literal
			'doc.status in "Open"',  # in against a scalar
			"doc.status in ()",  # empty sequence
			'__import__("os")',
			"doc.status ==",  # syntax error
			'{"a": 1}',  # unsupported node
		]
		for expr in cases:
			with self.subTest(expr=expr), self.assertRaises(ValueError):
				compile_expr(expr)

	def test_backtick_in_doctype_is_rejected(self):
		with self.assertRaises(ValueError):
			compile_dvr_expression('doc.status == "Open"', "Ta`sk", allowed_fields=FIELDS)


if __name__ == "__main__":
	unittest.main()
