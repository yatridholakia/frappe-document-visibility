"""
The list view and direct document access must return the same set of documents.

Frappe applies `permission_query_conditions` to list queries and `has_permission`
to a single document, and it does not re-check `has_permission` per list row. If
the two disagree, whichever is more permissive wins for the data it exposes - so
these tests assert they agree for every rule shape, then assert the set is right.
"""

import frappe

from document_visibility.tests.fixtures import (
	ROLE_A,
	ROLE_B,
	TEST_DOCTYPE,
	USER_A,
	USER_AB,
	USER_B,
	DVRTestCase,
	assign,
	create_doc,
	create_rule,
)


class TestVisibilityParity(DVRTestCase):
	def test_no_rules_means_no_filtering(self):
		docs = [create_doc(USER_A, status="Open"), create_doc(USER_B, status="Open")]
		self.assertParity(USER_A, docs, expected={d.name for d in docs})

	def test_creator_visibility(self):
		create_rule(ROLE_A, visible_to_creator=1)
		mine = create_doc(USER_A, status="Open")
		theirs = create_doc(USER_B, status="Open")

		self.assertParity(USER_A, [mine, theirs], expected={mine.name})

	def test_assignee_visibility_only_counts_open_todos(self):
		create_rule(ROLE_A, visible_to_assignees=1)
		assigned = create_doc(USER_B, status="Open")
		closed_assignment = create_doc(USER_B, status="Open")
		untouched = create_doc(USER_B, status="Open")

		assign(assigned, USER_A)
		assign(closed_assignment, USER_A, status="Closed")

		self.assertParity(USER_A, [assigned, closed_assignment, untouched], expected={assigned.name})

	def test_custom_visibility_expression(self):
		create_rule(
			ROLE_A,
			apply_custom_visibility=1,
			custom_visibility_expression='doc.department == "Sales"',
		)
		sales = create_doc(USER_B, department="Sales")
		other = create_doc(USER_B, department="Support")

		self.assertParity(USER_A, [sales, other], expected={sales.name})

	def test_restriction_narrows_visibility(self):
		create_rule(
			ROLE_A,
			visible_to_creator=1,
			restrict_visibility=1,
			restriction_expression='doc.status == "Open"',
		)
		open_doc = create_doc(USER_A, status="Open")
		closed_doc = create_doc(USER_A, status="Closed")

		self.assertParity(USER_A, [open_doc, closed_doc], expected={open_doc.name})

	def test_unrestricted_rule_does_not_lift_another_rules_restriction(self):
		"""
		A rule's restriction constrains only its own visibility.

		Role A grants creator visibility restricted to Open; Role B grants
		assignee visibility with no restriction. A document the user created
		while Closed must stay hidden - Role B does not lift Role A's
		restriction, in the list query or per document.
		"""
		create_rule(
			ROLE_A,
			visible_to_creator=1,
			restrict_visibility=1,
			restriction_expression='doc.status == "Open"',
		)
		create_rule(ROLE_B, visible_to_assignees=1)

		mine_open = create_doc(USER_AB, status="Open")
		mine_closed = create_doc(USER_AB, status="Closed")
		assigned_closed = create_doc(USER_A, status="Closed")
		assign(assigned_closed, USER_AB)

		# Visible: created and Open (Role A), or assigned (Role B, unrestricted).
		# Not visible: created but Closed - Role A's restriction still applies.
		self.assertParity(
			USER_AB,
			[mine_open, mine_closed, assigned_closed],
			expected={mine_open.name, assigned_closed.name},
		)

	def test_restrictions_from_different_roles_do_not_intersect(self):
		create_rule(
			ROLE_A,
			visible_to_creator=1,
			restrict_visibility=1,
			restriction_expression='doc.status == "Open"',
		)
		create_rule(
			ROLE_B,
			visible_to_creator=1,
			restrict_visibility=1,
			restriction_expression='doc.status == "Closed"',
		)
		open_doc = create_doc(USER_AB, status="Open")
		closed_doc = create_doc(USER_AB, status="Closed")
		cancelled = create_doc(USER_AB, status="Cancelled")

		self.assertParity(
			USER_AB,
			[open_doc, closed_doc, cancelled],
			expected={open_doc.name, closed_doc.name},
		)

	def test_rule_with_no_visibility_source_hides_everything(self):
		"""A restriction on its own grants nothing - it only ever narrows."""
		rule = frappe.get_doc(
			{
				"doctype": "Document Visibility Rule",
				"reference_doctype": TEST_DOCTYPE,
				"applies_to_role": ROLE_A,
				"enabled": 1,
				"restrict_visibility": 1,
				"restriction_expression": 'doc.status == "Open"',
			}
		)
		rule.flags.ignore_validate = True
		rule.insert(ignore_permissions=True)

		docs = [create_doc(USER_A, status="Open"), create_doc(USER_A, status="Closed")]
		self.assertParity(USER_A, docs, expected=set())

	def test_disabled_rule_is_ignored(self):
		rule = create_rule(ROLE_A, visible_to_creator=1)
		mine = create_doc(USER_A)
		theirs = create_doc(USER_B)

		self.assertParity(USER_A, [mine, theirs], expected={mine.name})

		rule.enabled = 0
		rule.save(ignore_permissions=True)

		self.assertParity(USER_A, [mine, theirs], expected={mine.name, theirs.name})

	def test_rule_for_another_role_does_not_apply(self):
		create_rule(ROLE_B, visible_to_creator=1)
		mine = create_doc(USER_A)
		theirs = create_doc(USER_B)

		self.assertParity(USER_A, [mine, theirs], expected={mine.name, theirs.name})
		self.assertParity(USER_B, [mine, theirs], expected={theirs.name})

	def test_administrator_is_never_filtered(self):
		create_rule(ROLE_A, visible_to_creator=1, restrict_visibility=1, restriction_expression='doc.status == "Nothing"')
		docs = [create_doc(USER_A), create_doc(USER_B)]

		frappe.set_user("Administrator")
		names = set(frappe.get_list(TEST_DOCTYPE, pluck="name", limit_page_length=0))
		self.assertTrue({d.name for d in docs}.issubset(names))
