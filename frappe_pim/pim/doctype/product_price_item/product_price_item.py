# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProductPriceItem(Document):
    def validate(self):
        """Validate price item data."""
        self.validate_date_range()
        self.validate_min_qty()

    def validate_date_range(self):
        """Ensure valid_from is before valid_to if both are set."""
        if self.valid_from and self.valid_to:
            if self.valid_from > self.valid_to:
                frappe.throw(
                    frappe._("Valid From date cannot be after Valid To date")
                )

    def validate_min_qty(self):
        """Ensure min_qty is positive."""
        if self.min_qty is not None and self.min_qty < 0:
            frappe.throw(frappe._("Minimum quantity cannot be negative"))
