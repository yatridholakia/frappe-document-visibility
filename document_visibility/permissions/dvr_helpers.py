import frappe
from frappe.permissions import get_role_permissions
from frappe.utils.safe_exec import safe_eval

DVR_FIELDS = [
	"name",
	"applies_to_role",
	"visible_to_creator",
	"visible_to_assignees",
	"visible_to_team",
	"apply_custom_visibility",
	"custom_visibility_expression",
	"restrict_visibility",
	"restriction_expression",
]

COVERED_DOCTYPES_CACHE_KEY = "dvr_covered_doctypes"

# DocTypes that rule evaluation itself reads. A rule on any of these would
# re-enter rule evaluation while answering a query about rule evaluation, so
# they are refused at save time and short-circuited defensively at runtime.
GUARDED_DOCTYPES = frozenset(
	{
		"Document Visibility Rule",
		"ToDo",
		"User Group Member",
	}
)


def get_cache():
	"""
	The persistent cache, across Frappe versions.

	`frappe.cache` is a callable in v15 and an object in v16.
	"""
	cache = frappe.cache
	return cache() if callable(cache) else cache


def request_cache():
	"""Per-request cache dict, created if the context does not have one yet."""
	if not hasattr(frappe.local, "cache") or frappe.local.cache is None:
		frappe.local.cache = {}
	return frappe.local.cache


def get_covered_doctypes():
	"""
	DocTypes that have at least one enabled rule.

	The permission hooks are registered against every DocType, so this set is
	what keeps the miss path free: a DocType nobody has written a rule for
	costs one cached lookup and no database query at all.
	"""
	cache = get_cache()
	covered = cache.get_value(COVERED_DOCTYPES_CACHE_KEY)

	if covered is None:
		covered = list(
			{
				d
				for d in frappe.get_all(
					"Document Visibility Rule",
					filters={"enabled": 1},
					pluck="reference_doctype",
				)
				if d
			}
		)
		cache.set_value(COVERED_DOCTYPES_CACHE_KEY, covered)

	return set(covered)


def clear_covered_doctypes_cache():
	"""Called whenever a rule is created, changed, disabled or deleted."""
	get_cache().delete_value(COVERED_DOCTYPES_CACHE_KEY)
	request_cache().pop(COVERED_DOCTYPES_CACHE_KEY, None)


def is_dvr_applicable(doctype):
	"""Whether rule evaluation should run at all for this DocType."""
	if not doctype or doctype in GUARDED_DOCTYPES:
		return False

	return doctype in get_covered_doctypes()


def get_applicable_dvrs(user, doctype):
	"""
	Enabled rules for any role the user holds on the given DocType.

	Memoised per request: a single list view resolves permissions many times
	over, and the answer cannot change mid-request.
	"""
	cache_key = f"dvr_rules::{user}::{doctype}"
	cache = request_cache()

	if cache_key in cache:
		return cache[cache_key]

	roles = frappe.get_roles(user)

	rules = frappe.get_all(
		"Document Visibility Rule",
		filters={
			"reference_doctype": doctype,
			"applies_to_role": ["in", roles],
			"enabled": 1,
		},
		fields=DVR_FIELDS,
	)

	cache[cache_key] = rules
	return rules


def get_team_users(user):
	"""
	All users belonging to any User Group the given user belongs to.

	Always includes the user themselves. Cached per request.
	"""
	cache_key = f"dvr_team_users::{user}"
	cache = request_cache()
	if cache_key in cache:
		return cache[cache_key]

	groups = frappe.get_all("User Group Member", filters={"user": user}, pluck="parent")

	team_users = (
		frappe.get_all("User Group Member", filters={"parent": ["in", groups]}, pluck="user")
		if groups
		else []
	)

	team_users = sorted({*team_users, user})

	cache[cache_key] = team_users
	return team_users


def has_rpm_read_permission(doctype, user):
	"""
	READ permission via Role Permission Manager only.

	DVR filters within what RPM already grants, so this is the gate that runs
	first. Safe to call inside controller hooks.
	"""
	meta = frappe.get_meta(doctype)
	perms = get_role_permissions(meta, user=user)

	return bool(perms.get("read"))


def passes_restriction(dvr, doc):
	"""Whether the document satisfies this rule's restriction expression."""
	if not dvr.restrict_visibility:
		return True

	if not dvr.restriction_expression:
		return False  # fail closed

	try:
		# Expressions are authored only by System Manager, are compiled against the
		# restricted DVR grammar on save, and run through frappe's safe_eval with no
		# globals and only `doc` in scope. See DocumentVisibilityRule.validate_expressions.
		return bool(
			# nosemgrep: frappe-semgrep-rules.rules.security.frappe-codeinjection-eval
			safe_eval(
				dvr.restriction_expression,
				eval_globals={},
				eval_locals={"doc": doc},
			)
		)
	except Exception:
		return False
