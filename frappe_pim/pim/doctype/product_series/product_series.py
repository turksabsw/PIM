# Copyright (c) 2024, Frappe PIM Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import re


class ProductSeries(Document):
    def validate(self):
        self.validate_series_code()
        self.validate_parent()
        self.validate_dates()

    def validate_series_code(self):
        """Ensure series_code is URL-safe slug"""
        if not self.series_code:
            self.series_code = frappe.scrub(self.series_name)

        if not re.match(r'^[a-z][a-z0-9_-]*$', self.series_code):
            frappe.throw(
                _("Series Code must start with a letter and contain only lowercase letters, numbers, hyphens, and underscores"),
                title=_("Invalid Series Code")
            )

    def validate_parent(self):
        """Prevent circular references in series hierarchy"""
        if not self.parent_series:
            return

        if self.parent_series == self.name:
            frappe.throw(
                _("A series cannot be its own parent"),
                title=_("Invalid Parent")
            )

        visited = set([self.name])
        current = self.parent_series

        while current:
            if current in visited:
                frappe.throw(
                    _("Circular reference detected in series hierarchy"),
                    title=_("Invalid Parent")
                )
            visited.add(current)
            parent = frappe.db.get_value("Product Series", current, "parent_series")
            current = parent

    def validate_dates(self):
        """Validate date range"""
        if self.valid_from and self.valid_to:
            if self.valid_from > self.valid_to:
                frappe.throw(
                    _("Valid From date cannot be after Valid To date"),
                    title=_("Invalid Date Range")
                )

    def on_trash(self):
        """Prevent deletion if series has products or children"""
        product_count = frappe.db.count("Product Master", {"product_series": self.name})
        if product_count > 0:
            frappe.throw(
                _("Cannot delete series '{0}' as it has {1} product(s)").format(
                    self.series_name, product_count
                ),
                title=_("Series In Use")
            )

        child_count = frappe.db.count("Product Series", {"parent_series": self.name})
        if child_count > 0:
            frappe.throw(
                _("Cannot delete series '{0}' as it has {1} child series").format(
                    self.series_name, child_count
                ),
                title=_("Series Has Children")
            )
