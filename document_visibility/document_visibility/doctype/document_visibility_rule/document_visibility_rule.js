const EXPRESSION_FIELDS = ["custom_visibility_expression", "restriction_expression"];

frappe.ui.form.on("Document Visibility Rule", {
	refresh(frm) {
		frm.trigger("show_field_hints");
		EXPRESSION_FIELDS.forEach((fieldname) => preview(frm, fieldname));

		if (!frm.is_new()) {
			frm.add_custom_button(__("Why can't a user see this?"), () => debug_visibility(frm));
		}
	},

	reference_doctype(frm) {
		frm.trigger("show_field_hints");
		EXPRESSION_FIELDS.forEach((fieldname) => preview(frm, fieldname));
	},

	custom_visibility_expression(frm) {
		preview(frm, "custom_visibility_expression");
	},

	restriction_expression(frm) {
		preview(frm, "restriction_expression");
	},

	// Lists the fields an expression may reference, so the usable vocabulary is
	// visible while writing rather than discovered by hitting a save error.
	show_field_hints(frm) {
		if (!frm.doc.reference_doctype) return;

		frappe.call({
			method: "document_visibility.api.get_field_options",
			args: { reference_doctype: frm.doc.reference_doctype },
			callback: ({ message }) => {
				if (!message) return;
				frm.__dvr_fields = message;
				const hint = __("Available fields: {0}", [message.join(", ")]);
				EXPRESSION_FIELDS.forEach((fieldname) => {
					frm.set_df_property(fieldname, "description", hint);
				});
			},
		});
	},
});

// Compiles the expression server-side and shows the resulting SQL, or the
// error, under the field. Turns the black box into something readable.
function preview(frm, fieldname) {
	const field = frm.get_field(fieldname);
	if (!field || !frm.doc.reference_doctype) return;

	const expression = frm.doc[fieldname];
	const wrapper = get_preview_area(field);

	if (!expression) {
		wrapper.empty();
		return;
	}

	frappe.call({
		method: "document_visibility.api.preview_expression",
		args: { expression, reference_doctype: frm.doc.reference_doctype },
		callback: ({ message }) => {
			if (!message) return;
			wrapper.empty();
			if (message.ok) {
				wrapper.append(
					$("<div>")
						.css({ "font-family": "monospace", "font-size": "11px", color: "var(--text-muted)" })
						.text(message.sql)
				);
			} else {
				wrapper.append(
					$("<div>")
						.css({ "font-size": "11px", color: "var(--red-500)" })
						.text(message.error)
				);
			}
		},
	});
}

function get_preview_area(field) {
	if (!field.__dvr_preview) {
		field.__dvr_preview = $("<div class='dvr-preview' style='margin-top:4px'></div>").appendTo(
			field.$wrapper
		);
	}
	return field.__dvr_preview;
}

function debug_visibility(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Explain Visibility"),
		fields: [
			{
				fieldname: "user",
				fieldtype: "Link",
				options: "User",
				label: __("User"),
				reqd: 1,
			},
			{
				fieldname: "reference_doctype_holder",
				fieldtype: "Data",
				hidden: 1,
				default: frm.doc.reference_doctype,
			},
			{
				fieldname: "docname",
				fieldtype: "Dynamic Link",
				options: "reference_doctype_holder",
				label: __("Document"),
				reqd: 1,
			},
			{ fieldname: "result", fieldtype: "HTML" },
		],
		primary_action_label: __("Explain"),
		primary_action(values) {
			frappe.call({
				method: "document_visibility.api.explain_visibility",
				args: {
					reference_doctype: frm.doc.reference_doctype,
					docname: values.docname,
					user: values.user,
				},
				callback: ({ message }) => {
					if (message) render_explanation(dialog, message);
				},
			});
		},
	});
	dialog.show();
}

function render_explanation(dialog, result) {
	const rows = (result.rules || [])
		.map(
			(rule) => `
				<tr>
					<td>${frappe.utils.escape_html(rule.role)}</td>
					<td>${rule.base_visibility ? __("matched") : __("no match")}</td>
					<td>${
						rule.restricted
							? rule.restriction_passed === null
								? "-"
								: rule.restriction_passed
									? __("passed")
									: __("excluded")
							: __("none")
					}</td>
					<td><b>${rule.grants_access ? __("grants access") : __("no access")}</b></td>
				</tr>`
		)
		.join("");

	const table = rows
		? `<table class="table table-bordered" style="margin-top:12px">
				<thead>
					<tr>
						<th>${__("Role")}</th>
						<th>${__("Base visibility")}</th>
						<th>${__("Restriction")}</th>
						<th>${__("Verdict")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>`
		: "";

	dialog.fields_dict.result.$wrapper.html(`
		<div class="alert alert-${result.visible ? "success" : "warning"}">
			<b>${result.visible ? __("Visible") : __("Not visible")}</b><br>
			${frappe.utils.escape_html(result.reason || "")}
		</div>
		${table}
	`);
}
