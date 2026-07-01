"""
Manufacturer Controller
Manages product manufacturers for PIM
"""

import frappe
from frappe import _
from frappe.model.document import Document
import re


class Manufacturer(Document):
    def validate(self):
        self.validate_manufacturer_code()

    def validate_manufacturer_code(self):
        """Ensure manufacturer_code is URL-safe slug"""
        if not self.manufacturer_code:
            # Auto-generate from manufacturer_name
            self.manufacturer_code = frappe.scrub(self.manufacturer_name)

        # Must be lowercase, no spaces, alphanumeric with underscores/hyphens
        if not re.match(r'^[a-z][a-z0-9_-]*$', self.manufacturer_code):
            frappe.throw(
                _("Manufacturer Code must start with a letter and contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Manufacturer Code")
            )

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        # Check if any products are using this manufacturer
        product_count = frappe.db.count("Product Master", {"manufacturer": self.name})
        if product_count > 0:
            frappe.throw(
                _("Cannot delete manufacturer '{0}' as it is used by {1} product(s). "
                  "Please delete or reassign these products first.").format(
                    self.manufacturer_name, product_count
                ),
                title=_("Manufacturer In Use")
            )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:manufacturer:{self.name}")
            frappe.cache().delete_key("pim:all_manufacturers")
        except Exception:
            pass


@frappe.whitelist()
def get_manufacturers(enabled_only=True):
    """Get all manufacturers ordered by manufacturer_name

    Args:
        enabled_only: If True, return only enabled manufacturers
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1

    return frappe.get_all(
        "Manufacturer",
        filters=filters,
        fields=[
            "name", "manufacturer_name", "manufacturer_code", "enabled"
        ],
        order_by="manufacturer_name asc"
    )
