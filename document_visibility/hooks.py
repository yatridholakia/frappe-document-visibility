app_name = "document_visibility"
app_title = "Document Visibility"
app_publisher = "Yatri Dholakia"
app_description = "Row-level read visibility rules for Frappe DocTypes, configured as data."
app_email = "yaatrie@gmail.com"
app_license = "mit"

# Permissions
# -----------
# DVR layers row-level READ visibility on top of Role Permission Manager. It is
# registered against every DocType; the covered-doctype cache makes the miss path
# free, so DocTypes with no rule configured cost nothing.

permission_query_conditions = {
	"*": "document_visibility.permissions.document_visibility.get_permission_query_conditions"
}

has_permission = {"*": "document_visibility.permissions.document_visibility.has_permission"}
