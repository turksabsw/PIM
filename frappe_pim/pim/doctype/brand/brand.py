"""
Brand Controller
Manages product brands for PIM
"""

import frappe
from frappe import _
from frappe.model.document import Document
import re


class Brand(Document):
    def validate(self):
        self.validate_brand_code()

    def validate_brand_code(self):
        """Ensure brand_code is URL-safe slug"""
        if not self.brand_code:
            # Auto-generate from brand_name
            self.brand_code = frappe.scrub(self.brand_name)

        # Must be lowercase, no spaces, alphanumeric with underscores/hyphens
        if not re.match(r'^[a-z][a-z0-9_-]*$', self.brand_code):
            frappe.throw(
                _("Brand Code must start with a letter and contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Brand Code")
            )

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        # Check if any products are using this brand
        product_count = frappe.db.count("Product Master", {"brand": self.name})
        if product_count > 0:
            frappe.throw(
                _("Cannot delete brand '{0}' as it is used by {1} product(s). "
                  "Please delete or reassign these products first.").format(
                    self.brand_name, product_count
                ),
                title=_("Brand In Use")
            )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:brand:{self.name}")
            frappe.cache().delete_key("pim:all_brands")
        except Exception:
            pass


@frappe.whitelist()
def get_brands(enabled_only=True):
    """Get all brands ordered by brand_name

    Args:
        enabled_only: If True, return only enabled brands
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1

    return frappe.get_all(
        "Brand",
        filters=filters,
        fields=[
            "name", "brand_name", "brand_code", "enabled"
        ],
        order_by="brand_name asc"
    )
