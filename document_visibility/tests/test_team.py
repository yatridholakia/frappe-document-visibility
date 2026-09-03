import frappe

from document_visibility.permissions.dvr_helpers import get_team_users
from document_visibility.tests.fixtures import (
	GROUP_ONE,
	GROUP_TWO,
	ROLE_A,
	USER_A,
	USER_AB,
	USER_B,
	DVRTestCase,
	add_to_group,
	create_doc,
	create_rule,
	reset_dvr_caches,
)


class TestTeamVisibility(DVRTestCase):
	def setUp(self):
		super().setUp()
		for group in (GROUP_ONE, GROUP_TWO):
			if frappe.db.exists("User Group", group):
				frappe.delete_doc("User Group", group, force=True, ignore_permissions=True)
		reset_dvr_caches()

	def test_user_in_no_group_is_their_own_team(self):
		self.assertEqual(get_team_users(USER_A), [USER_A])

	def test_team_spans_the_group(self):
		add_to_group(GROUP_ONE, [USER_A, USER_B])
		reset_dvr_caches()

		self.assertEqual(get_team_users(USER_A), sorted([USER_A, USER_B]))

	def test_team_spans_multiple_groups(self):
		add_to_group(GROUP_ONE, [USER_A, USER_B])
		add_to_group(GROUP_TWO, [USER_A, USER_AB])
		reset_dvr_caches()

		self.assertEqual(get_team_users(USER_A), sorted([USER_A, USER_B, USER_AB]))

	def test_team_visibility_shows_a_colleagues_documents(self):
		add_to_group(GROUP_ONE, [USER_A, USER_B])
		create_rule(ROLE_A, visible_to_creator=1, visible_to_team=1)

		colleague_doc = create_doc(USER_B)
		outsider_doc = create_doc(USER_AB)

		self.assertParity(USER_A, [colleague_doc, outsider_doc], expected={colleague_doc.name})

	def test_team_visibility_without_a_group_falls_back_to_self(self):
		create_rule(ROLE_A, visible_to_creator=1, visible_to_team=1)

		mine = create_doc(USER_A)
		theirs = create_doc(USER_B)

		self.assertParity(USER_A, [mine, theirs], expected={mine.name})
