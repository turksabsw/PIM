# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

"""
Bidirectional Sync Verification Script

This script provides functions to manually verify that the ERPNext Item ↔ Product Master
bidirectional synchronization works correctly without infinite loops.

Usage in Frappe Console:
    bench --site [site] console

    >>> from frappe_pim.pim.doctype.product_master.verify_sync import run_verification
    >>> run_verification()

Or run individual checks:
    >>> from frappe_pim.pim.doctype.product_master.verify_sync import *
    >>> check_pm_to_item_sync()
    >>> check_item_to_pm_sync()
    >>> check_no_infinite_loop()
"""

import frappe
from frappe.utils import random_string


def _print_status(message, status="info"):
    """Print a formatted status message."""
    icons = {
        "info": "",
        "success": "[OK]",
        "warning": "[WARN]",
        "error": "[FAIL]"
    }
    colors = {
        "info": "",
        "success": "\033[92m",
        "warning": "\033[93m",
        "error": "\033[91m"
    }
    reset = "\033[0m"
    icon = icons.get(status, "")
    color = colors.get(status, "")
    print(f"{color}{icon} {message}{reset}")


def _cleanup_test_item(item_name):
    """Clean up a test Item and its related data."""
    try:
        # Delete child tables
        child_tables = [
            "Product Media", "Product Attribute Value", "Product Price Item",
            "Product Channel", "Product Relation", "Product Supplier Item",
            "Product Certification Item", "Product Translation Item"
        ]
        for dt in child_tables:
            frappe.db.delete(dt, {"parent": item_name})

        # Delete Item
        if frappe.db.exists("Item", item_name):
            item = frappe.get_doc("Item", item_name)
            item.flags._from_pim_sync = True
            item.delete(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        _print_status(f"Cleanup warning for {item_name}: {e}", "warning")


def check_pm_to_item_sync():
    """
    Verify that creating a Product Master creates an ERPNext Item.

    Returns:
        bool: True if verification passed
    """
    _print_status("\n=== Test 1: Product Master -> Item Sync ===")

    product_code = f"VERIFY-PM-{random_string(6)}"
    product_name = f"Verification Product {random_string(4)}"
    test_passed = False

    try:
        _print_status(f"Creating Product Master: {product_code}")

        # Create Product Master
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = product_name
        pm.stock_uom = "Unit"
        pm.is_stock_item = 1
        pm.status = "Draft"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        _print_status(f"Product Master created with name: {pm.name}")

        # Verify Item exists
        if frappe.db.exists("Item", pm.name):
            _print_status("Item created in ERPNext", "success")

            # Verify field mapping
            item = frappe.get_doc("Item", pm.name)
            if item.item_code == product_code:
                _print_status("Item code matches", "success")
            else:
                _print_status(f"Item code mismatch: {item.item_code} != {product_code}", "error")

            if item.item_name == product_name:
                _print_status("Item name matches", "success")
            else:
                _print_status(f"Item name mismatch: {item.item_name} != {product_name}", "error")

            if item.custom_pim_status == "Draft":
                _print_status("PIM status synced to custom field", "success")
            else:
                _print_status(f"PIM status not synced: {item.custom_pim_status}", "warning")

            test_passed = True
        else:
            _print_status("Item NOT created in ERPNext", "error")

    except Exception as e:
        _print_status(f"Error: {e}", "error")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        _cleanup_test_item(product_code)

    return test_passed


def check_item_to_pm_sync():
    """
    Verify that modifying an Item reflects in Product Master.

    Returns:
        bool: True if verification passed
    """
    _print_status("\n=== Test 2: Item -> Product Master Sync ===")

    product_code = f"VERIFY-ITEM-{random_string(6)}"
    test_passed = False

    try:
        # Create Product Master first
        _print_status(f"Creating Product Master: {product_code}")
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Original PM Name"
        pm.stock_uom = "Unit"
        pm.status = "Draft"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        item_name = pm.name

        # Modify Item directly
        _print_status("Modifying Item directly in ERPNext...")
        item = frappe.get_doc("Item", item_name)
        item.item_name = "Modified via Item"
        item.description = "Updated description"
        item.save(ignore_permissions=True)
        frappe.db.commit()

        _print_status("Item modified, checking Product Master...")

        # Reload Product Master and check
        pm_reloaded = frappe.get_doc("Product Master", item_name)

        # Since PM is Virtual DocType, it reads directly from Item
        if pm_reloaded.product_name == "Modified via Item":
            _print_status("Product name reflects Item change", "success")
            test_passed = True
        else:
            _print_status(
                f"Product name not updated: {pm_reloaded.product_name}",
                "error"
            )

        if pm_reloaded.short_description == "Updated description":
            _print_status("Description reflects Item change", "success")
        else:
            _print_status(
                f"Description not updated: {pm_reloaded.short_description}",
                "warning"
            )

    except Exception as e:
        _print_status(f"Error: {e}", "error")
        import traceback
        traceback.print_exc()

    finally:
        _cleanup_test_item(product_code)

    return test_passed


def check_pm_update_to_item():
    """
    Verify that updating Product Master updates the Item.

    Returns:
        bool: True if verification passed
    """
    _print_status("\n=== Test 3: Product Master Update -> Item ===")

    product_code = f"VERIFY-UPD-{random_string(6)}"
    test_passed = False

    try:
        # Create Product Master
        _print_status(f"Creating Product Master: {product_code}")
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Initial Name"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        # Update Product Master
        _print_status("Updating Product Master...")
        pm.reload()
        pm.product_name = "Updated via PM"
        pm.short_description = "PM updated description"
        pm.save(ignore_permissions=True)
        frappe.db.commit()

        # Check Item
        item = frappe.get_doc("Item", pm.name)

        if item.item_name == "Updated via PM":
            _print_status("Item name updated correctly", "success")
            test_passed = True
        else:
            _print_status(f"Item name not updated: {item.item_name}", "error")

        if item.description == "PM updated description":
            _print_status("Item description updated correctly", "success")
        else:
            _print_status(f"Description not updated: {item.description}", "warning")

    except Exception as e:
        _print_status(f"Error: {e}", "error")
        import traceback
        traceback.print_exc()

    finally:
        _cleanup_test_item(product_code)

    return test_passed


def check_no_infinite_loop():
    """
    Verify that sync operations don't cause infinite loops.

    Returns:
        bool: True if verification passed (no loop detected)
    """
    _print_status("\n=== Test 4: No Infinite Loop Check ===")

    product_code = f"VERIFY-LOOP-{random_string(6)}"
    test_passed = False

    # Track sync calls
    sync_call_count = [0]
    max_allowed_calls = 5

    try:
        from frappe_pim.pim.sync import item_sync
        original_sync = item_sync._sync_item_to_product_master

        def tracked_sync(doc):
            sync_call_count[0] += 1
            _print_status(f"  Sync called #{sync_call_count[0]} for {doc.name}")
            if sync_call_count[0] > max_allowed_calls:
                raise Exception("INFINITE LOOP DETECTED!")
            return original_sync(doc)

        # Patch the sync function
        item_sync._sync_item_to_product_master = tracked_sync

        # Create Product Master
        _print_status(f"Creating Product Master: {product_code}")
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Loop Test"
        pm.stock_uom = "Unit"
        pm.status = "Active"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        _print_status(f"Sync count after PM create: {sync_call_count[0]}")

        # Update Product Master multiple times
        for i in range(3):
            sync_call_count[0] = 0  # Reset counter
            pm.reload()
            pm.product_name = f"Loop Test Update {i}"
            pm.save(ignore_permissions=True)
            frappe.db.commit()
            _print_status(f"Update {i+1}: Sync count = {sync_call_count[0]}")

        if sync_call_count[0] <= 2:
            _print_status("No infinite loop detected", "success")
            test_passed = True
        else:
            _print_status(f"Too many sync calls: {sync_call_count[0]}", "warning")

    except Exception as e:
        if "INFINITE LOOP DETECTED" in str(e):
            _print_status("INFINITE LOOP DETECTED!", "error")
        else:
            _print_status(f"Error: {e}", "error")
            import traceback
            traceback.print_exc()

    finally:
        # Restore original function
        try:
            from frappe_pim.pim.sync import item_sync
            item_sync._sync_item_to_product_master = original_sync
        except Exception:
            pass

        _cleanup_test_item(product_code)

    return test_passed


def check_sync_flag_works():
    """
    Verify that _from_pim_sync flag prevents sync.

    Returns:
        bool: True if verification passed
    """
    _print_status("\n=== Test 5: Sync Flag Prevention ===")

    product_code = f"VERIFY-FLAG-{random_string(6)}"
    test_passed = False
    sync_triggered = [False]

    try:
        from frappe_pim.pim.sync import item_sync
        original_sync = item_sync._sync_item_to_product_master

        def tracking_sync(doc):
            sync_triggered[0] = True
            _print_status(f"  Sync triggered for {doc.name}", "warning")
            return original_sync(doc)

        item_sync._sync_item_to_product_master = tracking_sync

        # Create Item with _from_pim_sync flag
        _print_status("Creating Item with _from_pim_sync flag...")
        item = frappe.new_doc("Item")
        item.item_code = product_code
        item.item_name = "Flag Test"
        item.item_group = "All Item Groups"
        item.stock_uom = "Unit"
        item.custom_pim_status = "Active"  # Makes it PIM-managed
        item.flags._from_pim_sync = True  # THIS SHOULD PREVENT SYNC
        item.insert(ignore_permissions=True)
        frappe.db.commit()

        if not sync_triggered[0]:
            _print_status("Sync correctly skipped due to flag", "success")
            test_passed = True
        else:
            _print_status("Sync was NOT skipped despite flag", "error")

        # Test update with flag
        sync_triggered[0] = False
        item.reload()
        item.item_name = "Flag Test Updated"
        item.flags._from_pim_sync = True
        item.save(ignore_permissions=True)
        frappe.db.commit()

        if not sync_triggered[0]:
            _print_status("Update sync correctly skipped due to flag", "success")
        else:
            _print_status("Update sync was NOT skipped despite flag", "error")
            test_passed = False

    except Exception as e:
        _print_status(f"Error: {e}", "error")
        import traceback
        traceback.print_exc()

    finally:
        # Restore
        try:
            from frappe_pim.pim.sync import item_sync
            item_sync._sync_item_to_product_master = original_sync
        except Exception:
            pass

        _cleanup_test_item(product_code)

    return test_passed


def run_verification():
    """
    Run all verification checks.

    Returns:
        dict: Summary of verification results
    """
    _print_status("=" * 60)
    _print_status("  BIDIRECTIONAL SYNC VERIFICATION")
    _print_status("=" * 60)

    results = {}

    # Run all checks
    results["pm_to_item"] = check_pm_to_item_sync()
    results["item_to_pm"] = check_item_to_pm_sync()
    results["pm_update_to_item"] = check_pm_update_to_item()
    results["no_infinite_loop"] = check_no_infinite_loop()
    results["sync_flag_works"] = check_sync_flag_works()

    # Summary
    _print_status("\n" + "=" * 60)
    _print_status("  VERIFICATION SUMMARY")
    _print_status("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "success" if result else "error"
        _print_status(f"  {test_name}: {'PASSED' if result else 'FAILED'}", status)

    _print_status("-" * 60)
    if passed == total:
        _print_status(f"  ALL TESTS PASSED ({passed}/{total})", "success")
    else:
        _print_status(f"  {passed}/{total} tests passed", "warning" if passed > 0 else "error")

    _print_status("=" * 60)

    return {
        "passed": passed,
        "total": total,
        "results": results,
        "all_passed": passed == total
    }


# Quick test function for console
def quick_test():
    """Quick test to verify basic sync is working."""
    _print_status("Running quick verification...")
    result = check_pm_to_item_sync()
    if result:
        _print_status("\nBasic sync is working!", "success")
    else:
        _print_status("\nSync test failed!", "error")
    return result
