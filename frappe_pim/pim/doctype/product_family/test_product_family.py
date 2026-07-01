# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""Product Family Unit Tests

This module contains unit tests for:
- Product Family creation and validation
- Family code (slug) validation
- NestedSet hierarchy operations (parent/child, ancestors, descendants)
- Attribute inheritance from parent families
- Variant axes configuration
- Duplicate attribute detection
- Deletion protection (children, products in use)

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestProductFamilyCreation(unittest.TestCase):
    """Test cases for Product Family creation and basic validation."""

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

    def test_basic_family_creation(self):
        """Test basic product family creation with required fields."""
        import frappe
        from frappe.utils import random_string

        family_name = f"Test Family {random_string(4)}"
        family_code = f"test_family_{random_string(6).lower()}"

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": family_name,
            "family_code": family_code,
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)

        self.assertEqual(doc.family_name, family_name)
        self.assertEqual(doc.family_code, family_code)
        self.assertEqual(doc.is_group, 0)
        self.assertEqual(doc.is_active, 1)

    def test_family_requires_name(self):
        """Test that family_name is required."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_code": f"test_{random_string(6).lower()}",
            "is_group": 0
        })

        with self.assertRaises(frappe.exceptions.MandatoryError):
            doc.insert(ignore_permissions=True)

    def test_family_requires_code(self):
        """Test that family_code is required."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "is_group": 0
        })
        # family_code is auto-generated from family_name if empty
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)

        # Should have auto-generated family_code
        self.assertTrue(doc.family_code)

    def test_family_code_uniqueness(self):
        """Test that family codes must be unique."""
        import frappe
        from frappe.utils import random_string

        code = f"unique_code_{random_string(6).lower()}"

        doc1 = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Family One {random_string(4)}",
            "family_code": code,
            "is_group": 0
        })
        doc1.insert(ignore_permissions=True)
        self.track_document("Product Family", doc1.name)

        doc2 = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Family Two {random_string(4)}",
            "family_code": code,
            "is_group": 0
        })

        with self.assertRaises(frappe.exceptions.DuplicateEntryError):
            doc2.insert(ignore_permissions=True)

    def test_family_default_settings(self):
        """Test that default settings are applied correctly."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Defaults {random_string(4)}",
            "family_code": f"test_defaults_{random_string(6).lower()}",
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)

        self.assertEqual(doc.is_active, 1)
        self.assertEqual(doc.allow_variants, 1)
        self.assertEqual(doc.inherit_parent_attributes, 1)

    def test_family_level_root(self):
        """Test that root families get level 1."""
        import frappe
        from frappe.utils import random_string

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Root Family {random_string(4)}",
            "family_code": f"root_{random_string(6).lower()}",
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)

        self.assertEqual(doc.level, 1)


class TestFamilyCodeValidation(unittest.TestCase):
    """Test cases for family code (slug) validation."""

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

    def test_valid_family_code_lowercase(self):
        """Test that lowercase family codes are accepted."""
        import frappe
        from frappe.utils import random_string

        code = f"valid_code_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": code,
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)

        self.assertEqual(doc.family_code, code)

    def test_valid_family_code_with_numbers(self):
        """Test that family codes with numbers are accepted."""
        import frappe
        from frappe.utils import random_string

        code = f"code123_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": code,
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)

        self.assertEqual(doc.family_code, code)

    def test_valid_family_code_with_underscores(self):
        """Test that family codes with underscores are accepted."""
        import frappe
        from frappe.utils import random_string

        code = f"my_test_code_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": code,
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)

        self.assertEqual(doc.family_code, code)

    def test_invalid_family_code_with_uppercase(self):
        """Test that uppercase family codes are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"INVALID_CODE_{random_string(4).upper()}"

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": code,
            "is_group": 0
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_invalid_family_code_with_spaces(self):
        """Test that family codes with spaces are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"invalid code {random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": code,
            "is_group": 0
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_invalid_family_code_starting_with_number(self):
        """Test that family codes starting with a number are rejected."""
        import frappe
        from frappe.utils import random_string

        code = f"123invalid_{random_string(4).lower()}"

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "family_code": code,
            "is_group": 0
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_family_code_auto_generation(self):
        """Test that family_code is auto-generated from family_name."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4)
        family_name = f"Auto Code Test {suffix}"

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": family_name,
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)

        # Should auto-generate via frappe.scrub()
        self.assertTrue(doc.family_code)
        self.assertNotIn(" ", doc.family_code)


class TestNestedSetHierarchy(unittest.TestCase):
    """Test cases for NestedSet hierarchy operations."""

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

    def _create_family(self, family_name, family_code, parent_family=None, is_group=0):
        """Helper to create a product family."""
        import frappe

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": family_name,
            "family_code": family_code,
            "parent_family": parent_family,
            "is_group": is_group
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)
        return doc

    def test_parent_child_relationship(self):
        """Test creating a parent-child hierarchy."""
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        parent = self._create_family(
            f"Parent {suffix}",
            f"parent_{suffix}",
            is_group=1
        )

        child = self._create_family(
            f"Child {suffix}",
            f"child_{suffix}",
            parent_family=parent.name
        )

        self.assertEqual(child.parent_family, parent.name)
        self.assertEqual(child.level, 2)

    def test_three_level_hierarchy(self):
        """Test creating a three-level hierarchy."""
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        grandparent = self._create_family(
            f"Grandparent {suffix}",
            f"grandparent_{suffix}",
            is_group=1
        )

        parent = self._create_family(
            f"Parent {suffix}",
            f"parent_{suffix}",
            parent_family=grandparent.name,
            is_group=1
        )

        child = self._create_family(
            f"Child {suffix}",
            f"child_{suffix}",
            parent_family=parent.name
        )

        self.assertEqual(grandparent.level, 1)
        self.assertEqual(parent.level, 2)
        self.assertEqual(child.level, 3)

    def test_get_ancestors(self):
        """Test get_ancestors returns correct ancestor chain."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        grandparent = self._create_family(
            f"GP {suffix}",
            f"gp_{suffix}",
            is_group=1
        )

        parent = self._create_family(
            f"P {suffix}",
            f"p_{suffix}",
            parent_family=grandparent.name,
            is_group=1
        )

        child = self._create_family(
            f"C {suffix}",
            f"c_{suffix}",
            parent_family=parent.name
        )

        # Reload to get latest data
        child_doc = frappe.get_doc("Product Family", child.name)
        ancestors = child_doc.get_ancestors()

        # Should return [grandparent, parent] (root-first order)
        self.assertEqual(len(ancestors), 2)
        self.assertEqual(ancestors[0].name, grandparent.name)
        self.assertEqual(ancestors[1].name, parent.name)

    def test_get_ancestors_root_family(self):
        """Test that root families have no ancestors."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        root = self._create_family(
            f"Root {suffix}",
            f"root_{suffix}"
        )

        root_doc = frappe.get_doc("Product Family", root.name)
        ancestors = root_doc.get_ancestors()

        self.assertEqual(len(ancestors), 0)

    def test_get_children(self):
        """Test get_children returns direct children."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        parent = self._create_family(
            f"Parent {suffix}",
            f"parent_{suffix}",
            is_group=1
        )

        child1 = self._create_family(
            f"Child A {suffix}",
            f"child_a_{suffix}",
            parent_family=parent.name
        )

        child2 = self._create_family(
            f"Child B {suffix}",
            f"child_b_{suffix}",
            parent_family=parent.name
        )

        parent_doc = frappe.get_doc("Product Family", parent.name)
        children = parent_doc.get_children()

        child_names = [c["name"] for c in children]
        self.assertIn(child1.name, child_names)
        self.assertIn(child2.name, child_names)

    def test_full_path_generation(self):
        """Test that full_path is generated correctly."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        parent = self._create_family(
            f"Fashion {suffix}",
            f"fashion_{suffix}",
            is_group=1
        )

        child = self._create_family(
            f"Tops {suffix}",
            f"tops_{suffix}",
            parent_family=parent.name
        )

        child_doc = frappe.get_doc("Product Family", child.name)
        self.assertIn(f"Fashion {suffix}", child_doc.full_path)
        self.assertIn(f"Tops {suffix}", child_doc.full_path)

    def test_cannot_be_own_parent(self):
        """Test that a family cannot be its own parent."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        doc = self._create_family(
            f"Self Parent {suffix}",
            f"self_parent_{suffix}"
        )

        doc.parent_family = doc.name

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.save(ignore_permissions=True)

    def test_parent_updates_is_group(self):
        """Test that parent's is_group is updated when children are added."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        parent = self._create_family(
            f"Parent {suffix}",
            f"parent_grp_{suffix}",
            is_group=0
        )

        _child = self._create_family(
            f"Child {suffix}",
            f"child_grp_{suffix}",
            parent_family=parent.name
        )

        # Reload parent to check is_group was updated
        parent_doc = frappe.get_doc("Product Family", parent.name)
        self.assertEqual(parent_doc.is_group, 1)


class TestAttributeInheritance(unittest.TestCase):
    """Test cases for attribute inheritance from parent families."""

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

    def _create_attribute(self, code_prefix):
        """Helper to create a PIM Attribute."""
        import frappe
        from frappe.utils import random_string

        code = f"{code_prefix}_{random_string(6).lower()}"
        doc = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Test Attr {code}",
            "attribute_code": code,
            "data_type": "Text"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", doc.name)
        return doc

    def _create_family(self, family_name, family_code, parent_family=None,
                       is_group=0, attributes=None, inherit_parent=1):
        """Helper to create a product family with optional attributes."""
        import frappe

        doc_data = {
            "doctype": "Product Family",
            "family_name": family_name,
            "family_code": family_code,
            "parent_family": parent_family,
            "is_group": is_group,
            "inherit_parent_attributes": inherit_parent
        }

        if attributes:
            doc_data["attributes"] = attributes

        doc = frappe.get_doc(doc_data)
        doc.insert(ignore_permissions=True)
        self.track_document("Product Family", doc.name)
        return doc

    def test_inherited_attributes_from_parent(self):
        """Test that child inherits attributes from parent family."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        attr1 = self._create_attribute("parent_attr")

        parent = self._create_family(
            f"Parent {suffix}",
            f"parent_{suffix}",
            is_group=1,
            attributes=[{
                "attribute": attr1.name,
                "is_required_in_family": 1,
                "sort_order": 1
            }]
        )

        child = self._create_family(
            f"Child {suffix}",
            f"child_{suffix}",
            parent_family=parent.name,
            inherit_parent=1
        )

        child_doc = frappe.get_doc("Product Family", child.name)
        inherited = child_doc.get_inherited_attributes()

        self.assertGreaterEqual(len(inherited), 1)
        inherited_attr_names = [a["attribute"] for a in inherited]
        self.assertIn(attr1.name, inherited_attr_names)

    def test_no_inheritance_when_disabled(self):
        """Test that inheritance is disabled when flag is off."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        attr1 = self._create_attribute("no_inherit_attr")

        parent = self._create_family(
            f"Parent NI {suffix}",
            f"parent_ni_{suffix}",
            is_group=1,
            attributes=[{
                "attribute": attr1.name,
                "is_required_in_family": 1,
                "sort_order": 1
            }]
        )

        child = self._create_family(
            f"Child NI {suffix}",
            f"child_ni_{suffix}",
            parent_family=parent.name,
            inherit_parent=0
        )

        child_doc = frappe.get_doc("Product Family", child.name)
        inherited = child_doc.get_inherited_attributes()

        self.assertEqual(len(inherited), 0)

    def test_get_all_attributes_combined(self):
        """Test get_all_attributes returns combined inherited + own attributes."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        parent_attr = self._create_attribute("all_parent")
        child_attr = self._create_attribute("all_child")

        parent = self._create_family(
            f"Parent All {suffix}",
            f"parent_all_{suffix}",
            is_group=1,
            attributes=[{
                "attribute": parent_attr.name,
                "is_required_in_family": 1,
                "sort_order": 1
            }]
        )

        child = self._create_family(
            f"Child All {suffix}",
            f"child_all_{suffix}",
            parent_family=parent.name,
            inherit_parent=1,
            attributes=[{
                "attribute": child_attr.name,
                "is_required_in_family": 0,
                "sort_order": 1
            }]
        )

        child_doc = frappe.get_doc("Product Family", child.name)
        all_attrs = child_doc.get_all_attributes()

        all_attr_names = [a["attribute"] for a in all_attrs]
        self.assertIn(parent_attr.name, all_attr_names)
        self.assertIn(child_attr.name, all_attr_names)

    def test_attribute_override_precedence(self):
        """Test that own attribute overrides inherited attribute with same name."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        shared_attr = self._create_attribute("shared")

        parent = self._create_family(
            f"Parent Ov {suffix}",
            f"parent_ov_{suffix}",
            is_group=1,
            attributes=[{
                "attribute": shared_attr.name,
                "is_required_in_family": 0,
                "default_value": "parent_default",
                "sort_order": 1
            }]
        )

        child = self._create_family(
            f"Child Ov {suffix}",
            f"child_ov_{suffix}",
            parent_family=parent.name,
            inherit_parent=1,
            attributes=[{
                "attribute": shared_attr.name,
                "is_required_in_family": 1,
                "default_value": "child_override",
                "sort_order": 1
            }]
        )

        child_doc = frappe.get_doc("Product Family", child.name)
        all_attrs = child_doc.get_all_attributes()

        # The shared attribute should only appear once (child's version)
        matching = [a for a in all_attrs if a["attribute"] == shared_attr.name]
        self.assertEqual(len(matching), 1)
        self.assertFalse(matching[0]["inherited"])
        self.assertTrue(matching[0].get("overrides_inherited"))

    def test_get_required_attributes(self):
        """Test get_required_attributes returns only required attributes."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        required_attr = self._create_attribute("req")
        optional_attr = self._create_attribute("opt")

        family = self._create_family(
            f"Req Family {suffix}",
            f"req_family_{suffix}",
            attributes=[
                {
                    "attribute": required_attr.name,
                    "is_required_in_family": 1,
                    "sort_order": 1
                },
                {
                    "attribute": optional_attr.name,
                    "is_required_in_family": 0,
                    "sort_order": 2
                }
            ]
        )

        family_doc = frappe.get_doc("Product Family", family.name)
        required = family_doc.get_required_attributes()

        self.assertIn(required_attr.name, required)
        self.assertNotIn(optional_attr.name, required)

    def test_validate_product_attributes_all_filled(self):
        """Test validate_product_attributes with all required attributes provided."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        attr1 = self._create_attribute("val_req")

        family = self._create_family(
            f"Val Family {suffix}",
            f"val_family_{suffix}",
            attributes=[{
                "attribute": attr1.name,
                "is_required_in_family": 1,
                "sort_order": 1
            }]
        )

        family_doc = frappe.get_doc("Product Family", family.name)
        result = family_doc.validate_product_attributes([
            {"attribute": attr1.name, "value": "some_value"}
        ])

        self.assertTrue(result["valid"])
        self.assertEqual(len(result["missing"]), 0)

    def test_validate_product_attributes_missing_required(self):
        """Test validate_product_attributes with missing required attributes."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        attr1 = self._create_attribute("val_miss")

        family = self._create_family(
            f"Miss Family {suffix}",
            f"miss_family_{suffix}",
            attributes=[{
                "attribute": attr1.name,
                "is_required_in_family": 1,
                "sort_order": 1
            }]
        )

        family_doc = frappe.get_doc("Product Family", family.name)
        result = family_doc.validate_product_attributes([])

        self.assertFalse(result["valid"])
        self.assertIn(attr1.name, result["missing"])
        self.assertGreater(len(result["errors"]), 0)


class TestDuplicateAttributeValidation(unittest.TestCase):
    """Test cases for duplicate attribute detection in family attributes."""

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

    def test_duplicate_attributes_rejected(self):
        """Test that duplicate attributes in family are rejected."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()
        code = f"dup_attr_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Dup Attr {suffix}",
            "attribute_code": code,
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Dup Family {suffix}",
            "family_code": f"dup_family_{suffix}",
            "is_group": 0,
            "attributes": [
                {"attribute": attr.name, "sort_order": 1},
                {"attribute": attr.name, "sort_order": 2}
            ]
        })

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.insert(ignore_permissions=True)


class TestVariantAxesConfiguration(unittest.TestCase):
    """Test cases for variant axes configuration."""

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

    def test_get_variant_axes_with_variants_allowed(self):
        """Test get_variant_axes when variants are allowed."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()
        code = f"axis_attr_{random_string(6).lower()}"

        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"Color {suffix}",
            "attribute_code": code,
            "data_type": "Select",
            "options": "Red, Blue, Green",
            "is_variant_axis": 1
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Variant Family {suffix}",
            "family_code": f"variant_family_{suffix}",
            "is_group": 0,
            "allow_variants": 1,
            "attributes": [
                {"attribute": attr.name, "sort_order": 1}
            ],
            "variant_attributes": [
                {"attribute": attr.name, "sort_order": 1}
            ]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        family_doc = frappe.get_doc("Product Family", family.name)
        axes = family_doc.get_variant_axes()

        self.assertGreaterEqual(len(axes), 1)
        axis_names = [a["attribute"] for a in axes]
        self.assertIn(attr.name, axis_names)

    def test_get_variant_axes_when_disabled(self):
        """Test get_variant_axes returns empty when variants not allowed."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"No Variant Family {suffix}",
            "family_code": f"no_variant_{suffix}",
            "is_group": 0,
            "allow_variants": 0
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        family_doc = frappe.get_doc("Product Family", family.name)
        axes = family_doc.get_variant_axes()

        self.assertEqual(len(axes), 0)


class TestFamilyDeletion(unittest.TestCase):
    """Test cases for family deletion protection."""

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

    def test_delete_unused_family(self):
        """Test that unused families can be deleted."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        doc = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Deletable {suffix}",
            "family_code": f"deletable_{suffix}",
            "is_group": 0
        })
        doc.insert(ignore_permissions=True)

        doc_name = doc.name
        frappe.delete_doc("Product Family", doc_name, ignore_permissions=True)
        frappe.db.commit()

        self.assertFalse(frappe.db.exists("Product Family", doc_name))

    def test_cannot_delete_family_with_children(self):
        """Test that families with children cannot be deleted."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()

        parent = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Parent Del {suffix}",
            "family_code": f"parent_del_{suffix}",
            "is_group": 1
        })
        parent.insert(ignore_permissions=True)
        self.track_document("Product Family", parent.name)

        child = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Child Del {suffix}",
            "family_code": f"child_del_{suffix}",
            "parent_family": parent.name,
            "is_group": 0
        })
        child.insert(ignore_permissions=True)
        self.track_document("Product Family", child.name)

        with self.assertRaises(frappe.exceptions.ValidationError):
            frappe.delete_doc("Product Family", parent.name)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
