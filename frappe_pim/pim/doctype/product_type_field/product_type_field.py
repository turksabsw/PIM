# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductTypeField(Document):
    """Child table controller for Product Type Fields.

    This child table stores custom field definitions for PIM Product Types,
    implementing a Drupal-style entity/bundle pattern where each Product Type
    can define its own set of fields.

    Fields:
        fieldname: Unique field identifier (e.g., 'color', 'material')
        label: Human-readable field label
        fieldtype: Type of field (Data, Int, Float, Check, Select, Link, Table, Text Editor)
        options: Options for Select/Link field types
        reqd: Whether the field is mandatory
        default_value: Default value for the field
        sort_order: Order in which fields appear in the form
    """
    pass
