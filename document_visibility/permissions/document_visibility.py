import frappe
from frappe.utils.safe_exec import safe_eval

from document_visibility.permissions.dvr_expression import compile_dvr_expression
from document_visibility.permissions.dvr_helpers import (
	get_applicable_dvrs,
	get_team_users,
	has_rpm_read_permission,
	is_dvr_applicable,
	passes_restriction,
)


def get_permission_query_conditions(user=None, doctype=None):
	"""
	Build the WHERE fragment Frappe appends to list, report and link queries.

	Each applicable rule contributes one block of `(visibility) AND (restriction)`,
	and the blocks are OR-ed together. That mirrors `has_permission` exactly: a
	rule's restriction constrains only its own visibility and never another
	rule's, so the list view and direct document access always agree.
	"""
	user = user or frappe.session.user

	if user == "Administrator" or not doctype:
		return ""

	# Checked before anything else: the hooks are registered for every DocType,
	# so this is the path taken by almost every query on the site.
	if not is_dvr_applicable(doctype):
		return ""

	if not has_rpm_read_permission(doctype, user):
		return "1 = 0"

	dvrs = get_applicable_dvrs(user, doctype)
	if not dvrs:
		return ""

	blocks = []

	for dvr in dvrs:
		try:
			block = _rule_sql(dvr, user, doctype)
		except Exception:
			# A rule that cannot be compiled grants nothing (fail closed).
			frappe.log_error(
				title="Document Visibility Rule could not be compiled",
				message=f"Rule: {dvr.get('name')}\nDocType: {doctype}\n\n{frappe.get_traceback()}",
			)
			continue

		if block:
			blocks.append(block)

	if not blocks:
		return "1 = 0"

	return "(" + " OR ".join(blocks) + ")"


def has_permission(doc, user=None, ptype=None):
	"""Document-level counterpart of `get_permission_query_conditions`."""
	user = user or frappe.session.user

	if user == "Administrator":
		return True

	# DVR controls READ only.
	if ptype and ptype != "read":
		return True

	if not is_dvr_applicable(getattr(doc, "doctype", None)):
		return True

	if not has_rpm_read_permission(doc.doctype, user):
		return False

	dvrs = get_applicable_dvrs(user, doc.doctype)
	if not dvrs:
		return True

	for dvr in dvrs:
		if not is_visible(dvr, doc, user):
			continue

		if passes_restriction(dvr, doc):
			return True

	return False


# ---------------------------------------------------------------------------
# Query path
# ---------------------------------------------------------------------------


def _rule_sql(dvr, user, doctype):
	"""SQL for one rule: `(visibility) AND (restriction)`, or "" if it grants nothing."""
	visibility = _visibility_sql(dvr, user, doctype)
	if not visibility:
		return ""

	if not dvr.restrict_visibility:
		return visibility

	if not dvr.restriction_expression:
		# Restricted with nothing to restrict by: grants nothing (fail closed),
		# matching `passes_restriction`.
		return ""

	restriction = compile_dvr_expression(dvr.restriction_expression, doctype)
	return f"({visibility} AND ({restriction}))"


def _visibility_sql(dvr, user, doctype):
	parts = []

	if dvr.visible_to_creator:
		if dvr.visible_to_team:
			parts.append(f"`tab{doctype}`.owner IN ({_user_list_sql(get_team_users(user))})")
		else:
			parts.append(f"`tab{doctype}`.owner = {frappe.db.escape(user)}")

	if dvr.visible_to_assignees:
		if dvr.visible_to_team:
			allocated = f"allocated_to IN ({_user_list_sql(get_team_users(user))})"
		else:
			allocated = f"allocated_to = {frappe.db.escape(user)}"
		parts.append(_open_assignment_sql(doctype, allocated))

	if dvr.apply_custom_visibility and dvr.get("custom_visibility_expression"):
		parts.append(f"({compile_dvr_expression(dvr.custom_visibility_expression, doctype)})")

	if not parts:
		return ""

	return "(" + " OR ".join(parts) + ")"


def _user_list_sql(users):
	return ", ".join(frappe.db.escape(u) for u in users)


def _open_assignment_sql(doctype, allocated_condition):
	return f"""EXISTS (
		SELECT 1
		FROM `tabToDo`
		WHERE `tabToDo`.reference_type = {frappe.db.escape(doctype)}
			AND `tabToDo`.reference_name = `tab{doctype}`.name
			AND `tabToDo`.status = 'Open'
			AND `tabToDo`.{allocated_condition}
	)"""


# ---------------------------------------------------------------------------
# Document path
# ---------------------------------------------------------------------------


def is_visible(dvr, doc, user):
	if dvr.visible_to_creator:
		if dvr.visible_to_team:
			if doc.owner in get_team_users(user):
				return True
		elif doc.owner == user:
			return True

	if dvr.visible_to_assignees and _has_open_assignment(dvr, doc, user):
		return True

	if dvr.apply_custom_visibility and dvr.get("custom_visibility_expression"):
		try:
			# Expressions are authored only by System Manager, are compiled against the
			# restricted DVR grammar on save, and run through frappe's safe_eval with no
			# globals and only `doc` in scope. See DocumentVisibilityRule.validate_expressions.
			# nosemgrep: frappe-semgrep-rules.rules.security.frappe-codeinjection-eval
			if safe_eval(
				dvr.custom_visibility_expression,
				eval_globals={},
				eval_locals={"doc": doc},
			):
				return True
		except Exception:
			pass  # fail closed

	return False


def _has_open_assignment(dvr, doc, user):
	allocated_to = ["in", get_team_users(user)] if dvr.visible_to_team else user

	return bool(
		frappe.db.exists(
			"ToDo",
			{
				"reference_type": doc.doctype,
				"reference_name": doc.name,
				"allocated_to": allocated_to,
				"status": "Open",
			},
		)
	)
