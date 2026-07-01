# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""DocType Integrity Unit Tests

This module contains unit tests for DocType integrity:
- Brand validation and uniqueness
- Manufacturer validation and uniqueness
- Family Variant Attribute child table validation

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestBrandIntegrity(unittest.TestCase):
    """Test cases for Brand DocType integrity."""

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

    def test_brand_creation_basic(self):
        """Test basic brand creation with required fields."""
        import frappe
        from frappe.utils import random_string

        brand_code = f"test-brand-{random_string(6).lower()}"
        brand_name = f"Test Brand {random_string(4)}"

        doc = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": brand_name,
            "brand_code": brand_code
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Brand", doc.name)

        self.assertEqual(doc.brand_name, brand_name)
        self.assertEqual(doc.brand_code, brand_code)

    def test_brand_requires_name(self):
        """Test that brand_name is required."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Brand",
            "brand_code": f"test-{random_string(6).lower()}"
        })

        with self.assertRaises(frappe.exceptions.MandatoryError):
            doc.insert(ignore_permissions=True)

    def test_brand_requires_code(self):
        """Test that brand_code is required."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": f"Test Brand {random_string(4)}"
        })

        with self.assertRaises(frappe.exceptions.MandatoryError):
            doc.insert(ignore_permissions=True)

    def test_brand_code_uniqueness(self):
        """Test that brand_code must be unique."""
        import frappe
        from frappe.utils import random_string

        brand_code = f"unique-brand-{random_string(6).lower()}"

        # Create first brand
        doc1 = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": f"Brand One {random_string(4)}",
            "brand_code": brand_code
        })
        doc1.insert(ignore_permissions=True)
        self.track_document("Brand", doc1.name)

        # Try to create second brand with same code
        doc2 = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": f"Brand Two {random_string(4)}",
            "brand_code": brand_code
        })

        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert(ignore_permissions=True)

    def test_brand_enabled_default(self):
        """Test that enabled defaults to 1."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": f"Test Brand {random_string(4)}",
            "brand_code": f"test-{random_string(6).lower()}"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Brand", doc.name)

        self.assertEqual(doc.enabled, 1)

    def test_brand_with_optional_fields(self):
        """Test brand creation with optional fields."""
        import frappe
        from frappe.utils import random_string

        brand_code = f"test-opt-{random_string(6).lower()}"
        website = "https://example.com"
        description = "This is a test brand description."

        doc = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": f"Test Brand {random_string(4)}",
            "brand_code": brand_code,
            "website": website,
            "description": description
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Brand", doc.name)

        self.assertEqual(doc.website, website)
        self.assertEqual(doc.description, description)

    def test_brand_naming_by_code(self):
        """Test that brand is named by brand_code."""
        import frappe
        from frappe.utils import random_string

        brand_code = f"naming-test-{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": f"Test Brand {random_string(4)}",
            "brand_code": brand_code
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Brand", doc.name)

        self.assertEqual(doc.name, brand_code)


class TestManufacturerIntegrity(unittest.TestCase):
    """Test cases for Manufacturer DocType integrity."""

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

    def test_manufacturer_creation_basic(self):
        """Test basic manufacturer creation with required fields."""
        import frappe
        from frappe.utils import random_string

        manufacturer_code = f"test-mfr-{random_string(6).lower()}"
        manufacturer_name = f"Test Manufacturer {random_string(4)}"

        doc = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": manufacturer_name,
            "manufacturer_code": manufacturer_code
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Manufacturer", doc.name)

        self.assertEqual(doc.manufacturer_name, manufacturer_name)
        self.assertEqual(doc.manufacturer_code, manufacturer_code)

    def test_manufacturer_requires_name(self):
        """Test that manufacturer_name is required."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_code": f"test-{random_string(6).lower()}"
        })

        with self.assertRaises(frappe.exceptions.MandatoryError):
            doc.insert(ignore_permissions=True)

    def test_manufacturer_requires_code(self):
        """Test that manufacturer_code is required."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": f"Test Manufacturer {random_string(4)}"
        })

        with self.assertRaises(frappe.exceptions.MandatoryError):
            doc.insert(ignore_permissions=True)

    def test_manufacturer_code_uniqueness(self):
        """Test that manufacturer_code must be unique."""
        import frappe
        from frappe.utils import random_string

        manufacturer_code = f"unique-mfr-{random_string(6).lower()}"

        # Create first manufacturer
        doc1 = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": f"Manufacturer One {random_string(4)}",
            "manufacturer_code": manufacturer_code
        })
        doc1.insert(ignore_permissions=True)
        self.track_document("Manufacturer", doc1.name)

        # Try to create second manufacturer with same code
        doc2 = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": f"Manufacturer Two {random_string(4)}",
            "manufacturer_code": manufacturer_code
        })

        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert(ignore_permissions=True)

    def test_manufacturer_enabled_default(self):
        """Test that enabled defaults to 1."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": f"Test Manufacturer {random_string(4)}",
            "manufacturer_code": f"test-{random_string(6).lower()}"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Manufacturer", doc.name)

        self.assertEqual(doc.enabled, 1)

    def test_manufacturer_with_optional_fields(self):
        """Test manufacturer creation with optional fields."""
        import frappe
        from frappe.utils import random_string

        manufacturer_code = f"test-opt-{random_string(6).lower()}"
        website = "https://manufacturer.example.com"
        description = "This is a test manufacturer description."

        doc = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": f"Test Manufacturer {random_string(4)}",
            "manufacturer_code": manufacturer_code,
            "website": website,
            "description": description
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Manufacturer", doc.name)

        self.assertEqual(doc.website, website)
        self.assertEqual(doc.description, description)

    def test_manufacturer_naming_by_code(self):
        """Test that manufacturer is named by manufacturer_code."""
        import frappe
        from frappe.utils import random_string

        manufacturer_code = f"naming-test-{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": f"Test Manufacturer {random_string(4)}",
            "manufacturer_code": manufacturer_code
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Manufacturer", doc.name)

        self.assertEqual(doc.name, manufacturer_code)


class TestFamilyVariantAttributeIntegrity(unittest.TestCase):
    """Test cases for Family Variant Attribute child table integrity."""

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

    def test_family_variant_attribute_with_valid_attribute(self):
        """Test adding variant attribute to family with valid PIM Attribute."""
        import frappe
        from frappe.utils import random_string

        # Create a PIM Attribute first
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"test_var_attr_{random_string(6).lower()}",
            "attribute_name": f"Test Variant Attr {random_string(4)}",
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create a Product Family with variant attribute
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": f"testfamily{random_string(6).lower()}",
            "allow_variants": 1,
            "variant_attributes": [{
                "attribute": attr.name,
                "sort_order": 0
            }]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Verify variant attribute was added
        self.assertEqual(len(family.variant_attributes), 1)
        self.assertEqual(family.variant_attributes[0].attribute, attr.name)

    def test_family_variant_attribute_invalid_link(self):
        """Test that linking to non-existent PIM Attribute fails."""
        import frappe
        from frappe.utils import random_string

        # Try to create family with invalid attribute reference
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": f"testfamily{random_string(6).lower()}",
            "allow_variants": 1,
            "variant_attributes": [{
                "attribute": "NonExistentAttribute12345",
                "sort_order": 0
            }]
        })

        with self.assertRaises(frappe.exceptions.LinkValidationError):
            family.insert(ignore_permissions=True)

    def test_family_variant_attribute_sort_order_default(self):
        """Test that sort_order defaults to 0."""
        import frappe
        from frappe.utils import random_string

        # Create a PIM Attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"test_sort_attr_{random_string(6).lower()}",
            "attribute_name": f"Test Sort Attr {random_string(4)}",
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create family without specifying sort_order
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": f"testfamily{random_string(6).lower()}",
            "allow_variants": 1,
            "variant_attributes": [{
                "attribute": attr.name
            }]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # sort_order should default to 0
        self.assertEqual(family.variant_attributes[0].sort_order, 0)

    def test_family_variant_attribute_sort_order_custom(self):
        """Test that custom sort_order is preserved."""
        import frappe
        from frappe.utils import random_string

        # Create two PIM Attributes
        attr1 = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"test_attr1_{random_string(6).lower()}",
            "attribute_name": f"Test Attr 1 {random_string(4)}",
            "data_type": "Text"
        })
        attr1.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr1.name)

        attr2 = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"test_attr2_{random_string(6).lower()}",
            "attribute_name": f"Test Attr 2 {random_string(4)}",
            "data_type": "Text"
        })
        attr2.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr2.name)

        # Create family with custom sort orders
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": f"testfamily{random_string(6).lower()}",
            "allow_variants": 1,
            "variant_attributes": [
                {"attribute": attr1.name, "sort_order": 10},
                {"attribute": attr2.name, "sort_order": 5}
            ]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Verify sort orders are preserved
        attr_dict = {va.attribute: va.sort_order for va in family.variant_attributes}
        self.assertEqual(attr_dict[attr1.name], 10)
        self.assertEqual(attr_dict[attr2.name], 5)

    def test_family_variant_attribute_multiple(self):
        """Test adding multiple variant attributes to family."""
        import frappe
        from frappe.utils import random_string

        # Create three PIM Attributes
        attrs = []
        for i in range(3):
            attr = frappe.get_doc({
                "doctype": "PIM Attribute",
                "attribute_code": f"test_multi_attr_{i}_{random_string(6).lower()}",
                "attribute_name": f"Test Multi Attr {i} {random_string(4)}",
                "data_type": "Text"
            })
            attr.insert(ignore_permissions=True)
            self.track_document("PIM Attribute", attr.name)
            attrs.append(attr)

        # Create family with multiple variant attributes
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": f"testfamily{random_string(6).lower()}",
            "allow_variants": 1,
            "variant_attributes": [
                {"attribute": attrs[0].name, "sort_order": 1},
                {"attribute": attrs[1].name, "sort_order": 2},
                {"attribute": attrs[2].name, "sort_order": 3}
            ]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Verify all variant attributes were added
        self.assertEqual(len(family.variant_attributes), 3)
        attr_names = [va.attribute for va in family.variant_attributes]
        for attr in attrs:
            self.assertIn(attr.name, attr_names)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
