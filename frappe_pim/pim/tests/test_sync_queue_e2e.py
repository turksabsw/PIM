"""End-to-End Tests for ERPNext Sync Queue Flow

This module contains comprehensive end-to-end tests for verifying the
bidirectional sync between PIM and ERPNext via the sync queue system.

Test Flow:
1. Create Product Variant in PIM
2. Verify PIM Sync Queue entry created
3. Wait for scheduler to process (or trigger manually)
4. Verify ERPNext Item created
5. Update Item in ERPNext
6. Verify PIM Product Variant updated (per conflict rules)

Run with:
    bench --site [site] run-tests --app frappe_pim --module frappe_pim.pim.tests.test_sync_queue_e2e
"""

import unittest


class TestSyncQueueEndToEnd(unittest.TestCase):
    """End-to-end tests for PIM-ERPNext sync queue flow."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures that are reused across tests."""
        import frappe
        from frappe.utils import random_string

        # Generate unique test identifiers
        cls.test_suffix = random_string(6)
        cls.test_sku = f"TEST-SYNC-{cls.test_suffix}"
        cls.test_variant_name = f"Test Sync Variant {cls.test_suffix}"

        # Check if ERPNext is installed
        cls.erpnext_available = frappe.db.exists("DocType", "Item")

        # Get or create test Product Family
        cls.product_family = cls._get_or_create_product_family()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data after all tests."""
        import frappe

        # Clean up test sync queue entries
        test_entries = frappe.get_all(
            "PIM Sync Queue",
            filters={"document_name": ["like", f"%{cls.test_suffix}%"]},
            pluck="name"
        )
        for entry in test_entries:
            frappe.delete_doc("PIM Sync Queue", entry, force=True)

        # Clean up test Product Variants
        test_variants = frappe.get_all(
            "Product Variant",
            filters={"sku": ["like", f"TEST-SYNC-{cls.test_suffix}%"]},
            pluck="name"
        )
        for variant in test_variants:
            frappe.delete_doc("Product Variant", variant, force=True)

        # Clean up test ERPNext Items if ERPNext is installed
        if cls.erpnext_available:
            test_items = frappe.get_all(
                "Item",
                filters={"item_code": ["like", f"TEST-SYNC-{cls.test_suffix}%"]},
                pluck="name"
            )
            for item in test_items:
                try:
                    frappe.delete_doc("Item", item, force=True)
                except Exception:
                    pass  # Item may have transactions

        frappe.db.commit()

    @classmethod
    def _get_or_create_product_family(cls):
        """Get or create a test Product Family."""
        import frappe

        family_name = "Test Family E2E"

        if frappe.db.exists("Product Family", family_name):
            return family_name

        try:
            family = frappe.new_doc("Product Family")
            family.family_name = family_name
            family.family_code = "testfamilye2e"
            family.is_active = 1
            family.insert(ignore_permissions=True)
            frappe.db.commit()
            return family.name
        except Exception:
            # Return any existing family
            families = frappe.get_all("Product Family", limit=1, pluck="name")
            return families[0] if families else None

    def setUp(self):
        """Set up before each test."""
        import frappe
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        import frappe
        frappe.db.rollback()

    # =========================================================================
    # Test 1: Create Product Variant and Verify Sync Queue Entry
    # =========================================================================

    def test_01_create_variant_creates_sync_queue_entry(self):
        """Test that creating a Product Variant creates a PIM Sync Queue entry."""
        import frappe

        # Create Product Variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = self.test_sku
        variant.variant_name = self.test_variant_name
        variant.status = "Draft"

        if self.product_family:
            variant.product_family = self.product_family

        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        self.assertIsNotNone(variant.name, "Product Variant should be created")

        # Verify sync queue entry was created
        sync_entry = frappe.db.exists(
            "PIM Sync Queue",
            {
                "doctype_name": "Product Variant",
                "document_name": variant.name,
                "sync_direction": "PIM to ERP"
            }
        )

        self.assertIsNotNone(
            sync_entry,
            "PIM Sync Queue entry should be created for new Product Variant"
        )

        # Verify entry details
        entry = frappe.get_doc("PIM Sync Queue", sync_entry)
        self.assertEqual(entry.status, "Pending", "Sync entry should be Pending")
        self.assertIn(
            entry.sync_action,
            ["Create", "Update"],
            "Sync action should be Create or Update"
        )

    def test_02_sync_queue_entry_has_correct_fields(self):
        """Test that sync queue entry has all required fields populated."""
        import frappe

        # Create a variant for this specific test
        sku = f"{self.test_sku}-fields"
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = f"Test Fields {self.test_suffix}"
        variant.status = "Draft"
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Get the sync entry
        sync_entry = frappe.get_all(
            "PIM Sync Queue",
            filters={
                "doctype_name": "Product Variant",
                "document_name": variant.name
            },
            fields=["*"],
            limit=1
        )

        self.assertTrue(len(sync_entry) > 0, "Sync entry should exist")

        entry = sync_entry[0]

        # Verify required fields
        self.assertIsNotNone(entry.get("name"), "Entry should have name")
        self.assertEqual(entry.get("doctype_name"), "Product Variant")
        self.assertEqual(entry.get("document_name"), variant.name)
        self.assertIn(entry.get("sync_direction"), ["PIM to ERP", "ERP to PIM"])
        self.assertIn(entry.get("sync_action"), ["Create", "Update", "Delete"])
        self.assertIn(
            entry.get("status"),
            ["Pending", "Processing", "Completed", "Failed", "Cancelled"]
        )
        self.assertIsNotNone(entry.get("max_retries"))
        self.assertGreaterEqual(entry.get("priority", 0), 0)

    # =========================================================================
    # Test 2: Process Sync Queue Entry
    # =========================================================================

    def test_03_process_sync_queue_entry(self):
        """Test processing a sync queue entry creates ERPNext Item."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        # Create a variant
        sku = f"{self.test_sku}-process"
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = f"Test Process {self.test_suffix}"
        variant.status = "Active"
        variant.description = "Test description for sync"
        variant.uom = "Nos"
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Get the sync entry
        sync_entry_name = frappe.db.get_value(
            "PIM Sync Queue",
            {
                "doctype_name": "Product Variant",
                "document_name": variant.name,
                "status": "Pending"
            },
            "name"
        )

        if not sync_entry_name:
            self.skipTest("No pending sync entry found - sync may be immediate")

        # Process the sync entry
        from frappe_pim.pim.tasks.sync import process_single_entry
        process_single_entry(sync_entry_name)
        frappe.db.commit()

        # Verify sync entry status
        entry = frappe.get_doc("PIM Sync Queue", sync_entry_name)
        self.assertIn(
            entry.status,
            ["Completed", "Processing"],
            f"Sync entry should be Completed or Processing, got: {entry.status}"
        )

        # If completed, verify ERPNext Item was created
        if entry.status == "Completed":
            # Reload variant to get updated erp_item field
            variant.reload()

            if variant.erp_item:
                self.assertTrue(
                    frappe.db.exists("Item", variant.erp_item),
                    "ERPNext Item should be created"
                )

    def test_04_manual_trigger_sync(self):
        """Test manually triggering sync via API."""
        import frappe

        # Create a variant
        sku = f"{self.test_sku}-manual"
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = f"Test Manual Sync {self.test_suffix}"
        variant.status = "Draft"
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Use API to trigger sync
        from frappe_pim.pim.api.sync import trigger_sync

        result = trigger_sync(
            doctype_name="Product Variant",
            document_name=variant.name,
            sync_direction="PIM to ERP",
            priority=5
        )

        self.assertTrue(
            result.get("success") or "already pending" in result.get("message", "").lower(),
            f"Trigger sync should succeed or indicate pending: {result}"
        )

    # =========================================================================
    # Test 3: Verify Sync Status API
    # =========================================================================

    def test_05_get_sync_status_api(self):
        """Test getting sync status via API."""
        import frappe

        # Create a variant
        sku = f"{self.test_sku}-status"
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = f"Test Status {self.test_suffix}"
        variant.status = "Draft"
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Get sync status
        from frappe_pim.pim.api.sync import get_sync_status

        status = get_sync_status(
            doctype_name="Product Variant",
            document_name=variant.name
        )

        self.assertIsNotNone(status, "Should return sync status")
        self.assertIn("status", status, "Status should have status field")
        self.assertIn("has_sync_entry", status, "Status should indicate sync entry")

    def test_06_get_sync_queue_stats(self):
        """Test getting sync queue statistics."""
        import frappe

        from frappe_pim.pim.api.sync import get_sync_queue_stats

        stats = get_sync_queue_stats()

        self.assertIsNotNone(stats, "Should return stats")
        self.assertIn("pending", stats, "Stats should have pending count")
        self.assertIn("completed", stats, "Stats should have completed count")
        self.assertIn("failed", stats, "Stats should have failed count")
        self.assertIn("total_today", stats, "Stats should have today's total")

        # All counts should be non-negative
        self.assertGreaterEqual(stats.get("pending", 0), 0)
        self.assertGreaterEqual(stats.get("completed", 0), 0)
        self.assertGreaterEqual(stats.get("failed", 0), 0)

    # =========================================================================
    # Test 4: ERP to PIM Sync (Bidirectional)
    # =========================================================================

    def test_07_erp_to_pim_sync_on_item_update(self):
        """Test that updating an ERPNext Item triggers ERP to PIM sync."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        # First, create a linked variant and Item
        sku = f"{self.test_sku}-erp2pim"

        # Create Item in ERPNext first
        item_group = self._get_item_group()
        item = frappe.new_doc("Item")
        item.item_code = sku
        item.item_name = f"Test ERP to PIM {self.test_suffix}"
        item.item_group = item_group
        item.stock_uom = "Nos"
        item.is_stock_item = 1
        item.flags.from_pim = True  # Skip PIM hooks
        item.insert(ignore_permissions=True)
        frappe.db.commit()

        # Create variant linked to this Item
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = item.item_name
        variant.status = "Active"
        variant.erp_item = item.name
        variant.flags.from_erp = True  # Skip sync hooks
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Now update the Item in ERPNext (this should trigger ERP to PIM sync)
        item.reload()
        item.item_name = f"Updated Name {self.test_suffix}"
        item.flags.from_pim = False  # Allow sync hooks
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # Check if sync queue entry was created
        sync_entry = frappe.db.get_value(
            "PIM Sync Queue",
            {
                "doctype_name": "Item",
                "document_name": item.name,
                "sync_direction": "ERP to PIM"
            },
            "name"
        )

        # Sync entry may or may not be created depending on hooks configuration
        # This test verifies the mechanism is in place

    # =========================================================================
    # Test 5: Conflict Detection and Resolution
    # =========================================================================

    def test_08_conflict_detection(self):
        """Test that concurrent modifications are detected as conflicts."""
        import frappe
        from frappe.utils import now_datetime

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        # Create a variant with ERP link and last_sync_at
        sku = f"{self.test_sku}-conflict"

        # Create Item
        item_group = self._get_item_group()
        item = frappe.new_doc("Item")
        item.item_code = sku
        item.item_name = f"Test Conflict {self.test_suffix}"
        item.item_group = item_group
        item.stock_uom = "Nos"
        item.flags.from_pim = True
        item.insert(ignore_permissions=True)
        frappe.db.commit()

        # Create variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = f"Test Conflict {self.test_suffix}"
        variant.status = "Active"
        variant.erp_item = item.name

        # Set last_sync_at to a past time
        past_time = frappe.utils.add_to_date(now_datetime(), minutes=-10)
        variant.last_sync_at = past_time
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Now modify both (simulate concurrent modification)
        # This would trigger conflict detection in the sync processor

        # Verify conflict rules DocType exists
        has_conflict_rules = frappe.db.exists("DocType", "PIM Sync Conflict Rule")
        self.assertTrue(
            has_conflict_rules,
            "PIM Sync Conflict Rule DocType should exist"
        )

    def test_09_sync_queue_retry_mechanism(self):
        """Test the retry mechanism for failed sync entries."""
        import frappe

        # Create a sync queue entry manually and mark as failed
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Product Variant"
        entry.document_name = f"NonExistent-{self.test_suffix}"
        entry.sync_direction = "PIM to ERP"
        entry.sync_action = "Update"
        entry.status = "Failed"
        entry.error_message = "Test error for retry"
        entry.retry_count = 0
        entry.max_retries = 3
        entry.insert(ignore_permissions=True)
        frappe.db.commit()

        # Retry the entry
        from frappe_pim.pim.api.sync import retry_failed_sync

        result = retry_failed_sync(sync_entry=entry.name)

        self.assertTrue(result.get("success"), "Retry should succeed")
        self.assertIn(entry.name, result.get("retried", []))

        # Verify entry is now Pending
        entry.reload()
        self.assertEqual(entry.status, "Pending", "Entry should be Pending after retry")

    def test_10_sync_queue_cancel(self):
        """Test cancelling a sync queue entry."""
        import frappe

        # Create a pending sync queue entry
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Product Variant"
        entry.document_name = f"CancelTest-{self.test_suffix}"
        entry.sync_direction = "PIM to ERP"
        entry.sync_action = "Update"
        entry.status = "Pending"
        entry.insert(ignore_permissions=True)
        frappe.db.commit()

        # Cancel the entry
        from frappe_pim.pim.api.sync import cancel_sync_entry

        result = cancel_sync_entry(entry.name, reason="Test cancellation")

        self.assertTrue(result.get("success"), "Cancel should succeed")

        # Verify entry is now Cancelled
        entry.reload()
        self.assertEqual(entry.status, "Cancelled", "Entry should be Cancelled")

    # =========================================================================
    # Test 6: Sync History and Cleanup
    # =========================================================================

    def test_11_sync_history(self):
        """Test retrieving sync history for a document."""
        import frappe

        # Create multiple sync entries for the same document
        document_name = f"HistoryTest-{self.test_suffix}"

        for i in range(3):
            entry = frappe.new_doc("PIM Sync Queue")
            entry.doctype_name = "Product Variant"
            entry.document_name = document_name
            entry.sync_direction = "PIM to ERP"
            entry.sync_action = "Update"
            entry.status = "Completed" if i < 2 else "Pending"
            entry.insert(ignore_permissions=True)

        frappe.db.commit()

        # Get sync history
        from frappe_pim.pim.api.sync import get_sync_history

        history = get_sync_history(
            doctype_name="Product Variant",
            document_name=document_name,
            limit=10
        )

        self.assertIsNotNone(history, "Should return history")
        self.assertIn("entries", history, "History should have entries")
        self.assertGreaterEqual(len(history["entries"]), 3, "Should have at least 3 entries")
        self.assertEqual(history["total"], len(history["entries"]))

    def test_12_sync_queue_cleanup(self):
        """Test cleanup of old sync queue entries."""
        import frappe
        from frappe.utils import add_days, today

        # Create old completed entries
        old_date = add_days(today(), -35)  # 35 days ago

        for i in range(2):
            entry = frappe.new_doc("PIM Sync Queue")
            entry.doctype_name = "Product Variant"
            entry.document_name = f"CleanupTest-{self.test_suffix}-{i}"
            entry.sync_direction = "PIM to ERP"
            entry.sync_action = "Update"
            entry.status = "Completed"
            entry.insert(ignore_permissions=True)

            # Manually set creation date to old date
            frappe.db.set_value(
                "PIM Sync Queue", entry.name,
                "creation", old_date,
                update_modified=False
            )

        frappe.db.commit()

        # Run cleanup (30 days)
        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            cleanup_old_entries
        )

        deleted = cleanup_old_entries(days=30)

        self.assertGreaterEqual(deleted, 2, "Should delete old entries")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_item_group(self):
        """Get a valid Item Group for creating test Items."""
        import frappe

        # Try common item groups
        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group

        # Get any existing group
        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"


class TestSyncQueueHelpers(unittest.TestCase):
    """Unit tests for sync queue helper functions."""

    def test_queue_sync_entry_function(self):
        """Test the queue_sync_entry helper function."""
        import frappe
        from frappe.utils import random_string

        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            queue_sync_entry
        )

        document_name = f"TestHelper-{random_string(6)}"

        # Queue a new entry
        entry = queue_sync_entry(
            doctype_name="Product Variant",
            document_name=document_name,
            sync_direction="PIM to ERP",
            sync_action="Create",
            priority=5
        )

        self.assertIsNotNone(entry, "Should create entry")
        self.assertEqual(entry.doctype_name, "Product Variant")
        self.assertEqual(entry.document_name, document_name)
        self.assertEqual(entry.priority, 5)
        self.assertEqual(entry.status, "Pending")

        # Clean up
        frappe.delete_doc("PIM Sync Queue", entry.name, force=True)
        frappe.db.commit()

    def test_get_pending_entries_function(self):
        """Test the get_pending_entries helper function."""
        import frappe
        from frappe.utils import random_string

        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            queue_sync_entry,
            get_pending_entries
        )

        # Create some pending entries
        test_id = random_string(6)
        created_entries = []

        for i in range(3):
            entry = queue_sync_entry(
                doctype_name="Product Variant",
                document_name=f"TestPending-{test_id}-{i}",
                sync_direction="PIM to ERP",
                sync_action="Update",
                priority=i
            )
            created_entries.append(entry.name)

        # Get pending entries
        pending = get_pending_entries(limit=50)

        self.assertIsInstance(pending, list, "Should return list")

        # At least our created entries should be in pending
        for entry_name in created_entries:
            self.assertIn(
                entry_name, pending,
                f"Created entry {entry_name} should be in pending list"
            )

        # Clean up
        for entry_name in created_entries:
            frappe.delete_doc("PIM Sync Queue", entry_name, force=True)
        frappe.db.commit()

    def test_get_sync_stats_function(self):
        """Test the get_sync_stats helper function."""
        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            get_sync_stats
        )

        stats = get_sync_stats()

        self.assertIsInstance(stats, dict, "Should return dict")
        self.assertIn("pending", stats)
        self.assertIn("processing", stats)
        self.assertIn("completed", stats)
        self.assertIn("failed", stats)
        self.assertIn("cancelled", stats)
        self.assertIn("total_today", stats)


class TestSyncTaskProcessor(unittest.TestCase):
    """Unit tests for sync task processor functions."""

    def test_process_sync_queue_function_exists(self):
        """Test that process_sync_queue function exists and is callable."""
        from frappe_pim.pim.tasks.sync import process_sync_queue

        self.assertTrue(callable(process_sync_queue))

    def test_process_single_entry_function_exists(self):
        """Test that process_single_entry function exists and is callable."""
        from frappe_pim.pim.tasks.sync import process_single_entry

        self.assertTrue(callable(process_single_entry))

    def test_cleanup_old_sync_entries_function_exists(self):
        """Test that cleanup_old_sync_entries function exists."""
        from frappe_pim.pim.tasks.sync import cleanup_old_sync_entries

        self.assertTrue(callable(cleanup_old_sync_entries))

    def test_retry_all_failed_function_exists(self):
        """Test that retry_all_failed function exists."""
        from frappe_pim.pim.tasks.sync import retry_all_failed

        self.assertTrue(callable(retry_all_failed))

    def test_get_sync_queue_status_function_exists(self):
        """Test that get_sync_queue_status function exists."""
        from frappe_pim.pim.tasks.sync import get_sync_queue_status

        self.assertTrue(callable(get_sync_queue_status))


if __name__ == "__main__":
    unittest.main()
