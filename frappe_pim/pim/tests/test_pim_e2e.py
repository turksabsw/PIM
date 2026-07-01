# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""PIM End-to-End Tests

This module contains end-to-end tests for complete PIM workflows:
- Full product creation workflow with Brand, Manufacturer, and Family
- Product Family setup with variant attributes and attribute templates
- Channel publishing workflow
- Complete product catalog management scenarios

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestFullProductCreationWorkflow(unittest.TestCase):
    """E2E test cases for complete product creation workflow.

    Tests the full lifecycle of creating a product with all related entities:
    Brand -> Manufacturer -> Product Family -> Product Master with all links.
    """

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

    def test_e2e_product_with_brand_and_manufacturer(self):
        """E2E: Create product with brand and manufacturer links."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Step 1: Create Brand
        brand = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": f"E2E Brand {suffix}",
            "brand_code": f"e2e-brand-{suffix}",
            "enabled": 1
        })
        brand.insert(ignore_permissions=True)
        self.track_document("Brand", brand.name)

        # Step 2: Create Manufacturer
        manufacturer = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": f"E2E Manufacturer {suffix}",
            "manufacturer_code": f"e2e-mfr-{suffix}",
            "enabled": 1
        })
        manufacturer.insert(ignore_permissions=True)
        self.track_document("Manufacturer", manufacturer.name)

        # Step 3: Create Product Master with Brand and Manufacturer
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E Product {suffix}",
            "product_code": f"E2E-PROD-{suffix.upper()}",
            "short_description": "E2E test product with all links",
            "brand": brand.name,
            "manufacturer": manufacturer.name,
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Verify all links are correct
        self.assertEqual(product.brand, brand.name)
        self.assertEqual(product.manufacturer, manufacturer.name)
        self.assertEqual(product.status, "Draft")

        # Verify we can reload and links persist
        product.reload()
        self.assertEqual(product.brand, brand.name)
        self.assertEqual(product.manufacturer, manufacturer.name)

    def test_e2e_complete_product_with_family_and_attributes(self):
        """E2E: Complete product workflow with family, attributes, brand, manufacturer."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Step 1: Create PIM Attribute Group
        attr_group = frappe.get_doc({
            "doctype": "PIM Attribute Group",
            "group_name": f"E2E Group {suffix}",
            "is_standard": 0
        })
        attr_group.insert(ignore_permissions=True)
        self.track_document("PIM Attribute Group", attr_group.name)

        # Step 2: Create PIM Attributes
        color_attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"e2e_color_{suffix}",
            "attribute_name": f"E2E Color {suffix}",
            "data_type": "Text",
            "attribute_group": attr_group.name
        })
        color_attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", color_attr.name)

        size_attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"e2e_size_{suffix}",
            "attribute_name": f"E2E Size {suffix}",
            "data_type": "Text",
            "attribute_group": attr_group.name
        })
        size_attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", size_attr.name)

        # Step 3: Create Product Family with attribute templates
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"E2E Family {suffix}",
            "family_code": f"e2efamily{suffix}",
            "is_group": 0,
            "attributes": [
                {"attribute": color_attr.name, "is_required_in_family": 1},
                {"attribute": size_attr.name, "is_required_in_family": 0}
            ]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Step 4: Create Brand
        brand = frappe.get_doc({
            "doctype": "Brand",
            "brand_name": f"E2E Brand {suffix}",
            "brand_code": f"e2e-brand-{suffix}",
            "enabled": 1
        })
        brand.insert(ignore_permissions=True)
        self.track_document("Brand", brand.name)

        # Step 5: Create Manufacturer
        manufacturer = frappe.get_doc({
            "doctype": "Manufacturer",
            "manufacturer_name": f"E2E Manufacturer {suffix}",
            "manufacturer_code": f"e2e-mfr-{suffix}",
            "enabled": 1
        })
        manufacturer.insert(ignore_permissions=True)
        self.track_document("Manufacturer", manufacturer.name)

        # Step 6: Create Product Master with all relationships and attributes
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E Complete Product {suffix}",
            "product_code": f"E2E-COMPLETE-{suffix.upper()}",
            "short_description": "Complete E2E test product",
            "product_family": family.name,
            "brand": brand.name,
            "manufacturer": manufacturer.name,
            "status": "Active",
            "attribute_values": [
                {"attribute": color_attr.name, "value_text": "Red"},
                {"attribute": size_attr.name, "value_text": "Large"}
            ]
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Verify all relationships
        self.assertEqual(product.product_family, family.name)
        self.assertEqual(product.brand, brand.name)
        self.assertEqual(product.manufacturer, manufacturer.name)
        self.assertEqual(product.status, "Active")
        self.assertEqual(len(product.attribute_values), 2)

        # Verify attribute values
        attr_values = {av.attribute: av.value_text for av in product.attribute_values}
        self.assertEqual(attr_values[color_attr.name], "Red")
        self.assertEqual(attr_values[size_attr.name], "Large")

        # Verify completeness score (should be 100% with all required fields filled)
        from frappe_pim.pim.utils.completeness import calculate_score
        score = calculate_score(product)
        self.assertEqual(score, 100.0)


class TestProductFamilyWorkflow(unittest.TestCase):
    """E2E test cases for Product Family setup workflow.

    Tests complete family setup with attribute templates and variant attributes.
    """

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

    def test_e2e_family_with_variant_attributes(self):
        """E2E: Create product family with variant attributes for variants."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create variant-defining attributes (Color, Size)
        color_attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"var_color_{suffix}",
            "attribute_name": f"Variant Color {suffix}",
            "data_type": "Text"
        })
        color_attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", color_attr.name)

        size_attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"var_size_{suffix}",
            "attribute_name": f"Variant Size {suffix}",
            "data_type": "Text"
        })
        size_attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", size_attr.name)

        # Create family with variant attributes
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Variant Family {suffix}",
            "family_code": f"varfamily{suffix}",
            "is_group": 0,
            "allow_variants": 1,
            "variant_attributes": [
                {"attribute": color_attr.name, "sort_order": 1},
                {"attribute": size_attr.name, "sort_order": 2}
            ]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Verify variant attributes are correctly set
        self.assertEqual(len(family.variant_attributes), 2)
        variant_attr_names = [va.attribute for va in family.variant_attributes]
        self.assertIn(color_attr.name, variant_attr_names)
        self.assertIn(size_attr.name, variant_attr_names)

    def test_e2e_family_hierarchy(self):
        """E2E: Create hierarchical product families (parent-child)."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create parent family (group)
        parent_family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Parent Family {suffix}",
            "family_code": f"parentfamily{suffix}",
            "is_group": 1
        })
        parent_family.insert(ignore_permissions=True)
        self.track_document("Product Family", parent_family.name)

        # Create child family under parent
        child_family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Child Family {suffix}",
            "family_code": f"childfamily{suffix}",
            "is_group": 0,
            "parent_product_family": parent_family.name
        })
        child_family.insert(ignore_permissions=True)
        self.track_document("Product Family", child_family.name)

        # Verify hierarchy
        self.assertEqual(child_family.parent_product_family, parent_family.name)

        # Query children of parent
        children = frappe.get_all(
            "Product Family",
            filters={"parent_product_family": parent_family.name},
            pluck="name"
        )
        self.assertIn(child_family.name, children)

    def test_e2e_family_with_attribute_templates(self):
        """E2E: Create family with required and optional attribute templates."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create multiple attributes with different purposes
        attrs = []
        for i, (name, required) in enumerate([
            ("Material", True),
            ("Weight", True),
            ("Certification", False),
            ("Notes", False)
        ]):
            attr = frappe.get_doc({
                "doctype": "PIM Attribute",
                "attribute_code": f"attr_{name.lower()}_{suffix}",
                "attribute_name": f"{name} {suffix}",
                "data_type": "Text" if name != "Notes" else "Text"
            })
            attr.insert(ignore_permissions=True)
            self.track_document("PIM Attribute", attr.name)
            attrs.append((attr, required))

        # Create family with attribute templates
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Template Family {suffix}",
            "family_code": f"templatefamily{suffix}",
            "is_group": 0,
            "attributes": [
                {"attribute": attr.name, "is_required_in_family": 1 if req else 0}
                for attr, req in attrs
            ]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Verify templates
        self.assertEqual(len(family.attribute_templates), 4)
        required_count = sum(1 for t in family.attribute_templates if t.is_required)
        self.assertEqual(required_count, 2)


class TestProductVariantWorkflow(unittest.TestCase):
    """E2E test cases for product variant creation workflow."""

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

    def test_e2e_product_with_variants(self):
        """E2E: Create product master and multiple variants."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create parent product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Master Product {suffix}",
            "product_code": f"MASTER-{suffix.upper()}",
            "short_description": "Master product for variants",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Create multiple variants
        variants_data = [
            ("Red", "Small"),
            ("Red", "Large"),
            ("Blue", "Small"),
            ("Blue", "Large")
        ]

        for color, size in variants_data:
            variant = frappe.get_doc({
                "doctype": "Product Variant",
                "variant_name": f"Variant {color} {size} {suffix}",
                "variant_code": f"VAR-{color[:1]}{size[:1]}-{suffix.upper()}",
                "product_master": product.name,
                "status": "Draft",
                "variant_attribute_1": "Color",
                "variant_value_1": color,
                "variant_attribute_2": "Size",
                "variant_value_2": size
            })
            variant.insert(ignore_permissions=True)
            self.track_document("Product Variant", variant.name)

        # Query all variants for the master product
        variants = frappe.get_all(
            "Product Variant",
            filters={"product_master": product.name},
            fields=["name", "variant_code", "variant_value_1", "variant_value_2"]
        )
        self.assertEqual(len(variants), 4)

        # Verify unique variant codes
        variant_codes = [v.variant_code for v in variants]
        self.assertEqual(len(variant_codes), len(set(variant_codes)))


class TestChannelPublishingWorkflow(unittest.TestCase):
    """E2E test cases for channel publishing workflow."""

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

    def test_e2e_product_with_channels(self):
        """E2E: Create product and assign to multiple channels."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create channels
        web_channel = frappe.get_doc({
            "doctype": "Channel",
            "channel_name": f"Web Store {suffix}",
            "channel_code": f"web-{suffix}",
            "channel_type": "E-commerce"
        })
        web_channel.insert(ignore_permissions=True)
        self.track_document("Channel", web_channel.name)

        mobile_channel = frappe.get_doc({
            "doctype": "Channel",
            "channel_name": f"Mobile App {suffix}",
            "channel_code": f"mobile-{suffix}",
            "channel_type": "Mobile"
        })
        mobile_channel.insert(ignore_permissions=True)
        self.track_document("Channel", mobile_channel.name)

        # Create product with channel assignments
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Multichannel Product {suffix}",
            "product_code": f"MULTI-{suffix.upper()}",
            "short_description": "Product published to multiple channels",
            "status": "Active",
            "channels": [
                {"channel": web_channel.name, "is_published": 1},
                {"channel": mobile_channel.name, "is_published": 0}
            ]
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Verify channel assignments
        self.assertEqual(len(product.channels), 2)
        channel_names = [c.channel for c in product.channels]
        self.assertIn(web_channel.name, channel_names)
        self.assertIn(mobile_channel.name, channel_names)

        # Verify published status
        published_channels = [c.channel for c in product.channels if c.is_published]
        self.assertIn(web_channel.name, published_channels)
        self.assertNotIn(mobile_channel.name, published_channels)


class TestDocTypeMetadataAccess(unittest.TestCase):
    """E2E test cases for DocType metadata loading (prevents 417 errors)."""

    @classmethod
    def setUpClass(cls):
        """Set up test class - called once before all tests."""
        import frappe
        frappe.set_user("Administrator")

    def test_e2e_product_master_doctype_loads(self):
        """E2E: Verify Product Master DocType metadata loads without errors."""
        import frappe

        # This simulates what the form load API does
        doctype_meta = frappe.get_meta("Product Master")

        # Verify essential link fields exist
        brand_field = doctype_meta.get_field("brand")
        self.assertIsNotNone(brand_field, "Brand field should exist")
        self.assertEqual(brand_field.fieldtype, "Link")
        self.assertEqual(brand_field.options, "Brand")

        manufacturer_field = doctype_meta.get_field("manufacturer")
        self.assertIsNotNone(manufacturer_field, "Manufacturer field should exist")
        self.assertEqual(manufacturer_field.fieldtype, "Link")
        self.assertEqual(manufacturer_field.options, "Manufacturer")

        family_field = doctype_meta.get_field("product_family")
        self.assertIsNotNone(family_field, "Product Family field should exist")
        self.assertEqual(family_field.fieldtype, "Link")
        self.assertEqual(family_field.options, "Product Family")

    def test_e2e_brand_doctype_exists(self):
        """E2E: Verify Brand DocType exists and is properly configured."""
        import frappe

        # Brand DocType must exist (was causing 417 error)
        self.assertTrue(
            frappe.db.exists("DocType", "Brand"),
            "Brand DocType must exist"
        )

        # Verify we can get metadata
        meta = frappe.get_meta("Brand")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.name, "Brand")

        # Verify key fields exist
        self.assertIsNotNone(meta.get_field("brand_name"))
        self.assertIsNotNone(meta.get_field("brand_code"))

    def test_e2e_manufacturer_doctype_exists(self):
        """E2E: Verify Manufacturer DocType exists and is properly configured."""
        import frappe

        # Manufacturer DocType must exist (was causing 417 error)
        self.assertTrue(
            frappe.db.exists("DocType", "Manufacturer"),
            "Manufacturer DocType must exist"
        )

        # Verify we can get metadata
        meta = frappe.get_meta("Manufacturer")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.name, "Manufacturer")

        # Verify key fields exist
        self.assertIsNotNone(meta.get_field("manufacturer_name"))
        self.assertIsNotNone(meta.get_field("manufacturer_code"))

    def test_e2e_family_variant_attribute_doctype_exists(self):
        """E2E: Verify Family Variant Attribute child table exists."""
        import frappe

        # Family Variant Attribute DocType must exist
        self.assertTrue(
            frappe.db.exists("DocType", "Family Variant Attribute"),
            "Family Variant Attribute DocType must exist"
        )

        # Verify it's a child table
        meta = frappe.get_meta("Family Variant Attribute")
        self.assertTrue(meta.istable, "Family Variant Attribute must be a child table")

    def test_e2e_all_link_fields_resolve(self):
        """E2E: Verify all Link fields in Product Master resolve to existing DocTypes."""
        import frappe

        meta = frappe.get_meta("Product Master")
        link_fields = meta.get_link_fields()

        for field in link_fields:
            linked_doctype = field.options
            self.assertTrue(
                frappe.db.exists("DocType", linked_doctype),
                f"Link field {field.fieldname} references non-existent DocType: {linked_doctype}"
            )


class TestCompletenessWorkflow(unittest.TestCase):
    """E2E test cases for completeness scoring workflow."""

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

    def test_e2e_completeness_score_progression(self):
        """E2E: Verify completeness score increases as product data is filled."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_score

        suffix = random_string(6).lower()

        # Create attribute and family with required attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"req_attr_{suffix}",
            "attribute_name": f"Required Attr {suffix}",
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Completeness Family {suffix}",
            "family_code": f"compfamily{suffix}",
            "is_group": 0,
            "attributes": [
                {"attribute": attr.name, "is_required_in_family": 1}
            ]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Create product with minimal data (missing description and attribute)
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Incomplete Product {suffix}",
            "product_code": f"INCOMPLETE-{suffix.upper()}",
            "product_family": family.name,
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Initial score should be less than 100
        initial_score = calculate_score(product)
        self.assertLess(initial_score, 100.0)

        # Add short description
        product.short_description = "Now has a description"
        product.save(ignore_permissions=True)
        score_with_desc = calculate_score(product)
        self.assertGreater(score_with_desc, initial_score)

        # Add required attribute value
        product.append("attribute_values", {
            "attribute": attr.name,
            "value_text": "Filled value"
        })
        product.save(ignore_permissions=True)
        final_score = calculate_score(product)
        self.assertEqual(final_score, 100.0)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
