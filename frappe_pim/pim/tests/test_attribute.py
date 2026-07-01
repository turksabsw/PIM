# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""PIM Attribute Unit Tests

This module contains unit tests for:
- PIM Attribute validation
- Attribute code (slug) validation
- Data type specific validation
- Options handling for Select/Multi Select
- Value constraint validation
- Type handling utilities

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestAttributeCreation(unittest.TestCase):
    """Test cases for PIM Attribute creation and basic validation."""

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

    def test_attribute_creation_text_type(self):
        """Test basic attribute creation with Text data type."""
        import frappe
        from frappe.utils import random_string

        code = f"test_text_{random_string(6).lower()}"
        name = f"Test Text Attr {random_string(4)}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": name,
            "attribute_code": code,
            "data_type": "Text"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.attribute_name, name)
        self.assertEqual(doc.attribute_code, code)
        self.assertEqual(doc.data_type, "Text")

    def test_attribute_creation_integer_type(self):
        """Test attribute creation with Integer data type."""
        import frappe
        from frappe.utils import random_string

        code = f"test_int_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Int Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Integer"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.data_type, "Integer")

    def test_attribute_creation_float_type(self):
        """Test attribute creation with Float data type."""
        import frappe
        from frappe.utils import random_string

        code = f"test_float_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Float Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Float"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.data_type, "Float")

    def test_attribute_creation_boolean_type(self):
        """Test attribute creation with Boolean data type."""
        import frappe
        from frappe.utils import random_string

        code = f"test_bool_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Bool Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Boolean"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.data_type, "Boolean")

    def test_attribute_creation_date_type(self):
        """Test attribute creation with Date data type."""
        import frappe
        from frappe.utils import random_string

        code = f"test_date_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Date Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Date"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.data_type, "Date")

    def test_attribute_creation_all_data_types(self):
        """Test attribute creation with all supported data types."""
        import frappe
        from frappe.utils import random_string

        data_types = [
            "Text", "Long Text", "Integer", "Float",
            "Boolean", "Date", "Datetime", "Image", "File"
        ]

        for dtype in data_types:
            code = f"test_{dtype.lower().replace(' ', '_')}_{random_string(4).lower()}"

            doc = frappe.get_doc({
                "doctype": "PIM Attribute",
                "attribute_name": f"Test {dtype} {random_string(4)}",
                "attribute_code": code,
                "data_type": dtype
            })
            doc.insert(ignore_permissions=True)
            self.track_document("PIM Attribute", doc.name)

            self.assertEqual(doc.data_type, dtype, f"Failed for data type: {dtype}")


class TestAttributeCodeValidation(unittest.TestCase):
    """Test cases for attribute code (slug) validation."""

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

    def test_valid_attribute_code_lowercase(self):
        """Test that lowercase attribute codes are accepted."""
        import frappe
        from frappe.utils import random_string

        code = f"valid_code_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.attribute_code, code)

    def test_valid_attribute_code_with_numbers(self):
        """Test that attribute codes with numbers are accepted."""
        import frappe
        from frappe.utils import random_string

        code = f"code123_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.attribute_code, code)

    def test_valid_attribute_code_with_underscores(self):
        """Test that attribute codes with underscores are accepted."""
        import frappe
        from frappe.utils import random_string

        code = f"my_test_code_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.attribute_code, code)

    def test_attribute_code_uniqueness(self):
        """Test that attribute codes must be unique."""
        import frappe
        from frappe.utils import random_string

        code = f"unique_code_{random_string(6).lower()}"

        # Create first attribute
        doc1 = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"First Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })
        doc1.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc1.name)

        # Try to create second attribute with same code
        doc2 = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Second Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })

        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert(ignore_permissions=True)

    def test_invalid_attribute_code_with_uppercase(self):
        """Test that uppercase attribute codes are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"INVALID_CODE_{random_string(4).upper()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_invalid_attribute_code_with_spaces(self):
        """Test that attribute codes with spaces are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"invalid code {random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_invalid_attribute_code_starting_with_number(self):
        """Test that attribute codes starting with a number are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"123invalid_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)


class TestSelectTypeValidation(unittest.TestCase):
    """Test cases for Select/Multi Select type validation."""

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

    def test_select_type_with_options(self):
        """Test Select type with valid options."""
        import frappe
        from frappe.utils import random_string

        code = f"test_select_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Select",
            "options": "Red, Blue, Green"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.data_type, "Select")
        self.assertIn("Red", doc.options)
        self.assertIn("Blue", doc.options)
        self.assertIn("Green", doc.options)

    def test_select_type_without_options_succeeds(self):
        """Test that Select type can be created without inline options.

        Options can be added later via PIM Attribute Option DocType,
        so inline options are not required at creation time.
        """
        import frappe
        from frappe.utils import random_string

        code = f"test_select_no_opt_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Select"
            # No inline options - valid because options can come from PIM Attribute Option
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)
        self.assertEqual(doc.data_type, "Select")

    def test_multi_select_type_with_options(self):
        """Test Multi Select type with valid options."""
        import frappe
        from frappe.utils import random_string

        code = f"test_multiselect_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Multi Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Multi Select",
            "options": "Option A, Option B, Option C"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.data_type, "Multi Select")

    def test_multi_select_type_without_options_succeeds(self):
        """Test that Multi Select type can be created without inline options.

        Options can be added later via PIM Attribute Option DocType,
        so inline options are not required at creation time.
        """
        import frappe
        from frappe.utils import random_string

        code = f"test_multi_no_opt_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Multi Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Multi Select"
            # No inline options - valid because options can come from PIM Attribute Option
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)
        self.assertEqual(doc.data_type, "Multi Select")

    def test_select_options_deduplication(self):
        """Test that duplicate options are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"test_dup_opt_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Select",
            "options": "Red, Blue, Red"  # Duplicate Red
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_get_parsed_options(self):
        """Test get_parsed_options returns list of options."""
        import frappe
        from frappe.utils import random_string

        code = f"test_parsed_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Select",
            "options": "Small, Medium, Large"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        options = doc.get_parsed_options()

        self.assertIsInstance(options, list)
        self.assertEqual(len(options), 3)
        self.assertEqual(options, ["Small", "Medium", "Large"])


class TestLinkTypeValidation(unittest.TestCase):
    """Test cases for Link type validation."""

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

    def test_link_type_with_linked_doctype(self):
        """Test Link type with valid linked_doctype."""
        import frappe
        from frappe.utils import random_string

        code = f"test_link_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Link {random_string(4)}",
            "attribute_code": code,
            "data_type": "Link",
            "linked_doctype": "User"  # Using existing DocType
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.data_type, "Link")
        self.assertEqual(doc.linked_doctype, "User")

    def test_link_type_without_linked_doctype_fails(self):
        """Test that Link type requires linked_doctype."""
        import frappe
        from frappe.utils import random_string

        code = f"test_link_no_dt_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Link {random_string(4)}",
            "attribute_code": code,
            "data_type": "Link"
            # No linked_doctype provided
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)


class TestValueConstraints(unittest.TestCase):
    """Test cases for value constraint validation (min/max values, max length)."""

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

    def test_integer_with_valid_min_max(self):
        """Test Integer type with valid min/max constraints."""
        import frappe
        from frappe.utils import random_string

        code = f"test_int_minmax_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Int {random_string(4)}",
            "attribute_code": code,
            "data_type": "Integer",
            "min_value": 0,
            "max_value": 100
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.min_value, 0)
        self.assertEqual(doc.max_value, 100)

    def test_integer_with_invalid_min_max_fails(self):
        """Test that min_value > max_value is rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"test_int_invalid_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Int {random_string(4)}",
            "attribute_code": code,
            "data_type": "Integer",
            "min_value": 100,  # Greater than max
            "max_value": 0
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_float_with_valid_min_max(self):
        """Test Float type with valid min/max constraints."""
        import frappe
        from frappe.utils import random_string

        code = f"test_float_minmax_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Float {random_string(4)}",
            "attribute_code": code,
            "data_type": "Float",
            "min_value": 0.0,
            "max_value": 99.99
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.min_value, 0.0)
        self.assertEqual(doc.max_value, 99.99)

    def test_text_with_max_length(self):
        """Test Text type with max_length constraint."""
        import frappe
        from frappe.utils import random_string

        code = f"test_text_maxlen_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Text {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text",
            "max_length": 255
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.max_length, 255)

    def test_non_numeric_type_clears_min_max(self):
        """Test that min/max values are cleared for non-numeric types."""
        import frappe
        from frappe.utils import random_string

        code = f"test_clear_minmax_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Text {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text",
            "min_value": 10,  # Should be cleared
            "max_value": 100  # Should be cleared
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        # min/max should be None for Text type
        self.assertIsNone(doc.min_value)
        self.assertIsNone(doc.max_value)


class TestAttributeValueValidation(unittest.TestCase):
    """Test cases for attribute value validation API."""

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

    def test_validate_text_value(self):
        """Test text value validation."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import validate_attribute_value

        code = f"test_val_text_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Text {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = validate_attribute_value(attr.name, "Sample text value")

        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)

    def test_validate_select_valid_option(self):
        """Test select value validation with valid option."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import validate_attribute_value

        code = f"test_val_select_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Select",
            "options": "Red, Blue, Green"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = validate_attribute_value(attr.name, "Blue")

        self.assertTrue(result["valid"])

    def test_validate_select_invalid_option(self):
        """Test select value validation with invalid option."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import validate_attribute_value

        code = f"test_val_select_inv_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Select",
            "options": "Red, Blue, Green"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = validate_attribute_value(attr.name, "Yellow")  # Invalid

        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)

    def test_validate_integer_in_range(self):
        """Test integer value validation within range."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import validate_attribute_value

        code = f"test_val_int_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Int {random_string(4)}",
            "attribute_code": code,
            "data_type": "Integer",
            "min_value": 0,
            "max_value": 100
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = validate_attribute_value(attr.name, "50")

        self.assertTrue(result["valid"])

    def test_validate_integer_below_min(self):
        """Test integer value validation below minimum."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import validate_attribute_value

        code = f"test_val_int_min_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Int {random_string(4)}",
            "attribute_code": code,
            "data_type": "Integer",
            "min_value": 10,
            "max_value": 100
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = validate_attribute_value(attr.name, "5")  # Below min

        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)

    def test_validate_integer_above_max(self):
        """Test integer value validation above maximum."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import validate_attribute_value

        code = f"test_val_int_max_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Int {random_string(4)}",
            "attribute_code": code,
            "data_type": "Integer",
            "min_value": 0,
            "max_value": 100
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = validate_attribute_value(attr.name, "150")  # Above max

        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)

    def test_validate_required_empty_value(self):
        """Test required attribute with empty value."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import validate_attribute_value

        code = f"test_val_req_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Required {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text",
            "is_required": 1
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = validate_attribute_value(attr.name, "")  # Empty

        self.assertFalse(result["valid"])

    def test_validate_text_max_length(self):
        """Test text value validation exceeding max length."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import validate_attribute_value

        code = f"test_val_maxlen_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Text {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text",
            "max_length": 10
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = validate_attribute_value(attr.name, "This is way too long")  # Exceeds 10 chars

        self.assertFalse(result["valid"])


class TestAttributeAPIFunctions(unittest.TestCase):
    """Test cases for attribute API functions."""

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

    def test_get_attribute_options_select(self):
        """Test get_attribute_options for Select type."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import get_attribute_options

        code = f"test_api_select_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Select {random_string(4)}",
            "attribute_code": code,
            "data_type": "Select",
            "options": "Small, Medium, Large",
            "is_required": 1
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = get_attribute_options(attr.name)

        self.assertEqual(result["data_type"], "Select")
        self.assertEqual(result["options"], ["Small", "Medium", "Large"])
        self.assertTrue(result["is_required"])

    def test_get_attribute_options_link(self):
        """Test get_attribute_options for Link type."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_attribute.pim_attribute import get_attribute_options

        code = f"test_api_link_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Link {random_string(4)}",
            "attribute_code": code,
            "data_type": "Link",
            "linked_doctype": "User"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        result = get_attribute_options(attr.name)

        self.assertEqual(result["data_type"], "Link")
        self.assertEqual(result["linked_doctype"], "User")


class TestAttributeDeletion(unittest.TestCase):
    """Test cases for attribute deletion protection."""

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

    def test_delete_unused_attribute(self):
        """Test that unused attributes can be deleted."""
        import frappe
        from frappe.utils import random_string

        code = f"test_del_unused_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)

        # Delete should succeed
        attr_name = attr.name
        frappe.delete_doc("PIM Attribute", attr_name, ignore_permissions=True)
        frappe.db.commit()

        self.assertFalse(frappe.db.exists("PIM Attribute", attr_name))

    def test_cannot_delete_attribute_in_use(self):
        """Test that attributes used in products cannot be deleted."""
        import frappe
        from frappe.utils import random_string

        code = f"test_del_inuse_{random_string(6).lower()}"

        # Create attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create product using this attribute
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": f"TEST-{random_string(6).upper()}",
            "status": "Draft",
            "attribute_values": [{
                "attribute": attr.name,
                "value_text": "Test value"
            }]
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Try to delete attribute - should fail
        with self.assertRaises(frappe.exceptions.ValidationError):
            frappe.delete_doc("PIM Attribute", attr.name)


class TestAttributeWithGroup(unittest.TestCase):
    """Test cases for attribute-group relationship."""

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

    def test_attribute_with_group(self):
        """Test creating attribute with attribute group."""
        import frappe
        from frappe.utils import random_string

        # Create group
        group = frappe.get_doc({
            "doctype": "PIM Attribute Group",
            "group_name": f"Test Group {random_string(4)}",
            "group_code": f"test_group_{random_string(6).lower()}"
        })
        group.insert(ignore_permissions=True)
        self.track_document("PIM Attribute Group", group.name)

        # Create attribute in group
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {random_string(4)}",
            "attribute_code": f"test_attr_{random_string(6).lower()}",
            "data_type": "Text",
            "attribute_group": group.name
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        self.assertEqual(attr.attribute_group, group.name)


class TestAttributeDisplaySettings(unittest.TestCase):
    """Test cases for attribute display settings."""

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

    def test_attribute_display_settings(self):
        """Test attribute display settings are saved correctly."""
        import frappe
        from frappe.utils import random_string

        code = f"test_display_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Display {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text",
            "is_filterable": 1,
            "is_searchable": 1,
            "show_in_grid": 1,
            "sort_order": 10
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.is_filterable, 1)
        self.assertEqual(doc.is_searchable, 1)
        self.assertEqual(doc.show_in_grid, 1)
        self.assertEqual(doc.sort_order, 10)

    def test_attribute_completeness_weight(self):
        """Test attribute completeness weight setting."""
        import frappe
        from frappe.utils import random_string

        code = f"test_weight_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Weight {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text",
            "weight_in_completeness": 5
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.weight_in_completeness, 5)

    def test_attribute_localizable_setting(self):
        """Test attribute is_localizable setting."""
        import frappe
        from frappe.utils import random_string

        code = f"test_local_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Localizable {random_string(4)}",
            "attribute_code": code,
            "data_type": "Text",
            "is_localizable": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)

        self.assertEqual(doc.is_localizable, 1)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
