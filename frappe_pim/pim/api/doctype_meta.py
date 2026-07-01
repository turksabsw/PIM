# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt

"""
API for DocType metadata – used by the PIM frontend to render forms
with the same fields as Frappe Desk (all fields, correct types, child tables).
"""

from __future__ import unicode_literals

import frappe


@frappe.whitelist()
def get_doctype_meta(doctype):
	"""
	Return field metadata for a DocType so the frontend can render
	a full form (all fields, types, options) like Frappe Desk.

	Returns:
		dict with:
		- fields: list of { fieldname, label, fieldtype, options, reqd, read_only, hidden }
		- child_tables: dict mapping fieldname -> { doctype, fields: [...] }
	"""
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(frappe._("No read permission for {0}").format(doctype), frappe.PermissionError)
	meta = frappe.get_meta(doctype)
	out = {
		"doctype": doctype,
		"fields": [],
		"child_tables": {},
	}
	for df in meta.fields:
		if getattr(df, "hidden", 0):
			continue
		field_info = {
			"fieldname": df.fieldname,
			"label": df.label or df.fieldname.replace("_", " ").title(),
			"fieldtype": df.fieldtype,
			"options": df.options or "",
			"reqd": 1 if getattr(df, "reqd", 0) else 0,
			"read_only": 1 if getattr(df, "read_only", 0) else 0,
			"description": (df.description or "").strip(),
		}
		if df.fieldtype in ("Table", "Table MultiSelect"):
			child_meta = frappe.get_meta(df.options)
			child_fields = []
			for cdf in child_meta.fields:
				if getattr(cdf, "hidden", 0):
					continue
				child_fields.append({
					"fieldname": cdf.fieldname,
					"label": cdf.label or cdf.fieldname.replace("_", " ").title(),
					"fieldtype": cdf.fieldtype,
					"options": cdf.options or "",
					"reqd": 1 if getattr(cdf, "reqd", 0) else 0,
					"read_only": 1 if getattr(cdf, "read_only", 0) else 0,
				})
			out["child_tables"][df.fieldname] = {
				"doctype": df.options,
				"fields": child_fields,
			}
		out["fields"].append(field_info)
	return out
