"""ERPNext Item Integration and Synchronization

This module provides functions for synchronizing PIM products with ERPNext Items.
These functions are called as doc_events hooks when Item documents are
created, updated, or deleted in ERPNext.

The sync is bidirectional:
- ERPNext Item changes trigger PIM product updates (on_item_*)
- PIM Product Variant creation can create ERPNext Items (create_erp_item)

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def on_item_insert(doc, method=None):
    """Handle ERPNext Item creation.

    Called when a new Item is created in ERPNext. If the Item was not
    created from PIM, this can trigger creation of a corresponding
    Product Variant in PIM.

    Args:
        doc: The Item document being inserted
        method: The hook method name (unused, for Frappe hook signature)
    """
    import frappe

    if not _is_erpnext_installed():
        return

    # Skip if this Item was created from PIM (to avoid loops)
    if doc.get("flags", {}).get("from_pim"):
        return

    # Check if PIM sync is enabled
    if not _is_pim_sync_enabled():
        return

    try:
        # Log the sync event
        frappe.log_error(
            message=f"Item created: {doc.name}",
            title="PIM ERP Sync - Item Insert"
        )

        # Check if a Product Variant already exists for this item
        if frappe.db.exists("Product Variant", {"erp_item": doc.name}):
            return

        # Auto-create Product Variant from Item is optional
        # Only do this if explicitly configured
        if frappe.db.get_single_value("PIM Settings", "auto_create_variant_from_item"):
            _create_product_variant_from_item(doc)

    except Exception as e:
        frappe.log_error(
            message=f"Error syncing Item {doc.name}: {str(e)}",
            title="PIM ERP Sync Error"
        )


def on_item_update(doc, method=None):
    """Handle ERPNext Item update.

    Called when an Item is updated in ERPNext. Syncs relevant changes
    to the corresponding Product Variant in PIM if one exists.

    Args:
        doc: The Item document being updated
        method: The hook method name (unused, for Frappe hook signature)
    """
    import frappe

    if not _is_erpnext_installed():
        return

    # Skip if this update originated from PIM
    if doc.get("flags", {}).get("from_pim"):
        return

    if not _is_pim_sync_enabled():
        return

    try:
        # Find linked Product Variant
        variant_name = frappe.db.get_value(
            "Product Variant",
            {"erp_item": doc.name},
            "name"
        )

        if not variant_name:
            return

        # Update Product Variant fields from Item
        variant = frappe.get_doc("Product Variant", variant_name)

        # Map Item fields to Variant fields
        field_mapping = {
            "item_name": "variant_name",
            "description": "description",
            "stock_uom": "uom",
        }

        has_changes = False
        for item_field, variant_field in field_mapping.items():
            item_value = doc.get(item_field)
            if item_value and variant.get(variant_field) != item_value:
                variant.set(variant_field, item_value)
                has_changes = True

        if has_changes:
            variant.flags.from_erp = True
            variant.save(ignore_permissions=True)
            frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            message=f"Error syncing Item update {doc.name}: {str(e)}",
            title="PIM ERP Sync Error"
        )


def on_item_delete(doc, method=None):
    """Handle ERPNext Item deletion.

    Called when an Item is deleted in ERPNext. Clears the erp_item
    reference in the corresponding Product Variant if one exists.
    Does not delete the Product Variant itself.

    Args:
        doc: The Item document being deleted
        method: The hook method name (unused, for Frappe hook signature)
    """
    import frappe

    if not _is_erpnext_installed():
        return

    if not _is_pim_sync_enabled():
        return

    try:
        # Find and unlink Product Variant
        variant_name = frappe.db.get_value(
            "Product Variant",
            {"erp_item": doc.name},
            "name"
        )

        if variant_name:
            frappe.db.set_value(
                "Product Variant",
                variant_name,
                "erp_item",
                None,
                update_modified=False
            )
            frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            message=f"Error handling Item deletion {doc.name}: {str(e)}",
            title="PIM ERP Sync Error"
        )


def create_erp_item(variant):
    """Create an ERPNext Item from a Product Variant.

    Creates a new Item in ERPNext based on the Product Variant data.
    Links the Item back to the Variant via the erp_item field.

    Args:
        variant: Product Variant document to create Item from

    Returns:
        str: Name of the created Item, or None if creation failed

    Raises:
        frappe.ValidationError: If ERPNext is not installed
    """
    import frappe
    from frappe import _

    if not _is_erpnext_installed():
        frappe.throw(_("ERPNext is not installed. Cannot create Item."))

    # Check if Item already exists
    if variant.get("erp_item") and frappe.db.exists("Item", variant.erp_item):
        return variant.erp_item

    # Check if an Item with the same code already exists
    if variant.get("sku") and frappe.db.exists("Item", variant.sku):
        # Link existing Item
        variant.db_set("erp_item", variant.sku, update_modified=False)
        return variant.sku

    try:
        # Get parent product info
        parent_doc = None
        if variant.get("parent_product"):
            parent_doc = frappe.get_doc("Product Master", variant.parent_product)

        # Build Item document
        item_data = {
            "doctype": "Item",
            "item_code": variant.sku or variant.name,
            "item_name": variant.variant_name or variant.name,
            "item_group": _get_item_group(variant, parent_doc),
            "stock_uom": variant.get("uom") or "Nos",
            "is_stock_item": 1,
            "description": variant.get("description") or "",
        }

        # Add custom fields if they exist
        if variant.get("barcode"):
            item_data["barcodes"] = [{
                "barcode": variant.barcode,
                "barcode_type": "EAN"
            }]

        # Create the Item
        item = frappe.get_doc(item_data)
        item.flags.from_pim = True
        item.insert(ignore_permissions=True)

        # Link Item to Variant
        variant.db_set("erp_item", item.name, update_modified=False)
        frappe.db.commit()

        return item.name

    except Exception as e:
        frappe.log_error(
            message=f"Error creating Item from Variant {variant.name}: {str(e)}",
            title="PIM ERP Sync Error"
        )
        return None


def sync_to_erp_item(variant):
    """Sync Product Variant changes to linked ERPNext Item.

    Updates the linked ERPNext Item with current Product Variant data.
    Creates the Item if it doesn't exist and auto_create is enabled.

    Args:
        variant: Product Variant document to sync

    Returns:
        bool: True if sync was successful, False otherwise
    """
    import frappe

    if not _is_erpnext_installed():
        return False

    if not _is_pim_sync_enabled():
        return False

    try:
        # Create Item if not exists
        if not variant.get("erp_item"):
            auto_create = frappe.db.get_single_value(
                "PIM Settings",
                "auto_create_item_from_variant"
            )
            if auto_create:
                create_erp_item(variant)
                return True
            return False

        # Check if Item exists
        if not frappe.db.exists("Item", variant.erp_item):
            variant.db_set("erp_item", None, update_modified=False)
            return False

        # Update Item from Variant
        item = frappe.get_doc("Item", variant.erp_item)

        # Map Variant fields to Item fields
        field_mapping = {
            "variant_name": "item_name",
            "description": "description",
            "uom": "stock_uom",
        }

        has_changes = False
        for variant_field, item_field in field_mapping.items():
            variant_value = variant.get(variant_field)
            if variant_value and item.get(item_field) != variant_value:
                item.set(item_field, variant_value)
                has_changes = True

        if has_changes:
            item.flags.from_pim = True
            item.save(ignore_permissions=True)
            frappe.db.commit()

        return True

    except Exception as e:
        frappe.log_error(
            message=f"Error syncing Variant {variant.name} to Item: {str(e)}",
            title="PIM ERP Sync Error"
        )
        return False


def _is_erpnext_installed():
    """Check if ERPNext is installed.

    Returns:
        bool: True if ERPNext is installed and Item DocType exists
    """
    import frappe

    try:
        return frappe.db.exists("DocType", "Item")
    except Exception:
        return False


def _is_pim_sync_enabled():
    """Check if PIM-ERP sync is enabled in settings.

    Returns:
        bool: True if sync is enabled, False otherwise
    """
    import frappe

    try:
        # Check if PIM Settings exists and sync is enabled
        if not frappe.db.exists("DocType", "PIM Settings"):
            # Default to enabled if settings don't exist
            return True
        return frappe.db.get_single_value("PIM Settings", "enable_erp_sync") or True
    except Exception:
        return True


def _get_item_group(variant, parent_doc=None):
    """Get the appropriate Item Group for a Product Variant.

    Tries to map Product Family to Item Group, falls back to default.

    Args:
        variant: Product Variant document
        parent_doc: Optional parent Product Master document

    Returns:
        str: Item Group name
    """
    import frappe

    default_group = "Products"

    try:
        # First check if the default group exists
        if not frappe.db.exists("Item Group", default_group):
            # Use first available Item Group
            groups = frappe.get_all("Item Group", limit=1, pluck="name")
            if groups:
                default_group = groups[0]
            else:
                default_group = "All Item Groups"

        # Try to get family from parent product
        family = None
        if parent_doc and parent_doc.get("product_family"):
            family = parent_doc.product_family
        elif variant.get("product_family"):
            family = variant.product_family

        if not family:
            return default_group

        # Check if a matching Item Group exists
        # Try exact match first
        if frappe.db.exists("Item Group", family):
            return family

        # Try to find by family mapping (if custom field exists)
        mapped_group = frappe.db.get_value(
            "Product Family",
            family,
            "item_group"
        )
        if mapped_group and frappe.db.exists("Item Group", mapped_group):
            return mapped_group

        return default_group

    except Exception:
        return default_group


def _create_product_variant_from_item(item):
    """Create a Product Variant from an ERPNext Item.

    Internal function called when auto-creation is enabled and
    an Item is created in ERPNext.

    Args:
        item: Item document to create Variant from
    """
    import frappe

    try:
        variant = frappe.get_doc({
            "doctype": "Product Variant",
            "sku": item.item_code,
            "variant_name": item.item_name,
            "description": item.description or "",
            "uom": item.stock_uom or "Nos",
            "erp_item": item.name,
            "status": "Draft"
        })
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(
            message=f"Error creating Variant from Item {item.name}: {str(e)}",
            title="PIM ERP Sync Error"
        )
