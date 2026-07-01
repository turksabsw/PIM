# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""Product Master Virtual DocType Unit Tests

This module contains unit tests for:
- Virtual DocType CRUD operations (get_list, get_count, db_insert, load_from_db, db_update, delete)
- Field mapping between Product Master and Item
- Integration with ERPNext Item backend

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestVirtualDocTypeCRUD(unittest.TestCase):
    """Test cases for Virtual DocType CRUD operations."""

    @classmethod
    def setUpClass(cls):
        """Set up test class - called once before all tests."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test - called before each test method."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test - called after each test method."""
        import frappe
        # Delete in reverse order to handle dependencies
        for doctype, name in reversed(self.created_documents):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        self.created_documents = []

    def track_document(self, doctype, name):
        """Track a document for cleanup after test."""
        self.created_documents.append((doctype, name))

    def test_product_master_db_insert(self):
        """Test that db_insert creates an Item in the backend."""
        import frappe
        from frappe.utils import random_string

        product_code = f"VIRT-{random_string(6).upper()}"
        product_name = f"Virtual Test Product {random_string(4)}"

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": product_name,
            "product_code": product_code,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        # Verify Item was created in backend
        self.assertTrue(frappe.db.exists("Item", doc.name))

        # Verify Item has correct data
        item = frappe.get_doc("Item", doc.name)
        self.assertEqual(item.item_name, product_name)
        self.assertEqual(item.item_code, product_code)

    def test_product_master_load_from_db(self):
        """Test that load_from_db retrieves data from Item."""
        import frappe
        from frappe.utils import random_string

        product_code = f"LOAD-{random_string(6).upper()}"
        product_name = f"Load Test Product {random_string(4)}"

        # Create product
        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": product_name,
            "product_code": product_code,
            "short_description": "Test description for loading",
            "status": "Active"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        # Load fresh from database
        loaded_doc = frappe.get_doc("Product Master", doc.name)

        self.assertEqual(loaded_doc.product_name, product_name)
        self.assertEqual(loaded_doc.product_code, product_code)
        self.assertEqual(loaded_doc.short_description, "Test description for loading")

    def test_product_master_db_update(self):
        """Test that db_update updates the backend Item."""
        import frappe
        from frappe.utils import random_string

        product_code = f"UPD-{random_string(6).upper()}"

        # Create product
        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Original Name {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        # Update product
        doc.product_name = "Updated Name"
        doc.short_description = "Updated description"
        doc.save(ignore_permissions=True)

        # Verify Item was updated
        item = frappe.get_doc("Item", doc.name)
        self.assertEqual(item.item_name, "Updated Name")
        self.assertEqual(item.description, "Updated description")

    def test_product_master_delete(self):
        """Test that delete removes the backend Item."""
        import frappe
        from frappe.utils import random_string

        product_code = f"DEL-{random_string(6).upper()}"

        # Create product
        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Delete Test {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        product_name = doc.name

        # Delete product
        frappe.delete_doc("Product Master", product_name, force=True, ignore_permissions=True)
        frappe.db.commit()

        # Verify Item was deleted
        self.assertFalse(frappe.db.exists("Item", product_name))

    def test_product_master_get_list(self):
        """Test that get_list returns Products from Items."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.product_master.product_master import ProductMaster

        suffix = random_string(6).upper()

        # Create test products
        products = []
        for i in range(3):
            doc = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"List Test {i} {suffix}",
                "product_code": f"LST{i}-{suffix}",
                "status": "Active"
            })
            doc.insert(ignore_permissions=True)
            self.track_document("Product Master", doc.name)
            products.append(doc)

        # Test get_list
        result = ProductMaster.get_list({
            "filters": {"product_code": ["like", f"LST%-{suffix}"]},
            "fields": ["name", "product_name", "product_code"],
            "limit_page_length": 10
        })

        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 3)

    def test_product_master_get_count(self):
        """Test that get_count returns correct count from Items."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.product_master.product_master import ProductMaster

        suffix = random_string(6).upper()

        # Create test products
        for i in range(2):
            doc = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Count Test {i} {suffix}",
                "product_code": f"CNT{i}-{suffix}",
                "status": "Active"
            })
            doc.insert(ignore_permissions=True)
            self.track_document("Product Master", doc.name)

        # Test get_count
        count = ProductMaster.get_count({
            "filters": {"product_code": ["like", f"CNT%-{suffix}"]}
        })

        self.assertGreaterEqual(count, 2)


class TestVirtualDocTypeFieldMapping(unittest.TestCase):
    """Test cases for field mapping between Product Master and Item."""

    @classmethod
    def setUpClass(cls):
        """Set up test class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test."""
        import frappe
        for doctype, name in reversed(self.created_documents):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        self.created_documents = []

    def track_document(self, doctype, name):
        """Track a document for cleanup."""
        self.created_documents.append((doctype, name))

    def test_product_to_item_field_mapping(self):
        """Test that Product Master fields map correctly to Item fields."""
        from frappe_pim.pim.doctype.product_master.product_master import PRODUCT_TO_ITEM_FIELDS

        # Verify expected mappings exist
        expected_mappings = {
            "product_name": "item_name",
            "product_code": "item_code",
            "short_description": "description",
        }

        for product_field, item_field in expected_mappings.items():
            self.assertIn(product_field, PRODUCT_TO_ITEM_FIELDS)
            self.assertEqual(PRODUCT_TO_ITEM_FIELDS[product_field], item_field)

    def test_item_to_product_field_mapping(self):
        """Test that Item fields map correctly back to Product Master fields."""
        from frappe_pim.pim.doctype.product_master.product_master import (
            PRODUCT_TO_ITEM_FIELDS,
            ITEM_TO_PRODUCT_FIELDS
        )

        # Verify reverse mapping is correct
        for product_field, item_field in PRODUCT_TO_ITEM_FIELDS.items():
            self.assertIn(item_field, ITEM_TO_PRODUCT_FIELDS)
            self.assertEqual(ITEM_TO_PRODUCT_FIELDS[item_field], product_field)

    def test_map_fields_to_item_conversion(self):
        """Test _map_fields_to_item static method."""
        from frappe_pim.pim.doctype.product_master.product_master import ProductMaster

        fields = ["product_name", "product_code", "status", "name"]
        item_fields = ProductMaster._map_fields_to_item(fields)

        self.assertIn("item_name", item_fields)
        self.assertIn("item_code", item_fields)
        self.assertIn("name", item_fields)

    def test_map_filters_to_item_conversion(self):
        """Test _map_filters_to_item static method."""
        from frappe_pim.pim.doctype.product_master.product_master import ProductMaster

        filters = {
            "product_name": "Test",
            "status": "Active",
        }
        item_filters = ProductMaster._map_filters_to_item(filters)

        self.assertIn("item_name", item_filters)
        self.assertEqual(item_filters["item_name"], "Test")

    def test_transform_item_to_product(self):
        """Test _transform_item_to_product static method."""
        from frappe_pim.pim.doctype.product_master.product_master import ProductMaster

        item_dict = {
            "name": "TEST-001",
            "item_name": "Test Item",
            "item_code": "TEST-001",
            "description": "Test description"
        }

        product_dict = ProductMaster._transform_item_to_product(item_dict)

        self.assertIn("product_name", product_dict)
        self.assertEqual(product_dict["product_name"], "Test Item")
        self.assertIn("short_description", product_dict)

    def test_map_order_by_conversion(self):
        """Test _map_order_by static method."""
        from frappe_pim.pim.doctype.product_master.product_master import ProductMaster

        # Test with Product Master field
        order_by = "product_name desc"
        mapped = ProductMaster._map_order_by(order_by)
        self.assertIn("item_name", mapped)

        # Test with None
        mapped = ProductMaster._map_order_by(None)
        self.assertEqual(mapped, "modified desc")


class TestVirtualDocTypeItemIntegration(unittest.TestCase):
    """Test integration between Product Master virtual DocType and ERPNext Item."""

    @classmethod
    def setUpClass(cls):
        """Set up test class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test."""
        import frappe
        for doctype, name in reversed(self.created_documents):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        self.created_documents = []

    def track_document(self, doctype, name):
        """Track a document for cleanup."""
        self.created_documents.append((doctype, name))

    def test_item_created_with_required_fields(self):
        """Test that Item is created with required fields."""
        import frappe
        from frappe.utils import random_string

        product_code = f"ITEM-{random_string(6).upper()}"

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Item Integration Test {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        # Verify Item has required ERPNext fields
        item = frappe.get_doc("Item", doc.name)
        self.assertIsNotNone(item.item_group)
        self.assertIsNotNone(item.stock_uom)

    def test_item_has_from_pim_flag(self):
        """Test that from_pim flag is used during operations."""
        import frappe
        from frappe.utils import random_string

        # Create product
        product_code = f"FLAG-{random_string(6).upper()}"

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Flag Test {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        # The from_pim flag prevents sync loops - verify product was created
        self.assertTrue(frappe.db.exists("Item", doc.name))

    def test_product_code_becomes_item_code(self):
        """Test that product_code maps to item_code."""
        import frappe
        from frappe.utils import random_string

        product_code = f"PCODE-{random_string(6).upper()}"

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Code Test {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        item = frappe.get_doc("Item", doc.name)
        self.assertEqual(item.item_code, product_code)


class TestVirtualDocTypeValidation(unittest.TestCase):
    """Test validation logic in Product Master virtual DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test."""
        import frappe
        for doctype, name in reversed(self.created_documents):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        self.created_documents = []

    def track_document(self, doctype, name):
        """Track a document for cleanup."""
        self.created_documents.append((doctype, name))

    def test_load_nonexistent_product_raises_error(self):
        """Test that loading a non-existent product raises an error."""
        import frappe

        with self.assertRaises(frappe.DoesNotExistError):
            frappe.get_doc("Product Master", "NONEXISTENT-PRODUCT-12345")

    def test_duplicate_product_code_raises_error(self):
        """Test that duplicate product codes raise an error."""
        import frappe
        from frappe.utils import random_string

        product_code = f"DUP-{random_string(6).upper()}"

        # Create first product
        doc1 = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Duplicate Test 1 {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })
        doc1.insert(ignore_permissions=True)
        self.track_document("Product Master", doc1.name)

        # Try to create second with same code - should fail
        doc2 = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Duplicate Test 2 {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })

        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert(ignore_permissions=True)


class TestVirtualDocTypeHelpers(unittest.TestCase):
    """Test helper functions for Product Master virtual DocType."""

    @classmethod
    def setUpClass(cls):
        """Set up test class."""
        import frappe
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test."""
        self.created_documents = []

    def tearDown(self):
        """Tear down test."""
        import frappe
        for doctype, name in reversed(self.created_documents):
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        self.created_documents = []

    def track_document(self, doctype, name):
        """Track a document for cleanup."""
        self.created_documents.append((doctype, name))

    def test_get_family_attributes_function(self):
        """Test get_family_attributes helper function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.product_master.product_master import get_family_attributes

        # Create attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"test_helper_{random_string(6).lower()}",
            "attribute_name": f"Test Helper Attr {random_string(4)}",
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create family with attribute
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Helper Test Family {random_string(4)}",
            "family_code": f"helperfam{random_string(6).lower()}",
            "is_group": 0,
            "attributes": [{
                "attribute": attr.name,
                "is_required_in_family": 1
            }]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Test function
        attributes = get_family_attributes(family.name)

        self.assertIsInstance(attributes, list)
        self.assertGreaterEqual(len(attributes), 1)
        self.assertTrue(any(a["attribute"] == attr.name for a in attributes))

    def test_bulk_update_attribute_function(self):
        """Test bulk_update_attribute helper function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.product_master.product_master import bulk_update_attribute

        # Create attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"bulk_test_{random_string(6).lower()}",
            "attribute_name": f"Bulk Test Attr {random_string(4)}",
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create family
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Bulk Test Family {random_string(4)}",
            "is_group": 0,
            "attributes": [{
                "attribute": attr.name,
                "is_required_in_family": 0
            }]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Create products
        products = []
        for i in range(2):
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Bulk Test Product {i} {random_string(4)}",
                "product_code": f"BULK{i}-{random_string(6).upper()}",
                "product_family": family.name,
                "status": "Draft"
            })
            product.insert(ignore_permissions=True)
            self.track_document("Product Master", product.name)
            products.append(product.name)

        # Test bulk update
        result = bulk_update_attribute(
            products=products,
            attribute=attr.name,
            value="Bulk Value",
            locale="tr"
        )

        self.assertEqual(result["updated"], 2)
        self.assertEqual(len(result["errors"]), 0)

    def test_duplicate_product_function(self):
        """Test duplicate_product helper function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.product_master.product_master import duplicate_product

        # Create original product
        original = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Original Product {random_string(4)}",
            "product_code": f"ORIG-{random_string(6).upper()}",
            "short_description": "Original description",
            "status": "Active"
        })
        original.insert(ignore_permissions=True)
        self.track_document("Product Master", original.name)

        # Duplicate product
        new_name = duplicate_product(original.name)
        self.track_document("Product Master", new_name)

        # Verify duplicate
        duplicate = frappe.get_doc("Product Master", new_name)
        self.assertIn("(Copy)", duplicate.product_name)
        self.assertEqual(duplicate.status, "Draft")
        self.assertNotEqual(duplicate.product_code, original.product_code)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
