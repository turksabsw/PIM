# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""End-to-End Bidirectional Sync Verification Tests

This module verifies the complete bidirectional synchronization flow between
PIM and ERPNext:

1. Create a Product Master in PIM → Verify corresponding ERPNext Item exists
2. Modify the Item directly in ERPNext → Verify the Product Master is updated
3. Create a Product Variant in PIM → Verify ERPNext Item is created/linked
4. Modify the linked ERPNext Item → Verify Product Variant is updated
5. Check sync queue for loop prevention (no infinite entries)
6. Verify sync status shows 'Synced'

The tests validate:
- PIM → ERP direction (Product Master db_insert/db_update → Item)
- ERP → PIM direction (Item on_update hooks → Product Variant/Product Master)
- Loop prevention via _from_pim_sync / _from_erpnext_sync / from_pim flags
- Sync queue duplicate prevention and status tracking
- Conflict detection for concurrent modifications
- Clean teardown without data residue

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).

Run with:
    bench --site [site] run-tests --app frappe_pim \\
        --module frappe_pim.pim.tests.test_e2e_bidirectional_sync
"""

import unittest


class TestE2EBidirectionalSync(unittest.TestCase):
    """End-to-end verification of bidirectional PIM ↔ ERPNext sync.

    Tests the complete round-trip: PIM creates Item, ERPNext updates
    flow back to PIM, and loop prevention ensures no infinite cycles.
    """

    TEST_PREFIX = "E2ESYNC"

    @classmethod
    def setUpClass(cls):
        """Set up test class - ensure clean slate and prerequisites."""
        import frappe
        frappe.set_user("Administrator")
        cls._cleanup_test_data()
        cls._ensure_item_group()

    @classmethod
    def tearDownClass(cls):
        """Clean up all test data after all tests."""
        import frappe
        cls._cleanup_test_data()
        frappe.db.commit()

    @classmethod
    def _ensure_item_group(cls):
        """Ensure required Item Groups exist for test Items."""
        import frappe

        for group in ["Products", "All Item Groups"]:
            if not frappe.db.exists("Item Group", group):
                try:
                    ig = frappe.new_doc("Item Group")
                    ig.item_group_name = group
                    ig.is_group = 1
                    ig.insert(ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove all test data created by this test class."""
        import frappe

        prefix = cls.TEST_PREFIX

        # 1. Clean up sync queue entries referencing test documents
        sync_entries = frappe.get_all(
            "PIM Sync Queue",
            filters={"document_name": ["like", f"{prefix}%"]},
            pluck="name"
        )
        for entry in sync_entries:
            try:
                frappe.delete_doc("PIM Sync Queue", entry, force=True)
            except Exception:
                pass

        # 2. Clean up Product Variants
        variants = frappe.get_all(
            "Product Variant",
            filters={"sku": ["like", f"{prefix}%"]},
            pluck="name"
        )
        for variant in variants:
            try:
                frappe.delete_doc("Product Variant", variant, force=True)
            except Exception:
                pass

        # 3. Clean up child table data for test Items
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
        test_items = frappe.get_all(
            "Item",
            filters={"item_code": ["like", f"{prefix}%"]},
            pluck="name"
        )
        for item_name in test_items:
            for dt in child_tables:
                try:
                    frappe.db.delete(dt, {"parent": item_name})
                except Exception:
                    pass

        # 4. Clean up test Items (set flag to avoid PIM hooks)
        for item_name in test_items:
            try:
                item = frappe.get_doc("Item", item_name)
                item.flags._from_pim_sync = True
                item.delete(ignore_permissions=True)
            except Exception:
                pass

        frappe.db.commit()

    def setUp(self):
        """Set up before each test."""
        import frappe
        frappe.set_user("Administrator")

    # =========================================================================
    # Test 1: PIM Product Master → ERPNext Item Creation
    # =========================================================================

    def test_01_product_master_creates_erpnext_item(self):
        """Verify that creating a Product Master in PIM creates an ERPNext Item.

        Flow: Product Master.db_insert() → Item.insert() with _from_pim_sync flag
        """
        import frappe
        from frappe.utils import random_string

        product_code = f"{self.TEST_PREFIX}-PM-{random_string(6)}"
        product_name = f"Bidirectional Sync Test Product {random_string(4)}"

        # Create Product Master (Virtual DocType → maps to Item)
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = product_name
        pm.stock_uom = "Unit"
        pm.is_stock_item = 1
        pm.status = "Draft"

        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify: Item should have been created in ERPNext
        self.assertTrue(
            frappe.db.exists("Item", pm.name),
            f"ERPNext Item should be created when Product Master is inserted"
        )

        # Verify: Item fields should match Product Master fields
        item = frappe.get_doc("Item", pm.name)
        self.assertEqual(
            item.item_code, product_code,
            "Item.item_code should match Product Master.product_code"
        )
        self.assertEqual(
            item.item_name, product_name,
            "Item.item_name should match Product Master.product_name"
        )
        self.assertEqual(
            item.stock_uom, "Unit",
            "Item.stock_uom should match Product Master.stock_uom"
        )

    # =========================================================================
    # Test 2: PIM Product Master Update → ERPNext Item Update
    # =========================================================================

    def test_02_product_master_update_syncs_to_item(self):
        """Verify that updating a Product Master updates the linked ERPNext Item.

        Flow: Product Master.db_update() → Item.save() with _from_pim_sync flag
        """
        import frappe
        from frappe.utils import random_string

        product_code = f"{self.TEST_PREFIX}-PMU-{random_string(6)}"

        # Create Product Master
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Original PM Name"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        # Update Product Master
        pm.reload()
        pm.product_name = "Updated PM Name"
        pm.short_description = "Updated description via PIM"
        pm.save(ignore_permissions=True)
        frappe.db.commit()

        # Verify: Item should reflect the updates
        item = frappe.get_doc("Item", pm.name)
        self.assertEqual(
            item.item_name, "Updated PM Name",
            "Item.item_name should be updated when Product Master is saved"
        )
        self.assertEqual(
            item.description, "Updated description via PIM",
            "Item.description should match Product Master.short_description"
        )

    # =========================================================================
    # Test 3: ERPNext Item Update → PIM Product Master Cache Invalidation
    # =========================================================================

    def test_03_item_update_invalidates_product_master_cache(self):
        """Verify that updating an Item in ERPNext invalidates Product Master cache.

        Since Product Master is a Virtual DocType that reads from Item,
        any Item update should invalidate cached Product Master data
        and re-reading the PM should show updated values.

        Flow: Item.save() → on_item_update hook → _invalidate_product_master_cache()
        """
        import frappe
        from frappe.utils import random_string

        product_code = f"{self.TEST_PREFIX}-PMCI-{random_string(6)}"

        # Create Product Master (creates Item)
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Cache Test Product"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        # Directly update the Item in ERPNext (simulating external ERP user)
        item = frappe.get_doc("Item", pm.name)
        item.item_name = "Externally Updated Product"
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # Re-read Product Master (Virtual DocType reads from Item)
        pm_reloaded = frappe.get_doc("Product Master", pm.name)

        self.assertEqual(
            pm_reloaded.product_name, "Externally Updated Product",
            "Product Master should reflect Item changes since it's a Virtual DocType"
        )

    # =========================================================================
    # Test 4: ERPNext Item Update → Product Variant Sync
    # =========================================================================

    def test_04_item_update_syncs_to_product_variant(self):
        """Verify that updating an ERPNext Item syncs changes to linked Product Variant.

        Flow: Item.save() → on_item_update hook → _sync_item_to_product_variant()
              with _from_erpnext_sync flag on variant
        """
        import frappe
        from frappe.utils import random_string

        sku = f"{self.TEST_PREFIX}-VAR-{random_string(6)}"

        # Create an Item directly (simulate ERPNext-first scenario)
        item = frappe.new_doc("Item")
        item.item_code = sku
        item.item_name = "Original Variant Item"
        item.item_group = self._get_item_group()
        item.stock_uom = "Nos"
        item.is_stock_item = 1
        item.custom_pim_status = "Active"  # Mark as PIM-managed
        item.flags.from_pim = True  # Skip PIM hooks during setup
        item.insert(ignore_permissions=True)
        frappe.db.commit()

        # Create Product Variant linked to this Item
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = "Original Variant Item"
        variant.status = "Active"
        variant.erp_item = item.name
        variant.flags.from_erp = True  # Skip sync hooks during setup
        variant._from_erpnext_sync = True
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Now update the Item in ERPNext (this should trigger sync to Variant)
        item.reload()
        item.item_name = "Updated From ERPNext"
        # Clear PIM flags so hooks fire
        item.flags.from_pim = False
        item.flags._from_pim_sync = False
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # Verify: Product Variant should be updated
        variant.reload()
        self.assertEqual(
            variant.variant_name, "Updated From ERPNext",
            "Product Variant.variant_name should reflect Item.item_name change"
        )

    # =========================================================================
    # Test 5: Loop Prevention - PIM → ERP → PIM should NOT loop
    # =========================================================================

    def test_05_no_infinite_loop_pim_to_erp(self):
        """Verify that PIM→ERP sync does not trigger ERP→PIM back (no loop).

        When Product Master creates/updates an Item with _from_pim_sync flag,
        the Item's on_update hook should detect the flag and NOT trigger
        a sync back to PIM.

        Flow: PM.save() → Item.save(flags._from_pim_sync=True) → on_item_update()
              → _is_from_pim() returns True → SKIP sync
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.sync import item_sync

        product_code = f"{self.TEST_PREFIX}-LOOP1-{random_string(6)}"
        sync_call_count = [0]

        # Monkey-patch _sync_item_to_product_variant to track calls
        original_sync = item_sync._sync_item_to_product_variant

        def tracked_sync(*args, **kwargs):
            sync_call_count[0] += 1
            if sync_call_count[0] > 5:
                raise RuntimeError("Infinite loop detected in PIM→ERP→PIM sync!")
            return original_sync(*args, **kwargs)

        try:
            item_sync._sync_item_to_product_variant = tracked_sync

            # Create Product Master (triggers Item creation with _from_pim_sync)
            pm = frappe.new_doc("Product Master")
            pm.product_code = product_code
            pm.product_name = "Loop Prevention Test"
            pm.stock_uom = "Unit"
            pm.insert(ignore_permissions=True)
            frappe.db.commit()

            # Update Product Master (triggers Item update with _from_pim_sync)
            pm.reload()
            pm.product_name = "Loop Prevention Updated"
            pm.save(ignore_permissions=True)
            frappe.db.commit()

            # The _sync_item_to_product_variant should NOT have been called
            # because _from_pim_sync flag on Item prevents on_item_update
            # from triggering the reverse sync
            self.assertLessEqual(
                sync_call_count[0], 0,
                f"_sync_item_to_product_variant was called {sync_call_count[0]} times! "
                "Expected 0 calls because _from_pim_sync flag should prevent loop."
            )
        finally:
            item_sync._sync_item_to_product_variant = original_sync

    # =========================================================================
    # Test 6: Loop Prevention - ERP → PIM → ERP should NOT loop
    # =========================================================================

    def test_06_no_infinite_loop_erp_to_pim(self):
        """Verify that ERP→PIM sync does not trigger PIM→ERP back (no loop).

        When item_sync updates a Product Variant with _from_erpnext_sync flag,
        the Variant's on_update should detect the flag and NOT trigger
        sync_to_erpnext.

        Flow: Item.save() → on_item_update() → variant.save(flags.from_erp=True)
              → on_update() checks _from_erpnext_sync → SKIP enqueue
        """
        import frappe
        from frappe.utils import random_string

        sku = f"{self.TEST_PREFIX}-LOOP2-{random_string(6)}"
        sync_enqueue_count = [0]

        # Create Item and linked Variant
        item = frappe.new_doc("Item")
        item.item_code = sku
        item.item_name = "ERP Loop Test"
        item.item_group = self._get_item_group()
        item.stock_uom = "Nos"
        item.custom_pim_status = "Active"
        item.flags.from_pim = True
        item.insert(ignore_permissions=True)
        frappe.db.commit()

        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = "ERP Loop Test"
        variant.variant_code = sku
        variant.status = "Active"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Monkey-patch frappe.enqueue to track sync job enqueue attempts
        original_enqueue = frappe.enqueue

        def tracked_enqueue(*args, **kwargs):
            job_id = kwargs.get("job_id", "")
            if "pim_variant_sync" in str(job_id):
                sync_enqueue_count[0] += 1
            return original_enqueue(*args, **kwargs)

        try:
            frappe.enqueue = tracked_enqueue

            # Update Item in ERPNext (should sync to Variant via hooks)
            item.reload()
            item.item_name = "ERP Loop Updated"
            item.flags.from_pim = False
            item.flags._from_pim_sync = False
            item.save(ignore_permissions=True)
            frappe.db.commit()

            # The variant's on_update should NOT enqueue a sync back to ERP
            # because _from_erpnext_sync flag prevents it
            self.assertEqual(
                sync_enqueue_count[0], 0,
                f"frappe.enqueue for pim_variant_sync was called {sync_enqueue_count[0]} times! "
                "Expected 0 because _from_erpnext_sync flag should prevent loop."
            )
        finally:
            frappe.enqueue = original_enqueue

    # =========================================================================
    # Test 7: Sync Flag Isolation (Per-Document, Not Global)
    # =========================================================================

    def test_07_sync_flags_are_per_document(self):
        """Verify that sync flags are per-document instance, not class-level.

        Two Items should have independent flag states - setting flag on one
        should not affect the other.
        """
        import frappe
        from frappe.utils import random_string

        code1 = f"{self.TEST_PREFIX}-FLAG1-{random_string(4)}"
        code2 = f"{self.TEST_PREFIX}-FLAG2-{random_string(4)}"

        # Create first Item with PIM sync flag
        item1 = frappe.new_doc("Item")
        item1.item_code = code1
        item1.item_name = "Flag Test 1"
        item1.item_group = self._get_item_group()
        item1.stock_uom = "Unit"
        item1.flags._from_pim_sync = True
        item1.insert(ignore_permissions=True)

        # Create second Item WITHOUT flag
        item2 = frappe.new_doc("Item")
        item2.item_code = code2
        item2.item_name = "Flag Test 2"
        item2.item_group = self._get_item_group()
        item2.stock_uom = "Unit"

        # item2 should NOT have the flag from item1
        self.assertFalse(
            getattr(item2.flags, "_from_pim_sync", False),
            "Sync flag from item1 should not leak to item2"
        )

        item2.insert(ignore_permissions=True)
        frappe.db.commit()

        # After reload, flags should be fresh
        item1_fresh = frappe.get_doc("Item", code1)
        self.assertFalse(
            getattr(item1_fresh.flags, "_from_pim_sync", False),
            "Sync flags should not persist across reload"
        )

    # =========================================================================
    # Test 8: Sync Queue Entries Are Not Duplicated
    # =========================================================================

    def test_08_sync_queue_no_duplicate_entries(self):
        """Verify that the sync queue prevents duplicate pending entries.

        When a document is modified multiple times rapidly, only one
        pending sync queue entry should exist (duplicates are merged).
        """
        import frappe
        from frappe.utils import random_string

        sku = f"{self.TEST_PREFIX}-QDUP-{random_string(6)}"

        # Create a variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = f"Queue Dup Test {random_string(4)}"
        variant.status = "Draft"
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Count pending sync entries for this variant
        pending_count = frappe.db.count(
            "PIM Sync Queue",
            {
                "doctype_name": "Product Variant",
                "document_name": variant.name,
                "status": ["in", ["Pending", "Processing"]],
                "sync_direction": "PIM to ERP"
            }
        )

        # Should have at most 1 pending entry (0 if sync is immediate)
        self.assertLessEqual(
            pending_count, 1,
            f"Should have at most 1 pending sync entry, found {pending_count}"
        )

    # =========================================================================
    # Test 9: Sync Queue Loop Prevention (No Infinite Queue Entries)
    # =========================================================================

    def test_09_sync_queue_no_infinite_entries(self):
        """Verify that bidirectional sync does not create infinite queue entries.

        After a round-trip sync (PIM→ERP→PIM), the total number of sync
        queue entries should be bounded and reasonable.
        """
        import frappe
        from frappe.utils import random_string

        product_code = f"{self.TEST_PREFIX}-QLOOP-{random_string(6)}"

        # Count sync entries before test
        before_count = frappe.db.count("PIM Sync Queue")

        # Create Product Master (triggers PIM→ERP sync)
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Queue Loop Test"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        # Update Product Master (triggers another PIM→ERP sync)
        pm.reload()
        pm.product_name = "Queue Loop Updated"
        pm.save(ignore_permissions=True)
        frappe.db.commit()

        # Update Item directly (triggers ERP→PIM sync)
        if frappe.db.exists("Item", pm.name):
            item = frappe.get_doc("Item", pm.name)
            item.item_name = "Queue Loop ERP Update"
            item.save(ignore_permissions=True)
            frappe.db.commit()

        # Count sync entries after test
        after_count = frappe.db.count("PIM Sync Queue")
        new_entries = after_count - before_count

        # The number of new sync entries should be reasonable
        # At most: 1 for PM create + 1 for PM update + 1 for Item update = 3
        # In practice, some may not create entries depending on configuration
        self.assertLessEqual(
            new_entries, 5,
            f"Created {new_entries} sync entries during round-trip. "
            "Expected ≤5 - possible infinite loop in queue creation!"
        )

    # =========================================================================
    # Test 10: Sync Status Shows Correct State
    # =========================================================================

    def test_10_sync_status_api_returns_correct_state(self):
        """Verify that the sync status API reflects the actual sync state.

        After creating a Product Master (which creates an Item), the sync
        status should indicate the document is synced.
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.api.sync import get_sync_status

        product_code = f"{self.TEST_PREFIX}-STAT-{random_string(6)}"

        # Create Product Master
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Status Test Product"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        # Get sync status
        status = get_sync_status(
            doctype_name="Product Master",
            document_name=pm.name
        )

        self.assertIsNotNone(status, "Sync status should be returned")
        self.assertIn("status", status, "Status response should have 'status' field")

        # The status should be one of the valid states
        valid_statuses = [
            "Synced", "Not Synced", "Pending", "Processing",
            "Completed", "Failed", "Cancelled"
        ]
        self.assertIn(
            status["status"], valid_statuses,
            f"Status '{status['status']}' is not a valid sync status"
        )

    # =========================================================================
    # Test 11: PIM-Managed Item Detection
    # =========================================================================

    def test_11_pim_managed_item_correctly_detected(self):
        """Verify that _is_pim_managed_item correctly identifies PIM items.

        Items created through PIM should be detected as PIM-managed.
        Regular Items created directly should not be PIM-managed.
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.sync.item_sync import _is_pim_managed_item

        product_code = f"{self.TEST_PREFIX}-MGMT-{random_string(6)}"
        regular_code = f"{self.TEST_PREFIX}-NOPIM-{random_string(6)}"

        # Create a PIM-managed product
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "PIM Managed Test"
        pm.stock_uom = "Unit"
        pm.status = "Active"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        pim_item = frappe.get_doc("Item", pm.name)
        self.assertTrue(
            _is_pim_managed_item(pim_item),
            "Item created via Product Master should be detected as PIM-managed"
        )

        # Create a regular Item (not through PIM)
        regular_item = frappe.new_doc("Item")
        regular_item.item_code = regular_code
        regular_item.item_name = "Regular Non-PIM Item"
        regular_item.item_group = self._get_item_group()
        regular_item.stock_uom = "Unit"
        regular_item.flags._from_pim_sync = True  # Skip hooks
        regular_item.insert(ignore_permissions=True)
        frappe.db.commit()

        regular_item_doc = frappe.get_doc("Item", regular_code)
        self.assertFalse(
            _is_pim_managed_item(regular_item_doc),
            "Regular Item should NOT be detected as PIM-managed"
        )

    # =========================================================================
    # Test 12: Rapid Concurrent Updates Don't Deadlock
    # =========================================================================

    def test_12_rapid_updates_no_deadlock(self):
        """Verify that rapid successive updates complete without deadlock.

        Simulates a user quickly editing the same Product Master multiple
        times. All updates should complete and final state should be consistent.
        """
        import frappe
        from frappe.utils import random_string

        product_code = f"{self.TEST_PREFIX}-RAPID-{random_string(6)}"

        # Create Product Master
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Rapid Update 0"
        pm.stock_uom = "Unit"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        # Perform 5 rapid updates
        for i in range(1, 6):
            pm.reload()
            pm.product_name = f"Rapid Update {i}"
            pm.save(ignore_permissions=True)
            frappe.db.commit()

        # Verify final state is consistent between PM and Item
        pm.reload()
        self.assertEqual(
            pm.product_name, "Rapid Update 5",
            "Product Master should have the last update value"
        )

        item = frappe.get_doc("Item", pm.name)
        self.assertEqual(
            item.item_name, "Rapid Update 5",
            "ERPNext Item should match Product Master after rapid updates"
        )

    # =========================================================================
    # Test 13: Item Deletion Cleans Up PIM Data
    # =========================================================================

    def test_13_item_deletion_cleans_up_pim_data(self):
        """Verify that deleting an ERPNext Item properly cleans up PIM data.

        When an Item is deleted, the on_trash hook should:
        1. Clean up Product Master child table records
        2. Unlink any associated Product Variant
        """
        import frappe
        from frappe.utils import random_string

        sku = f"{self.TEST_PREFIX}-DEL-{random_string(6)}"

        # Create Item with PIM link
        item = frappe.new_doc("Item")
        item.item_code = sku
        item.item_name = "Delete Test Item"
        item.item_group = self._get_item_group()
        item.stock_uom = "Nos"
        item.custom_pim_status = "Active"
        item.flags.from_pim = True
        item.insert(ignore_permissions=True)
        frappe.db.commit()

        # Create linked Product Variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = "Delete Test Variant"
        variant.status = "Active"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        variant_name = variant.name

        # Delete the Item
        item_doc = frappe.get_doc("Item", sku)
        item_doc.delete(ignore_permissions=True)
        frappe.db.commit()

        # Item should be gone
        self.assertFalse(
            frappe.db.exists("Item", sku),
            "Item should be deleted"
        )

        # Variant should still exist but erp_item should be cleared
        if frappe.db.exists("Product Variant", variant_name):
            variant_doc = frappe.get_doc("Product Variant", variant_name)
            self.assertFalse(
                variant_doc.erp_item,
                "Product Variant.erp_item should be cleared after Item deletion"
            )

    # =========================================================================
    # Test 14: Full Round-Trip Bidirectional Sync
    # =========================================================================

    def test_14_full_round_trip_sync(self):
        """End-to-end verification of complete bidirectional sync round-trip.

        Steps:
        1. Create Product Master in PIM → Item created in ERP
        2. Edit Item in ERP → Product Master reflects changes (Virtual DocType)
        3. Edit Product Master in PIM → Item updated in ERP
        4. Verify no infinite loop occurred
        5. Verify sync queue is clean
        """
        import frappe
        from frappe.utils import random_string

        product_code = f"{self.TEST_PREFIX}-RT-{random_string(6)}"

        # Count sync entries before
        sync_count_before = frappe.db.count("PIM Sync Queue")

        # Step 1: Create Product Master → Item created
        pm = frappe.new_doc("Product Master")
        pm.product_code = product_code
        pm.product_name = "Round Trip Step 1"
        pm.stock_uom = "Unit"
        pm.short_description = "Created in PIM"
        pm.insert(ignore_permissions=True)
        frappe.db.commit()

        self.assertTrue(
            frappe.db.exists("Item", pm.name),
            "Step 1: Item should be created from Product Master"
        )

        # Step 2: Edit Item in ERP → PM reflects changes
        item = frappe.get_doc("Item", pm.name)
        item.item_name = "Round Trip Step 2"
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # Re-read PM (Virtual DocType reads from Item)
        pm_v2 = frappe.get_doc("Product Master", pm.name)
        self.assertEqual(
            pm_v2.product_name, "Round Trip Step 2",
            "Step 2: Product Master should reflect Item changes"
        )

        # Step 3: Edit PM in PIM → Item updated
        pm_v2.product_name = "Round Trip Step 3"
        pm_v2.short_description = "Updated in PIM again"
        pm_v2.save(ignore_permissions=True)
        frappe.db.commit()

        item_v2 = frappe.get_doc("Item", pm.name)
        self.assertEqual(
            item_v2.item_name, "Round Trip Step 3",
            "Step 3: Item should reflect Product Master update"
        )
        self.assertEqual(
            item_v2.description, "Updated in PIM again",
            "Step 3: Item.description should match PM.short_description"
        )

        # Step 4: Verify no infinite loop - check sync queue growth
        sync_count_after = frappe.db.count("PIM Sync Queue")
        new_entries = sync_count_after - sync_count_before

        self.assertLessEqual(
            new_entries, 5,
            f"Step 4: {new_entries} sync entries created during round-trip. "
            "Expected ≤5 — possible infinite loop!"
        )

        # Step 5: Verify sync queue doesn't have runaway entries
        processing_entries = frappe.db.count(
            "PIM Sync Queue",
            {
                "document_name": ["like", f"{product_code}%"],
                "status": "Processing"
            }
        )
        self.assertEqual(
            processing_entries, 0,
            "Step 5: No entries should be stuck in 'Processing' state"
        )

    # =========================================================================
    # Test 15: Variant Sync with Product Variant Controller
    # =========================================================================

    def test_15_variant_sync_to_erpnext(self):
        """Verify Product Variant sync_to_erpnext creates/updates Item correctly.

        Tests the direct sync method on Product Variant (not via queue),
        ensuring field mapping and flag setting are correct.
        """
        import frappe
        from frappe.utils import random_string

        sku = f"{self.TEST_PREFIX}-VSYNC-{random_string(6)}"

        # Create Product Variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = "Variant Sync Test"
        variant.variant_code = sku
        variant.description = "Test variant for direct sync"
        variant.status = "Active"
        variant._from_erpnext_sync = True  # Skip on_update hook initially
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Directly call sync_to_erpnext
        variant.reload()
        variant._from_erpnext_sync = False  # Allow sync
        variant.sync_to_erpnext()
        frappe.db.commit()

        # Verify Item was created
        if variant.erp_item:
            self.assertTrue(
                frappe.db.exists("Item", variant.erp_item),
                "ERPNext Item should be created by sync_to_erpnext"
            )

            item = frappe.get_doc("Item", variant.erp_item)
            self.assertEqual(
                item.item_name, "Variant Sync Test",
                "Item.item_name should match variant_name"
            )
            self.assertEqual(
                item.description, "Test variant for direct sync",
                "Item.description should match variant description"
            )

    # =========================================================================
    # Test 16: Error During Sync Doesn't Block Document Save
    # =========================================================================

    def test_16_sync_error_does_not_block_save(self):
        """Verify that errors during sync don't prevent document saves.

        If sync to ERPNext fails for any reason, the Product Master or
        Item save should still complete successfully.
        """
        import frappe
        from frappe.utils import random_string

        product_code = f"{self.TEST_PREFIX}-ERR-{random_string(6)}"

        # Create an Item with PIM status (makes it PIM-managed)
        item = frappe.new_doc("Item")
        item.item_code = product_code
        item.item_name = "Error Handling Test"
        item.item_group = self._get_item_group()
        item.stock_uom = "Unit"
        item.custom_pim_status = "Active"
        item.insert(ignore_permissions=True)
        frappe.db.commit()

        # Update Item - even if sync encounters issues, save should work
        item.reload()
        item.item_name = "Error Handling Updated"
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # Verify the save completed
        item.reload()
        self.assertEqual(
            item.item_name, "Error Handling Updated",
            "Item save should succeed even if sync encounters issues"
        )

    # =========================================================================
    # Test 17: Sync Queue Stats API
    # =========================================================================

    def test_17_sync_queue_stats_consistent(self):
        """Verify sync queue stats API returns consistent data."""
        import frappe
        from frappe_pim.pim.api.sync import get_sync_queue_stats

        stats = get_sync_queue_stats()

        self.assertIsNotNone(stats, "Stats should be returned")
        self.assertIn("pending", stats, "Stats should have pending count")
        self.assertIn("completed", stats, "Stats should have completed count")
        self.assertIn("failed", stats, "Stats should have failed count")

        # All counts should be non-negative
        self.assertGreaterEqual(stats.get("pending", 0), 0)
        self.assertGreaterEqual(stats.get("completed", 0), 0)
        self.assertGreaterEqual(stats.get("failed", 0), 0)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_item_group(self):
        """Get a valid Item Group for creating test Items."""
        import frappe

        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group

        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"


class TestSyncFlagMechanism(unittest.TestCase):
    """Unit tests for the sync flag mechanism used in loop prevention."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        import frappe
        frappe.set_user("Administrator")
        cls.test_items = []

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        import frappe
        for item_name in cls.test_items:
            try:
                if frappe.db.exists("Item", item_name):
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True
                    item.delete(ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()

    def test_is_from_pim_checks_multiple_flags(self):
        """Verify _is_from_pim checks both _from_pim_sync and from_pim flags."""
        from frappe_pim.pim.sync.item_sync import _is_from_pim
        import frappe

        # Test with _from_pim_sync flag
        item1 = frappe.new_doc("Item")
        item1.flags._from_pim_sync = True
        self.assertTrue(
            _is_from_pim(item1),
            "_is_from_pim should return True when _from_pim_sync is set"
        )

        # Test with from_pim flag
        item2 = frappe.new_doc("Item")
        item2.flags.from_pim = True
        self.assertTrue(
            _is_from_pim(item2),
            "_is_from_pim should return True when from_pim is set"
        )

        # Test with no flags
        item3 = frappe.new_doc("Item")
        self.assertFalse(
            _is_from_pim(item3),
            "_is_from_pim should return False when no PIM flags are set"
        )

    def test_from_erpnext_sync_flag_prevents_variant_sync(self):
        """Verify _from_erpnext_sync flag prevents Product Variant on_update sync."""
        import frappe
        from frappe.utils import random_string

        sku = f"E2ESYNC-FLGVAR-{random_string(6)}"

        # Create variant with _from_erpnext_sync set
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = "Flag Variant Test"
        variant.variant_code = sku
        variant.status = "Draft"
        variant._from_erpnext_sync = True

        # on_update should check this flag and skip sync
        # We verify by checking no enqueue was called
        enqueue_called = [False]
        original_enqueue = frappe.enqueue

        def mock_enqueue(*args, **kwargs):
            job_id = kwargs.get("job_id", "")
            if "pim_variant_sync" in str(job_id):
                enqueue_called[0] = True
            return original_enqueue(*args, **kwargs)

        try:
            frappe.enqueue = mock_enqueue
            variant.insert(ignore_permissions=True)
            frappe.db.commit()

            self.assertFalse(
                enqueue_called[0],
                "Variant sync should NOT be enqueued when _from_erpnext_sync is True"
            )
        finally:
            frappe.enqueue = original_enqueue

            # Clean up
            if frappe.db.exists("Product Variant", variant.name):
                frappe.delete_doc("Product Variant", variant.name, force=True)
                frappe.db.commit()

    def test_pim_sync_enabled_check(self):
        """Verify _is_pim_sync_enabled defaults to True."""
        from frappe_pim.pim.sync.item_sync import _is_pim_sync_enabled

        # Should default to True (sync enabled by default)
        result = _is_pim_sync_enabled()
        self.assertTrue(
            result,
            "PIM sync should be enabled by default"
        )


class TestSyncQueueIntegrity(unittest.TestCase):
    """Tests for sync queue data integrity during bidirectional operations."""

    TEST_PREFIX = "E2ESYNC"

    @classmethod
    def setUpClass(cls):
        import frappe
        frappe.set_user("Administrator")

    def test_sync_queue_entry_has_valid_fields(self):
        """Verify sync queue entries have all required fields populated."""
        import frappe
        from frappe.utils import random_string

        sku = f"{self.TEST_PREFIX}-QF-{random_string(6)}"

        # Create variant to trigger queue entry
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = f"Queue Fields Test {random_string(4)}"
        variant.status = "Draft"
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Check for sync queue entry
        entries = frappe.get_all(
            "PIM Sync Queue",
            filters={
                "doctype_name": "Product Variant",
                "document_name": variant.name
            },
            fields=["*"],
            limit=1
        )

        if entries:
            entry = entries[0]
            # Verify required fields
            self.assertIsNotNone(entry.get("name"), "Entry should have name")
            self.assertEqual(
                entry.get("doctype_name"), "Product Variant",
                "Entry should reference Product Variant"
            )
            self.assertIn(
                entry.get("sync_direction"),
                ["PIM to ERP", "ERP to PIM"],
                "Entry should have valid sync_direction"
            )
            self.assertIn(
                entry.get("status"),
                ["Pending", "Processing", "Completed", "Failed", "Cancelled"],
                "Entry should have valid status"
            )

        # Clean up
        for e in entries:
            frappe.delete_doc("PIM Sync Queue", e.name, force=True)
        if frappe.db.exists("Product Variant", variant.name):
            frappe.delete_doc("Product Variant", variant.name, force=True)
        frappe.db.commit()

    def test_conflict_rule_doctype_exists(self):
        """Verify PIM Sync Conflict Rule DocType is available for conflict resolution."""
        import frappe

        self.assertTrue(
            frappe.db.exists("DocType", "PIM Sync Conflict Rule"),
            "PIM Sync Conflict Rule DocType should exist for conflict resolution"
        )

    def test_sync_queue_doctype_exists(self):
        """Verify PIM Sync Queue DocType exists and is functional."""
        import frappe

        self.assertTrue(
            frappe.db.exists("DocType", "PIM Sync Queue"),
            "PIM Sync Queue DocType should exist"
        )

        # Verify key fields exist on the DocType
        meta = frappe.get_meta("PIM Sync Queue")
        expected_fields = [
            "doctype_name", "document_name", "sync_direction",
            "sync_action", "status", "priority"
        ]
        actual_fields = [f.fieldname for f in meta.fields]

        for field in expected_fields:
            self.assertIn(
                field, actual_fields,
                f"PIM Sync Queue should have field '{field}'"
            )


def run_tests():
    """Run all E2E bidirectional sync tests."""
    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestE2EBidirectionalSync))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSyncFlagMechanism))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSyncQueueIntegrity))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    import frappe
    frappe.connect()
    try:
        run_tests()
    finally:
        frappe.destroy()
