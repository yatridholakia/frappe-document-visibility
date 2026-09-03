"""Validation tests: a bad rule must be rejected at save time, not at query time."""

import frappe

from document_visibility.tests.fixtures import (
	ROLE_A,
	ROLE_B,
	TEST_DOCTYPE,
	DVRTestCase,
	create_rule,
)


class TestDocumentVisibilityRule(DVRTestCase):
	def make(self, **kwargs):
		values = {
			"doctype": "Document Visibility Rule",
			"reference_doctype": TEST_DOCTYPE,
			"applies_to_role": ROLE_A,
			"enabled": 1,
			"visible_to_creator": 1,
		}
		values.update(kwargs)
		return frappe.get_doc(values)

	def assertRejected(self, doc, message_fragment=None):
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert(ignore_permissions=True)
		if message_fragment:
			self.assertIn(message_fragment, str(ctx.exception))

	# -- uniqueness ---------------------------------------------------------

	def test_one_enabled_rule_per_role_and_doctype(self):
		create_rule(ROLE_A, visible_to_creator=1)
		self.assertRejected(self.make())

	def test_a_second_rule_for_a_different_role_is_allowed(self):
		create_rule(ROLE_A, visible_to_creator=1)
		self.make(applies_to_role=ROLE_B).insert(ignore_permissions=True)

	# -- visibility source --------------------------------------------------

	def test_rule_needs_a_visibility_source(self):
		self.assertRejected(
			self.make(
				visible_to_creator=0,
				restrict_visibility=1,
				restriction_expression='doc.status == "Open"',
			),
			"at least one visibility source",
		)

	def test_restriction_requires_an_expression(self):
		self.assertRejected(self.make(restrict_visibility=1), "Restriction Expression is required")

	def test_custom_visibility_requires_an_expression(self):
		self.assertRejected(
			self.make(visible_to_creator=0, apply_custom_visibility=1),
			"Custom Visibility Expression is required",
		)

	# -- expressions --------------------------------------------------------

	def test_unknown_field_is_rejected_at_save(self):
		self.assertRejected(
			self.make(restrict_visibility=1, restriction_expression='doc.no_such_field == "x"'),
			"no_such_field",
		)

	def test_user_identifier_is_rejected_at_save(self):
		self.assertRejected(
			self.make(restrict_visibility=1, restriction_expression="doc.owner == user"),
			"Unknown identifier",
		)

	def test_valid_expression_is_accepted(self):
		self.make(
			restrict_visibility=1,
			restriction_expression='doc.status in ("Open", "Working") and doc.closed_on is None',
		).insert(ignore_permissions=True)

	def test_unused_expression_does_not_block_saving(self):
		"""A leftover expression on an unticked checkbox is not compiled."""
		self.make(restrict_visibility=0, restriction_expression="doc.nonsense == 1").insert(
			ignore_permissions=True
		)

	# -- reference doctype --------------------------------------------------

	def test_guarded_doctypes_are_rejected(self):
		for doctype in ("ToDo", "Document Visibility Rule", "User Group Member"):
			with self.subTest(doctype=doctype):
				self.assertRejected(self.make(reference_doctype=doctype))

	def test_single_doctype_is_rejected(self):
		self.assertRejected(self.make(reference_doctype="System Settings"), "Single DocType")

	def test_child_table_is_rejected(self):
		self.assertRejected(self.make(reference_doctype="Has Role"), "child table")

	def test_user_doctype_is_allowed(self):
		"""
		Rule evaluation resolves roles through the Has Role child table, which is
		never list-queried, so a rule on User does not re-enter evaluation.
		Restricting which users a role can see is a real use case.
		"""
		rule = self.make(reference_doctype="User")
		rule.insert(ignore_permissions=True)
		# User is a real DocType, not the scratch one the fixtures clean up, so
		# remove the rule even if the assertion below fails.
		self.addCleanup(frappe.delete_doc, "Document Visibility Rule", rule.name, force=True)
		self.assertTrue(frappe.db.exists("Document Visibility Rule", rule.name))
