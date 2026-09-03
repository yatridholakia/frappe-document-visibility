"""
Whitelisted helpers for the desk UI.

All are restricted to System Manager: they report on arbitrary users and
disclose rule configuration.
"""

import frappe
from frappe import _

from document_visibility.permissions.document_visibility import is_visible
from document_visibility.permissions.dvr_expression import compile_dvr_expression
from document_visibility.permissions.dvr_helpers import (
	GUARDED_DOCTYPES,
	get_applicable_dvrs,
	has_rpm_read_permission,
	is_dvr_applicable,
	passes_restriction,
)


@frappe.whitelist()
def preview_expression(expression, reference_doctype):
	"""Compile an expression and return the SQL it produces, or the error."""
	frappe.only_for("System Manager")

	if not (expression or "").strip():
		return {"ok": True, "sql": ""}

	try:
		return {"ok": True, "sql": compile_dvr_expression(expression, reference_doctype)}
	except ValueError as e:
		return {"ok": False, "error": str(e)}


@frappe.whitelist()
def get_field_options(reference_doctype):
	"""Field names an expression may reference, for autocomplete in the form."""
	frappe.only_for("System Manager")

	from document_visibility.permissions.dvr_expression import get_allowed_fields

	return sorted(get_allowed_fields(reference_doctype))


@frappe.whitelist()
def explain_visibility(reference_doctype, docname, user):
	"""
	Explain, rule by rule, why a user can or cannot read a document.

	Returns the verdict plus the reasoning behind it: whether Role Permission
	Manager grants read at all, which rules apply, and for each one whether base
	visibility matched and whether the restriction passed.
	"""
	frappe.only_for("System Manager")

	result = {
		"user": user,
		"doctype": reference_doctype,
		"docname": docname,
		"rules": [],
		"visible": False,
		"reason": "",
	}

	if user == "Administrator":
		result["visible"] = True
		result["reason"] = _("Administrator is never filtered.")
		return result

	if reference_doctype in GUARDED_DOCTYPES:
		result["visible"] = True
		result["reason"] = _("{0} is never filtered: evaluating a rule reads it.").format(reference_doctype)
		return result

	if not has_rpm_read_permission(reference_doctype, user):
		result["reason"] = _(
			"Role Permission Manager does not grant read on {0}. Visibility rules narrow what "
			"RPM allows; they cannot grant access."
		).format(reference_doctype)
		return result

	if not is_dvr_applicable(reference_doctype):
		result["visible"] = True
		result["reason"] = _("No enabled rule covers {0}, so nothing is filtered.").format(reference_doctype)
		return result

	rules = get_applicable_dvrs(user, reference_doctype)
	if not rules:
		result["visible"] = True
		result["reason"] = _("{0} has rules, but none for any role {1} holds.").format(
			reference_doctype, user
		)
		return result

	doc = frappe.get_doc(reference_doctype, docname)

	for rule in rules:
		visible = is_visible(rule, doc, user)
		restricted = bool(rule.restrict_visibility)
		passed = passes_restriction(rule, doc) if visible else None

		result["rules"].append(
			{
				"rule": rule.name,
				"role": rule.applies_to_role,
				"base_visibility": visible,
				"restricted": restricted,
				"restriction_passed": passed,
				"grants_access": bool(visible and passed),
			}
		)

		if visible and passed:
			result["visible"] = True

	if result["visible"]:
		granting = [r["role"] for r in result["rules"] if r["grants_access"]]
		result["reason"] = _("Granted by {0}.").format(", ".join(granting))
	elif any(r["base_visibility"] for r in result["rules"]):
		blocked = [r["role"] for r in result["rules"] if r["base_visibility"]]
		result["reason"] = _(
			"Base visibility matched for {0}, but that rule's restriction excluded this document."
		).format(", ".join(blocked))
	else:
		result["reason"] = _(
			"No applicable rule grants base visibility: the user is not the creator, has no open "
			"assignment, and no custom visibility expression matched."
		)

	return result
