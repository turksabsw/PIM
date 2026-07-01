# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class ProductCertificationItem(Document):
    def validate(self):
        self.validate_dates()

    def validate_dates(self):
        """Validate that valid_from is before valid_to"""
        if self.valid_from and self.valid_to:
            if getdate(self.valid_from) > getdate(self.valid_to):
                frappe.throw(
                    frappe._("Valid From date cannot be after Valid To date for certification {0}").format(
                        self.certification_name
                    )
                )
