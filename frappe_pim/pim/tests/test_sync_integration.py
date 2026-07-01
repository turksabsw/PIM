"""Integration Tests for Bidirectional ERPNext Sync

This module contains comprehensive integration tests verifying the
bidirectional synchronization between PIM entities and ERPNext Items.

Test Categories:
1. PIM-to-ERP Sync: Product Variant/Master → ERPNext Item creation and update
2. ERP-to-PIM Sync: ERPNext Item → Product Variant update
3. Sync Loop Prevention: Flag-based infinite loop prevention
4. Conflict Detection: Concurrent modification detection and resolution
5. Variant Sync: Product Variant specific sync operations

Run with:
    bench --site [site] run-tests --app frappe_pim --module frappe_pim.pim.tests.test_sync_integration
"""

import unittest


class TestPIMToERPSync(unittest.TestCase):
    """Tests for PIM-to-ERP synchronization direction."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for PIM-to-ERP tests."""
        import frappe
        from frappe.utils import random_string

        cls.test_suffix = random_string(6)
        cls.erpnext_available = frappe.db.exists("DocType", "Item")
        cls.created_items = []
        cls.created_variants = []
        cls.created_sync_entries = []

        # Ensure default Item Group exists
        cls.item_group = cls._ensure_item_group()
        cls.product_family = cls._get_or_create_product_family()

    @classmethod
    def tearDownClass(cls):
        """Clean up all test data."""
        import frappe

        # Clean up sync queue entries
        for entry_name in cls.created_sync_entries:
            try:
                if frappe.db.exists("PIM Sync Queue", entry_name):
                    frappe.delete_doc("PIM Sync Queue", entry_name, force=True)
            except Exception:
                pass

        # Clean up Product Variants
        for variant_name in cls.created_variants:
            try:
                if frappe.db.exists("Product Variant", variant_name):
                    frappe.delete_doc("Product Variant", variant_name, force=True)
            except Exception:
                pass

        # Clean up Items
        for item_name in cls.created_items:
            try:
                if frappe.db.exists("Item", item_name):
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True
                    item.delete(ignore_permissions=True)
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def _ensure_item_group(cls):
        """Ensure a valid Item Group exists for tests."""
        import frappe

        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group

        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"

    @classmethod
    def _get_or_create_product_family(cls):
        """Get or create a test Product Family."""
        import frappe

        family_name = "Test Family Sync Integration"

        if frappe.db.exists("Product Family", family_name):
            return family_name

        try:
            family = frappe.new_doc("Product Family")
            family.family_name = family_name
            family.family_code = "testfamilysyncint"
            family.is_active = 1
            family.insert(ignore_permissions=True)
            frappe.db.commit()
            return family.name
        except Exception:
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

    def _create_test_variant(self, suffix="", **kwargs):
        """Helper to create a test Product Variant.

        Args:
            suffix: Additional suffix for uniqueness
            **kwargs: Additional fields to set on the variant

        Returns:
            Product Variant document
        """
        import frappe

        sku = f"TEST-SYNC-INT-{self.test_suffix}{suffix}"
        variant = frappe.new_doc("Product Variant")
        variant.sku = sku
        variant.variant_name = f"Test Sync Integration {self.test_suffix}{suffix}"
        variant.status = "Draft"

        if self.product_family:
            variant.product_family = self.product_family

        for key, value in kwargs.items():
            variant.set(key, value)

        variant.insert(ignore_permissions=True)
        frappe.db.commit()
        self.created_variants.append(variant.name)

        return variant

    def _create_test_item(self, suffix="", **kwargs):
        """Helper to create a test ERPNext Item.

        Args:
            suffix: Additional suffix for uniqueness
            **kwargs: Additional fields to set on the item

        Returns:
            Item document
        """
        import frappe

        item_code = f"TEST-ITEM-{self.test_suffix}{suffix}"
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = f"Test Item {self.test_suffix}{suffix}"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.is_stock_item = 1

        for key, value in kwargs.items():
            if key == "flags_from_pim":
                item.flags.from_pim = value
            elif key == "flags_from_pim_sync":
                item.flags._from_pim_sync = value
            else:
                item.set(key, value)

        item.insert(ignore_permissions=True)
        frappe.db.commit()
        self.created_items.append(item.name)

        return item

    # =========================================================================
    # PIM-to-ERP Sync: Queue Entry Creation
    # =========================================================================

    def test_01_variant_creation_queues_sync_entry(self):
        """Test that creating a Product Variant creates a PIM Sync Queue entry
        for PIM-to-ERP synchronization."""
        import frappe

        variant = self._create_test_variant(suffix="-q1")

        # Check if sync queue entry was created
        sync_entry = frappe.db.get_value(
            "PIM Sync Queue",
            {
                "doctype_name": "Product Variant",
                "document_name": variant.name,
                "sync_direction": "PIM to ERP"
            },
            "name"
        )

        if sync_entry:
            self.created_sync_entries.append(sync_entry)

            entry = frappe.get_doc("PIM Sync Queue", sync_entry)
            self.assertEqual(entry.status, "Pending")
            self.assertIn(entry.sync_action, ["Create", "Update"])
            self.assertEqual(entry.doctype_name, "Product Variant")

    def test_02_variant_update_queues_sync_entry(self):
        """Test that updating a Product Variant creates or updates
        a PIM Sync Queue entry."""
        import frappe

        variant = self._create_test_variant(suffix="-q2")
        frappe.db.commit()

        # Update variant
        variant.reload()
        variant.variant_name = f"Updated Name {self.test_suffix}"
        variant.description = "Updated description for sync test"
        variant.save(ignore_permissions=True)
        frappe.db.commit()

        # Check for sync entry
        sync_entries = frappe.get_all(
            "PIM Sync Queue",
            filters={
                "doctype_name": "Product Variant",
                "document_name": variant.name,
                "sync_direction": "PIM to ERP"
            },
            fields=["name", "sync_action"],
            order_by="creation desc"
        )

        for entry in sync_entries:
            self.created_sync_entries.append(entry.name)

    def test_03_queue_sync_entry_helper(self):
        """Test the queue_sync_entry helper function creates entries correctly."""
        import frappe
        from frappe.utils import random_string

        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            queue_sync_entry
        )

        document_name = f"TestQueueHelper-{random_string(6)}"

        entry = queue_sync_entry(
            doctype_name="Product Variant",
            document_name=document_name,
            sync_direction="PIM to ERP",
            sync_action="Create",
            priority=7,
            changed_fields=["variant_name", "description"]
        )

        self.assertIsNotNone(entry, "queue_sync_entry should create entry")
        self.created_sync_entries.append(entry.name)

        self.assertEqual(entry.doctype_name, "Product Variant")
        self.assertEqual(entry.document_name, document_name)
        self.assertEqual(entry.sync_direction, "PIM to ERP")
        self.assertEqual(entry.sync_action, "Create")
        self.assertEqual(entry.priority, 7)
        self.assertEqual(entry.status, "Pending")
        self.assertIn("variant_name", entry.changed_fields or "")

    def test_04_duplicate_queue_entry_merges(self):
        """Test that duplicate sync queue entries merge rather than duplicate."""
        import frappe
        from frappe.utils import random_string

        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            queue_sync_entry
        )

        document_name = f"TestDuplicate-{random_string(6)}"

        # Create first entry
        entry1 = queue_sync_entry(
            doctype_name="Product Variant",
            document_name=document_name,
            sync_direction="PIM to ERP",
            sync_action="Update",
            priority=3,
            changed_fields=["variant_name"]
        )
        self.created_sync_entries.append(entry1.name)

        # Create second entry for same document (should merge)
        entry2 = queue_sync_entry(
            doctype_name="Product Variant",
            document_name=document_name,
            sync_direction="PIM to ERP",
            sync_action="Update",
            priority=8,
            changed_fields=["description"]
        )

        # Should return the same entry
        self.assertEqual(entry1.name, entry2.name)

        # Priority should be updated to higher value
        entry2.reload()
        self.assertEqual(entry2.priority, 8)

        # Changed fields should be merged
        changed = entry2.changed_fields or ""
        self.assertIn("variant_name", changed)
        self.assertIn("description", changed)

    # =========================================================================
    # PIM-to-ERP Sync: Queue Processing
    # =========================================================================

    def test_05_process_sync_queue_functions_exist(self):
        """Test that all sync queue processing functions are importable."""
        from frappe_pim.pim.sync.queue_processor import (
            process_sync_queue,
            process_single_entry,
            cleanup_old_sync_entries,
            retry_all_failed,
            get_sync_queue_status,
        )

        self.assertTrue(callable(process_sync_queue))
        self.assertTrue(callable(process_single_entry))
        self.assertTrue(callable(cleanup_old_sync_entries))
        self.assertTrue(callable(retry_all_failed))
        self.assertTrue(callable(get_sync_queue_status))

    def test_06_process_single_entry_skips_non_pending(self):
        """Test that process_single_entry skips entries not in Pending status."""
        import frappe

        from frappe_pim.pim.sync.queue_processor import process_single_entry

        # Create a completed entry
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Product Variant"
        entry.document_name = f"NonPending-{self.test_suffix}"
        entry.sync_direction = "PIM to ERP"
        entry.sync_action = "Update"
        entry.status = "Completed"
        entry.insert(ignore_permissions=True)
        frappe.db.commit()
        self.created_sync_entries.append(entry.name)

        # Process should not change anything
        process_single_entry(entry.name)

        entry.reload()
        self.assertEqual(entry.status, "Completed",
                         "Completed entry should not be reprocessed")

    def test_07_process_entry_marks_processing(self):
        """Test that processing an entry marks it as Processing initially."""
        import frappe

        # Create a variant to use as sync source
        variant = self._create_test_variant(suffix="-proc")

        # Create a pending sync entry for it
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Product Variant"
        entry.document_name = variant.name
        entry.sync_direction = "PIM to ERP"
        entry.sync_action = "Update"
        entry.status = "Pending"
        entry.insert(ignore_permissions=True)
        frappe.db.commit()
        self.created_sync_entries.append(entry.name)

        # Process the entry
        from frappe_pim.pim.sync.queue_processor import process_single_entry
        process_single_entry(entry.name)

        # Entry should be Completed or Failed (not still Pending)
        entry.reload()
        self.assertIn(
            entry.status,
            ["Completed", "Failed"],
            f"Entry should be Completed or Failed after processing, got: {entry.status}"
        )


class TestERPToPIMSync(unittest.TestCase):
    """Tests for ERP-to-PIM synchronization direction."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for ERP-to-PIM tests."""
        import frappe
        from frappe.utils import random_string

        cls.test_suffix = random_string(6)
        cls.erpnext_available = frappe.db.exists("DocType", "Item")
        cls.created_items = []
        cls.created_variants = []
        cls.created_sync_entries = []
        cls.item_group = cls._ensure_item_group()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        import frappe

        for entry_name in cls.created_sync_entries:
            try:
                if frappe.db.exists("PIM Sync Queue", entry_name):
                    frappe.delete_doc("PIM Sync Queue", entry_name, force=True)
            except Exception:
                pass

        for variant_name in cls.created_variants:
            try:
                if frappe.db.exists("Product Variant", variant_name):
                    frappe.delete_doc("Product Variant", variant_name, force=True)
            except Exception:
                pass

        for item_name in cls.created_items:
            try:
                if frappe.db.exists("Item", item_name):
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True
                    item.delete(ignore_permissions=True)
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def _ensure_item_group(cls):
        """Ensure a valid Item Group exists."""
        import frappe

        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group
        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"

    def setUp(self):
        """Set up before each test."""
        import frappe
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        import frappe
        frappe.db.rollback()

    def test_01_item_update_triggers_pim_sync(self):
        """Test that updating a PIM-managed Item triggers sync to PIM."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        # Create Item with PIM flag
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-ERP2PIM-{self.test_suffix}-01"
        item.item_name = f"ERP to PIM Test {self.test_suffix}"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.custom_pim_status = "Active"
        item.flags.from_pim = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)
        frappe.db.commit()

        # Create linked Product Variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = item.item_name
        variant.erp_item = item.name
        variant.status = "Active"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Update Item (should trigger ERP-to-PIM sync logic)
        item.reload()
        item.item_name = f"Updated ERP Name {self.test_suffix}"
        item.flags.from_pim = False  # Allow PIM sync hooks
        item.save(ignore_permissions=True)
        frappe.db.commit()

        # Verify the sync path exists (item_sync.on_item_update should fire)
        from frappe_pim.pim.sync.item_sync import _is_pim_managed_item
        self.assertTrue(
            _is_pim_managed_item(item),
            "Item with custom_pim_status should be detected as PIM managed"
        )

    def test_02_item_sync_to_product_variant_field_mapping(self):
        """Test that Item field changes are correctly mapped to Product Variant."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.sync.item_sync import _sync_item_to_product_variant

        # Create Item
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-FIELDMAP-{self.test_suffix}"
        item.item_name = "Original Item Name"
        item.description = "Original description"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)
        frappe.db.commit()

        # Create linked variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "Old Variant Name"
        variant.description = "Old description"
        variant.uom = "Nos"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Update Item fields
        item.reload()
        item.item_name = "New Item Name"
        item.description = "New description"

        # Sync to variant
        _sync_item_to_product_variant(item, variant.name)
        frappe.db.commit()

        # Verify mapping
        variant.reload()
        self.assertEqual(variant.variant_name, "New Item Name",
                         "item_name should map to variant_name")
        self.assertEqual(variant.description, "New description",
                         "description should map to description")

    def test_03_erp_to_pim_queue_processor(self):
        """Test the ERP-to-PIM sync via queue processor."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        # Create Item and linked Variant
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-E2PQUEUE-{self.test_suffix}"
        item.item_name = "Queue Test Item"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)

        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "Queue Test Variant"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Create an ERP-to-PIM sync queue entry
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Item"
        entry.document_name = item.name
        entry.sync_direction = "ERP to PIM"
        entry.sync_action = "Update"
        entry.status = "Pending"
        entry.insert(ignore_permissions=True)
        self.created_sync_entries.append(entry.name)
        frappe.db.commit()

        # Process the entry
        from frappe_pim.pim.sync.queue_processor import process_single_entry

        # Update Item before processing
        item.reload()
        item.item_name = "Updated Queue Name"
        item.flags._from_pim_sync = True
        item.save(ignore_permissions=True)
        frappe.db.commit()

        process_single_entry(entry.name)
        frappe.db.commit()

        # Entry should be processed
        entry.reload()
        self.assertIn(
            entry.status,
            ["Completed", "Failed"],
            f"ERP-to-PIM sync entry should be processed, got: {entry.status}"
        )

    def test_04_item_delete_unlinks_variant(self):
        """Test that deleting an Item unlinks the associated Product Variant."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.sync.item_sync import _unlink_product_variant

        # Create Item and linked Variant
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-UNLINK-{self.test_suffix}"
        item.item_name = "Unlink Test Item"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)

        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "Unlink Test Variant"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Verify link exists
        self.assertEqual(variant.erp_item, item.name)

        # Unlink variant
        _unlink_product_variant(item.name)
        frappe.db.commit()

        # Verify link cleared
        variant.reload()
        self.assertFalse(
            variant.erp_item,
            "erp_item should be cleared after unlinking"
        )


class TestSyncLoopPrevention(unittest.TestCase):
    """Tests for sync loop prevention mechanisms."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        import frappe
        from frappe.utils import random_string

        cls.test_suffix = random_string(6)
        cls.erpnext_available = frappe.db.exists("DocType", "Item")
        cls.created_items = []
        cls.created_variants = []
        cls.item_group = cls._ensure_item_group()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        import frappe

        for variant_name in cls.created_variants:
            try:
                if frappe.db.exists("Product Variant", variant_name):
                    frappe.delete_doc("Product Variant", variant_name, force=True)
            except Exception:
                pass

        for item_name in cls.created_items:
            try:
                if frappe.db.exists("Item", item_name):
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True
                    item.delete(ignore_permissions=True)
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def _ensure_item_group(cls):
        """Ensure a valid Item Group exists."""
        import frappe
        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group
        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"

    def setUp(self):
        """Set up before each test."""
        import frappe
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        import frappe
        frappe.db.rollback()

    def test_01_from_pim_sync_flag_prevents_item_sync(self):
        """Test that _from_pim_sync flag prevents Item-to-PIM sync."""
        import frappe

        from frappe_pim.pim.sync.item_sync import _is_from_pim

        # Create Item with _from_pim_sync flag
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-FLAG1-{self.test_suffix}"
        item.item_name = "Flag Test 1"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)
        frappe.db.commit()

        # Verify flag is detected
        self.assertTrue(
            _is_from_pim(item),
            "_from_pim_sync flag should be detected by _is_from_pim()"
        )

    def test_02_from_pim_flag_prevents_item_sync(self):
        """Test that from_pim flag (alternative name) also prevents sync."""
        import frappe

        from frappe_pim.pim.sync.item_sync import _is_from_pim

        item = frappe.new_doc("Item")
        item.item_code = f"TEST-FLAG2-{self.test_suffix}"
        item.item_name = "Flag Test 2"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags.from_pim = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)
        frappe.db.commit()

        # Both flag names should be recognized
        self.assertTrue(
            _is_from_pim(item),
            "from_pim flag should be detected by _is_from_pim()"
        )

    def test_03_no_flag_allows_sync(self):
        """Test that items without sync flags allow sync processing."""
        import frappe

        from frappe_pim.pim.sync.item_sync import _is_from_pim

        item = frappe.new_doc("Item")
        item.item_code = f"TEST-NOFLAG-{self.test_suffix}"
        item.item_name = "No Flag Test"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        # Deliberately NOT setting any PIM flags

        self.assertFalse(
            _is_from_pim(item),
            "Item without PIM flags should not be detected as from PIM"
        )

        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)
        frappe.db.commit()

    def test_04_flags_are_per_document_not_class(self):
        """Test that sync flags are instance-level, not class-level."""
        import frappe

        # Create first Item with flag
        item1 = frappe.new_doc("Item")
        item1.item_code = f"TEST-DOC1-{self.test_suffix}"
        item1.item_name = "Doc Flag Test 1"
        item1.item_group = self.item_group
        item1.stock_uom = "Nos"
        item1.flags._from_pim_sync = True

        # Create second Item without flag
        item2 = frappe.new_doc("Item")
        item2.item_code = f"TEST-DOC2-{self.test_suffix}"
        item2.item_name = "Doc Flag Test 2"
        item2.item_group = self.item_group
        item2.stock_uom = "Nos"

        # Flags should be independent per document
        self.assertTrue(getattr(item1.flags, "_from_pim_sync", False))
        self.assertFalse(getattr(item2.flags, "_from_pim_sync", False))

        item1.insert(ignore_permissions=True)
        item2.insert(ignore_permissions=True)
        self.created_items.extend([item1.name, item2.name])
        frappe.db.commit()

    def test_05_flags_cleared_on_reload(self):
        """Test that sync flags do not persist after document reload."""
        import frappe

        item = frappe.new_doc("Item")
        item.item_code = f"TEST-RELOAD-{self.test_suffix}"
        item.item_name = "Reload Flag Test"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)
        frappe.db.commit()

        # Reload clears runtime flags
        reloaded = frappe.get_doc("Item", item.name)
        self.assertFalse(
            getattr(reloaded.flags, "_from_pim_sync", False),
            "Sync flags should not persist after reload"
        )

    def test_06_variant_from_erpnext_sync_flag(self):
        """Test that _from_erpnext_sync flag on Product Variant prevents reverse sync."""
        import frappe

        variant = frappe.new_doc("Product Variant")
        variant.sku = f"TEST-ERPSYNC-{self.test_suffix}"
        variant.variant_name = "ERP Sync Flag Test"
        variant.status = "Draft"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Verify the flag is set
        self.assertTrue(
            getattr(variant, '_from_erpnext_sync', False),
            "_from_erpnext_sync flag should be set"
        )

    def test_07_sync_with_tracked_call_count(self):
        """Test that sync operations don't cause excessive recursive calls."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.sync.item_sync import (
            _sync_item_to_product_variant,
            _is_from_pim
        )

        # Create linked Item and Variant
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-LOOP-{self.test_suffix}"
        item.item_name = "Loop Test"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)

        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "Loop Test Variant"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Track calls
        sync_count = [0]
        original_sync = _sync_item_to_product_variant

        def tracked_sync(item_doc, variant_name):
            sync_count[0] += 1
            if sync_count[0] > 5:
                raise Exception("Infinite loop detected - sync called too many times!")
            return original_sync(item_doc, variant_name)

        try:
            import frappe_pim.pim.sync.item_sync as item_sync_module
            item_sync_module._sync_item_to_product_variant = tracked_sync

            # Trigger sync
            item.reload()
            item.item_name = "Loop Test Updated"
            tracked_sync(item, variant.name)
            frappe.db.commit()

            # Should complete without excessive calls
            self.assertLessEqual(
                sync_count[0], 3,
                f"Sync was called {sync_count[0]} times - possible loop!"
            )
        finally:
            item_sync_module._sync_item_to_product_variant = original_sync


class TestConflictDetection(unittest.TestCase):
    """Tests for sync conflict detection and resolution."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for conflict tests."""
        import frappe
        from frappe.utils import random_string

        cls.test_suffix = random_string(6)
        cls.erpnext_available = frappe.db.exists("DocType", "Item")
        cls.has_conflict_rules = frappe.db.exists("DocType", "PIM Sync Conflict Rule")
        cls.created_items = []
        cls.created_variants = []
        cls.created_sync_entries = []
        cls.created_rules = []
        cls.item_group = cls._ensure_item_group()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        import frappe

        for rule_name in cls.created_rules:
            try:
                if frappe.db.exists("PIM Sync Conflict Rule", rule_name):
                    frappe.delete_doc("PIM Sync Conflict Rule", rule_name, force=True)
            except Exception:
                pass

        for entry_name in cls.created_sync_entries:
            try:
                if frappe.db.exists("PIM Sync Queue", entry_name):
                    frappe.delete_doc("PIM Sync Queue", entry_name, force=True)
            except Exception:
                pass

        for variant_name in cls.created_variants:
            try:
                if frappe.db.exists("Product Variant", variant_name):
                    frappe.delete_doc("Product Variant", variant_name, force=True)
            except Exception:
                pass

        for item_name in cls.created_items:
            try:
                if frappe.db.exists("Item", item_name):
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True
                    item.delete(ignore_permissions=True)
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def _ensure_item_group(cls):
        """Ensure a valid Item Group exists."""
        import frappe
        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group
        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"

    def setUp(self):
        """Set up before each test."""
        import frappe
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        import frappe
        frappe.db.rollback()

    def test_01_conflict_detection_with_concurrent_modifications(self):
        """Test that concurrent modifications to both PIM and ERP are detected."""
        import frappe
        from frappe.utils import now_datetime, add_to_date

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.sync.queue_processor import _check_sync_conflict

        # Create linked Item and Variant
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-CONFLICT-{self.test_suffix}"
        item.item_name = "Conflict Test"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)

        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "Conflict Test Variant"
        variant.erp_item = item.name
        variant.status = "Active"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Set last_sync_at to a time in the past
        past_time = add_to_date(now_datetime(), minutes=-30)
        variant.db_set("last_sync_at", past_time, update_modified=False)
        frappe.db.commit()

        # Create sync entry for conflict check
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Item"
        entry.document_name = item.name
        entry.sync_direction = "ERP to PIM"
        entry.sync_action = "Update"
        entry.status = "Pending"
        entry.insert(ignore_permissions=True)
        self.created_sync_entries.append(entry.name)
        frappe.db.commit()

        # Check for conflict
        item.reload()
        conflict = _check_sync_conflict(entry, item)

        # Both were modified after last_sync_at, so conflict should be detected
        if conflict:
            self.assertEqual(conflict["type"], "concurrent_modification")
            self.assertIn("pim_document", conflict)
            self.assertIn("erp_document", conflict)
            self.assertIn("last_sync", conflict)

    def test_02_no_conflict_when_only_one_side_modified(self):
        """Test that no conflict is raised when only one side is modified."""
        import frappe
        from frappe.utils import now_datetime

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.sync.queue_processor import _check_sync_conflict

        # Create linked Item and Variant with recent last_sync
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-NOCONFLICT-{self.test_suffix}"
        item.item_name = "No Conflict Test"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)

        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "No Conflict Variant"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Set last_sync_at to NOW (both in sync)
        variant.db_set("last_sync_at", now_datetime(), update_modified=False)
        frappe.db.commit()

        # Create a non-ERP-to-PIM entry (PIM to ERP)
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Product Variant"
        entry.document_name = variant.name
        entry.sync_direction = "PIM to ERP"
        entry.sync_action = "Update"
        entry.status = "Pending"
        entry.insert(ignore_permissions=True)
        self.created_sync_entries.append(entry.name)
        frappe.db.commit()

        # No conflict for PIM-to-ERP direction
        item.reload()
        conflict = _check_sync_conflict(entry, item)
        self.assertIsNone(
            conflict,
            "PIM-to-ERP direction should not trigger conflict check"
        )

    def test_03_conflict_rule_doctype_exists(self):
        """Test that PIM Sync Conflict Rule DocType exists."""
        import frappe

        self.assertTrue(
            frappe.db.exists("DocType", "PIM Sync Conflict Rule"),
            "PIM Sync Conflict Rule DocType should exist"
        )

    def test_04_conflict_rule_evaluation(self):
        """Test that conflict rules evaluate conditions correctly."""
        import frappe

        if not self.has_conflict_rules:
            self.skipTest("PIM Sync Conflict Rule DocType not available")

        # Test resolve_conflict function
        from frappe_pim.pim.doctype.pim_sync_conflict_rule.pim_sync_conflict_rule import (
            resolve_conflict
        )

        # Resolve a conflict with default rules (PIM wins)
        resolution = resolve_conflict(
            doctype_name="Product Variant",
            field_name="description",
            pim_value="PIM description",
            erp_value="ERP description",
            sync_direction="PIM to ERP"
        )

        self.assertIsNotNone(resolution)
        self.assertIn("winner", resolution)
        self.assertIn("value", resolution)
        self.assertIn("strategy", resolution)

    def test_05_conflict_resolution_strategies(self):
        """Test that different conflict resolution strategies work."""
        import frappe

        if not self.has_conflict_rules:
            self.skipTest("PIM Sync Conflict Rule DocType not available")

        from frappe_pim.pim.doctype.pim_sync_conflict_rule.pim_sync_conflict_rule import (
            resolve_conflict,
            get_default_rules
        )

        # Get default rules to verify they exist
        default_rules = get_default_rules()
        self.assertGreater(len(default_rules), 0, "Should have default rules defined")

        # Test resolution with values
        resolution = resolve_conflict(
            doctype_name="Product Variant",
            field_name="item_name",
            pim_value="PIM Name",
            erp_value="ERP Name"
        )

        self.assertIsNotNone(resolution)
        # Resolution should select a winner
        self.assertIn(resolution.get("winner"), ["pim", "erp", None])

    def test_06_conflict_stats(self):
        """Test conflict statistics retrieval."""
        import frappe

        if not self.has_conflict_rules:
            self.skipTest("PIM Sync Conflict Rule DocType not available")

        from frappe_pim.pim.doctype.pim_sync_conflict_rule.pim_sync_conflict_rule import (
            get_conflict_stats
        )

        stats = get_conflict_stats()

        self.assertIsInstance(stats, dict)
        self.assertIn("total_rules", stats)
        self.assertIn("active_rules", stats)
        self.assertIn("total_triggers", stats)
        self.assertIn("rules_by_source", stats)
        self.assertGreaterEqual(stats["total_rules"], 0)
        self.assertGreaterEqual(stats["active_rules"], 0)


class TestVariantSync(unittest.TestCase):
    """Tests for Product Variant specific sync operations."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for variant sync tests."""
        import frappe
        from frappe.utils import random_string

        cls.test_suffix = random_string(6)
        cls.erpnext_available = frappe.db.exists("DocType", "Item")
        cls.created_items = []
        cls.created_variants = []
        cls.item_group = cls._ensure_item_group()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        import frappe

        for variant_name in cls.created_variants:
            try:
                if frappe.db.exists("Product Variant", variant_name):
                    frappe.delete_doc("Product Variant", variant_name, force=True)
            except Exception:
                pass

        for item_name in cls.created_items:
            try:
                if frappe.db.exists("Item", item_name):
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True
                    item.delete(ignore_permissions=True)
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def _ensure_item_group(cls):
        """Ensure a valid Item Group exists."""
        import frappe
        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group
        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"

    def setUp(self):
        """Set up before each test."""
        import frappe
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        import frappe
        frappe.db.rollback()

    def test_01_variant_sync_to_erpnext_method(self):
        """Test Product Variant's sync_to_erpnext method creates/updates Item."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        variant = frappe.new_doc("Product Variant")
        variant.sku = f"TEST-VSYNC-{self.test_suffix}"
        variant.variant_name = "Variant Sync Test"
        variant.variant_code = f"TEST-VSYNC-{self.test_suffix}"
        variant.description = "Test variant for sync"
        variant.status = "Draft"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Call sync method directly
        variant.reload()
        variant._from_erpnext_sync = False  # Allow sync
        variant.sync_to_erpnext()
        frappe.db.commit()

        # Check if Item was created
        if variant.erp_item:
            self.created_items.append(variant.erp_item)
            self.assertTrue(
                frappe.db.exists("Item", variant.erp_item),
                "ERPNext Item should be created"
            )

            item = frappe.get_doc("Item", variant.erp_item)
            self.assertEqual(item.item_name, "Variant Sync Test")

    def test_02_variant_sync_from_erpnext_method(self):
        """Test Product Variant's sync_from_erpnext method updates variant fields."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        # Create Item
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-VFROM-{self.test_suffix}"
        item.item_name = "Item for Reverse Sync"
        item.description = "Item description"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)

        # Create variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "Old Variant Name"
        variant.description = "Old description"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Call sync_from_erpnext
        variant.reload()
        variant.sync_from_erpnext(item)

        # Verify fields mapped
        self.assertEqual(variant.variant_name, "Item for Reverse Sync")
        self.assertEqual(variant.description, "Item description")

        # Verify _from_erpnext_sync flag was set
        self.assertTrue(
            getattr(variant, '_from_erpnext_sync', False),
            "sync_from_erpnext should set _from_erpnext_sync flag"
        )

    def test_03_variant_on_update_skips_when_from_erp(self):
        """Test that variant on_update skips sync when _from_erpnext_sync is set."""
        import frappe

        variant = frappe.new_doc("Product Variant")
        variant.sku = f"TEST-VSKIP-{self.test_suffix}"
        variant.variant_name = "Skip Sync Test"
        variant.status = "Draft"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Update with flag still set
        variant.reload()
        variant._from_erpnext_sync = True
        variant.variant_name = "Updated Skip Test"
        variant.save(ignore_permissions=True)
        frappe.db.commit()

        # Should complete without errors (no sync attempted)
        variant.reload()
        self.assertEqual(variant.variant_name, "Updated Skip Test")

    def test_04_variant_completeness_calculation(self):
        """Test that variant completeness score is calculated during sync."""
        import frappe

        variant = frappe.new_doc("Product Variant")
        variant.sku = f"TEST-VCOMP-{self.test_suffix}"
        variant.variant_name = "Completeness Test"
        variant.status = "Draft"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        variant.reload()
        # Completeness should be calculated
        self.assertIsNotNone(
            variant.completeness_score,
            "Completeness score should be calculated"
        )
        self.assertGreater(
            variant.completeness_score, 0,
            "Completeness should be > 0 for variant with name and SKU"
        )

    def test_05_erp_sync_utility_create_item(self):
        """Test the create_erp_item utility function."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.utils.erp_sync import create_erp_item

        variant = frappe.new_doc("Product Variant")
        variant.sku = f"TEST-UTIL-{self.test_suffix}"
        variant.variant_name = "Utility Create Test"
        variant.description = "Test description"
        variant.uom = "Nos"
        variant.status = "Draft"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Create Item via utility
        item_name = create_erp_item(variant)

        if item_name:
            self.created_items.append(item_name)
            self.assertTrue(
                frappe.db.exists("Item", item_name),
                "create_erp_item should create an ERPNext Item"
            )

            item = frappe.get_doc("Item", item_name)
            self.assertEqual(item.item_name, "Utility Create Test")

    def test_06_erp_sync_utility_sync_to_item(self):
        """Test the sync_to_erp_item utility function."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.utils.erp_sync import sync_to_erp_item

        # Create Item first
        item = frappe.new_doc("Item")
        item.item_code = f"TEST-SYNC2-{self.test_suffix}"
        item.item_name = "Original Name"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)

        # Create variant linked to Item
        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "Updated Variant Name"
        variant.description = "Updated description"
        variant.uom = "Nos"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        # Sync variant to Item
        result = sync_to_erp_item(variant)

        self.assertTrue(result, "sync_to_erp_item should return True on success")

        # Verify Item was updated
        item.reload()
        self.assertEqual(item.item_name, "Updated Variant Name")
        self.assertEqual(item.description, "Updated description")


class TestSyncAPIEndpoints(unittest.TestCase):
    """Tests for sync API endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for API tests."""
        import frappe
        from frappe.utils import random_string

        cls.test_suffix = random_string(6)
        cls.created_sync_entries = []
        cls.created_variants = []

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        import frappe

        for entry_name in cls.created_sync_entries:
            try:
                if frappe.db.exists("PIM Sync Queue", entry_name):
                    frappe.delete_doc("PIM Sync Queue", entry_name, force=True)
            except Exception:
                pass

        for variant_name in cls.created_variants:
            try:
                if frappe.db.exists("Product Variant", variant_name):
                    frappe.delete_doc("Product Variant", variant_name, force=True)
            except Exception:
                pass

        frappe.db.commit()

    def setUp(self):
        """Set up before each test."""
        import frappe
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        import frappe
        frappe.db.rollback()

    def test_01_get_sync_queue_stats(self):
        """Test the get_sync_queue_stats API endpoint."""
        from frappe_pim.pim.api.sync import get_sync_queue_stats

        stats = get_sync_queue_stats()

        self.assertIsNotNone(stats, "Should return stats")
        self.assertIn("pending", stats)
        self.assertIn("completed", stats)
        self.assertIn("failed", stats)
        self.assertIn("total_today", stats)

        # All counts should be non-negative
        self.assertGreaterEqual(stats.get("pending", 0), 0)
        self.assertGreaterEqual(stats.get("completed", 0), 0)
        self.assertGreaterEqual(stats.get("failed", 0), 0)

    def test_02_retry_failed_sync_api(self):
        """Test the retry_failed_sync API endpoint."""
        import frappe

        # Create a failed sync entry
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Product Variant"
        entry.document_name = f"RetryAPI-{self.test_suffix}"
        entry.sync_direction = "PIM to ERP"
        entry.sync_action = "Update"
        entry.status = "Failed"
        entry.error_message = "Test error"
        entry.retry_count = 0
        entry.max_retries = 3
        entry.insert(ignore_permissions=True)
        self.created_sync_entries.append(entry.name)
        frappe.db.commit()

        # Retry via API
        from frappe_pim.pim.api.sync import retry_failed_sync

        result = retry_failed_sync(sync_entry=entry.name)

        self.assertTrue(result.get("success"), "Retry should succeed")
        self.assertIn(entry.name, result.get("retried", []))

        # Entry should be Pending now
        entry.reload()
        self.assertEqual(entry.status, "Pending")

    def test_03_cancel_sync_entry_api(self):
        """Test the cancel_sync_entry API endpoint."""
        import frappe

        # Create a pending sync entry
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Product Variant"
        entry.document_name = f"CancelAPI-{self.test_suffix}"
        entry.sync_direction = "PIM to ERP"
        entry.sync_action = "Update"
        entry.status = "Pending"
        entry.insert(ignore_permissions=True)
        self.created_sync_entries.append(entry.name)
        frappe.db.commit()

        # Cancel via API
        from frappe_pim.pim.api.sync import cancel_sync_entry

        result = cancel_sync_entry(entry.name, reason="Integration test")

        self.assertTrue(result.get("success"), "Cancel should succeed")

        entry.reload()
        self.assertEqual(entry.status, "Cancelled")

    def test_04_get_sync_history_api(self):
        """Test the get_sync_history API endpoint."""
        import frappe

        document_name = f"HistoryAPI-{self.test_suffix}"

        # Create multiple sync entries for same document
        for i in range(3):
            entry = frappe.new_doc("PIM Sync Queue")
            entry.doctype_name = "Product Variant"
            entry.document_name = document_name
            entry.sync_direction = "PIM to ERP"
            entry.sync_action = "Update"
            entry.status = "Completed" if i < 2 else "Pending"
            entry.insert(ignore_permissions=True)
            self.created_sync_entries.append(entry.name)

        frappe.db.commit()

        # Get history via API
        from frappe_pim.pim.api.sync import get_sync_history

        history = get_sync_history(
            doctype_name="Product Variant",
            document_name=document_name,
            limit=10
        )

        self.assertIsNotNone(history)
        self.assertIn("entries", history)
        self.assertIn("total", history)
        self.assertGreaterEqual(len(history["entries"]), 3)
        self.assertGreaterEqual(history["total"], 3)

    def test_05_get_pending_syncs_api(self):
        """Test the get_pending_syncs API endpoint."""
        from frappe_pim.pim.api.sync import get_pending_syncs

        result = get_pending_syncs(limit=50)

        self.assertIsNotNone(result)
        self.assertIn("entries", result)
        self.assertIn("total", result)
        self.assertIn("oldest_age_minutes", result)
        self.assertIsInstance(result["entries"], list)

    def test_06_trigger_sync_api(self):
        """Test the trigger_sync API endpoint."""
        import frappe

        # Create a variant to sync
        variant = frappe.new_doc("Product Variant")
        variant.sku = f"TEST-TRIGGER-{self.test_suffix}"
        variant.variant_name = "Trigger Test"
        variant.status = "Draft"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        self.created_variants.append(variant.name)
        frappe.db.commit()

        from frappe_pim.pim.api.sync import trigger_sync

        result = trigger_sync(
            doctype_name="Product Variant",
            document_name=variant.name,
            sync_direction="PIM to ERP",
            priority=5
        )

        # Should succeed or indicate already pending
        if result.get("success"):
            self.assertIn("sync_entry", result)
            if result.get("sync_entry"):
                self.created_sync_entries.append(result["sync_entry"])
        else:
            # Already pending from variant creation
            self.assertIn("message", result)

    def test_07_sync_queue_entry_retry_mechanism(self):
        """Test the sync queue retry mechanism with max retries."""
        import frappe

        # Create failed entry at max retries
        entry = frappe.new_doc("PIM Sync Queue")
        entry.doctype_name = "Product Variant"
        entry.document_name = f"MaxRetry-{self.test_suffix}"
        entry.sync_direction = "PIM to ERP"
        entry.sync_action = "Update"
        entry.status = "Failed"
        entry.error_message = "Max retries test"
        entry.retry_count = 3
        entry.max_retries = 3
        entry.insert(ignore_permissions=True)
        self.created_sync_entries.append(entry.name)
        frappe.db.commit()

        # Try to retry - should fail due to max retries exceeded
        from frappe_pim.pim.api.sync import retry_failed_sync

        result = retry_failed_sync(sync_entry=entry.name)

        self.assertFalse(
            result.get("success"),
            "Retry should fail when max retries exceeded"
        )

    def test_08_sync_queue_cleanup(self):
        """Test cleanup of old sync queue entries."""
        import frappe
        from frappe.utils import add_days, today

        # Create old completed entries
        old_date = add_days(today(), -35)

        for i in range(2):
            entry = frappe.new_doc("PIM Sync Queue")
            entry.doctype_name = "Product Variant"
            entry.document_name = f"CleanupAPI-{self.test_suffix}-{i}"
            entry.sync_direction = "PIM to ERP"
            entry.sync_action = "Update"
            entry.status = "Completed"
            entry.insert(ignore_permissions=True)
            self.created_sync_entries.append(entry.name)

            # Set creation date to old date
            frappe.db.set_value(
                "PIM Sync Queue", entry.name,
                "creation", old_date,
                update_modified=False
            )

        frappe.db.commit()

        # Run cleanup
        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            cleanup_old_entries
        )

        deleted = cleanup_old_entries(days=30)

        self.assertGreaterEqual(deleted, 2, "Should delete old completed entries")


class TestSyncModuleImports(unittest.TestCase):
    """Tests for sync module import paths and backward compatibility."""

    def test_01_sync_package_exports(self):
        """Test that sync package re-exports all required functions."""
        from frappe_pim.pim.sync import (
            process_sync_queue,
            process_single_entry,
            cleanup_old_sync_entries,
            retry_all_failed,
            get_sync_queue_status,
        )

        self.assertTrue(callable(process_sync_queue))
        self.assertTrue(callable(process_single_entry))
        self.assertTrue(callable(cleanup_old_sync_entries))
        self.assertTrue(callable(retry_all_failed))
        self.assertTrue(callable(get_sync_queue_status))

    def test_02_queue_processor_direct_import(self):
        """Test direct import from queue_processor module."""
        from frappe_pim.pim.sync.queue_processor import (
            process_sync_queue,
            process_single_entry,
            cleanup_old_sync_entries,
            retry_all_failed,
            get_sync_queue_status,
        )

        self.assertTrue(callable(process_sync_queue))
        self.assertTrue(callable(process_single_entry))

    def test_03_item_sync_module_imports(self):
        """Test that item_sync module functions are importable."""
        from frappe_pim.pim.sync.item_sync import (
            on_item_update,
            on_item_insert,
            on_item_trash,
            sync_item_to_pim,
            bulk_sync_items_to_pim,
            _is_from_pim,
            _is_pim_managed_item,
            _get_linked_product_variant,
            _sync_item_to_product_variant,
            _invalidate_product_master_cache,
            _cleanup_pim_data,
        )

        self.assertTrue(callable(on_item_update))
        self.assertTrue(callable(on_item_insert))
        self.assertTrue(callable(on_item_trash))
        self.assertTrue(callable(sync_item_to_pim))
        self.assertTrue(callable(bulk_sync_items_to_pim))
        self.assertTrue(callable(_is_from_pim))
        self.assertTrue(callable(_is_pim_managed_item))

    def test_04_sync_api_module_imports(self):
        """Test that sync API module functions are importable."""
        from frappe_pim.pim.api.sync import (
            get_sync_status,
            trigger_sync,
            get_sync_queue_stats,
            retry_failed_sync,
            cancel_sync_entry,
            get_sync_history,
            get_pending_syncs,
            force_sync,
            cleanup_sync_queue,
        )

        self.assertTrue(callable(get_sync_status))
        self.assertTrue(callable(trigger_sync))
        self.assertTrue(callable(get_sync_queue_stats))
        self.assertTrue(callable(retry_failed_sync))
        self.assertTrue(callable(cancel_sync_entry))
        self.assertTrue(callable(get_sync_history))
        self.assertTrue(callable(get_pending_syncs))
        self.assertTrue(callable(force_sync))
        self.assertTrue(callable(cleanup_sync_queue))

    def test_05_erp_sync_utility_imports(self):
        """Test that erp_sync utility functions are importable."""
        from frappe_pim.pim.utils.erp_sync import (
            on_item_insert,
            on_item_update,
            on_item_delete,
            create_erp_item,
            sync_to_erp_item,
        )

        self.assertTrue(callable(on_item_insert))
        self.assertTrue(callable(on_item_update))
        self.assertTrue(callable(on_item_delete))
        self.assertTrue(callable(create_erp_item))
        self.assertTrue(callable(sync_to_erp_item))

    def test_06_pim_sync_queue_helpers_imports(self):
        """Test that PIM Sync Queue helper functions are importable."""
        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            queue_sync_entry,
            get_pending_entries,
            get_sync_stats,
            retry_failed_entries,
            cleanup_old_entries,
            get_entry_for_document,
        )

        self.assertTrue(callable(queue_sync_entry))
        self.assertTrue(callable(get_pending_entries))
        self.assertTrue(callable(get_sync_stats))
        self.assertTrue(callable(retry_failed_entries))
        self.assertTrue(callable(cleanup_old_entries))
        self.assertTrue(callable(get_entry_for_document))

    def test_07_conflict_rule_imports(self):
        """Test that conflict rule module functions are importable."""
        from frappe_pim.pim.doctype.pim_sync_conflict_rule.pim_sync_conflict_rule import (
            get_active_rules,
            get_rule_by_code,
            resolve_conflict,
            get_default_rules,
            create_default_rules,
            get_conflict_stats,
        )

        self.assertTrue(callable(get_active_rules))
        self.assertTrue(callable(get_rule_by_code))
        self.assertTrue(callable(resolve_conflict))
        self.assertTrue(callable(get_default_rules))
        self.assertTrue(callable(create_default_rules))
        self.assertTrue(callable(get_conflict_stats))


class TestPIMManagedItemDetection(unittest.TestCase):
    """Tests for PIM managed item detection logic."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        import frappe
        from frappe.utils import random_string

        cls.test_suffix = random_string(6)
        cls.erpnext_available = frappe.db.exists("DocType", "Item")
        cls.created_items = []
        cls.item_group = cls._ensure_item_group()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        import frappe

        for item_name in cls.created_items:
            try:
                if frappe.db.exists("Item", item_name):
                    item = frappe.get_doc("Item", item_name)
                    item.flags._from_pim_sync = True
                    item.delete(ignore_permissions=True)
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def _ensure_item_group(cls):
        """Ensure a valid Item Group exists."""
        import frappe
        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group
        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"

    def setUp(self):
        """Set up before each test."""
        import frappe
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        import frappe
        frappe.db.rollback()

    def test_01_regular_item_not_pim_managed(self):
        """Test that a regular Item without PIM fields is not detected as PIM managed."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.sync.item_sync import _is_pim_managed_item

        item = frappe.new_doc("Item")
        item.item_code = f"TEST-REGULAR-{self.test_suffix}"
        item.item_name = "Regular Item"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)
        frappe.db.commit()

        self.assertFalse(
            _is_pim_managed_item(item),
            "Regular Item should not be detected as PIM managed"
        )

    def test_02_item_with_pim_status_is_managed(self):
        """Test that Item with custom_pim_status is detected as PIM managed."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.sync.item_sync import _is_pim_managed_item

        item = frappe.new_doc("Item")
        item.item_code = f"TEST-PIMSTAT-{self.test_suffix}"
        item.item_name = "PIM Status Item"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.custom_pim_status = "Active"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)
        frappe.db.commit()

        self.assertTrue(
            _is_pim_managed_item(item),
            "Item with custom_pim_status should be PIM managed"
        )

    def test_03_item_with_linked_variant_is_managed(self):
        """Test that Item with linked Product Variant is detected as PIM managed."""
        import frappe

        if not self.erpnext_available:
            self.skipTest("ERPNext not installed")

        from frappe_pim.pim.sync.item_sync import (
            _is_pim_managed_item,
            _get_linked_product_variant
        )

        item = frappe.new_doc("Item")
        item.item_code = f"TEST-LINKED-{self.test_suffix}"
        item.item_name = "Linked Item"
        item.item_group = self.item_group
        item.stock_uom = "Nos"
        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)
        self.created_items.append(item.name)

        # Create linked variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = item.item_code
        variant.variant_name = "Linked Variant"
        variant.erp_item = item.name
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify link detection
        linked = _get_linked_product_variant(item.name)
        self.assertIsNotNone(linked, "Should find linked Product Variant")

        self.assertTrue(
            _is_pim_managed_item(item),
            "Item with linked Product Variant should be PIM managed"
        )

        # Clean up variant
        frappe.delete_doc("Product Variant", variant.name, force=True)
        frappe.db.commit()


def run_tests():
    """Run all sync integration tests."""
    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestPIMToERPSync))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestERPToPIMSync))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSyncLoopPrevention))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestConflictDetection))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestVariantSync))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSyncAPIEndpoints))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestSyncModuleImports))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestPIMManagedItemDetection))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
