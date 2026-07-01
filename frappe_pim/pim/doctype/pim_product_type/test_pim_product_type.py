# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""PIM Product Type Unit Tests

This module contains unit tests for:
- PIM Product Type creation and validation
- Type code (slug) validation
- Type fields (custom field definitions) validation
- Allowed families configuration and validation
- Variant configuration validation
- Product validation against type requirements
- Deletion protection (products in use)

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestProductTypeCreation(unittest.TestCase):
    """Test cases for PIM Product Type creation and basic validation."""

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

    def test_basic_product_type_creation(self):
        """Test basic product type creation with required fields."""
        import frappe
        from frappe.utils import random_string

        type_name = f"Test Type {random_string(4)}"

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": type_name,
            "is_active": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertEqual(doc.type_name, type_name)
        self.assertEqual(doc.is_active, 1)
        # type_code should be auto-generated
        self.assertTrue(doc.type_code)

    def test_product_type_requires_name(self):
        """Test that type_name is required."""
        import frappe

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_code": "test_type",
            "is_active": 1
        })

        with self.assertRaises(frappe.exceptions.MandatoryError):
            doc.insert(ignore_permissions=True)

    def test_product_type_name_uniqueness(self):
        """Test that type_name must be unique (used as naming)."""
        import frappe
        from frappe.utils import random_string

        type_name = f"Unique Type {random_string(6)}"

        doc1 = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": type_name,
            "is_active": 1
        })
        doc1.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc1.name)

        doc2 = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": type_name,
            "is_active": 1
        })

        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert(ignore_permissions=True)

    def test_product_type_default_inactive(self):
        """Test creating a product type with is_active toggled."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Inactive Type {random_string(4)}",
            "is_active": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertEqual(doc.is_active, 0)

    def test_product_type_with_description(self):
        """Test product type creation with description."""
        import frappe
        from frappe.utils import random_string

        desc = "A test product type for apparel items"
        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Described Type {random_string(4)}",
            "description": desc,
            "is_active": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertEqual(doc.description, desc)


class TestTypeCodeValidation(unittest.TestCase):
    """Test cases for type code (slug) validation."""

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

    def test_valid_type_code_lowercase(self):
        """Test that lowercase type codes are accepted."""
        import frappe
        from frappe.utils import random_string

        code = f"valid_type_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Valid Type {random_string(4)}",
            "type_code": code,
            "is_active": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertEqual(doc.type_code, code)

    def test_valid_type_code_with_numbers(self):
        """Test that type codes with numbers are accepted."""
        import frappe
        from frappe.utils import random_string

        code = f"type123_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Num Type {random_string(4)}",
            "type_code": code,
            "is_active": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertEqual(doc.type_code, code)

    def test_invalid_type_code_with_uppercase(self):
        """Test that uppercase type codes are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"INVALID_TYPE_{random_string(4).upper()}"

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Invalid Type {random_string(4)}",
            "type_code": code,
            "is_active": 1
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_invalid_type_code_with_spaces(self):
        """Test that type codes with spaces are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"invalid type {random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Space Type {random_string(4)}",
            "type_code": code,
            "is_active": 1
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_invalid_type_code_starting_with_number(self):
        """Test that type codes starting with a number are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"123invalid_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Num Start Type {random_string(4)}",
            "type_code": code,
            "is_active": 1
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_type_code_auto_generation(self):
        """Test that type_code is auto-generated from type_name."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4)
        type_name = f"Auto Generated {suffix}"

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": type_name,
            "is_active": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertTrue(doc.type_code)
        self.assertNotIn(" ", doc.type_code)

    def test_type_code_uniqueness(self):
        """Test that type codes must be unique."""
        import frappe
        from frappe.utils import random_string

        code = f"unique_type_{random_string(6).lower()}"

        doc1 = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Type One {random_string(4)}",
            "type_code": code,
            "is_active": 1
        })
        doc1.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc1.name)

        doc2 = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Type Two {random_string(4)}",
            "type_code": code,
            "is_active": 1
        })

        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert(ignore_permissions=True)


class TestTypeFieldsValidation(unittest.TestCase):
    """Test cases for type_fields (custom field definitions) validation."""

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

    def test_product_type_with_valid_fields(self):
        """Test product type creation with valid custom fields."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Fields Type {random_string(4)}",
            "is_active": 1,
            "type_fields": [
                {
                    "fieldname": "custom_color",
                    "label": "Color",
                    "fieldtype": "Data",
                    "sort_order": 1
                },
                {
                    "fieldname": "custom_size",
                    "label": "Size",
                    "fieldtype": "Select",
                    "options": "S\nM\nL\nXL",
                    "sort_order": 2
                }
            ]
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertEqual(len(doc.type_fields), 2)

    def test_type_field_duplicate_fieldnames_rejected(self):
        """Test that duplicate fieldnames in type_fields are rejected."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Dup Fields {random_string(4)}",
            "is_active": 1,
            "type_fields": [
                {
                    "fieldname": "duplicate_field",
                    "label": "Field One",
                    "fieldtype": "Data",
                    "sort_order": 1
                },
                {
                    "fieldname": "duplicate_field",
                    "label": "Field Two",
                    "fieldtype": "Data",
                    "sort_order": 2
                }
            ]
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_type_field_invalid_fieldname_uppercase(self):
        """Test that uppercase fieldnames are rejected."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Upper Fields {random_string(4)}",
            "is_active": 1,
            "type_fields": [
                {
                    "fieldname": "INVALID_NAME",
                    "label": "Invalid",
                    "fieldtype": "Data",
                    "sort_order": 1
                }
            ]
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_type_field_link_requires_options(self):
        """Test that Link fieldtype requires options (DocType name)."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Link Fields {random_string(4)}",
            "is_active": 1,
            "type_fields": [
                {
                    "fieldname": "link_field",
                    "label": "Link Field",
                    "fieldtype": "Link",
                    "sort_order": 1
                    # No options provided - should fail
                }
            ]
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_type_field_missing_fieldname(self):
        """Test that empty fieldname is rejected."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"No Fieldname {random_string(4)}",
            "is_active": 1,
            "type_fields": [
                {
                    "fieldname": "",
                    "label": "Missing Name",
                    "fieldtype": "Data",
                    "sort_order": 1
                }
            ]
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_get_type_fields(self):
        """Test get_type_fields returns sorted field definitions."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Get Fields {random_string(4)}",
            "is_active": 1,
            "type_fields": [
                {
                    "fieldname": "field_b",
                    "label": "Field B",
                    "fieldtype": "Data",
                    "sort_order": 20
                },
                {
                    "fieldname": "field_a",
                    "label": "Field A",
                    "fieldtype": "Data",
                    "sort_order": 10
                }
            ]
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        type_doc = frappe.get_doc("PIM Product Type", doc.name)
        fields = type_doc.get_type_fields()

        self.assertEqual(len(fields), 2)
        # Should be sorted by sort_order
        self.assertEqual(fields[0]["fieldname"], "field_a")
        self.assertEqual(fields[1]["fieldname"], "field_b")

    def test_get_type_fields_empty(self):
        """Test get_type_fields returns empty list when no fields defined."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"No Fields {random_string(4)}",
            "is_active": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        type_doc = frappe.get_doc("PIM Product Type", doc.name)
        fields = type_doc.get_type_fields()

        self.assertEqual(len(fields), 0)


class TestAllowedFamilies(unittest.TestCase):
    """Test cases for allowed families configuration."""

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

    def _create_family(self, suffix):
        """Helper to create a product family."""
        import frappe
        from frappe.utils import random_string

        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Family {suffix}",
            "family_code": f"family_{suffix}_{random_string(4).lower()}",
            "is_group": 0
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)
        return family

    def test_is_family_allowed_no_restrictions(self):
        """Test that all families are allowed when no restrictions set."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4)

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Open Type {suffix}",
            "is_active": 1
            # No allowed_families
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        type_doc = frappe.get_doc("PIM Product Type", doc.name)
        self.assertTrue(type_doc.is_family_allowed("any_family_name"))

    def test_get_allowed_families_empty(self):
        """Test get_allowed_families returns empty list when none set."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"No Families {random_string(4)}",
            "is_active": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        type_doc = frappe.get_doc("PIM Product Type", doc.name)
        families = type_doc.get_allowed_families()

        self.assertEqual(len(families), 0)


class TestVariantConfiguration(unittest.TestCase):
    """Test cases for variant configuration validation."""

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

    def test_allow_variants_flag(self):
        """Test allow_variants flag is persisted correctly."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Variant Type {random_string(4)}",
            "is_active": 1,
            "allow_variants": 1
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertEqual(doc.allow_variants, 1)

    def test_no_variants_flag(self):
        """Test product type with variants disabled."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Simple Type {random_string(4)}",
            "is_active": 1,
            "allow_variants": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        self.assertEqual(doc.allow_variants, 0)


class TestProductValidation(unittest.TestCase):
    """Test cases for validating products against type requirements."""

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

    def test_validate_product_no_required_fields(self):
        """Test validation passes when type has no required fields."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4)

        # Create product type with no required fields
        type_doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"No Req Type {suffix}",
            "is_active": 1
        })
        type_doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", type_doc.name)

        # Create a product (Item)
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": f"TEST-ITEM-{random_string(6).upper()}",
            "item_name": f"Test Item {suffix}",
            "item_group": "All Item Groups"
        })
        item.insert(ignore_permissions=True)
        self.track_document("Item", item.name)

        loaded_type = frappe.get_doc("PIM Product Type", type_doc.name)
        result = loaded_type.validate_product(item)

        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)

    def test_validate_product_variant_mismatch(self):
        """Test validation fails when product has variants but type doesn't allow them."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4)

        # Create product type that does NOT allow variants
        type_doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"No Var Type {suffix}",
            "is_active": 1,
            "allow_variants": 0
        })
        type_doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", type_doc.name)

        # Create an Item with has_variants enabled
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": f"TEST-VAR-{random_string(6).upper()}",
            "item_name": f"Variant Item {suffix}",
            "item_group": "All Item Groups",
            "has_variants": 1
        })
        item.insert(ignore_permissions=True)
        self.track_document("Item", item.name)

        loaded_type = frappe.get_doc("PIM Product Type", type_doc.name)
        result = loaded_type.validate_product(item)

        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)

    def test_validate_product_with_required_type_fields(self):
        """Test validation detects missing required type-specific fields."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4)

        # Create product type with a required field
        type_doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Req Fields Type {suffix}",
            "is_active": 1,
            "type_fields": [
                {
                    "fieldname": "custom_material",
                    "label": "Material",
                    "fieldtype": "Data",
                    "reqd": 1,
                    "sort_order": 1
                }
            ]
        })
        type_doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", type_doc.name)

        # Create an Item WITHOUT the custom_material field value
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": f"TEST-REQ-{random_string(6).upper()}",
            "item_name": f"Missing Field Item {suffix}",
            "item_group": "All Item Groups"
        })
        item.insert(ignore_permissions=True)
        self.track_document("Item", item.name)

        loaded_type = frappe.get_doc("PIM Product Type", type_doc.name)
        result = loaded_type.validate_product(item)

        # Should have errors for missing required field
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)


class TestProductTypeDeletion(unittest.TestCase):
    """Test cases for product type deletion protection."""

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

    def test_delete_unused_product_type(self):
        """Test that unused product types can be deleted."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Deletable Type {random_string(4)}",
            "is_active": 0
        })
        doc.insert(ignore_permissions=True)

        doc_name = doc.name
        frappe.delete_doc("PIM Product Type", doc_name, ignore_permissions=True)
        frappe.db.commit()

        self.assertFalse(frappe.db.exists("PIM Product Type", doc_name))


class TestProductTypeAPIFunctions(unittest.TestCase):
    """Test cases for product type API functions."""

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

    def test_get_product_types_api(self):
        """Test get_product_types returns active product types."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_product_type.pim_product_type import get_product_types

        suffix = random_string(4)

        active_type = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Active API Type {suffix}",
            "is_active": 1
        })
        active_type.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", active_type.name)

        inactive_type = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"Inactive API Type {suffix}",
            "is_active": 0
        })
        inactive_type.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", inactive_type.name)

        result = get_product_types()

        result_names = [r["name"] for r in result]
        self.assertIn(active_type.name, result_names)
        self.assertNotIn(inactive_type.name, result_names)

    def test_get_type_fields_for_product_api(self):
        """Test get_type_fields_for_product API endpoint."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.doctype.pim_product_type.pim_product_type import get_type_fields_for_product

        suffix = random_string(4)

        doc = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"API Fields Type {suffix}",
            "is_active": 1,
            "type_fields": [
                {
                    "fieldname": "api_field",
                    "label": "API Field",
                    "fieldtype": "Data",
                    "sort_order": 1
                }
            ]
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Product Type", doc.name)

        result = get_type_fields_for_product(doc.name)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fieldname"], "api_field")


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
