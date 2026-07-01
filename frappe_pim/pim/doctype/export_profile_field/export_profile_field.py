# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ExportProfileField(Document):
    """Export Profile Field child table for defining fields to include in exports.

    This child table allows users to configure which fields should be included
    in a product data export. Each row represents a single field to export with
    options for:
    - field_name: The actual field name from the source DocType
    - field_label: Human-readable label for the field
    - source_doctype: Which DocType the field comes from
    - export_column_name: Custom column header in the export output
    - sort_order: Order of columns in the export
    - is_enabled: Toggle to include/exclude the field
    - is_required: Whether the field must have a value for export
    - default_value: Fallback value if field is empty
    - transformation: Optional value transformation (uppercase, lowercase, etc.)
    - max_length: Character limit for truncation
    """

    pass
