# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ProductSupplierItem(Document):
    def validate(self):
        """Validate supplier item data."""
        self.validate_min_order_qty()
        self.validate_lead_time()

    def validate_min_order_qty(self):
        """Ensure min_order_qty is positive."""
        if self.min_order_qty is not None and self.min_order_qty < 0:
            frappe.throw(frappe._("Minimum order quantity cannot be negative"))

    def validate_lead_time(self):
        """Ensure lead_time is non-negative."""
        if self.lead_time is not None and self.lead_time < 0:
            frappe.throw(frappe._("Lead time cannot be negative"))
