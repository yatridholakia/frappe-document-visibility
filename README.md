# Document Visibility

Row-level read visibility for Frappe DocTypes, configured as data.

A **Document Visibility Rule** says, for one Role on one DocType: *which documents
may this role read?* Rules layer on top of Role Permission Manager — they narrow
what RPM already grants and can never widen it.

```
Role Permission Manager  →  can this role read this DocType at all?
Document Visibility Rule →  which of those documents, specifically?
```

Supported on **Frappe v15 and v16**.

---

## Why not User Permissions?

This is the first question every Frappe developer asks, so here is the honest answer.

| | User Permissions | Permission Level | Share | **Document Visibility Rule** |
|---|---|---|---|---|
| Scope | One user | One field | One document | One **role**, on one DocType |
| Filters by | Value of a link field | — | Explicit grant | Creator, assignee, team, or an expression |
| Owner / assignee aware | No | No | Manual | Yes |
| Conditional on document state | No | No | No | Yes — `doc.status in (...)` |
| Configured per | User (n rows) | Field | Document (n rows) | Role (1 row) |
| Scales with | Number of users | Number of fields | Number of documents | Number of roles |

Use **User Permissions** when visibility follows a link field — a user belongs to a
Company or a Territory and should see that partition. It is simpler and it is the
right tool for that shape.

Reach for a Document Visibility Rule when visibility depends on the *document's*
state or on the user's *relationship* to it: "Sales users see the leads they own,
but only while those leads are Open", "Reviewers see anything assigned to them",
"a team sees each other's work". Expressing that with User Permissions means one
row per user, maintained forever.

The two compose. Both are applied; a document must satisfy both.

---

## Install

```bash
bench get-app https://github.com/yatridholakia/frappe-document-visibility
bench --site <site> install-app document_visibility
```

## Use

Go to **Document Visibility Rule → New**. Pick a DocType and a Role, then choose
what that role may see.

**Base visibility** — a document is visible if *any* of these matches:

| Option | Meaning |
|---|---|
| Visible to Creator | `owner` is the user |
| Visible to Assignees | an **open** ToDo assigns the document to the user |
| Visible to Team | expands the two above from "the user" to "anyone in the user's User Groups" |
| Apply Custom Visibility | a condition on the document, independent of who owns it |

**Restriction** — an extra condition that must *also* hold. Base visibility says
*whose* documents; the restriction says *which* of them.

### Worked example

Sales users should see the leads they own, but only while those leads are open.
Their manager should see everything the team owns, at any status.

| | Rule for `Sales User` | Rule for `Sales Manager` |
|---|---|---|
| Visible to Creator | ✅ | ✅ |
| Visible to Team | — | ✅ |
| Restrict Visibility | ✅ `doc.status in ("Open", "Working")` | — |

A user holding **both** roles sees the union: everything the team owns. Each rule
is evaluated on its own and the results are OR-ed, so one role's restriction never
constrains another role's grant — and never leaks past its own.

### Expression grammar

```python
doc.status == "Open"
doc.status in ("Open", "Working")
doc.department != "Internal"
doc.amount >= 10000 and doc.status != "Cancelled"
doc.closed_on is None
```

Allowed: `doc.<fieldname>`, string / number / boolean literals, `==` `!=` `>` `<`
`>=` `<=`, `in` / `not in` over a tuple or list, `is None` / `is not None`, and
`and` / `or`.

Rejected — at save time, with a message: function calls, method access, anything
that is not `doc.<fieldname>`, unknown field names, chained comparisons
(`1 < doc.amount < 5`), and `== None` (which never matches in SQL — use `is None`).

The same expression is compiled to SQL for list queries and evaluated in Python
for a single document, so both paths always agree. The form shows you the compiled
SQL as you type.

### Why can't a user see this document?

Open any rule and use **Why can't a user see this?**. Pick a user and a document
and it reports, rule by rule, whether base visibility matched, whether the
restriction passed, and the final verdict. System Manager only.

---

## Behaviour worth knowing

- **Read only.** Rules never affect write, create, delete, submit or cancel.
- **Never grants access.** If Role Permission Manager does not grant read, no rule
  can add it.
- **Administrator is never filtered.**
- **One enabled rule per Role + DocType.** A user with several roles gets the union
  of their rules.
- **A rule with no visibility source hides everything** for that role, so the form
  refuses to save one.
- **Rules are refused on `ToDo`, `User Group Member` and `Document Visibility Rule`**
  themselves: evaluating a rule reads those, so a rule there would call itself.
  Single and child DocTypes are refused too — there is no list to filter.
- **A DocType nobody has written a rule for costs nothing.** The set of covered
  DocTypes is cached and checked first.
- Changing rules with `frappe.db.set_value` bypasses the controller and so bypasses
  cache invalidation. Save the document, or call
  `document_visibility.permissions.dvr_helpers.clear_covered_doctypes_cache()`.

---

## Development

```bash
bench --site <site> run-tests --app document_visibility
```

The expression compiler tests need no site:

```bash
python -m unittest document_visibility.tests.test_expression
```

## License

MIT. See [license.txt](license.txt).
