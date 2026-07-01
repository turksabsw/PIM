# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""Product Master Unit Tests

This module contains unit tests for:
- Product Master validation
- Product code (SKU) generation
- Completeness score calculation

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestProductMasterValidation(unittest.TestCase):
    """Test cases for Product Master validation logic."""

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

    def test_product_creation_basic(self):
        """Test basic product creation with required fields."""
        import frappe
        from frappe.utils import random_string

        product_code = f"TEST-{random_string(6).upper()}"
        product_name = f"Test Product {random_string(4)}"

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": product_name,
            "product_code": product_code,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        self.assertEqual(doc.product_name, product_name)
        self.assertEqual(doc.product_code, product_code)
        self.assertEqual(doc.status, "Draft")

    def test_product_requires_name(self):
        """Test that product name is required."""
        import frappe

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_code": "TEST-001",
            "status": "Draft"
        })

        # product_name is likely mandatory, should raise error
        with self.assertRaises(frappe.exceptions.MandatoryError):
            doc.insert(ignore_permissions=True)

    def test_product_code_uniqueness(self):
        """Test that product codes must be unique."""
        import frappe
        from frappe.utils import random_string

        product_code = f"UNIQUE-{random_string(6).upper()}"

        # Create first product
        doc1 = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Product One {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })
        doc1.insert(ignore_permissions=True)
        self.track_document("Product Master", doc1.name)

        # Try to create second product with same code
        doc2 = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Product Two {random_string(4)}",
            "product_code": product_code,
            "status": "Draft"
        })

        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert(ignore_permissions=True)

    def test_product_status_validation(self):
        """Test that product status must be a valid option."""
        import frappe
        from frappe.utils import random_string

        # Valid statuses should work
        for status in ["Draft", "Active", "Inactive", "Archived"]:
            doc = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Product {random_string(4)}",
                "product_code": f"TEST-{random_string(6).upper()}",
                "status": status
            })
            doc.insert(ignore_permissions=True)
            self.track_document("Product Master", doc.name)
            self.assertEqual(doc.status, status)

    def test_product_with_family_link(self):
        """Test product creation with product family link."""
        import frappe
        from frappe.utils import random_string

        # Create a product family first
        _rs = random_string(4).lower()
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {_rs}",
            "family_code": f"testfamily{_rs}",
            "is_group": 0
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Create product linked to family
        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": f"TEST-{random_string(6).upper()}",
            "product_family": family.name,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        self.assertEqual(doc.product_family, family.name)

    def test_product_invalid_family_link(self):
        """Test that linking to non-existent family fails."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": f"TEST-{random_string(6).upper()}",
            "product_family": "NonExistentFamily123",
            "status": "Draft"
        })

        # Should raise link validation error
        with self.assertRaises(frappe.exceptions.LinkValidationError):
            doc.insert(ignore_permissions=True)


class TestProductCodeGeneration(unittest.TestCase):
    """Test cases for product code (SKU) generation."""

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

    def test_product_code_format_alphanumeric(self):
        """Test that product codes can contain alphanumeric characters."""
        import frappe
        from frappe.utils import random_string

        _sfx = random_string(4).upper()
        valid_codes = [
            f"ABC{_sfx}",
            f"TEST{_sfx}001",
            f"PROD{_sfx}A",
            f"SKU{_sfx}45"
        ]

        for code in valid_codes:
            doc = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Test Product {random_string(4)}",
                "product_code": code,
                "status": "Draft"
            })
            doc.insert(ignore_permissions=True)
            self.track_document("Product Master", doc.name)
            self.assertEqual(doc.product_code, code)

    def test_product_code_uppercase_preservation(self):
        """Test that product codes preserve uppercase."""
        import frappe
        from frappe.utils import random_string

        code = f"UPPER-{random_string(4).upper()}"
        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": code,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        self.assertEqual(doc.product_code, code)

    def test_product_code_with_hyphens_underscores(self):
        """Test that product codes work with hyphens and underscores."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).upper()
        codes = [
            f"TEST-CODE-{suffix}",
            f"TEST_CODE_{suffix}",
            f"TEST-CODE_{suffix}"
        ]

        for code in codes:
            doc = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Test Product {random_string(4)}",
                "product_code": code,
                "status": "Draft"
            })
            doc.insert(ignore_permissions=True)
            self.track_document("Product Master", doc.name)
            self.assertEqual(doc.product_code, code)


class TestCompletenessScoring(unittest.TestCase):
    """Test cases for completeness score calculation."""

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

    def test_completeness_score_calculation_basic(self):
        """Test basic completeness score calculation."""
        from frappe_pim.pim.utils.completeness import calculate_score

        # Create a mock document-like object
        class MockDoc:
            def __init__(self):
                self.name = "TEST-001"
                self.product_name = "Test Product"
                self.product_code = "TEST-001"
                self.short_description = "Test description"
                self.product_family = None
                self.completeness_score = 0

            def get(self, field, default=None):
                return getattr(self, field, default)

        doc = MockDoc()
        score = calculate_score(doc)

        # With all 3 core fields filled and no family, should be 100%
        self.assertEqual(score, 100.0)

    def test_completeness_score_missing_field(self):
        """Test completeness score with missing fields."""
        from frappe_pim.pim.utils.completeness import calculate_score

        class MockDoc:
            def __init__(self):
                self.name = "TEST-002"
                self.product_name = "Test Product"
                self.product_code = "TEST-002"
                self.short_description = ""  # Empty = not filled
                self.product_family = None
                self.completeness_score = 0

            def get(self, field, default=None):
                return getattr(self, field, default)

        doc = MockDoc()
        score = calculate_score(doc)

        # With 2 of 3 core fields filled, should be ~66.67%
        self.assertAlmostEqual(score, 66.67, places=1)

    def test_completeness_score_zero_for_missing_all(self):
        """Test completeness score is low with all fields missing."""
        from frappe_pim.pim.utils.completeness import calculate_score

        class MockDoc:
            def __init__(self):
                self.name = "TEST-003"
                self.product_name = ""
                self.product_code = ""
                self.short_description = None
                self.product_family = None
                self.completeness_score = 0

            def get(self, field, default=None):
                return getattr(self, field, default)

        doc = MockDoc()
        score = calculate_score(doc)

        # With 0 of 3 core fields filled, should be 0%
        self.assertEqual(score, 0.0)

    def test_completeness_updates_document_field(self):
        """Test that calculate_score updates the document's completeness_score."""
        from frappe_pim.pim.utils.completeness import calculate_score

        class MockDoc:
            def __init__(self):
                self.name = "TEST-004"
                self.product_name = "Test"
                self.product_code = "TEST-004"
                self.short_description = "Desc"
                self.product_family = None
                self.completeness_score = 0

            def get(self, field, default=None):
                return getattr(self, field, default)

        doc = MockDoc()
        calculate_score(doc)

        # Document's completeness_score should be updated
        self.assertEqual(doc.completeness_score, 100.0)

    def test_completeness_with_family_attributes(self):
        """Test completeness score includes family required attributes."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_score

        # Create attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"test_attr_{random_string(6).lower()}",
            "attribute_name": f"Test Attribute {random_string(4)}",
            "data_type": "Text",
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create family with required attribute
        _rs_fam2 = random_string(4).lower()
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {_rs_fam2}",
            "family_code": f"testfam{_rs_fam2}",
            "is_group": 0,
            "attributes": [{
                "attribute": attr.name,
                "is_required_in_family": 1
            }]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Create product without the required attribute value
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": f"TEST-{random_string(6).upper()}",
            "short_description": "Test description",
            "product_family": family.name,
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Calculate score - should be less than 100% since required attr is missing
        score = calculate_score(product)

        # 3 core fields filled, 1 required attr missing = 3/4 = 75%
        self.assertEqual(score, 75.0)

    def test_completeness_with_filled_attribute(self):
        """Test completeness score with filled required attribute."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_score

        # Create attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"test_attr_{random_string(6).lower()}",
            "attribute_name": f"Test Attribute {random_string(4)}",
            "data_type": "Text",
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create family with required attribute
        _rs1 = random_string(4).lower()
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {_rs1}",
            "family_code": f"testfam{_rs1}",
            "is_group": 0,
            "attributes": [{
                "attribute": attr.name,
                "is_required_in_family": 1
            }]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Create product WITH the required attribute value filled
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": f"TEST-{random_string(6).upper()}",
            "short_description": "Test description",
            "product_family": family.name,
            "status": "Draft",
            "attribute_values": [{
                "attribute": attr.name,
                "value_text": "Sample value"
            }]
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Calculate score - should be 100% since all requirements are filled
        score = calculate_score(product)

        # 3 core fields + 1 required attr = 4/4 = 100%
        self.assertEqual(score, 100.0)


class TestCompletenessHelpers(unittest.TestCase):
    """Test cases for completeness helper functions."""

    def test_has_field_value_with_string(self):
        """Test _has_field_value with string values."""
        from frappe_pim.pim.utils.completeness import _has_field_value

        class MockDoc:
            def __init__(self):
                self.filled_field = "some value"
                self.empty_field = ""
                self.whitespace_field = "   "
                self.none_field = None

            def get(self, field, default=None):
                return getattr(self, field, default)

        doc = MockDoc()

        self.assertTrue(_has_field_value(doc, "filled_field"))
        self.assertFalse(_has_field_value(doc, "empty_field"))
        self.assertFalse(_has_field_value(doc, "whitespace_field"))
        self.assertFalse(_has_field_value(doc, "none_field"))

    def test_has_field_value_with_numbers(self):
        """Test _has_field_value with numeric values."""
        from frappe_pim.pim.utils.completeness import _has_field_value

        class MockDoc:
            def __init__(self):
                self.int_value = 42
                self.zero_value = 0
                self.float_value = 3.14

            def get(self, field, default=None):
                return getattr(self, field, default)

        doc = MockDoc()

        self.assertTrue(_has_field_value(doc, "int_value"))
        self.assertTrue(_has_field_value(doc, "zero_value"))  # 0 is a valid value
        self.assertTrue(_has_field_value(doc, "float_value"))

    def test_has_eav_value(self):
        """Test _has_eav_value with various value types."""
        from frappe_pim.pim.utils.completeness import _has_eav_value

        # Test text value
        row_text = {"attribute": "test", "value_text": "hello"}
        self.assertTrue(_has_eav_value(row_text))

        # Test empty text
        row_empty = {"attribute": "test", "value_text": ""}
        self.assertFalse(_has_eav_value(row_empty))

        # Test int value
        row_int = {"attribute": "test", "value_int": 42}
        self.assertTrue(_has_eav_value(row_int))

        # Test float value
        row_float = {"attribute": "test", "value_float": 3.14}
        self.assertTrue(_has_eav_value(row_float))

        # Test boolean value
        row_bool = {"attribute": "test", "value_boolean": True}
        self.assertTrue(_has_eav_value(row_bool))

        # Test date value
        row_date = {"attribute": "test", "value_date": "2024-01-01"}
        self.assertTrue(_has_eav_value(row_date))

        # Test no value
        row_none = {"attribute": "test"}
        self.assertFalse(_has_eav_value(row_none))

    def test_is_attribute_filled(self):
        """Test _is_attribute_filled function."""
        from frappe_pim.pim.utils.completeness import _is_attribute_filled

        attribute_values = [
            {"attribute": "color", "value_text": "Red"},
            {"attribute": "size", "value_text": "Large"},
            {"attribute": "weight", "value_float": 2.5},
            {"attribute": "empty_attr", "value_text": ""},
        ]

        self.assertTrue(_is_attribute_filled(attribute_values, "color"))
        self.assertTrue(_is_attribute_filled(attribute_values, "size"))
        self.assertTrue(_is_attribute_filled(attribute_values, "weight"))
        self.assertFalse(_is_attribute_filled(attribute_values, "empty_attr"))
        self.assertFalse(_is_attribute_filled(attribute_values, "nonexistent"))


class TestCompletenessSummary(unittest.TestCase):
    """Test cases for completeness summary functionality."""

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

    def test_completeness_summary_basic(self):
        """Test get_completeness_summary returns proper structure."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import get_completeness_summary

        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": f"TEST-{random_string(6).upper()}",
            "short_description": "Test description",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        summary = get_completeness_summary(product.name)

        # Check structure
        self.assertIn("product_name", summary)
        self.assertIn("score", summary)
        self.assertIn("total_required", summary)
        self.assertIn("total_filled", summary)
        self.assertIn("core_fields", summary)
        self.assertIn("missing_core", summary)

        # All core fields should be filled
        self.assertEqual(summary["score"], 100.0)
        self.assertEqual(len(summary["missing_core"]), 0)

    def test_completeness_summary_identifies_missing(self):
        """Test that summary correctly identifies missing required attributes."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import get_completeness_summary

        # Create attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"req_attr_{random_string(6).lower()}",
            "attribute_name": f"Required Attr {random_string(4)}",
            "data_type": "Text",
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create family with required attribute
        _rs = random_string(4).lower()
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {_rs}",
            "family_code": f"testfam{_rs}",
            "is_group": 0,
            "attributes": [{"attribute": attr.name, "is_required_in_family": 1}]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Create product with family but without filling the required attribute
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": f"TEST-{random_string(6).upper()}",
            "short_description": "Test description",
            "product_family": family.name,
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        summary = get_completeness_summary(product.name)

        # The required attribute should be in missing_attributes
        self.assertIn(attr.name, summary["missing_attributes"])
        self.assertLess(summary["score"], 100.0)


class TestProductMasterIntegration(unittest.TestCase):
    """Integration tests for Product Master with all related components."""

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

    def test_full_product_workflow(self):
        """Test complete product creation workflow with family and attributes."""
        import frappe
        from frappe.utils import random_string

        # 1. Create attribute group
        _rs_grp = random_string(4).lower()
        attr_group = frappe.get_doc({
            "doctype": "PIM Attribute Group",
            "group_name": f"Test Group {_rs_grp}",
            "group_code": f"testgrp{_rs_grp}",
            "is_standard": 0
        })
        attr_group.insert(ignore_permissions=True)
        self.track_document("PIM Attribute Group", attr_group.name)

        # 2. Create attributes
        color_attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"color_{random_string(6).lower()}",
            "attribute_name": f"Color {random_string(4)}",
            "data_type": "Text",
            "attribute_group": attr_group.name
        })
        color_attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", color_attr.name)

        size_attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"size_{random_string(6).lower()}",
            "attribute_name": f"Size {random_string(4)}",
            "data_type": "Text",
            "attribute_group": attr_group.name
        })
        size_attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", size_attr.name)

        # 3. Create family with attribute templates
        _rs_fam = random_string(4).lower()
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {_rs_fam}",
            "family_code": f"testfam{_rs_fam}",
            "is_group": 0,
            "attributes": [
                {"attribute": color_attr.name, "is_required_in_family": 1},
                {"attribute": size_attr.name, "is_required_in_family": 0}
            ]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # 4. Create product with attributes
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Widget {random_string(4)}",
            "product_code": f"WIDGET-{random_string(6).upper()}",
            "short_description": "A test widget product",
            "product_family": family.name,
            "status": "Draft",
            "attribute_values": [
                {"attribute": color_attr.name, "value_text": "Blue"},
                {"attribute": size_attr.name, "value_text": "Medium"}
            ]
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Verify product
        self.assertEqual(product.product_family, family.name)
        self.assertEqual(len(product.attribute_values), 2)

        # Verify completeness is 100%
        from frappe_pim.pim.utils.completeness import calculate_score
        score = calculate_score(product)
        self.assertEqual(score, 100.0)

    def test_product_with_variant_creation(self):
        """Test creating a product and then a variant."""
        import frappe
        from frappe.utils import random_string

        # Create product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Master {random_string(4)}",
            "product_code": f"MASTER-{random_string(6).upper()}",
            "short_description": "Master product",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Create variant
        variant = frappe.get_doc({
            "doctype": "Product Variant",
            "variant_name": f"Test Variant {random_string(4)}",
            "variant_code": f"VAR-{random_string(6).upper()}",
            "parent_product": product.name,
            "status": "Draft"
        })
        variant.insert(ignore_permissions=True)
        self.track_document("Product Variant", variant.name)

        # Verify linkage
        self.assertEqual(variant.parent_product, product.name)

        # Verify variant can be queried
        variants = frappe.get_all(
            "Product Variant",
            filters={"parent_product": product.name},
            pluck="name"
        )
        self.assertIn(variant.name, variants)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
