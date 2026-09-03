from __future__ import annotations

import ast
import re

FIELDNAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Columns present on every DocType table but absent from `meta.fields`.
STANDARD_FIELDS = frozenset(
	{
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"idx",
		"parent",
		"parentfield",
		"parenttype",
		"_user_tags",
		"_comments",
		"_assign",
		"_liked_by",
	}
)

COMPARISON_OPERATORS = {
	ast.Eq: "=",
	ast.NotEq: "!=",
	ast.Gt: ">",
	ast.Lt: "<",
	ast.GtE: ">=",
	ast.LtE: "<=",
}


def compile_dvr_expression(expr: str, doctype: str, allowed_fields: set | None = None) -> str:
	"""
	Compile a restricted Python expression into a SQL condition.

	Example:
	    doc.status in ("Open", "Working")

	Output:
	    `tabTask`.`status` IN ('Open', 'Working')

	Only ``doc.<fieldname>``, literals, comparisons, ``in`` / ``not in``,
	``is None`` / ``is not None`` and ``and`` / ``or`` are accepted. Field names
	are validated against the DocType, so a typo is rejected when the rule is
	saved instead of producing a silently wrong query.

	:param allowed_fields: field names the expression may reference. Defaults to
	    the DocType's own fields plus the standard columns. Pass it explicitly to
	    compile without a database connection.
	"""
	if "`" in doctype:
		raise ValueError("Invalid DocType name")

	if allowed_fields is None:
		allowed_fields = get_allowed_fields(doctype)

	try:
		tree = ast.parse(expr, mode="eval")
	except SyntaxError as e:
		raise ValueError(f"Invalid expression: {e.msg}")

	return _compile_node(tree.body, doctype, allowed_fields)


def get_allowed_fields(doctype: str) -> set:
	"""Field names an expression may reference for the given DocType."""
	import frappe

	meta = frappe.get_meta(doctype)
	return {df.fieldname for df in meta.fields if df.fieldname} | set(STANDARD_FIELDS)


def _compile_node(node, doctype, allowed_fields):
	if isinstance(node, ast.BoolOp):
		op = "AND" if isinstance(node.op, ast.And) else "OR"
		values = [_compile_node(v, doctype, allowed_fields) for v in node.values]
		return "(" + f" {op} ".join(values) + ")"

	if isinstance(node, ast.Compare):
		return _compile_compare(node, doctype, allowed_fields)

	if isinstance(node, ast.Attribute):
		return _compile_field(node, doctype, allowed_fields)

	if isinstance(node, ast.Constant):
		return _sql_literal(node.value)

	if isinstance(node, (ast.Tuple, ast.List)):
		if not node.elts:
			raise ValueError("Empty sequence is not allowed")
		values = ", ".join(_compile_node(v, doctype, allowed_fields) for v in node.elts)
		return f"({values})"

	if isinstance(node, ast.Name):
		raise ValueError(f"Unknown identifier: {node.id}. Only doc.<fieldname> and literals are allowed.")

	raise ValueError(f"Unsupported expression: {type(node).__name__}")


def _compile_compare(node, doctype, allowed_fields):
	if len(node.ops) != 1:
		raise ValueError("Chained comparisons are not supported; use 'and' instead")

	op = node.ops[0]
	left = _compile_node(node.left, doctype, allowed_fields)
	right_node = node.comparators[0]

	# `doc.field is None` / `is not None` -> IS NULL / IS NOT NULL.
	# SQL never matches `= NULL`, so these must not go through the operator map.
	if isinstance(op, (ast.Is, ast.IsNot)):
		if not (isinstance(right_node, ast.Constant) and right_node.value is None):
			raise ValueError("'is' may only be used as 'is None' or 'is not None'")
		return f"{left} IS NULL" if isinstance(op, ast.Is) else f"{left} IS NOT NULL"

	if isinstance(op, (ast.In, ast.NotIn)):
		if not isinstance(right_node, (ast.Tuple, ast.List)):
			raise ValueError("'in' requires a tuple or list on the right-hand side")
		right = _compile_node(right_node, doctype, allowed_fields)
		return f"{left} {'IN' if isinstance(op, ast.In) else 'NOT IN'} {right}"

	sql_op = COMPARISON_OPERATORS.get(type(op))
	if not sql_op:
		raise ValueError(f"Unsupported comparison operator: {type(op).__name__}")

	right = _compile_node(right_node, doctype, allowed_fields)
	return f"{left} {sql_op} {right}"


def _compile_field(node, doctype, allowed_fields):
	if not isinstance(node.value, ast.Name) or node.value.id != "doc":
		raise ValueError("Only doc.<fieldname> is allowed")

	fieldname = node.attr

	if not FIELDNAME_PATTERN.match(fieldname):
		raise ValueError(f"Invalid field name: {fieldname}")

	if fieldname not in allowed_fields:
		raise ValueError(f"Unknown field '{fieldname}' on {doctype}")

	return f"`tab{doctype}`.`{fieldname}`"


def _sql_literal(value):
	if isinstance(value, bool):
		return "1" if value else "0"
	if isinstance(value, str):
		return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"
	if isinstance(value, (int, float)):
		return str(value)
	if value is None:
		raise ValueError("Compare against None with 'is None' or 'is not None'")
	raise ValueError(f"Unsupported literal: {type(value).__name__}")
