# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ImportFieldMapping(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attribute_code: DF.Link | None
		create_if_missing: DF.Check
		data_type: DF.Literal[
			"Text", "Number", "Decimal", "Boolean", "Date", "Datetime", "JSON", "HTML"
		]
		default_value: DF.Data | None
		enabled: DF.Check
		field_type: DF.Literal[
			"Standard Field",
			"Attribute",
			"Classification",
			"Relationship",
			"Media URL",
			"Custom",
		]
		is_identifier: DF.Check
		is_required: DF.Check
		lookup_doctype: DF.Link | None
		lookup_field: DF.Data | None
		notes: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		scope_channel: DF.Link | None
		scope_locale: DF.Link | None
		source_field: DF.Data
		target_field: DF.Data
		transformation: DF.Literal[
			"",
			"None",
			"Uppercase",
			"Lowercase",
			"Trim",
			"Slugify",
			"Number Format",
			"Date Parse",
			"Boolean Parse",
			"JSON Parse",
			"Split to Array",
			"Custom Script",
		]
		transformation_config: DF.Code | None
		validation_error_message: DF.Data | None
		validation_regex: DF.Data | None
	# end: auto-generated types

	pass

