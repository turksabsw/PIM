"""PIM Bundle Utilities

This module provides utility functions for PIM Bundle management including
pricing calculations, validation, and ERPNext sync helpers.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def calculate_bundle_pricing(doc, method=None):
    """Calculate bundle pricing before save.

    Calculates the bundle's total price, savings, and validates pricing rules
    based on the bundle type and pricing method.

    Args:
        doc: The PIM Bundle document being saved
        method: The hook method name (unused, for Frappe hook signature)

    Pricing Methods:
        - Fixed: Uses base_price as the final price
        - Sum: Adds up all slot prices
        - Discounted Sum: Sum with discount applied
        - Tiered: Price based on quantity tiers
    """
    import frappe
    from frappe.utils import flt

    try:
        pricing_method = doc.get("pricing_method") or "Sum"
        total_price = flt(0)
        original_price = flt(0)
        total_items = 0

        # Calculate price based on slots
        if doc.get("slots"):
            for slot in doc.slots:
                slot_qty = flt(slot.get("qty") or 1)
                total_items += slot_qty

                # Get slot product price
                slot_price = _get_slot_price(slot)
                slot_total = slot_price * slot_qty

                # Apply price modifier if set
                modifier_type = slot.get("price_modifier_type")
                modifier_value = flt(slot.get("price_modifier") or 0)

                if modifier_type == "Percentage":
                    slot_total = slot_total * (1 + modifier_value / 100)
                elif modifier_type == "Fixed":
                    slot_total = slot_total + modifier_value

                original_price += slot_price * slot_qty
                total_price += slot_total

        # Apply bundle-level pricing based on method
        if pricing_method == "Fixed":
            final_price = flt(doc.get("base_price") or 0)
        elif pricing_method == "Sum":
            final_price = total_price
        elif pricing_method == "Discounted Sum":
            discount_type = doc.get("discount_type")
            discount_value = flt(doc.get("discount_value") or 0)

            if discount_type == "Percentage":
                final_price = total_price * (1 - discount_value / 100)
            else:  # Fixed amount
                final_price = total_price - discount_value

            final_price = max(flt(0), final_price)  # Don't go negative
        elif pricing_method == "Tiered":
            final_price = _get_tiered_price(doc, total_items)
        else:
            final_price = total_price

        # Calculate savings
        savings_amount = original_price - final_price
        savings_percent = flt(0)
        if original_price > 0:
            savings_percent = (savings_amount / original_price) * 100

        # Update document fields
        doc.total_items = total_items
        doc.calculated_price = final_price
        doc.savings_amount = max(flt(0), savings_amount)
        doc.savings_percent = max(flt(0), savings_percent)

    except Exception as e:
        frappe.log_error(
            message=f"Error calculating bundle pricing for {doc.name}: {str(e)}",
            title="PIM Bundle Pricing Error"
        )


def _get_slot_price(slot):
    """Get the price for a bundle slot.

    Args:
        slot: PIM Bundle Slot child document

    Returns:
        float: The slot product price
    """
    import frappe
    from frappe.utils import flt

    # Check for variant price
    variant = slot.get("product_variant")
    if variant:
        price = frappe.db.get_value(
            "Product Variant",
            variant,
            "price"
        )
        if price:
            return flt(price)

        # Fallback to ERP Item Price
        erp_item = frappe.db.get_value(
            "Product Variant",
            variant,
            "erp_item"
        )
        if erp_item:
            item_price = frappe.db.get_value(
                "Item Price",
                {"item_code": erp_item, "selling": 1},
                "price_list_rate"
            )
            if item_price:
                return flt(item_price)

    # Check for master product price
    master = slot.get("product_master")
    if master:
        price = frappe.db.get_value(
            "Product Master",
            master,
            "base_price"
        )
        if price:
            return flt(price)

    return flt(0)


def _get_tiered_price(doc, total_items):
    """Get tiered price based on quantity.

    Args:
        doc: The PIM Bundle document
        total_items: Total number of items in the bundle

    Returns:
        float: The tiered price
    """
    import frappe
    from frappe.utils import flt

    # Check tiered pricing table
    if doc.get("tiered_pricing"):
        for tier in sorted(doc.tiered_pricing, key=lambda x: x.min_qty, reverse=True):
            if total_items >= flt(tier.get("min_qty") or 0):
                return flt(tier.get("price") or 0)

    # Fallback to base price
    return flt(doc.get("base_price") or 0)


def validate_bundle_slots(doc):
    """Validate bundle slots configuration.

    Args:
        doc: The PIM Bundle document

    Raises:
        frappe.ValidationError: If validation fails
    """
    import frappe
    from frappe import _
    from frappe.utils import flt

    if not doc.get("slots") and doc.bundle_type not in ["Dynamic", "Build Your Own"]:
        frappe.throw(_("Static and Configurable bundles require at least one slot"))

    seen_slot_codes = set()
    for idx, slot in enumerate(doc.get("slots") or [], 1):
        # Check for duplicate slot codes
        slot_code = slot.get("slot_code")
        if slot_code:
            if slot_code in seen_slot_codes:
                frappe.throw(_("Duplicate slot code '{0}' in row {1}").format(slot_code, idx))
            seen_slot_codes.add(slot_code)

        # Validate quantity constraints
        min_qty = flt(slot.get("min_qty") or 0)
        max_qty = flt(slot.get("max_qty") or 0)
        qty = flt(slot.get("qty") or 0)

        if min_qty > 0 and qty < min_qty:
            frappe.throw(_("Quantity in slot row {0} must be at least {1}").format(idx, min_qty))

        if max_qty > 0 and qty > max_qty:
            frappe.throw(_("Quantity in slot row {0} cannot exceed {1}").format(idx, max_qty))

        # Validate product selection
        if slot.get("is_required") and not slot.get("product_variant") and not slot.get("product_master"):
            frappe.throw(_("Required slot in row {0} must have a product selected").format(idx))


def get_bundle_by_code(bundle_code):
    """Get a bundle by its code.

    Args:
        bundle_code: The bundle code to look up

    Returns:
        PIM Bundle document or None
    """
    import frappe

    bundle_name = frappe.db.get_value(
        "PIM Bundle",
        {"bundle_code": bundle_code},
        "name"
    )

    if bundle_name:
        return frappe.get_doc("PIM Bundle", bundle_name)

    return None


def get_active_bundles(bundle_type=None, channel=None):
    """Get all active bundles, optionally filtered.

    Args:
        bundle_type: Filter by bundle type (Static, Configurable, Dynamic, Build Your Own)
        channel: Filter by channel availability

    Returns:
        list: List of active bundle documents
    """
    import frappe

    filters = {"status": "Active"}

    if bundle_type:
        filters["bundle_type"] = bundle_type

    bundles = frappe.get_all(
        "PIM Bundle",
        filters=filters,
        fields=["name", "bundle_name", "bundle_code", "bundle_type",
                "calculated_price", "savings_percent", "total_items"]
    )

    # Filter by channel if specified
    if channel:
        bundles = [
            b for b in bundles
            if _bundle_available_for_channel(b.name, channel)
        ]

    return bundles


def _bundle_available_for_channel(bundle_name, channel):
    """Check if a bundle is available for a specific channel.

    Args:
        bundle_name: Name of the PIM Bundle
        channel: Channel to check availability for

    Returns:
        bool: True if available
    """
    import frappe

    doc = frappe.get_doc("PIM Bundle", bundle_name)

    if doc.get("all_channels"):
        return True

    channels = doc.get("channels") or []
    return channel in [c.get("channel") for c in channels]
