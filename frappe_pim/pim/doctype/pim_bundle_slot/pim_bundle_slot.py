"""
PIM Bundle Slot Controller
Child table for PIM Bundle - defines individual slots/components within a bundle
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Defer frappe import to function level for module import without Frappe context

class PIMBundleSlot(Document):

        # Child tables typically don't need much validation
        # as they are validated at the parent level (PIM Bundle)

        def validate_qty_constraints(self):
            """Validate quantity constraints are logical"""
            if self.min_qty and self.max_qty and self.max_qty > 0:
                if self.min_qty > self.max_qty:
                    from frappe import _
                    import frappe
                    frappe.throw(_(
                        "Minimum quantity cannot be greater than maximum quantity for slot {0}"
                    ).format(self.slot_name))

            if self.qty:
                if self.min_qty and self.qty < self.min_qty:
                    from frappe import _
                    import frappe
                    frappe.throw(_(
                        "Default quantity cannot be less than minimum quantity for slot {0}"
                    ).format(self.slot_name))

                if self.max_qty and self.max_qty > 0 and self.qty > self.max_qty:
                    from frappe import _
                    import frappe
                    frappe.throw(_(
                        "Default quantity cannot be greater than maximum quantity for slot {0}"
                    ).format(self.slot_name))
# Helper functions for working with bundle slots

def get_slot_products(slot, limit=50):
    """Get available products for a configurable slot based on filters

    Args:
        slot: PIM Bundle Slot document or dict
        limit: Maximum number of products to return

    Returns:
        list: List of Product Variant names/dicts matching slot criteria
    """
    import frappe

    filters = {"disabled": 0}

    # Apply category filter
    if slot.get("allowed_category"):
        # Get products in category (need to join with Product Master)
        filters["category"] = slot.get("allowed_category")

    # Apply product type filter
    if slot.get("allowed_product_type"):
        filters["product_type"] = slot.get("allowed_product_type")

    # Apply brand filter
    if slot.get("allowed_brand"):
        filters["brand"] = slot.get("allowed_brand")

    # Apply custom filter expression if provided
    if slot.get("filter_expression"):
        try:
            import json
            custom_filters = json.loads(slot.get("filter_expression"))
            filters.update(custom_filters)
        except json.JSONDecodeError:
            pass

    return frappe.get_all(
        "Product Variant",
        filters=filters,
        fields=["name", "sku", "variant_name"],
        limit=limit,
        order_by="variant_name"
    )

def calculate_slot_price(slot, base_price=None):
    """Calculate the effective price for a slot including modifiers

    Args:
        slot: PIM Bundle Slot document or dict
        base_price: Base price of the product (if not provided, fetched from product)

    Returns:
        float: Calculated price for the slot
    """
    import frappe

    # Get base price from product if not provided
    if base_price is None and slot.get("product_variant"):
        variant = frappe.get_cached_doc("Product Variant", slot.get("product_variant"))
        base_price = variant.get("standard_selling_price") or 0

    if base_price is None:
        base_price = 0

    qty = slot.get("qty") or 1
    modifier = slot.get("price_modifier") or 0
    modifier_type = slot.get("price_modifier_type")

    # Calculate unit price with modifier
    if modifier_type == "Percentage":
        unit_price = base_price * (1 + modifier / 100)
    elif modifier_type == "Fixed Amount":
        unit_price = base_price + modifier
    else:
        unit_price = base_price

    return unit_price * qty

def validate_slot_selection(slot, selected_product):
    """Validate that a selected product is valid for a configurable slot

    Args:
        slot: PIM Bundle Slot document or dict
        selected_product: Product Variant name to validate

    Returns:
        tuple: (is_valid, error_message)
    """
    import frappe
    from frappe import _

    if not slot.get("is_configurable"):
        # Non-configurable slots only allow the fixed product
        if slot.get("product_variant") and selected_product != slot.get("product_variant"):
            return False, _("This slot is not configurable")
        return True, None

    # Get the product details
    if not frappe.db.exists("Product Variant", selected_product):
        return False, _("Product not found: {0}").format(selected_product)

    product = frappe.get_cached_doc("Product Variant", selected_product)

    # Validate category
    if slot.get("allowed_category"):
        master = frappe.get_cached_doc("Product Master", product.product_master)
        if master.category != slot.get("allowed_category"):
            return False, _("Product is not in the allowed category")

    # Validate product type
    if slot.get("allowed_product_type"):
        master = frappe.get_cached_doc("Product Master", product.product_master)
        if master.product_type != slot.get("allowed_product_type"):
            return False, _("Product is not of the allowed type")

    # Validate brand
    if slot.get("allowed_brand"):
        master = frappe.get_cached_doc("Product Master", product.product_master)
        if master.brand != slot.get("allowed_brand"):
            return False, _("Product is not from the allowed brand")

    return True, None
