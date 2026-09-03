"""
Shared scaffolding for the integration tests.

Builds a throwaway DocType, two roles and three users - one holding each role
and one holding both. The both-roles user matters: rules only interact when a
single user's roles pull in more than one of them.
"""

import frappe

from document_visibility.permissions.dvr_helpers import clear_covered_doctypes_cache
from document_visibility.tests import IntegrationTestCase

TEST_DOCTYPE = "DVR Test Task"
ROLE_A = "DVR Test Role A"
ROLE_B = "DVR Test Role B"
USER_A = "dvr-user-a@example.com"
USER_B = "dvr-user-b@example.com"
USER_AB = "dvr-user-ab@example.com"
GROUP_ONE = "DVR Test Group One"
GROUP_TWO = "DVR Test Group Two"


def reset_dvr_caches():
	"""
	Drop every cached answer DVR holds.

	Without this the per-request memo of one test case answers the next one.
	"""
	clear_covered_doctypes_cache()
	cache = getattr(frappe.local, "cache", None)
	if isinstance(cache, dict):
		for key in [k for k in cache if isinstance(k, str) and k.startswith("dvr_")]:
			cache.pop(key, None)


def create_role(name):
	if not frappe.db.exists("Role", name):
		frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert(
			ignore_permissions=True
		)


def create_user(email, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	existing = {r.role for r in user.roles}
	for role in roles:
		if role not in existing:
			user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	return user


def create_test_doctype():
	"""
	Scratch DocType for the tests to filter.

	`custom: 1` keeps it in the database. A non-custom DocType would be written
	to disk inside the app whenever the site runs in developer mode.
	"""
	if frappe.db.exists("DocType", TEST_DOCTYPE):
		return

	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": TEST_DOCTYPE,
			"module": "Document Visibility",
			"custom": 1,
			"naming_rule": "Random",
			"autoname": "hash",
			"fields": [
				{"fieldname": "title", "fieldtype": "Data", "label": "Title"},
				{"fieldname": "status", "fieldtype": "Data", "label": "Status"},
				{"fieldname": "department", "fieldtype": "Data", "label": "Department"},
				{"fieldname": "closed_on", "fieldtype": "Date", "label": "Closed On"},
			],
			"permissions": [
				{"role": role, "read": 1, "write": 1, "create": 1, "delete": 1}
				for role in (ROLE_A, ROLE_B)
			],
		}
	).insert(ignore_permissions=True)


def create_rule(role, **kwargs):
	"""Create an enabled rule on the test DocType for the given role."""
	values = {
		"doctype": "Document Visibility Rule",
		"reference_doctype": TEST_DOCTYPE,
		"applies_to_role": role,
		"enabled": 1,
	}
	values.update(kwargs)
	rule = frappe.get_doc(values).insert(ignore_permissions=True)
	reset_dvr_caches()
	return rule


def create_doc(owner, **kwargs):
	"""Create a test document owned by `owner`."""
	values = {"doctype": TEST_DOCTYPE, "title": kwargs.get("title", "Doc")}
	values.update(kwargs)
	doc = frappe.get_doc(values).insert(ignore_permissions=True)
	if owner and doc.owner != owner:
		frappe.db.set_value(TEST_DOCTYPE, doc.name, "owner", owner, update_modified=False)
		doc.reload()
	return doc


def assign(doc, user, status="Open"):
	return frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": user,
			"reference_type": doc.doctype,
			"reference_name": doc.name,
			"status": status,
			"description": f"Assignment for {doc.name}",
		}
	).insert(ignore_permissions=True)


def add_to_group(group, users):
	if frappe.db.exists("User Group", group):
		doc = frappe.get_doc("User Group", group)
	else:
		doc = frappe.new_doc("User Group")
		doc.name = group

	existing = {m.user for m in doc.get("user_group_members", [])}
	for user in users:
		if user not in existing:
			doc.append("user_group_members", {"user": user})

	doc.flags.ignore_permissions = True
	doc.save()
	reset_dvr_caches()
	return doc


def destroy_test_fixtures():
	"""
	Remove everything `setUpClass` created, in dependency order.

	Creating the scratch DocType issues DDL, which commits implicitly, so the
	roles and users inserted alongside it are committed too and outlive the
	transaction rollback the test runner performs. Without this they stay on the
	site for good.

	Safe to call by hand on a site left dirty by an aborted run.
	"""
	frappe.set_user("Administrator")

	# Discard whatever a test left uncommitted, so the commit below makes only
	# these deletions durable and never some half-finished test's rows.
	frappe.db.rollback()

	frappe.db.delete("ToDo", {"reference_type": TEST_DOCTYPE})
	frappe.db.delete("Document Visibility Rule", {"reference_doctype": TEST_DOCTYPE})

	_delete("DocType", TEST_DOCTYPE)
	# Deleting the DocType record does not reliably drop its table across Frappe
	# versions, and an orphan table blocks the next run from recreating it.
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{TEST_DOCTYPE}`")

	for group in (GROUP_ONE, GROUP_TWO):
		_delete("User Group", group)

	for user in (USER_A, USER_B, USER_AB):
		# Frappe creates a Contact for every new User. Deleting the User does not
		# take the Contact with it, and the Contact outlives the rollback for the
		# same reason the User does.
		for contact in _contacts_for(user):
			_delete("Contact", contact)
		_delete("User", user)

	for role in (ROLE_A, ROLE_B):
		_delete("Role", role)

	reset_dvr_caches()
	frappe.db.commit()


def _delete(doctype, name):
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, ignore_missing=True)


def _contacts_for(email):
	"""Every Contact that points at this user, by any of the three links Frappe uses."""
	names = set(frappe.get_all("Contact Email", filters={"email_id": email}, pluck="parent"))
	names.update(frappe.get_all("Contact", filters={"email_id": email}, pluck="name"))
	names.update(frappe.get_all("Contact", filters={"user": email}, pluck="name"))
	return names


class DVRTestCase(IntegrationTestCase):
	"""Base class that provisions the scratch DocType, roles and users once."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_role(ROLE_A)
		create_role(ROLE_B)
		create_test_doctype()
		create_user(USER_A, [ROLE_A])
		create_user(USER_B, [ROLE_B])
		create_user(USER_AB, [ROLE_A, ROLE_B])
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		destroy_test_fixtures()

	def setUp(self):
		frappe.set_user("Administrator")
		# Frappe rolls the transaction back once per test class, not per test
		# method, so rows created by one test survive into the next. Every test
		# starts from an empty table.
		frappe.db.delete("Document Visibility Rule", {"reference_doctype": TEST_DOCTYPE})
		frappe.db.delete("ToDo", {"reference_type": TEST_DOCTYPE})
		frappe.db.delete(TEST_DOCTYPE)
		reset_dvr_caches()

	def tearDown(self):
		frappe.set_user("Administrator")
		reset_dvr_caches()

	def visible_in_list(self, user):
		"""Names the list view returns for `user` - the query-conditions path."""
		frappe.set_user(user)
		try:
			return set(frappe.get_list(TEST_DOCTYPE, pluck="name", limit_page_length=0))
		finally:
			frappe.set_user("Administrator")

	def visible_per_document(self, user, docs):
		"""Names `user` may open directly - the has_permission path."""
		frappe.set_user(user)
		try:
			return {
				doc.name for doc in docs if frappe.has_permission(TEST_DOCTYPE, "read", doc=doc, user=user)
			}
		finally:
			frappe.set_user("Administrator")

	def assertParity(self, user, docs, expected=None):
		"""
		Assert the list-query path and the document path return the same set.

		Frappe does not re-check `has_permission` per list row, so if the two
		disagree the list view exposes whatever it returns. `expected` pins the
		agreed set to the right answer.
		"""
		reset_dvr_caches()
		from_list = self.visible_in_list(user)
		reset_dvr_caches()
		from_document = self.visible_per_document(user, docs)

		self.assertEqual(
			from_list,
			from_document,
			f"List view and document access disagree for {user}: "
			f"only in list {sorted(from_list - from_document)}, "
			f"only per document {sorted(from_document - from_list)}",
		)

		if expected is not None:
			self.assertEqual(from_list, set(expected))

		return from_list
