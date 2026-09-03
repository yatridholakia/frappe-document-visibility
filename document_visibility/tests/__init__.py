"""
Version compatibility shim for the test base class.

Frappe v16 exposes `frappe.tests.IntegrationTestCase`; v15 calls the same thing
`frappe.tests.utils.FrappeTestCase`. Every test imports the base class from
here, so the difference lives in one place.

Resolved lazily (PEP 562): importing this package must not require frappe, or
the compiler tests could not be collected without a bench.
"""

__all__ = ["IntegrationTestCase"]


def __getattr__(name):
	if name == "IntegrationTestCase":
		try:  # Frappe v16
			from frappe.tests import IntegrationTestCase
		except ImportError:  # Frappe v15
			from frappe.tests.utils import FrappeTestCase as IntegrationTestCase
		return IntegrationTestCase
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
