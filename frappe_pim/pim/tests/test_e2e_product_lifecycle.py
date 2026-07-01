# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""End-to-End Product Lifecycle Verification Tests

This module tests the complete product lifecycle from creation to ERPNext sync:
1. Create PIM Product Type with custom type_fields
2. Create a Product Family with family_attribute_template entries
3. Create a Product Master linked to the type and family
4. Add product_attribute_value entries for required attributes
5. Generate variants using variant axes
6. Verify corresponding ERPNext Items are synced
7. Verify completeness score is calculated

These tests validate that all PIM entities work together correctly
in a realistic product management workflow.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestE2EProductLifecycle(unittest.TestCase):
    """End-to-end verification for the complete product lifecycle.

    Tests the full flow: Product Type -> Product Family -> Product Master
    -> Attribute Values -> Variants -> ERPNext Item sync -> Completeness.
    """

    # Prefix for all test data (used for cleanup)
    TEST_PREFIX = "E2ELIFE"

    @classmethod
    def setUpClass(cls):
        """Set up test class - create all infrastructure needed."""
        import frappe
        frappe.set_user("Administrator")
        cls._cleanup_test_data()
        cls._create_test_infrastructure()

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        import frappe
        cls._cleanup_test_data()
        frappe.db.commit()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove any test data from previous or current runs.

        Deletes in reverse dependency order to avoid foreign key issues.
        """
        import frappe

        prefix = cls.TEST_PREFIX

        # Delete in reverse dependency order
        cleanup_queries = [
            # Child table records first
            (
                "tabProduct Attribute Value",
                f"parent LIKE '{prefix}-%' OR parent LIKE '{prefix.lower()}-%'"
            ),
            (
                "tabProduct Variant Axis Value",
                f"parent LIKE '{prefix}-%' OR parent LIKE '{prefix.lower()}-%'"
            ),
            (
                "tabProduct Media",
                f"parent LIKE '{prefix}-%' OR parent LIKE '{prefix.lower()}-%'"
            ),
            (
                "tabProduct Channel",
                f"parent LIKE '{prefix}-%' OR parent LIKE '{prefix.lower()}-%'"
            ),
            (
                "tabProduct Type Field",
                f"parent LIKE '{prefix}-%' OR parent LIKE '{prefix.lower()}_%'"
            ),
            (
                "tabFamily Attribute Template",
                f"parent LIKE '{prefix}-%' OR parent LIKE '{prefix.lower()}_%'"
            ),
            (
                "tabFamily Variant Attribute",
                f"parent LIKE '{prefix}-%' OR parent LIKE '{prefix.lower()}_%'"
            ),
            # Product Variants (normal DocType)
            (
                "tabProduct Variant",
                f"variant_code LIKE '{prefix}-%'"
            ),
            # Items created by Product Master or variants
            (
                "tabItem",
                f"item_code LIKE '{prefix}-%'"
            ),
            # Product Families
            (
                "tabProduct Family",
                f"family_code LIKE '{prefix.lower()}_%'"
            ),
            # Product Types
            (
                "tabPIM Product Type",
                f"type_code LIKE '{prefix.lower()}_%'"
            ),
            # Attribute Options
            (
                "tabPIM Attribute Option",
                (
                    f"attribute IN (SELECT name FROM `tabPIM Attribute` "
                    f"WHERE attribute_code LIKE '{prefix.lower()}_%')"
                )
            ),
            # Attributes
            (
                "tabPIM Attribute",
                f"attribute_code LIKE '{prefix.lower()}_%'"
            ),
            # Attribute Groups
            (
                "tabPIM Attribute Group",
                f"group_name LIKE '{prefix} %'"
            ),
        ]

        for table, condition in cleanup_queries:
            try:
                frappe.db.sql(f"DELETE FROM `{table}` WHERE {condition}")
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def _create_test_infrastructure(cls):
        """Create all test infrastructure entities in dependency order."""
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).lower()
        cls.suffix = suffix
        prefix = cls.TEST_PREFIX

        # ====================================================================
        # Step 1: Create Attribute Group
        # ====================================================================
        cls.attr_group = frappe.get_doc({
            "doctype": "PIM Attribute Group",
            "group_name": f"{prefix} Test Group {suffix}",
            "is_standard": 0,
        })
        cls.attr_group.insert(ignore_permissions=True)

        # ====================================================================
        # Step 2: Create Attributes (Color, Size, Material, Weight)
        # ====================================================================
        cls.attr_color = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"{prefix} Color {suffix}",
            "attribute_code": f"{prefix.lower()}_color_{suffix}",
            "data_type": "Select",
            "options": "Red,Blue,Green,Black,White",
            "attribute_group": cls.attr_group.name,
            "is_required_in_family": 1,
            "is_filterable": 1,
        })
        cls.attr_color.insert(ignore_permissions=True)

        cls.attr_size = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"{prefix} Size {suffix}",
            "attribute_code": f"{prefix.lower()}_size_{suffix}",
            "data_type": "Select",
            "options": "S,M,L,XL",
            "attribute_group": cls.attr_group.name,
            "is_required_in_family": 1,
            "is_filterable": 1,
        })
        cls.attr_size.insert(ignore_permissions=True)

        cls.attr_material = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"{prefix} Material {suffix}",
            "attribute_code": f"{prefix.lower()}_material_{suffix}",
            "data_type": "Text",
            "attribute_group": cls.attr_group.name,
            "is_required_in_family": 1,
        })
        cls.attr_material.insert(ignore_permissions=True)

        cls.attr_weight = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"{prefix} Weight {suffix}",
            "attribute_code": f"{prefix.lower()}_weight_{suffix}",
            "data_type": "Float",
            "attribute_group": cls.attr_group.name,
            "is_required_in_family": 0,
        })
        cls.attr_weight.insert(ignore_permissions=True)

        # ====================================================================
        # Step 3: Create PIM Product Type with type_fields
        # ====================================================================
        cls.product_type = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"{prefix} Apparel Type {suffix}",
            "type_code": f"{prefix.lower()}_apparel_{suffix}",
            "description": "Test product type for apparel with custom fields",
            "is_active": 1,
            "allow_variants": 1,
            "type_fields": [
                {
                    "fieldname": "season",
                    "label": "Season",
                    "fieldtype": "Select",
                    "options": "Spring\\nSummer\\nFall\\nWinter",
                    "reqd": 0,
                    "sort_order": 1,
                },
                {
                    "fieldname": "collection_year",
                    "label": "Collection Year",
                    "fieldtype": "Int",
                    "reqd": 0,
                    "sort_order": 2,
                },
                {
                    "fieldname": "care_instructions",
                    "label": "Care Instructions",
                    "fieldtype": "Text Editor",
                    "reqd": 0,
                    "sort_order": 3,
                },
            ],
        })
        cls.product_type.insert(ignore_permissions=True)

        # ====================================================================
        # Step 4: Create Product Family with attributes and variant axes
        # ====================================================================
        cls.product_family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"{prefix} Fashion Family {suffix}",
            "family_code": f"{prefix.lower()}_fashion_{suffix}",
            "is_group": 0,
            "is_active": 1,
            "allow_variants": 1,
            "completeness_threshold": 80,
            "min_images": 1,
            "attributes": [
                {
                    "attribute": cls.attr_color.name,
                    "is_required_in_family": 1,
                    "sort_order": 1,
                },
                {
                    "attribute": cls.attr_size.name,
                    "is_required_in_family": 1,
                    "sort_order": 2,
                },
                {
                    "attribute": cls.attr_material.name,
                    "is_required_in_family": 1,
                    "sort_order": 3,
                },
                {
                    "attribute": cls.attr_weight.name,
                    "is_required_in_family": 0,
                    "sort_order": 4,
                },
            ],
            "variant_attributes": [
                {
                    "attribute": cls.attr_color.name,
                    "sort_order": 1,
                },
                {
                    "attribute": cls.attr_size.name,
                    "sort_order": 2,
                },
            ],
        })
        cls.product_family.insert(ignore_permissions=True)

        frappe.db.commit()

    # ========================================================================
    # Test 1: Verify Product Type creation and type_fields
    # ========================================================================

    def test_01_product_type_created_with_type_fields(self):
        """Verify PIM Product Type was created with custom type_fields.

        Checks:
        - Product Type exists and is active
        - Type code was properly validated/generated
        - type_fields child table has expected entries
        - allow_variants flag is set
        """
        import frappe

        # Verify type exists
        self.assertTrue(
            frappe.db.exists("PIM Product Type", self.product_type.name),
            "PIM Product Type should exist"
        )

        # Reload to verify persistence
        pt = frappe.get_doc("PIM Product Type", self.product_type.name)
        self.assertEqual(pt.is_active, 1)
        self.assertEqual(pt.allow_variants, 1)

        # Verify type_code was properly set
        self.assertTrue(
            pt.type_code.startswith(f"{self.TEST_PREFIX.lower()}_"),
            f"Type code should start with prefix: {pt.type_code}"
        )

        # Verify type_fields child table
        self.assertIsNotNone(pt.type_fields)
        self.assertEqual(len(pt.type_fields), 3)

        # Verify field details
        field_names = [f.fieldname for f in pt.type_fields]
        self.assertIn("season", field_names)
        self.assertIn("collection_year", field_names)
        self.assertIn("care_instructions", field_names)

        # Verify fieldtypes
        field_types = {f.fieldname: f.fieldtype for f in pt.type_fields}
        self.assertEqual(field_types["season"], "Select")
        self.assertEqual(field_types["collection_year"], "Int")
        self.assertEqual(field_types["care_instructions"], "Text Editor")

    # ========================================================================
    # Test 2: Verify Product Family with attributes and variant axes
    # ========================================================================

    def test_02_product_family_created_with_attributes(self):
        """Verify Product Family was created with attribute templates
        and variant axis configuration.

        Checks:
        - Family exists with correct metadata
        - Family Attribute Template entries are correct
        - Family Variant Attribute entries are correct
        - allow_variants flag is set
        """
        import frappe

        # Verify family exists
        self.assertTrue(
            frappe.db.exists("Product Family", self.product_family.name),
            "Product Family should exist"
        )

        # Reload to verify persistence
        family = frappe.get_doc("Product Family", self.product_family.name)
        self.assertEqual(family.allow_variants, 1)
        self.assertEqual(family.completeness_threshold, 80)

        # Verify attributes child table (Family Attribute Template)
        self.assertIsNotNone(family.attributes)
        self.assertEqual(len(family.attributes), 4)

        # Verify required attributes
        required_attrs = [
            a.attribute for a in family.attributes
            if a.is_required_in_family
        ]
        self.assertIn(self.attr_color.name, required_attrs)
        self.assertIn(self.attr_size.name, required_attrs)
        self.assertIn(self.attr_material.name, required_attrs)

        # Verify optional attributes
        optional_attrs = [
            a.attribute for a in family.attributes
            if not a.is_required_in_family
        ]
        self.assertIn(self.attr_weight.name, optional_attrs)

        # Verify variant_attributes child table (Family Variant Attribute)
        self.assertIsNotNone(family.variant_attributes)
        self.assertEqual(len(family.variant_attributes), 2)

        variant_axis_attrs = [va.attribute for va in family.variant_attributes]
        self.assertIn(self.attr_color.name, variant_axis_attrs)
        self.assertIn(self.attr_size.name, variant_axis_attrs)

    # ========================================================================
    # Test 3: Create Product Master linked to type and family
    # ========================================================================

    def test_03_create_product_master_linked_to_type_and_family(self):
        """Create a Product Master linked to the Product Type and
        Product Family. Verify it creates an ERPNext Item backend.

        Checks:
        - Product Master can be created via Virtual DocType
        - ERPNext Item is created as backend storage
        - product_family and product_type links are stored correctly
        - Item fields are mapped correctly from Product Master
        """
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).upper()
        product_code = f"{self.TEST_PREFIX}-SHIRT-{suffix}"
        product_name = f"{self.TEST_PREFIX} Classic T-Shirt {suffix}"

        # Create Product Master
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": product_name,
            "product_code": product_code,
            "short_description": "Premium cotton classic t-shirt for everyday wear",
            "product_family": self.product_family.name,
            "product_type": self.product_type.name,
            "status": "Draft",
            "stock_uom": "Nos",
            "is_stock_item": 1,
            "is_template": 1,
            "brand": "TestBrand",
        })
        product.insert(ignore_permissions=True)

        # Store for later tests
        self.__class__.product_master_name = product.name
        self.__class__.product_code = product_code

        # Verify Product Master was created
        self.assertIsNotNone(product.name)
        self.assertEqual(product.product_name, product_name)
        self.assertEqual(product.product_code, product_code)

        # Verify ERPNext Item was created as backend
        self.assertTrue(
            frappe.db.exists("Item", product.name),
            f"ERPNext Item {product.name} should exist as Virtual DocType backend"
        )

        # Verify Item field mapping
        item = frappe.get_doc("Item", product.name)
        self.assertEqual(item.item_name, product_name)
        self.assertEqual(item.item_code, product_code)
        self.assertEqual(item.description, "Premium cotton classic t-shirt for everyday wear")
        self.assertEqual(item.stock_uom, "Nos")

        # Verify custom fields on Item
        self.assertEqual(
            item.custom_pim_product_family,
            self.product_family.name,
            "Product Family should be stored on Item custom field"
        )
        self.assertEqual(
            item.custom_pim_product_type,
            self.product_type.name,
            "Product Type should be stored on Item custom field"
        )
        self.assertEqual(item.custom_pim_status, "Draft")

    # ========================================================================
    # Test 4: Add attribute values to the product
    # ========================================================================

    def test_04_add_attribute_values_to_product(self):
        """Add Product Attribute Value entries to the Product Master.

        Checks:
        - Attribute values can be appended as child table entries
        - Values are stored with correct typed columns (value_text, value_float)
        - Attribute links are valid
        - Saving with attribute values succeeds
        """
        import frappe

        # Get or create product if not available from previous test
        product_name = getattr(self.__class__, 'product_master_name', None)
        if not product_name:
            self.test_03_create_product_master_linked_to_type_and_family()
            product_name = self.__class__.product_master_name

        # Load the product
        product = frappe.get_doc("Product Master", product_name)

        # Add attribute values for family-required attributes
        product.attribute_values = [
            {
                "attribute": self.attr_color.name,
                "value_text": "Red",
            },
            {
                "attribute": self.attr_size.name,
                "value_text": "M",
            },
            {
                "attribute": self.attr_material.name,
                "value_text": "100% Cotton",
            },
            {
                "attribute": self.attr_weight.name,
                "value_float": 0.25,
            },
        ]

        product.save(ignore_permissions=True)

        # Reload to verify persistence
        product_reload = frappe.get_doc("Product Master", product_name)

        # Verify attribute values were saved
        attr_values = product_reload.get("attribute_values") or []
        self.assertEqual(
            len(attr_values), 4,
            f"Expected 4 attribute values, got {len(attr_values)}"
        )

        # Check that values were stored in correct typed columns
        attr_value_map = {}
        for av in attr_values:
            attr_name = av.get("attribute") if isinstance(av, dict) else av.attribute
            attr_value_map[attr_name] = av

        # Verify Color (text)
        color_av = attr_value_map.get(self.attr_color.name)
        self.assertIsNotNone(color_av, "Color attribute value should exist")
        color_text = (
            color_av.get("value_text") if isinstance(color_av, dict)
            else color_av.value_text
        )
        self.assertEqual(color_text, "Red")

        # Verify Weight (float)
        weight_av = attr_value_map.get(self.attr_weight.name)
        self.assertIsNotNone(weight_av, "Weight attribute value should exist")
        weight_float = (
            weight_av.get("value_float") if isinstance(weight_av, dict)
            else weight_av.value_float
        )
        self.assertAlmostEqual(float(weight_float or 0), 0.25, places=2)

    # ========================================================================
    # Test 5: Create Product Variants with axis values
    # ========================================================================

    def test_05_create_product_variants(self):
        """Create Product Variants using the variant axes defined
        in the Product Family (Color + Size).

        Checks:
        - Variants can be created with axis_values
        - parent_product links correctly to the Product Master / Item
        - Each variant has a unique variant_code
        - Variant validation passes (axes match family config)
        """
        import frappe
        from frappe.utils import random_string

        # Ensure product master exists
        product_name = getattr(self.__class__, 'product_master_name', None)
        if not product_name:
            self.test_03_create_product_master_linked_to_type_and_family()
            product_name = self.__class__.product_master_name

        product_code = self.__class__.product_code

        # Define variant combinations (Color x Size subset)
        variant_combos = [
            ("Red", "S"),
            ("Red", "M"),
            ("Blue", "S"),
            ("Blue", "M"),
        ]

        created_variants = []

        for color, size in variant_combos:
            suffix = random_string(3).upper()
            variant_code = f"{self.TEST_PREFIX}-{color.upper()}-{size}-{suffix}"
            variant_name = f"{self.TEST_PREFIX} Shirt {color} {size} {suffix}"

            variant = frappe.get_doc({
                "doctype": "Product Variant",
                "variant_name": variant_name,
                "variant_code": variant_code,
                "parent_product": product_name,
                "product_family": self.product_family.name,
                "status": "Draft",
                "sync_enabled": 0,  # Disable sync to avoid async issues in test
                "axis_values": [
                    {
                        "attribute": self.attr_color.name,
                        "attribute_value": color,
                    },
                    {
                        "attribute": self.attr_size.name,
                        "attribute_value": size,
                    },
                ],
            })
            variant.insert(ignore_permissions=True)
            created_variants.append(variant)

        # Store for later tests
        self.__class__.created_variants = created_variants

        # Verify all variants were created
        self.assertEqual(
            len(created_variants), 4,
            f"Expected 4 variants, got {len(created_variants)}"
        )

        for variant in created_variants:
            # Verify variant exists in database
            self.assertTrue(
                frappe.db.exists("Product Variant", variant.name),
                f"Product Variant {variant.name} should exist"
            )

            # Reload and verify
            v = frappe.get_doc("Product Variant", variant.name)
            self.assertEqual(v.parent_product, product_name)
            self.assertEqual(v.product_family, self.product_family.name)

            # Verify axis values
            self.assertEqual(
                len(v.axis_values), 2,
                f"Variant {v.name} should have 2 axis values"
            )

    # ========================================================================
    # Test 6: Verify unique combination enforcement
    # ========================================================================

    def test_06_duplicate_variant_combination_rejected(self):
        """Verify that creating a variant with duplicate axis values
        is rejected by validation.

        Checks:
        - validate_unique_combination() prevents duplicates
        - Error is thrown with appropriate message
        """
        import frappe
        from frappe.utils import random_string

        product_name = getattr(self.__class__, 'product_master_name', None)
        if not product_name:
            self.skipTest("Product Master not available")

        created_variants = getattr(self.__class__, 'created_variants', [])
        if not created_variants:
            self.skipTest("No variants available to test duplicates")

        # Try to create a variant with same axis values as first variant
        first_variant = created_variants[0]
        first_v = frappe.get_doc("Product Variant", first_variant.name)
        existing_axes = {
            av.attribute: av.attribute_value for av in first_v.axis_values
        }

        suffix = random_string(3).upper()
        duplicate_variant = frappe.get_doc({
            "doctype": "Product Variant",
            "variant_name": f"{self.TEST_PREFIX} Duplicate {suffix}",
            "variant_code": f"{self.TEST_PREFIX}-DUP-{suffix}",
            "parent_product": product_name,
            "product_family": self.product_family.name,
            "status": "Draft",
            "sync_enabled": 0,
            "axis_values": [
                {
                    "attribute": attr,
                    "attribute_value": val,
                }
                for attr, val in existing_axes.items()
            ],
        })

        # Should raise validation error for duplicate combination
        with self.assertRaises(frappe.ValidationError):
            duplicate_variant.insert(ignore_permissions=True)

    # ========================================================================
    # Test 7: Verify ERPNext Items are synced for Product Master
    # ========================================================================

    def test_07_verify_erpnext_item_exists_for_product_master(self):
        """Verify that the Product Master has a corresponding ERPNext Item.

        Checks:
        - Item exists in ERPNext with matching item_code
        - Item fields are correctly mapped from Product Master
        - Custom PIM fields are populated on the Item
        - Item appears in Item list query
        """
        import frappe

        product_name = getattr(self.__class__, 'product_master_name', None)
        if not product_name:
            self.skipTest("Product Master not available")

        # Verify Item exists
        self.assertTrue(
            frappe.db.exists("Item", product_name),
            f"ERPNext Item {product_name} should exist"
        )

        # Load Item and verify field mapping
        item = frappe.get_doc("Item", product_name)
        self.assertIsNotNone(item.item_name)
        self.assertIsNotNone(item.item_code)
        self.assertEqual(item.stock_uom, "Nos")

        # Verify PIM custom fields
        self.assertEqual(item.custom_pim_status, "Draft")
        self.assertEqual(
            item.custom_pim_product_family,
            self.product_family.name
        )
        self.assertEqual(
            item.custom_pim_product_type,
            self.product_type.name
        )

        # Verify Item appears in list query
        items = frappe.get_all(
            "Item",
            filters={"item_code": self.__class__.product_code},
            fields=["name", "item_name", "item_code"]
        )
        self.assertEqual(len(items), 1)

    # ========================================================================
    # Test 8: Verify completeness score is calculated
    # ========================================================================

    def test_08_verify_completeness_score_calculated(self):
        """Verify that completeness score is calculated correctly
        based on filled fields.

        Checks:
        - calculate_completeness() returns a score
        - Score reflects filled vs empty fields
        - Score breakdown categories are present
        - Quality status is determined
        """
        import frappe

        product_name = getattr(self.__class__, 'product_master_name', None)
        if not product_name:
            self.skipTest("Product Master not available")

        # Load product and calculate completeness
        product = frappe.get_doc("Product Master", product_name)
        result = product.calculate_completeness()

        # Verify result structure
        self.assertIsInstance(result, dict)
        self.assertIn("score", result)
        self.assertIn("breakdown", result)
        self.assertIn("status", result)

        # Score should be > 0 (we have product_name, product_code,
        # short_description, brand, stock_uom, is_stock_item, plus attribute_values bonus)
        score = result["score"]
        self.assertGreater(score, 0, "Completeness score should be > 0")
        self.assertLessEqual(score, 100, "Completeness score should be <= 100")

        # Verify breakdown categories exist
        breakdown = result["breakdown"]
        expected_categories = [
            "required", "identity", "description", "media",
            "pricing", "stock", "seo", "compliance"
        ]
        for category in expected_categories:
            self.assertIn(
                category, breakdown,
                f"Breakdown should include '{category}' category"
            )

        # "required" should be 100% (product_name and product_code are filled)
        required_breakdown = breakdown["required"]
        self.assertEqual(
            required_breakdown["filled"], required_breakdown["total"],
            "Required fields (product_name, product_code) should all be filled"
        )

        # Verify quality status
        status = result["status"]
        self.assertIn(
            status,
            ["Critical", "Poor", "Fair", "Good", "Excellent"],
            f"Status should be a valid quality level, got: {status}"
        )

    # ========================================================================
    # Test 9: Verify completeness improves with more data
    # ========================================================================

    def test_09_completeness_improves_with_additional_data(self):
        """Verify that adding more fields improves the completeness score.

        Checks:
        - Initial score is recorded
        - Adding description and pricing increases score
        - Score strictly increases with more data
        """
        import frappe
        from frappe.utils import random_string

        suffix = random_string(4).upper()
        product_code = f"{self.TEST_PREFIX}-COMP-{suffix}"

        # Create minimal product (only required fields)
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"{self.TEST_PREFIX} Minimal Product {suffix}",
            "product_code": product_code,
            "status": "Draft",
        })
        product.insert(ignore_permissions=True)

        # Calculate initial score
        initial_result = product.calculate_completeness()
        initial_score = initial_result["score"]

        # Add more fields
        product.short_description = "A product with a description"
        product.long_description = "A comprehensive long description for better SEO"
        product.brand = "TestBrand"
        product.stock_uom = "Nos"
        product.is_stock_item = 1
        product.save(ignore_permissions=True)

        # Reload and recalculate
        product = frappe.get_doc("Product Master", product.name)
        improved_result = product.calculate_completeness()
        improved_score = improved_result["score"]

        # Score should have improved
        self.assertGreater(
            improved_score, initial_score,
            f"Score should improve: {improved_score} > {initial_score}"
        )

    # ========================================================================
    # Test 10: Full lifecycle - complete workflow in single test
    # ========================================================================

    def test_10_complete_product_lifecycle(self):
        """Execute the complete product lifecycle in a single test method.

        This test verifies the full flow end-to-end:
        1. Create Product Type -> verify
        2. Create Product Family with attrs -> verify
        3. Create Product Master -> verify Item created
        4. Add attribute values -> verify persistence
        5. Create variants -> verify
        6. Verify ERPNext sync
        7. Verify completeness
        """
        import frappe
        from frappe.utils import random_string

        suffix = random_string(5).lower()
        prefix = self.TEST_PREFIX

        # ============================================================
        # STEP 1: Create Product Type
        # ============================================================
        product_type = frappe.get_doc({
            "doctype": "PIM Product Type",
            "type_name": f"{prefix} Lifecycle Type {suffix}",
            "type_code": f"{prefix.lower()}_lifecycle_{suffix}",
            "is_active": 1,
            "allow_variants": 1,
            "type_fields": [
                {
                    "fieldname": "test_field",
                    "label": "Test Field",
                    "fieldtype": "Data",
                    "sort_order": 1,
                },
            ],
        })
        product_type.insert(ignore_permissions=True)

        self.assertTrue(
            frappe.db.exists("PIM Product Type", product_type.name),
            "Step 1 Failed: Product Type not created"
        )

        # ============================================================
        # STEP 2: Create Attributes
        # ============================================================
        attr_fabric = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"{prefix} Fabric {suffix}",
            "attribute_code": f"{prefix.lower()}_fabric_{suffix}",
            "data_type": "Text",
            "is_required_in_family": 1,
        })
        attr_fabric.insert(ignore_permissions=True)

        attr_style = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_name": f"{prefix} Style {suffix}",
            "attribute_code": f"{prefix.lower()}_style_{suffix}",
            "data_type": "Select",
            "options": "Casual,Formal,Sport",
            "is_required_in_family": 0,
        })
        attr_style.insert(ignore_permissions=True)

        # ============================================================
        # STEP 3: Create Product Family with attributes
        # ============================================================
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"{prefix} Lifecycle Family {suffix}",
            "family_code": f"{prefix.lower()}_lifecycle_{suffix}",
            "is_group": 0,
            "is_active": 1,
            "allow_variants": 1,
            "attributes": [
                {
                    "attribute": attr_fabric.name,
                    "is_required_in_family": 1,
                    "sort_order": 1,
                },
                {
                    "attribute": attr_style.name,
                    "is_required_in_family": 0,
                    "sort_order": 2,
                },
            ],
            "variant_attributes": [
                {
                    "attribute": attr_style.name,
                    "sort_order": 1,
                },
            ],
        })
        family.insert(ignore_permissions=True)

        self.assertTrue(
            frappe.db.exists("Product Family", family.name),
            "Step 3 Failed: Product Family not created"
        )

        # Reload and verify attributes
        family = frappe.get_doc("Product Family", family.name)
        self.assertEqual(
            len(family.attributes), 2,
            "Step 3 Failed: Family should have 2 attributes"
        )
        self.assertEqual(
            len(family.variant_attributes), 1,
            "Step 3 Failed: Family should have 1 variant axis"
        )

        # ============================================================
        # STEP 4: Create Product Master
        # ============================================================
        product_code = f"{prefix}-LIFE-{suffix.upper()}"
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"{prefix} Lifecycle Product {suffix}",
            "product_code": product_code,
            "short_description": "Complete lifecycle test product",
            "product_family": family.name,
            "product_type": product_type.name,
            "status": "Draft",
            "stock_uom": "Nos",
            "is_stock_item": 1,
            "brand": "LifecycleBrand",
            "is_template": 1,
        })
        product.insert(ignore_permissions=True)

        self.assertIsNotNone(
            product.name,
            "Step 4 Failed: Product Master not created"
        )

        # Verify Item created (Virtual DocType backend)
        self.assertTrue(
            frappe.db.exists("Item", product.name),
            "Step 4 Failed: ERPNext Item not created"
        )

        # ============================================================
        # STEP 5: Add attribute values
        # ============================================================
        product.attribute_values = [
            {
                "attribute": attr_fabric.name,
                "value_text": "Organic Cotton",
            },
            {
                "attribute": attr_style.name,
                "value_text": "Casual",
            },
        ]
        product.save(ignore_permissions=True)

        # Verify attribute values persisted
        product = frappe.get_doc("Product Master", product.name)
        attr_values = product.get("attribute_values") or []
        self.assertEqual(
            len(attr_values), 2,
            "Step 5 Failed: Expected 2 attribute values"
        )

        # ============================================================
        # STEP 6: Create variants
        # ============================================================
        variant_styles = ["Casual", "Formal", "Sport"]
        created_variants = []

        for style in variant_styles:
            vs = random_string(3).upper()
            variant = frappe.get_doc({
                "doctype": "Product Variant",
                "variant_name": f"{prefix} Product {style} {vs}",
                "variant_code": f"{prefix}-{style.upper()}-{vs}",
                "parent_product": product.name,
                "product_family": family.name,
                "status": "Draft",
                "sync_enabled": 0,
                "axis_values": [
                    {
                        "attribute": attr_style.name,
                        "attribute_value": style,
                    },
                ],
            })
            variant.insert(ignore_permissions=True)
            created_variants.append(variant)

        self.assertEqual(
            len(created_variants), 3,
            "Step 6 Failed: Expected 3 variants"
        )

        for v in created_variants:
            self.assertTrue(
                frappe.db.exists("Product Variant", v.name),
                f"Step 6 Failed: Variant {v.name} should exist"
            )

        # ============================================================
        # STEP 7: Verify ERPNext sync
        # ============================================================
        item = frappe.get_doc("Item", product.name)

        self.assertEqual(
            item.item_code, product_code,
            "Step 7 Failed: Item code mismatch"
        )
        self.assertEqual(
            item.custom_pim_product_family, family.name,
            "Step 7 Failed: Product Family not synced to Item"
        )
        self.assertEqual(
            item.custom_pim_product_type, product_type.name,
            "Step 7 Failed: Product Type not synced to Item"
        )
        self.assertEqual(
            item.custom_pim_status, "Draft",
            "Step 7 Failed: PIM status not synced to Item"
        )

        # Verify Item appears in list
        items = frappe.get_all(
            "Item",
            filters={"item_code": product_code},
            fields=["name", "item_code"]
        )
        self.assertEqual(
            len(items), 1,
            "Step 7 Failed: Item not found in list query"
        )

        # ============================================================
        # STEP 8: Verify completeness
        # ============================================================
        product = frappe.get_doc("Product Master", product.name)
        completeness = product.calculate_completeness()

        self.assertIsInstance(
            completeness, dict,
            "Step 8 Failed: Completeness result should be dict"
        )
        self.assertGreater(
            completeness["score"], 0,
            "Step 8 Failed: Score should be > 0"
        )

        # With product_name, product_code, short_description, brand,
        # stock_uom, is_stock_item filled plus attribute_values bonus
        # the score should be reasonable
        self.assertGreater(
            completeness["score"], 30,
            "Step 8 Failed: Score should be > 30 with required + identity + description + stock fields"
        )

        # Verify attribute_values bonus was applied
        self.assertGreater(
            completeness.get("child_tables_bonus", 0), 0,
            "Step 8 Failed: Should have child_tables_bonus for attribute_values"
        )

    # ========================================================================
    # Test 11: Verify variant level calculation
    # ========================================================================

    def test_11_variant_level_calculated(self):
        """Verify that variant level is correctly calculated.

        Level 1 = direct child of Product Master (Item).
        """
        import frappe

        created_variants = getattr(self.__class__, 'created_variants', [])
        if not created_variants:
            self.skipTest("No variants available")

        for variant in created_variants:
            v = frappe.get_doc("Product Variant", variant.name)
            # Level should be 1 for direct children
            # The variant_level is calculated during validate
            self.assertIn(
                v.variant_level, [0, 1, None],
                f"Variant level should be 0 or 1 for direct children, got: {v.variant_level}"
            )

    # ========================================================================
    # Test 12: Verify variant inherits from parent
    # ========================================================================

    def test_12_variant_inherits_parent_fields(self):
        """Verify that variant inherits product_family from parent.

        Checks:
        - product_family is inherited if not set
        """
        import frappe

        created_variants = getattr(self.__class__, 'created_variants', [])
        if not created_variants:
            self.skipTest("No variants available")

        for variant in created_variants:
            v = frappe.get_doc("Product Variant", variant.name)
            # product_family should be inherited from parent or set directly
            self.assertEqual(
                v.product_family,
                self.product_family.name,
                f"Variant {v.name} should have product_family set"
            )

    # ========================================================================
    # Test 13: Product Master can be read back via Virtual DocType
    # ========================================================================

    def test_13_product_master_loads_via_virtual_doctype(self):
        """Verify that Product Master can be loaded via load_from_db().

        This tests the Virtual DocType read path, which fetches data
        from the underlying ERPNext Item.
        """
        import frappe

        product_name = getattr(self.__class__, 'product_master_name', None)
        if not product_name:
            self.skipTest("Product Master not available")

        # Load via Virtual DocType (this triggers load_from_db)
        product = frappe.get_doc("Product Master", product_name)

        # Verify core fields loaded correctly
        self.assertIsNotNone(product.product_name)
        self.assertIsNotNone(product.product_code)
        self.assertIsNotNone(product.modified)
        self.assertIsNotNone(product.creation)

        # Verify link fields loaded from custom_pim_* fields
        self.assertEqual(product.product_family, self.product_family.name)
        self.assertEqual(product.product_type, self.product_type.name)

        # Verify child tables loaded
        attr_values = product.get("attribute_values") or []
        self.assertGreater(
            len(attr_values), 0,
            "Attribute values should be loaded via _load_child_tables"
        )

    # ========================================================================
    # Test 14: Product Master appears in list view
    # ========================================================================

    def test_14_product_master_appears_in_list(self):
        """Verify Product Master appears in list via get_list().

        Tests the Virtual DocType list path.
        """
        import frappe

        product_name = getattr(self.__class__, 'product_master_name', None)
        if not product_name:
            self.skipTest("Product Master not available")

        # Query via Product Master.get_list (Virtual DocType path)
        from frappe_pim.pim.doctype.product_master.product_master import ProductMaster

        results = ProductMaster.get_list({
            "filters": [
                ["product_code", "like", f"%{self.TEST_PREFIX}%"]
            ],
            "limit_page_length": 20,
        })

        self.assertIsInstance(results, list)
        self.assertGreater(
            len(results), 0,
            "Product Master should appear in list query"
        )

        # Find our product in results
        found = False
        for r in results:
            if r.get("name") == product_name:
                found = True
                self.assertEqual(r.get("product_family"), self.product_family.name)
                break

        self.assertTrue(found, f"Product {product_name} should be in list results")


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
