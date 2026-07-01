# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DataQualityRule(Document):
    """Data Quality Rule child table for configuring validation rules.

    This child table stores individual validation rules that are part of
    a Data Quality Policy. Each rule defines a specific validation check
    to be performed on product data.
    """
    pass
