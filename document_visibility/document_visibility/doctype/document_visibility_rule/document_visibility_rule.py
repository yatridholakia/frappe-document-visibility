import frappe
from frappe import _
from frappe.model.document import Document

from document_visibility.permissions.dvr_expression import compile_dvr_expression
from document_visibility.permissions.dvr_helpers import (
	GUARDED_DOCTYPES,
	clear_covered_doctypes_cache,
)


class DocumentVisibilityRule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		applies_to_role: DF.Link
		apply_custom_visibility: DF.Check
		custom_visibility_expression: DF.Code | None
		enabled: DF.Check
		reference_doctype: DF.Link
		restrict_visibility: DF.Check
		restriction_expression: DF.Code | None
		visible_to_assignees: DF.Check
		visible_to_creator: DF.Check
		visible_to_team: DF.Check
	# end: auto-generated types

	def validate(self):
		self.validate_reference_doctype()
		self.validate_unique_rule()
		self.validate_visibility_source()
		self.validate_expressions()

	def on_update(self):
		clear_covered_doctypes_cache()

	def on_trash(self):
		clear_covered_doctypes_cache()

	def after_rename(self, *args, **kwargs):
		clear_covered_doctypes_cache()

	def validate_reference_doctype(self):
		if self.reference_doctype in GUARDED_DOCTYPES:
			frappe.throw(
				_(
					"{0} cannot be restricted: evaluating a rule reads this DocType, so a rule on it "
					"would call itself."
				).format(frappe.bold(self.reference_doctype))
			)

		meta = frappe.get_meta(self.reference_doctype)

		if meta.issingle:
			frappe.throw(
				_("{0} is a Single DocType and has no list of documents to filter.").format(
					frappe.bold(self.reference_doctype)
				)
			)

		if meta.istable:
			frappe.throw(
				_(
					"{0} is a child table. Its rows are read through the parent document, so a rule "
					"here has no effect. Add the rule to the parent DocType instead."
				).format(frappe.bold(self.reference_doctype))
			)

	def validate_unique_rule(self):
		"""
		One rule per Role and DocType.

		Autoname is `format:{reference_doctype} - {applies_to_role}`, so a second
		rule for the pair also collides on the primary key. Two consequences:

		- Only exclude self when updating. On insert there is no self yet, and
		  `name != self.name` would exclude the only row that can ever match,
		  letting the duplicate through as a raw DuplicateEntryError.
		- Do not filter on `enabled`. A disabled rule occupies the name just as
		  an enabled one does.
		"""
		filters = {
			"reference_doctype": self.reference_doctype,
			"applies_to_role": self.applies_to_role,
		}
		if not self.is_new():
			filters["name"] = ["!=", self.name]

		if frappe.get_all("Document Visibility Rule", filters=filters, limit=1):
			frappe.throw(_("Only one Document Visibility Rule is allowed per Role and DocType."))

	def validate_visibility_source(self):
		"""A rule with no visibility source hides everything - almost never intended."""
		if not self.enabled:
			return

		if not (self.visible_to_creator or self.visible_to_assignees or self.apply_custom_visibility):
			frappe.throw(
				_(
					"Enable at least one visibility source: Visible to Creator, Visible to Assignees "
					"or Apply Custom Visibility. Otherwise this rule hides every document from {0}."
				).format(frappe.bold(self.applies_to_role))
			)

	def validate_expressions(self):
		if self.apply_custom_visibility and not self.custom_visibility_expression:
			frappe.throw(_("Custom Visibility Expression is required when Apply Custom Visibility is set."))

		if self.restrict_visibility and not self.restriction_expression:
			frappe.throw(_("Restriction Expression is required when Restrict Visibility is set."))

		# Only compile what is actually in use, so a leftover expression on a
		# disabled checkbox never blocks a save.
		for label, expression in (
			(_("Custom Visibility Expression"), self.apply_custom_visibility and self.custom_visibility_expression),
			(_("Restriction Expression"), self.restrict_visibility and self.restriction_expression),
		):
			if not expression:
				continue
			try:
				compile_dvr_expression(expression, self.reference_doctype)
			except ValueError as e:
				frappe.throw(_("{0}: {1}").format(label, str(e)), title=_("Invalid Expression"))
