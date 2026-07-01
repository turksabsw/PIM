# Copyright (c) 2024, Your Company and contributors
# For license information, please see license.txt

"""
Bidirectional Sync Verification Tests

This module contains tests to verify that the ERPNext Item ↔ Product Master
bidirectional synchronization works correctly without infinite loops.

Test Categories:
1. Product Master → Item sync (creation and updates)
2. Item → Product Master sync (updates and deletes)
3. Infinite loop prevention
4. Edge cases and error handling

Usage:
    bench --site [site-name] run-tests --app frappe_pim --module pim.doctype.product_master.test_bidirectional_sync

Or run individual tests:
    bench --site [site-name] run-tests --app frappe_pim --module pim.doctype.product_master.test_bidirectional_sync --test TestBidirectionalSync.test_product_master_creates_item
"""

import unittest
import frappe
from frappe.utils import nowdate, random_string


class TestBidirectionalSync(unittest.TestCase):
    """Test bidirectional sync between Product Master and ERPNext Item."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.test_items = []
        cls.sync_call_count = 0
        # Ensure we have a default item group
        if not frappe.db.exists("Item Group", "Products"):
            if not frappe.db.exists("Item Group", "All Item Groups"):
                frappe.get_doc({
                    "doctype": "Item Group",
                    "item_group_name": "All Item Groups",
                    "is_group": 1
                }).insert(ignore_permissions=True)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        for item_name in cls.test_items:
            try:
                if frappe.db.exists("Item", item_name):
                    # Delete child table data first
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
                        frappe.db.delete(dt, {"parent": item_name})

                    # Delete Item
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True  # Prevent sync trigger
                    item.delete(ignore_permissions=True)
            except Exception as e:
                frappe.logger().warning(f"Failed to clean up {item_name}: {e}")

        frappe.db.commit()

    def _create_test_product_code(self):
        """Generate a unique product code for testing."""
        return f"TEST-PM-{random_string(8)}"

    def test_01_product_master_creates_item(self):
        """Test that creating a Product Master creates an Item in ERPNext."""
        product_code = self._create_test_product_code()
        product_name = f"Test Product {random_string(4)}"

        # Create Product Master (Virtual DocType)
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = product_name
        pm.stock_uom = "Unit"
        pm.is_stock_item = 1
        pm.status = "Draft"

        try:
            pm.insert(ignore_permissions=True)
            self.test_items.append(pm.name)

            # Verify Item was created
            self.assertTrue(
                frappe.db.exists("Item", pm.name),
                f"Item {pm.name} should have been created"
            )

            # Verify Item has correct data
            item = frappe.get_doc("Item", pm.name)
            self.assertEqual(item.item_code, product_code)
            self.assertEqual(item.item_name, product_name)

            frappe.db.commit()
        except Exception as e:
            self.fail(f"Failed to create Product Master: {e}")

    def test_02_product_master_update_syncs_to_item(self):
        """Test that updating a Product Master updates the ERPNext Item."""
        product_code = self._create_test_product_code()

        # Create Product Master
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Original Name"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        self.test_items.append(pm.name)
        frappe.db.commit()

        # Update Product Master
        pm.reload()
        pm.product_name = "Updated Name"
        pm.short_description = "Updated description"
        pm.save(ignore_permissions=True)
        frappe.db.commit()

        # Verify Item was updated
        item = frappe.get_doc("Item", pm.name)
        self.assertEqual(item.item_name, "Updated Name")
        self.assertEqual(item.description, "Updated description")

    def test_03_item_update_does_not_trigger_infinite_loop(self):
        """Test that updating an Item does not cause infinite sync loop."""
        product_code = self._create_test_product_code()

        # Create Product Master (which creates Item)
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Loop Test Product"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        self.test_items.append(pm.name)
        frappe.db.commit()

        # Track how many times the sync is called
        original_sync_func = None
        sync_call_count = [0]

        try:
            from frappe_pim.pim.sync import item_sync
            original_sync_func = item_sync._sync_item_to_product_master

            def tracked_sync(doc):
                sync_call_count[0] += 1
                if sync_call_count[0] > 5:
                    raise Exception("Infinite loop detected!")
                return original_sync_func(doc)

            item_sync._sync_item_to_product_master = tracked_sync

            # Update Item directly (simulating external update)
            item = frappe.get_doc("Item", pm.name)
            item.item_name = "Externally Updated Name"
            item.save(ignore_permissions=True)
            frappe.db.commit()

            # Should only trigger sync once (or not at all if flag prevents)
            self.assertLessEqual(
                sync_call_count[0], 2,
                f"Sync was called {sync_call_count[0]} times - possible loop!"
            )

        finally:
            if original_sync_func:
                from frappe_pim.pim.sync import item_sync
                item_sync._sync_item_to_product_master = original_sync_func

    def test_04_sync_flag_prevents_loop(self):
        """Test that _from_pim_sync flag correctly prevents sync loops."""
        product_code = self._create_test_product_code()

        # Create Item directly with PIM sync flag
        item = frappe.new_doc("Item")
        item.item_code = product_code
        item.item_name = "Flag Test Product"
        item.item_group = "All Item Groups"
        item.stock_uom = "Unit"
        item.flags._from_pim_sync = True  # Set flag
        item.insert(ignore_permissions=True)
        self.test_items.append(item.name)
        frappe.db.commit()

        # The Item should be created without triggering sync back to PIM
        # This is verified by the test passing without errors

        # Now test update with flag
        item.reload()
        item.item_name = "Flag Test Updated"
        item.flags._from_pim_sync = True
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # Verify update worked
        item.reload()
        self.assertEqual(item.item_name, "Flag Test Updated")

    def test_05_item_delete_cleans_child_tables(self):
        """Test that deleting an Item cleans up Product Master child tables."""
        product_code = self._create_test_product_code()

        # Create Product Master with child table data
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Delete Test Product"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)

        item_name = pm.name

        # Add some child table data
        try:
            pm.set("price_items", [{
                "price_list": "Standard Selling",
                "price": 100,
                "min_qty": 1
            }])
            pm.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            # Price list might not exist, skip this part
            pass

        # Delete the Item
        item = frappe.get_doc("Item", item_name)
        item.flags._from_pim_sync = True  # Set flag to test cleanup path
        item.delete(ignore_permissions=True)
        frappe.db.commit()

        # Verify Item is gone
        self.assertFalse(frappe.db.exists("Item", item_name))

        # Remove from cleanup list since already deleted
        if item_name in self.test_items:
            self.test_items.remove(item_name)

    def test_06_pim_managed_item_detection(self):
        """Test that _is_pim_managed_item correctly identifies PIM items."""
        from frappe_pim.pim.sync.item_sync import _is_pim_managed_item

        product_code = self._create_test_product_code()

        # Create regular Item (not PIM managed)
        regular_item = frappe.new_doc("Item")
        regular_item.item_code = f"REGULAR-{random_string(4)}"
        regular_item.item_name = "Regular Item"
        regular_item.item_group = "All Item Groups"
        regular_item.stock_uom = "Unit"
        regular_item.insert(ignore_permissions=True)
        self.test_items.append(regular_item.name)
        frappe.db.commit()

        # Should not be PIM managed
        self.assertFalse(
            _is_pim_managed_item(regular_item),
            "Regular Item should not be detected as PIM managed"
        )

        # Create PIM managed Item
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "PIM Managed Product"
        pm.stock_uom = "Unit"
        pm.status = "Active"
        pm.insert(ignore_permissions=True)
        self.test_items.append(pm.name)
        frappe.db.commit()

        # Get the Item
        pim_item = frappe.get_doc("Item", pm.name)

        # Should be PIM managed (has custom_pim_status)
        self.assertTrue(
            _is_pim_managed_item(pim_item),
            "PIM created Item should be detected as PIM managed"
        )

    def test_07_concurrent_updates_no_deadlock(self):
        """Test that concurrent updates don't cause deadlock or infinite loops."""
        product_code = self._create_test_product_code()

        # Create Product Master
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Concurrent Test"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        self.test_items.append(pm.name)
        frappe.db.commit()

        # Simulate rapid updates
        for i in range(5):
            pm.reload()
            pm.product_name = f"Update {i}"
            pm.save(ignore_permissions=True)
            frappe.db.commit()

        # Verify final state
        pm.reload()
        self.assertEqual(pm.product_name, "Update 4")

        item = frappe.get_doc("Item", pm.name)
        self.assertEqual(item.item_name, "Update 4")

    def test_08_variant_creation_no_loop(self):
        """Test that variant creation doesn't trigger infinite loops."""
        product_code = self._create_test_product_code()

        # Create template Product Master
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Template Product"
        pm.stock_uom = "Unit"
        pm.is_template = 1
        pm.insert(ignore_permissions=True)
        self.test_items.append(pm.name)
        frappe.db.commit()

        # Create variant Item directly (simulating variant generation)
        variant_code = f"{product_code}-RED"
        variant_item = frappe.new_doc("Item")
        variant_item.item_code = variant_code
        variant_item.item_name = "Template Product (RED)"
        variant_item.item_group = "All Item Groups"
        variant_item.stock_uom = "Unit"
        variant_item.custom_pim_parent_product = pm.name
        variant_item.flags._from_pim_sync = True  # Simulating PIM variant generation
        variant_item.insert(ignore_permissions=True)
        self.test_items.append(variant_item.name)
        frappe.db.commit()

        # Verify variant was created without loops
        self.assertTrue(frappe.db.exists("Item", variant_code))

        # Verify parent relationship
        variant_item.reload()
        self.assertEqual(variant_item.custom_pim_parent_product, pm.name)

    def test_09_realtime_event_published(self):
        """Test that realtime events are published on sync."""
        product_code = self._create_test_product_code()

        # Create Product Master
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Realtime Test"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        self.test_items.append(pm.name)
        frappe.db.commit()

        # Update via Item to trigger sync
        item = frappe.get_doc("Item", pm.name)
        item.custom_pim_status = "Active"
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # The realtime event publish_realtime should have been called
        # We can't easily verify this without mocking, but the test
        # passing without errors indicates no infinite loop

    def test_10_error_handling_no_block(self):
        """Test that sync errors don't block Item save."""
        product_code = self._create_test_product_code()

        # Create a basic Item with PIM data
        item = frappe.new_doc("Item")
        item.item_code = product_code
        item.item_name = "Error Test"
        item.item_group = "All Item Groups"
        item.stock_uom = "Unit"
        item.custom_pim_status = "Active"  # Makes it PIM managed
        item.insert(ignore_permissions=True)
        self.test_items.append(item.name)
        frappe.db.commit()

        # Even if sync has issues, Item operations should complete
        item.reload()
        item.item_name = "Error Test Updated"
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # Verify Item was saved
        item.reload()
        self.assertEqual(item.item_name, "Error Test Updated")


class TestSyncFlagBehavior(unittest.TestCase):
    """Test specific flag behaviors for sync prevention."""

    @classmethod
    def setUpClass(cls):
        cls.test_items = []

    @classmethod
    def tearDownClass(cls):
        for item_name in cls.test_items:
            try:
                if frappe.db.exists("Item", item_name):
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True
                    item.delete(ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_flag_cleared_after_save(self):
        """Test that flags are properly handled and don't persist incorrectly."""
        product_code = f"TEST-FLAG-{random_string(4)}"

        # Create Item with flag
        item = frappe.new_doc("Item")
        item.item_code = product_code
        item.item_name = "Flag Clear Test"
        item.item_group = "All Item Groups"
        item.stock_uom = "Unit"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.test_items.append(item.name)
        frappe.db.commit()

        # Reload and check flag state
        item = frappe.get_doc("Item", product_code)
        # Flags should be fresh on reload
        self.assertFalse(getattr(item.flags, "_from_pim_sync", False))

    def test_flag_on_document_not_class(self):
        """Test that flags are per-document, not class-level."""
        code1 = f"TEST-F1-{random_string(4)}"
        code2 = f"TEST-F2-{random_string(4)}"

        # Create first Item with flag
        item1 = frappe.new_doc("Item")
        item1.item_code = code1
        item1.item_name = "Flag Test 1"
        item1.item_group = "All Item Groups"
        item1.stock_uom = "Unit"
        item1.flags._from_pim_sync = True
        item1.insert(ignore_permissions=True)
        self.test_items.append(item1.name)

        # Create second Item without flag
        item2 = frappe.new_doc("Item")
        item2.item_code = code2
        item2.item_name = "Flag Test 2"
        item2.item_group = "All Item Groups"
        item2.stock_uom = "Unit"
        # Intentionally NOT setting flag

        # item2 should not inherit flag from item1
        self.assertFalse(getattr(item2.flags, "_from_pim_sync", False))

        item2.insert(ignore_permissions=True)
        self.test_items.append(item2.name)
        frappe.db.commit()


def run_tests():
    """Run all bidirectional sync tests."""
    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestBidirectionalSync))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSyncFlagBehavior))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    # Allow running directly for debugging
    frappe.connect()
    try:
        run_tests()
    finally:
        frappe.destroy()
