"""
The permission hooks are registered for every DocType, so the cheap miss path is
what makes that affordable. These tests pin both halves: the cached set is
actually cached, and it is invalidated whenever a rule changes.
"""

import frappe

from document_visibility.permissions.document_visibility import get_permission_query_conditions
from document_visibility.permissions.dvr_helpers import (
	GUARDED_DOCTYPES,
	get_applicable_dvrs,
	get_covered_doctypes,
	is_dvr_applicable,
)
from document_visibility.tests.fixtures import (
	ROLE_A,
	TEST_DOCTYPE,
	USER_A,
	DVRTestCase,
	create_rule,
	reset_dvr_caches,
)


class TestCoveredDocTypeCache(DVRTestCase):
	def test_uncovered_doctype_is_not_evaluated(self):
		self.assertNotIn(TEST_DOCTYPE, get_covered_doctypes())
		self.assertFalse(is_dvr_applicable(TEST_DOCTYPE))
		self.assertEqual(get_permission_query_conditions(USER_A, TEST_DOCTYPE), "")

	def test_creating_a_rule_covers_the_doctype(self):
		create_rule(ROLE_A, visible_to_creator=1)

		self.assertIn(TEST_DOCTYPE, get_covered_doctypes())
		self.assertTrue(is_dvr_applicable(TEST_DOCTYPE))

	def test_deleting_a_rule_uncovers_the_doctype(self):
		rule = create_rule(ROLE_A, visible_to_creator=1)
		self.assertIn(TEST_DOCTYPE, get_covered_doctypes())

		rule.delete(ignore_permissions=True)

		self.assertNotIn(TEST_DOCTYPE, get_covered_doctypes())

	def test_disabling_a_rule_uncovers_the_doctype(self):
		rule = create_rule(ROLE_A, visible_to_creator=1)

		rule.enabled = 0
		rule.save(ignore_permissions=True)

		self.assertNotIn(TEST_DOCTYPE, get_covered_doctypes())

	def test_the_set_is_actually_cached(self):
		"""
		Delete a rule behind the controller's back. The cached answer must
		survive - proof the set is not being recomputed on every call.
		"""
		create_rule(ROLE_A, visible_to_creator=1)
		self.assertIn(TEST_DOCTYPE, get_covered_doctypes())

		frappe.db.delete("Document Visibility Rule", {"reference_doctype": TEST_DOCTYPE})

		self.assertIn(TEST_DOCTYPE, get_covered_doctypes())

		reset_dvr_caches()
		self.assertNotIn(TEST_DOCTYPE, get_covered_doctypes())

	def test_guarded_doctypes_are_never_evaluated(self):
		"""
		Evaluating a rule reads these DocTypes, so a rule on one of them would
		call itself. They short-circuit before the covered-set lookup.
		"""
		for doctype in GUARDED_DOCTYPES:
			with self.subTest(doctype=doctype):
				self.assertFalse(is_dvr_applicable(doctype))
				self.assertEqual(get_permission_query_conditions(USER_A, doctype), "")

	def test_rules_are_memoised_per_request(self):
		"""The same lookup within one request must not hit the database twice."""
		create_rule(ROLE_A, visible_to_creator=1)

		first = get_applicable_dvrs(USER_A, TEST_DOCTYPE)
		second = get_applicable_dvrs(USER_A, TEST_DOCTYPE)
		self.assertIs(first, second)

		reset_dvr_caches()
		self.assertIsNot(first, get_applicable_dvrs(USER_A, TEST_DOCTYPE))
