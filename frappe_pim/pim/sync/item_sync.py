# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

"""
Item Sync Module

Handles bidirectional synchronization between ERPNext Item and PIM entities.

This module provides event handlers for Item document events to ensure
that changes made to Items in ERPNext are reflected in Product Master
(Virtual DocType) and Product Variant.

The sync uses flags to prevent infinite loops:
- _from_pim_sync: Set by Product Master/Variant when modifying an Item
- from_pim: Set by erp_sync.py utility when creating/updating Items
- _from_variant_generation: Set during variant generation
- _from_erpnext_sync: Set by this module when syncing to Product Variant
"""

import frappe
from frappe import _
from frappe.utils import now_datetime


# ============================================================================
# SYNC FLAG HELPERS
# ============================================================================

def _is_from_pim(doc):
    """
    Check if this document operation originated from PIM.

    Checks multiple flag names for compatibility across modules:
    - _from_pim_sync: Set by Product Master and Product Variant controllers
    - from_pim: Set by erp_sync.py utility functions and queue processor

    Args:
        doc: The document to check

    Returns:
        bool: True if operation originated from PIM
    """
    return (
        getattr(doc.flags, "_from_pim_sync", False)
        or getattr(doc.flags, "from_pim", False)
    )


def _is_pim_sync_enabled():
    """
    Check if PIM-ERP sync is enabled in settings.

    Returns:
        bool: True if sync is enabled (defaults to True if settings don't exist)
    """
    try:
        if not frappe.db.exists("DocType", "PIM Settings"):
            return True
        return frappe.db.get_single_value("PIM Settings", "enable_erp_sync") or True
    except Exception:
        return True


# ============================================================================
# ITEM EVENT HANDLERS
# ============================================================================

def on_item_update(doc, method=None):
    """
    Handle Item on_update event.

    Syncs Item changes to Product Master (cache invalidation) and/or
    Product Variant if the Item was not updated from PIM.

    Args:
        doc: The Item document being updated
        method: The method name (unused, required by Frappe hooks)
    """
    # Skip if this update originated from PIM sync
    # Check both flag names: _from_pim_sync (set by Product Master/Variant)
    # and from_pim (set by erp_sync.py utility)
    if _is_from_pim(doc):
        return

    # Skip if this is a variant being created by PIM
    if getattr(doc.flags, "_from_variant_generation", False):
        return

    # Skip if PIM sync is globally disabled
    if not _is_pim_sync_enabled():
        return

    # Check if this Item has PIM data (was created/managed by PIM)
    if not _is_pim_managed_item(doc):
        return

    try:
        # Sync to Product Variant if linked
        variant_name = _get_linked_product_variant(doc.name)
        if variant_name:
            _sync_item_to_product_variant(doc, variant_name)

        # Always invalidate Product Master cache since it's a Virtual DocType
        _invalidate_product_master_cache(doc)
    except Exception as e:
        # Log error but don't block the Item save
        frappe.log_error(
            message=f"Failed to sync Item {doc.name} to PIM: {str(e)}",
            title="PIM Sync Error"
        )


def on_item_insert(doc, method=None):
    """
    Handle Item after_insert event.

    If an Item is created directly in ERPNext (not via PIM), we may want
    to create a corresponding Product Master record or ignore it based
    on configuration.

    Args:
        doc: The Item document being inserted
        method: The method name (unused, required by Frappe hooks)
    """
    # Skip if this insert originated from PIM sync
    if _is_from_pim(doc):
        return

    # Skip if this is a variant being created by PIM
    if getattr(doc.flags, "_from_variant_generation", False):
        return

    # Skip if PIM sync is globally disabled
    if not _is_pim_sync_enabled():
        return

    # For now, we don't auto-create Product Master for new Items
    # This could be enabled via a setting in the future
    # _create_product_master_for_item(doc)

    frappe.logger("pim_sync").debug(
        f"New Item {doc.name} created outside PIM"
    )


def on_item_trash(doc, method=None):
    """
    Handle Item on_trash event.

    When an Item is deleted, we need to:
    1. Clean up Product Master child tables (since PM is a Virtual DocType,
       deleting the Item effectively deletes the Product Master too)
    2. Unlink any associated Product Variant

    Args:
        doc: The Item document being deleted
        method: The method name (unused, required by Frappe hooks)
    """
    # Skip if this delete originated from PIM sync
    if _is_from_pim(doc):
        return

    # Check if this Item has PIM data
    if not _is_pim_managed_item(doc):
        return

    try:
        _cleanup_pim_data(doc.name)
    except Exception as e:
        # Log error but don't block the Item delete
        frappe.log_error(
            message=f"Failed to cleanup PIM data for Item {doc.name}: {str(e)}",
            title="PIM Cleanup Error"
        )


# ============================================================================
# PIM MANAGED ITEM DETECTION
# ============================================================================

def _is_pim_managed_item(doc):
    """
    Check if an Item is managed by PIM.

    An Item is considered PIM-managed if it has any PIM custom fields set,
    has associated Product Master child table data, or has a linked Product
    Variant.

    Args:
        doc: The Item document

    Returns:
        bool: True if PIM-managed, False otherwise
    """
    # Check for PIM custom fields on Item
    pim_fields = [
        "custom_pim_sku",
        "custom_pim_status",
        "custom_pim_lifecycle_stage",
        "custom_pim_parent_product",
        "custom_pim_product_family",
        "custom_pim_product_type",
    ]

    for field in pim_fields:
        value = doc.get(field)
        if value:
            return True

    # Check for linked Product Variant
    if _get_linked_product_variant(doc.name):
        return True

    # Check for associated Product Master child table data
    child_tables = [
        "Product Media",
        "Product Attribute Value",
        "Product Price Item",
        "Product Channel",
        "Product Relation",
        "Product Supplier Item",
        "Product Certification Item",
        "Product Translation Item",
    ]

    for dt in child_tables:
        try:
            count = frappe.db.count(
                dt,
                {"parent": doc.name, "parenttype": "Product Master"}
            )
            if count > 0:
                return True
        except Exception:
            # Table might not exist yet
            pass

    return False


def _get_linked_product_variant(item_name):
    """
    Get the Product Variant linked to an Item.

    Args:
        item_name: The Item name to look up

    Returns:
        str or None: Product Variant name if linked, None otherwise
    """
    try:
        return frappe.db.get_value(
            "Product Variant",
            {"erp_item": item_name},
            "name"
        )
    except Exception:
        return None


# ============================================================================
# SYNC FUNCTIONS
# ============================================================================

def _sync_item_to_product_variant(item_doc, variant_name):
    """
    Sync Item changes to a linked Product Variant.

    Maps Item fields to Product Variant fields and saves with the
    _from_erpnext_sync flag to prevent infinite sync loops.

    Args:
        item_doc: The Item document
        variant_name: The name of the linked Product Variant
    """
    variant = frappe.get_doc("Product Variant", variant_name)

    # Map Item fields to Variant fields
    field_mapping = {
        "item_name": "variant_name",
        "description": "description",
        "stock_uom": "uom",
    }

    has_changes = False
    for item_field, variant_field in field_mapping.items():
        item_value = item_doc.get(item_field)
        if item_value and variant.get(variant_field) != item_value:
            variant.set(variant_field, item_value)
            has_changes = True

    if has_changes:
        # Set flag to prevent sync loop back to ERPNext
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.flags.ignore_version = True
        variant.save(ignore_permissions=True)

        frappe.logger("pim_sync").debug(
            f"Synced Item {item_doc.name} changes to Product Variant {variant_name}"
        )


def _invalidate_product_master_cache(item_doc):
    """
    Invalidate Product Master cache and notify listeners.

    Since Product Master is a Virtual DocType that reads from Item,
    this function ensures cached data is cleared and real-time
    listeners are notified of the change.

    Args:
        item_doc: The Item document
    """
    # Clear cached Product Master data
    cache_key = f"product_master_{item_doc.name}"
    frappe.cache().delete_value(cache_key)

    # Notify real-time listeners
    frappe.publish_realtime(
        "product_master_changed",
        {"product": item_doc.name},
        doctype="Product Master",
        docname=item_doc.name
    )

    frappe.logger("pim_sync").debug(
        f"Invalidated Product Master cache for Item {item_doc.name}"
    )


# ============================================================================
# CLEANUP FUNCTIONS
# ============================================================================

def _cleanup_pim_data(item_name):
    """
    Clean up all PIM data when an Item is deleted.

    Handles:
    1. Product Master child table records (since PM is a Virtual DocType)
    2. Unlinking associated Product Variant

    Args:
        item_name: The name of the Item being deleted
    """
    _cleanup_product_master_child_tables(item_name)
    _unlink_product_variant(item_name)

    # Clear cached data
    cache_key = f"product_master_{item_name}"
    frappe.cache().delete_value(cache_key)

    frappe.logger("pim_sync").info(
        f"Cleaned up PIM data for deleted Item {item_name}"
    )


def _cleanup_product_master_child_tables(item_name):
    """
    Clean up Product Master child table data when an Item is deleted.

    Since Product Master is a Virtual DocType, the "document" itself
    doesn't exist in the database. But the child tables do have their
    own records that need to be cleaned up.

    Args:
        item_name: The name of the Item being deleted
    """
    child_tables = [
        "Product Media",
        "Product Attribute Value",
        "Product Price Item",
        "Product Channel",
        "Product Relation",
        "Product Supplier Item",
        "Product Certification Item",
        "Product Translation Item",
    ]

    for dt in child_tables:
        try:
            frappe.db.delete(
                dt,
                {"parent": item_name, "parenttype": "Product Master"}
            )
            frappe.logger("pim_sync").debug(
                f"Cleaned up {dt} records for {item_name}"
            )
        except Exception as e:
            frappe.logger("pim_sync").warning(
                f"Could not clean up {dt} for {item_name}: {str(e)}"
            )


def _unlink_product_variant(item_name):
    """
    Unlink Product Variant from a deleted Item.

    Clears the erp_item reference on the Product Variant but does not
    delete the Variant itself.

    Args:
        item_name: The name of the Item being deleted
    """
    variant_name = _get_linked_product_variant(item_name)
    if variant_name:
        frappe.db.set_value(
            "Product Variant",
            variant_name,
            "erp_item",
            None,
            update_modified=False
        )
        frappe.logger("pim_sync").debug(
            f"Unlinked Product Variant {variant_name} from deleted Item {item_name}"
        )


def _create_product_master_for_item(item_doc):
    """
    Create a basic Product Master entry for an Item created outside PIM.

    This is a placeholder function that could be enabled via configuration
    to auto-create Product Master records for new Items.

    Args:
        item_doc: The Item document
    """
    # This function is not currently active
    # It would set basic PIM fields on the Item
    pass


# ============================================================================
# WHITELISTED API FUNCTIONS
# ============================================================================

@frappe.whitelist()
def sync_item_to_pim(item_name):
    """
    Manually trigger sync of an Item to PIM.

    This can be called from a button or script to force sync
    an Item's changes to the PIM system.

    Args:
        item_name: The name of the Item to sync

    Returns:
        dict: Status of the sync operation
    """
    if not item_name:
        frappe.throw(_("Item name is required"))

    if not frappe.db.exists("Item", item_name):
        frappe.throw(_("Item {0} does not exist").format(item_name))

    item_doc = frappe.get_doc("Item", item_name)

    try:
        # Sync to Product Variant if linked
        variant_name = _get_linked_product_variant(item_name)
        if variant_name:
            _sync_item_to_product_variant(item_doc, variant_name)

        # Always invalidate Product Master cache
        _invalidate_product_master_cache(item_doc)

        return {
            "success": True,
            "message": _("Item {0} synced to PIM successfully").format(item_name)
        }
    except Exception as e:
        frappe.log_error(
            message=str(e),
            title=f"Manual PIM Sync Error for {item_name}"
        )
        return {
            "success": False,
            "message": _("Failed to sync: {0}").format(str(e))
        }


@frappe.whitelist()
def bulk_sync_items_to_pim(item_names):
    """
    Bulk sync multiple Items to PIM.

    Args:
        item_names: List of Item names or JSON string of list

    Returns:
        dict: Summary of sync results
    """
    import json

    if isinstance(item_names, str):
        item_names = json.loads(item_names)

    if not item_names:
        frappe.throw(_("No items provided"))

    results = {
        "success": [],
        "failed": []
    }

    for item_name in item_names:
        result = sync_item_to_pim(item_name)
        if result.get("success"):
            results["success"].append(item_name)
        else:
            results["failed"].append({
                "item": item_name,
                "error": result.get("message")
            })

    return {
        "total": len(item_names),
        "synced": len(results["success"]),
        "failed": len(results["failed"]),
        "details": results
    }
