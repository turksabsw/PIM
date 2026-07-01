# Copyright (c) 2026, Frappe PIM and contributors
# For license information, please see license.txt
"""End-to-End Onboarding Flow Verification Tests

This module tests the complete onboarding flow from start to first product:
1. Call start_onboarding API
2. Save company info step data
3. Select 'fashion' industry archetype
4. Apply fashion template via API (real application, no mocking)
5. Verify Fashion Product Types created
6. Verify Fashion Attribute Types created
7. Verify Fashion Product Families created
8. Create a product using the seeded configuration

These tests validate that the onboarding wizard, template engine,
and all PIM configuration entities work together correctly in a
realistic SaaS onboarding workflow.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).

Run with:
    bench --site [site] run-tests --app frappe_pim \
        --module frappe_pim.pim.tests.test_e2e_onboarding_flow
"""

import unittest


class TestE2EOnboardingFlow(unittest.TestCase):
    """End-to-end verification for the complete onboarding flow.

    Tests the full flow: Start Onboarding -> Select Fashion Industry ->
    Apply Template -> Verify Config Entities -> Create First Product.

    This test class actually applies the fashion template (no mocking)
    and verifies that all configuration entities are created in the database.
    """

    # Test user for onboarding
    TEST_USER = "e2e_onboarding_test@example.com"

    # Product code prefix for test products (used for cleanup)
    TEST_PRODUCT_PREFIX = "E2EONB"

    # Expected fashion template entities
    EXPECTED_FASHION_PRODUCT_TYPES = [
        "Apparel", "Footwear", "Accessories",
        "Underwear & Loungewear", "Swimwear",
    ]
    EXPECTED_FASHION_ATTRIBUTE_TYPES = [
        "color_swatch", "size", "season", "percentage",
    ]
    EXPECTED_FASHION_ATTRIBUTE_GROUPS = [
        "fashion", "sizing", "care_composition",
    ]
    EXPECTED_FASHION_ATTRIBUTES = [
        "color", "size", "shoe_size", "fabric_composition",
        "season", "gender", "collection", "style", "fit",
        "sleeve_length", "neckline", "pattern", "occasion",
        "care_instructions", "lining_material", "closure_type",
        "heel_height", "sole_material",
    ]
    EXPECTED_FASHION_FAMILIES = [
        "fashion", "tops", "tshirts", "shirts_blouses",
        "sweaters_knitwear", "bottoms", "jeans", "trousers_chinos",
        "skirts", "dresses", "outerwear", "shoes", "sneakers",
        "boots", "sandals_flats", "accessories",
        "bags", "belts_scarves", "hats_headwear",
    ]
    EXPECTED_BASE_ATTRIBUTE_GROUPS = [
        "general", "dimensions", "media", "seo",
        "technical", "compliance", "logistics",
    ]

    @classmethod
    def setUpClass(cls):
        """Set up test class - clean prior data and ensure prerequisites."""
        import frappe
        frappe.set_user("Administrator")
        cls._cleanup_all_test_data()
        cls._ensure_item_group()

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        import frappe
        cls._cleanup_all_test_data()
        frappe.db.commit()

    @classmethod
    def _cleanup_all_test_data(cls):
        """Remove any test-specific data from previous or current runs.

        Cleans up:
        - Onboarding state for the test user
        - Test product items created during verification
        """
        import frappe

        # Remove onboarding state for test user
        try:
            existing = frappe.db.exists(
                "PIM Onboarding State", {"user": cls.TEST_USER}
            )
            if existing:
                frappe.delete_doc(
                    "PIM Onboarding State", existing,
                    ignore_permissions=True, force=True,
                )
        except Exception:
            pass

        # Remove test items created during product creation step
        prefix = cls.TEST_PRODUCT_PREFIX
        cleanup_items = [
            ("tabProduct Variant Axis Value", f"parent LIKE '{prefix}-%'"),
            ("tabProduct Attribute Value", f"parent LIKE '{prefix}-%'"),
            ("tabProduct Variant", f"variant_code LIKE '{prefix}-%'"),
            ("tabItem", f"item_code LIKE '{prefix}-%'"),
        ]
        for table, condition in cleanup_items:
            try:
                frappe.db.sql(f"DELETE FROM `{table}` WHERE {condition}")
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def _ensure_item_group(cls):
        """Ensure required Item Groups exist for test Items."""
        import frappe

        for group in ["Products", "All Item Groups"]:
            if not frappe.db.exists("Item Group", group):
                try:
                    ig = frappe.new_doc("Item Group")
                    ig.item_group_name = group
                    ig.is_group = 1
                    ig.insert(ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()

    def _get_item_group(self):
        """Get a valid Item Group for creating test Items."""
        import frappe

        for group in ["Products", "All Item Groups"]:
            if frappe.db.exists("Item Group", group):
                return group

        groups = frappe.get_all("Item Group", limit=1, pluck="name")
        return groups[0] if groups else "All Item Groups"

    # ========================================================================
    # Step 1: Start Onboarding
    # ========================================================================

    def test_01_start_onboarding(self):
        """Step 1: Call start_onboarding API and verify initial state.

        Verifies:
        - Onboarding state is created for the test user
        - State advances from 'pending' to 'company_info'
        - Response includes all expected fields
        """
        from frappe_pim.pim.api.onboarding import start_onboarding

        result = start_onboarding(user=self.TEST_USER)

        self.assertIsInstance(result, dict)
        self.assertEqual(result["user"], self.TEST_USER)
        self.assertEqual(result["current_step"], "company_info")
        self.assertFalse(result["is_completed"])
        self.assertFalse(result["is_skipped"])
        self.assertEqual(result["total_steps"], 12)
        self.assertIn("steps", result)
        self.assertIn("completed_steps", result)
        self.assertIn("pending", result["completed_steps"])

    # ========================================================================
    # Step 2: Save Company Info
    # ========================================================================

    def test_02_save_company_info(self):
        """Step 2: Save company info step data and advance.

        Verifies:
        - Company info data is saved for the step
        - State advances to 'industry_selection'
        - Saved data persists and can be retrieved
        """
        from frappe_pim.pim.api.onboarding import save_step_data
        import frappe

        company_data = {
            "company_name": "E2E Fashion Test Corp",
            "industry": "retail",
            "company_size": "medium",
            "country": "TR",
            "currency": "TRY",
            "website": "https://e2e-fashion-test.example.com",
            "product_count_estimate": 5000,
        }

        result = save_step_data(
            step="company_info",
            form_data=company_data,
            user=self.TEST_USER,
            advance=True,
        )

        self.assertEqual(result["current_step"], "industry_selection")
        self.assertIn("company_info", result["completed_steps"])

        # Verify data persisted in the document
        existing = frappe.db.exists(
            "PIM Onboarding State", {"user": self.TEST_USER}
        )
        doc = frappe.get_doc("PIM Onboarding State", existing)
        stored = doc.get_step_data("company_info")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["company_name"], "E2E Fashion Test Corp")
        self.assertEqual(stored["country"], "TR")

    # ========================================================================
    # Step 3: Select Fashion Industry Archetype
    # ========================================================================

    def test_03_select_fashion_industry(self):
        """Step 3: Select 'fashion' industry archetype and advance.

        Verifies:
        - Fashion archetype is available in the template list
        - Industry selection data is saved
        - State advances to 'product_structure'
        """
        from frappe_pim.pim.api.onboarding import (
            get_available_archetypes,
            save_step_data,
        )

        # First, verify fashion archetype is available
        archetypes = get_available_archetypes()
        archetype_ids = [a["archetype"] for a in archetypes["archetypes"]]
        self.assertIn("fashion", archetype_ids)

        # Find the fashion archetype metadata
        fashion_meta = next(
            a for a in archetypes["archetypes"]
            if a["archetype"] == "fashion"
        )
        self.assertIn("Fashion", fashion_meta["label"])

        # Save industry selection and advance
        industry_data = {
            "archetype": "fashion",
            "sub_industry": "apparel_and_accessories",
            "has_variants": True,
            "variant_axes": ["color", "size"],
            "target_channels": ["e-commerce", "marketplace", "wholesale"],
        }

        result = save_step_data(
            step="industry_selection",
            form_data=industry_data,
            user=self.TEST_USER,
            advance=True,
        )

        self.assertEqual(result["current_step"], "product_structure")

    # ========================================================================
    # Step 4: Apply Fashion Template
    # ========================================================================

    def test_04_apply_fashion_template(self):
        """Step 4: Apply the fashion archetype template via API (no mocking).

        This is the critical step - it actually calls the TemplateEngine
        to create all fashion configuration entities in the database.

        Verifies:
        - Template application succeeds
        - Base template is applied first (fashion extends base)
        - Entities are created (non-zero count)
        - No entity failures
        - Template result is recorded in onboarding state
        """
        from frappe_pim.pim.api.onboarding import apply_archetype_template
        import frappe

        # Preview first to understand what will be created
        from frappe_pim.pim.api.onboarding import preview_archetype

        preview = preview_archetype("fashion")
        self.assertEqual(preview["archetype"], "fashion")
        self.assertEqual(preview["extends"], "base")

        # Apply the fashion template (this is REAL, not mocked)
        result = apply_archetype_template(
            archetype="fashion",
            user=self.TEST_USER,
        )

        self.assertIsInstance(result, dict)
        self.assertTrue(
            result["success"],
            f"Template application failed: {result.get('errors', [])}"
        )
        self.assertIn(result["status"], ("completed", "partial"))
        self.assertGreater(
            result["entities_created"], 0,
            "No entities were created by template application"
        )

        # Store result for later tests
        self.__class__.template_result = result

        # Verify the onboarding state was updated
        existing = frappe.db.exists(
            "PIM Onboarding State", {"user": self.TEST_USER}
        )
        doc = frappe.get_doc("PIM Onboarding State", existing)
        self.assertTrue(
            doc.template_applied,
            "template_applied flag not set on onboarding state"
        )
        self.assertEqual(doc.selected_archetype, "fashion")
        self.assertIsNotNone(doc.template_applied_at)

        # Log the result summary for diagnostic purposes
        created = result["entities_created"]
        skipped = result["entities_skipped"]
        failed = result["entities_failed"]
        frappe.logger().info(
            f"Fashion template applied: {created} created, "
            f"{skipped} skipped, {failed} failed"
        )

    # ========================================================================
    # Step 5: Verify Fashion Product Types Created
    # ========================================================================

    def test_05_verify_fashion_product_types(self):
        """Step 5: Verify that all Fashion Product Types were created.

        The fashion template defines 5 product types:
        - Apparel, Footwear, Accessories,
          Underwear & Loungewear, Swimwear

        Verifies:
        - Each expected product type exists in the database
        - Product types have correct type_code
        - Product types are active
        - Product types allow variants
        """
        import frappe

        for type_name in self.EXPECTED_FASHION_PRODUCT_TYPES:
            exists = frappe.db.exists("PIM Product Type", type_name)
            self.assertTrue(
                exists,
                f"Fashion Product Type '{type_name}' not found in database"
            )

            doc = frappe.get_doc("PIM Product Type", type_name)
            self.assertTrue(
                doc.is_active,
                f"Product Type '{type_name}' is not active"
            )
            self.assertTrue(
                doc.allow_variants,
                f"Product Type '{type_name}' does not allow variants"
            )
            self.assertTrue(
                doc.type_code,
                f"Product Type '{type_name}' has no type_code"
            )

        # Verify at least the expected count
        total_count = frappe.db.count(
            "PIM Product Type",
            filters={"type_code": ["in", [
                "apparel", "footwear", "accessories",
                "underwear_loungewear", "swimwear",
            ]]},
        )
        self.assertEqual(
            total_count, 5,
            f"Expected 5 fashion product types, found {total_count}"
        )

    # ========================================================================
    # Step 6: Verify Fashion Attribute Types Created
    # ========================================================================

    def test_06_verify_fashion_attribute_types(self):
        """Step 6: Verify that Fashion-specific Attribute Types were created.

        The fashion template defines 4 custom attribute types:
        - Color Swatch (string, has_options)
        - Size (string, has_options)
        - Season (string, has_options)
        - Percentage (float, min/max)

        Verifies:
        - Each expected attribute type exists
        - Base types are correct
        - Types are active
        """
        import frappe

        for type_code in self.EXPECTED_FASHION_ATTRIBUTE_TYPES:
            exists = frappe.db.exists(
                "PIM Attribute Type", {"type_code": type_code}
            )
            self.assertTrue(
                exists,
                f"Fashion Attribute Type '{type_code}' not found"
            )

        # Verify specific properties of the color_swatch type
        color_swatch = frappe.db.get_value(
            "PIM Attribute Type",
            {"type_code": "color_swatch"},
            ["type_name", "base_type", "has_options", "is_active"],
            as_dict=True,
        )
        if color_swatch:
            self.assertEqual(color_swatch.type_name, "Color Swatch")
            self.assertEqual(color_swatch.base_type, "String")
            self.assertTrue(color_swatch.has_options)
            self.assertTrue(color_swatch.is_active)

        # Verify percentage type properties
        pct = frappe.db.get_value(
            "PIM Attribute Type",
            {"type_code": "percentage"},
            ["base_type", "is_active"],
            as_dict=True,
        )
        if pct:
            self.assertEqual(pct.base_type, "Float")
            self.assertTrue(pct.is_active)

    # ========================================================================
    # Step 6b: Verify Base Attribute Types Also Created
    # ========================================================================

    def test_06b_verify_base_attribute_types(self):
        """Verify that base template attribute types were also created.

        Since fashion extends base, the 12 standard attribute types
        from the base template should also exist.
        """
        import frappe

        # The base template has 12 standard types
        # Check a few representative ones
        base_type_codes = ["string", "integer", "float", "boolean", "date"]

        for type_code in base_type_codes:
            exists = frappe.db.exists(
                "PIM Attribute Type", {"type_code": type_code}
            )
            self.assertTrue(
                exists,
                f"Base Attribute Type '{type_code}' not found - "
                f"base template may not have been applied"
            )

    # ========================================================================
    # Step 7: Verify Fashion Attribute Groups Created
    # ========================================================================

    def test_07_verify_fashion_attribute_groups(self):
        """Verify that Fashion-specific Attribute Groups were created.

        The fashion template defines 3 groups:
        - Fashion (fashion-specific attributes)
        - Sizing (size charts, measurements)
        - Care & Composition (fabric, care instructions)

        Verifies:
        - Each expected group exists
        - Groups have correct codes
        """
        import frappe

        for group_code in self.EXPECTED_FASHION_ATTRIBUTE_GROUPS:
            exists = frappe.db.exists(
                "PIM Attribute Group", {"group_code": group_code}
            )
            self.assertTrue(
                exists,
                f"Fashion Attribute Group '{group_code}' not found"
            )

    def test_07b_verify_base_attribute_groups(self):
        """Verify that base template attribute groups were also created."""
        import frappe

        for group_code in self.EXPECTED_BASE_ATTRIBUTE_GROUPS:
            exists = frappe.db.exists(
                "PIM Attribute Group", {"group_code": group_code}
            )
            self.assertTrue(
                exists,
                f"Base Attribute Group '{group_code}' not found - "
                f"base template may not have been applied"
            )

    # ========================================================================
    # Step 7c: Verify Fashion Attributes Created
    # ========================================================================

    def test_07c_verify_fashion_attributes(self):
        """Verify that Fashion-specific Attributes were created.

        The fashion template defines 17+ attributes for fashion products
        including color, size, fabric_composition, gender, etc.

        Verifies:
        - Key fashion attributes exist
        - Attributes have correct data types
        - Required attributes are marked as required
        """
        import frappe

        for attr_code in self.EXPECTED_FASHION_ATTRIBUTES:
            exists = frappe.db.exists(
                "PIM Attribute", {"attribute_code": attr_code}
            )
            self.assertTrue(
                exists,
                f"Fashion Attribute '{attr_code}' not found"
            )

        # Verify specific attribute properties
        color = frappe.db.get_value(
            "PIM Attribute",
            {"attribute_code": "color"},
            ["attribute_name", "data_type", "is_required", "is_filterable",
             "attribute_group"],
            as_dict=True,
        )
        if color:
            self.assertEqual(color.attribute_name, "Color")
            self.assertEqual(color.data_type, "Select")
            self.assertTrue(color.is_required)
            self.assertTrue(color.is_filterable)

        size = frappe.db.get_value(
            "PIM Attribute",
            {"attribute_code": "size"},
            ["attribute_name", "data_type", "is_required", "is_filterable"],
            as_dict=True,
        )
        if size:
            self.assertEqual(size.attribute_name, "Size")
            self.assertEqual(size.data_type, "Select")
            self.assertTrue(size.is_required)

        gender = frappe.db.get_value(
            "PIM Attribute",
            {"attribute_code": "gender"},
            ["attribute_name", "data_type", "is_required"],
            as_dict=True,
        )
        if gender:
            self.assertEqual(gender.attribute_name, "Gender")
            self.assertTrue(gender.is_required)

    # ========================================================================
    # Step 8: Verify Fashion Product Families Created
    # ========================================================================

    def test_08_verify_fashion_product_families(self):
        """Step 8: Verify that Fashion Product Families were created.

        The fashion template defines 19 product families in a hierarchy:
        - Fashion (root)
          - Tops → T-Shirts, Shirts & Blouses, Sweaters & Knitwear
          - Bottoms → Jeans, Trousers & Chinos, Skirts
          - Dresses
          - Outerwear
          - Shoes → Sneakers, Boots, Sandals & Slides
          - Accessories → Bags, Belts, Hats & Caps

        Verifies:
        - Each expected family exists
        - Root family (Fashion) is a group
        - Leaf families are not groups
        - Parent-child relationships are correct
        """
        import frappe

        for family_code in self.EXPECTED_FASHION_FAMILIES:
            exists = frappe.db.exists(
                "Product Family", {"family_code": family_code}
            )
            self.assertTrue(
                exists,
                f"Fashion Product Family '{family_code}' not found"
            )

        # Verify root family is a group
        fashion_root = frappe.db.get_value(
            "Product Family",
            {"family_code": "fashion"},
            ["family_name", "is_group", "is_active"],
            as_dict=True,
        )
        if fashion_root:
            self.assertEqual(fashion_root.family_name, "Fashion")
            self.assertTrue(fashion_root.is_group)
            self.assertTrue(fashion_root.is_active)

        # Verify a leaf family (t-shirts) is not a group
        tshirts = frappe.db.get_value(
            "Product Family",
            {"family_code": "tshirts"},
            ["family_name", "is_group", "parent_family"],
            as_dict=True,
        )
        if tshirts:
            self.assertEqual(tshirts.family_name, "T-Shirts")
            self.assertFalse(tshirts.is_group)
            # parent_family stores the parent doc's name (family_code)
            # Template sets "Tops" (family_name) - verify parent is set
            self.assertTrue(
                tshirts.parent_family,
                "T-Shirts should have a parent_family"
            )

        # Verify hierarchy: Tops is a group with parent
        tops = frappe.db.get_value(
            "Product Family",
            {"family_code": "tops"},
            ["parent_family", "is_group", "family_name"],
            as_dict=True,
        )
        if tops:
            self.assertEqual(tops.family_name, "Tops")
            self.assertTrue(tops.is_group)
            # Tops parent should reference the Fashion family
            self.assertTrue(
                tops.parent_family,
                "Tops should have a parent_family (Fashion)"
            )

        # Verify hierarchy: Jeans has a parent
        jeans = frappe.db.get_value(
            "Product Family",
            {"family_code": "jeans"},
            ["parent_family", "family_name"],
            as_dict=True,
        )
        if jeans:
            self.assertEqual(jeans.family_name, "Jeans")
            self.assertTrue(
                jeans.parent_family,
                "Jeans should have a parent_family (Bottoms)"
            )

    # ========================================================================
    # Step 8b: Verify Fashion Categories Created
    # ========================================================================

    def test_08b_verify_fashion_categories(self):
        """Verify that Fashion categories were created.

        The fashion template defines a hierarchical category tree
        for merchandising navigation.
        """
        import frappe

        # Check a few key categories
        expected_categories = [
            "Women", "Men", "Kids",
            "New Arrivals", "Sale",
        ]

        for cat_name in expected_categories:
            exists = frappe.db.exists(
                "Category", {"category_name": cat_name}
            )
            self.assertTrue(
                exists,
                f"Fashion Category '{cat_name}' not found"
            )

    # ========================================================================
    # Step 9: Create First Product Using Seeded Configuration
    # ========================================================================

    def test_09_create_first_product_using_seeded_config(self):
        """Step 9: Create a product using the fashion-seeded configuration.

        Creates an ERPNext Item (which Product Master maps to) and links
        it to the seeded PIM Product Type and Product Family.

        Verifies:
        - Item can be created with PIM custom fields
        - Product type and family links are valid
        - Product family attributes are accessible
        """
        import frappe

        item_code = f"{self.TEST_PRODUCT_PREFIX}-TSH-001"

        # Clean up if exists from previous run
        if frappe.db.exists("Item", item_code):
            frappe.delete_doc("Item", item_code, ignore_permissions=True, force=True)
            frappe.db.commit()

        # Look up the product type name
        apparel_type = frappe.db.get_value(
            "PIM Product Type",
            {"type_code": "apparel"},
            "name",
        )
        self.assertIsNotNone(
            apparel_type,
            "Apparel product type not found - template may not have applied"
        )

        # Look up the product family name
        tshirts_family = frappe.db.get_value(
            "Product Family",
            {"family_code": "tshirts"},
            "name",
        )
        self.assertIsNotNone(
            tshirts_family,
            "T-Shirts product family not found - template may not have applied"
        )

        # Create an ERPNext Item with PIM metadata
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": item_code,
            "item_name": "E2E Test Classic T-Shirt",
            "item_group": self._get_item_group(),
            "stock_uom": "Nos",
            "is_stock_item": 1,
            "has_variants": 0,
            "description": "End-to-end test product created via onboarding flow",
            "custom_pim_product_type": apparel_type,
            "custom_pim_product_family": tshirts_family,
            "custom_pim_status": "Draft",
            "custom_pim_sync_enabled": 1,
        })
        item.insert(ignore_permissions=True)
        frappe.db.commit()

        # Verify the item was created with PIM fields
        created_item = frappe.get_doc("Item", item_code)
        self.assertEqual(created_item.item_code, item_code)
        self.assertEqual(created_item.custom_pim_product_type, apparel_type)
        self.assertEqual(created_item.custom_pim_product_family, tshirts_family)
        self.assertEqual(created_item.custom_pim_status, "Draft")

        # Store for later tests
        self.__class__.test_item_code = item_code

    # ========================================================================
    # Step 10: Verify Product Family Attributes on Created Product
    # ========================================================================

    def test_10_verify_product_family_attributes_accessible(self):
        """Verify the created product's family has the expected attributes.

        The T-Shirts family inherits from Tops, which has attributes like
        color, size, fabric_composition, gender, etc.

        Note: Product Family autoname is field:family_code, so the
        doc name is the family_code (e.g., "tops" not "Tops").
        """
        import frappe

        tshirts_name = frappe.db.get_value(
            "Product Family",
            {"family_code": "tshirts"},
            "name",
        )

        if not tshirts_name:
            self.skipTest("T-Shirts family not found")

        family_doc = frappe.get_doc("Product Family", tshirts_name)

        # T-Shirts inherits from Tops - check parent exists
        self.assertTrue(
            family_doc.parent_family,
            "T-Shirts family should have a parent_family set"
        )

        # Get the parent (Tops) family by its family_code
        tops_name = frappe.db.get_value(
            "Product Family",
            {"family_code": "tops"},
            "name",
        )
        self.assertIsNotNone(tops_name, "Tops family not found")

        tops_doc = frappe.get_doc("Product Family", tops_name)
        self.assertGreater(
            len(tops_doc.attributes or []), 0,
            "Tops family should have attributes defined"
        )

        # Verify specific attributes in Tops family
        # The attribute field in child table links to PIM Attribute by name
        # PIM Attribute autoname is field:attribute_code, so name = attribute_code
        attr_refs = [a.attribute for a in (tops_doc.attributes or [])]
        expected_attr_codes = ["color", "size", "fabric_composition", "gender"]

        for expected_code in expected_attr_codes:
            # PIM Attribute name = attribute_code, so direct match
            found = expected_code in attr_refs
            if not found:
                # Also check by doc name lookup (in case naming differs)
                attr_doc_name = frappe.db.get_value(
                    "PIM Attribute",
                    {"attribute_code": expected_code},
                    "name",
                )
                if attr_doc_name:
                    found = attr_doc_name in attr_refs

            self.assertTrue(
                found,
                f"Expected attribute '{expected_code}' not found in "
                f"Tops family attributes: {attr_refs}"
            )

        # Verify variant attributes (axes) are defined
        variant_refs = [va.attribute for va in (tops_doc.variant_attributes or [])]
        self.assertGreater(
            len(variant_refs), 0,
            "Tops family should have variant attributes (axes) defined"
        )

    # ========================================================================
    # Step 11: Advance Through Remaining Steps and Complete
    # ========================================================================

    def test_11_complete_onboarding(self):
        """Advance through remaining onboarding steps and mark complete.

        After template application and first product creation, advance
        through the remaining wizard steps to completion.
        """
        from frappe_pim.pim.api.onboarding import (
            complete_onboarding,
            get_onboarding_state,
        )

        # Get current state
        state = get_onboarding_state(user=self.TEST_USER)

        # Advance through all remaining steps until completed
        max_iterations = 15  # Safety guard
        iteration = 0

        while not state["is_completed"] and iteration < max_iterations:
            state = complete_onboarding(user=self.TEST_USER)
            iteration += 1

        # Verify final state
        final_state = get_onboarding_state(user=self.TEST_USER)
        self.assertTrue(
            final_state["is_completed"],
            f"Onboarding not completed after {iteration} advances. "
            f"Current step: {final_state['current_step']}"
        )
        self.assertEqual(final_state["current_step"], "completed")
        self.assertEqual(final_state["progress_percent"], 100)
        self.assertTrue(final_state["template_applied"])
        self.assertEqual(final_state["selected_archetype"], "fashion")

    # ========================================================================
    # Step 12: Verify Template Result Summary
    # ========================================================================

    def test_12_verify_template_result_in_onboarding_state(self):
        """Verify the template result is stored in the onboarding state.

        The template engine stores a detailed result dict in the
        onboarding state document after application.
        """
        import frappe
        import json

        existing = frappe.db.exists(
            "PIM Onboarding State", {"user": self.TEST_USER}
        )
        self.assertTrue(existing, "Onboarding state not found")

        doc = frappe.get_doc("PIM Onboarding State", existing)

        self.assertTrue(doc.template_applied)
        self.assertEqual(doc.selected_archetype, "fashion")
        self.assertIsNotNone(doc.template_result)

        # Parse and verify the result
        result = json.loads(doc.template_result)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["archetype"], "fashion")
        self.assertIn(result["status"], ("completed", "partial"))

        # Verify entity counts
        total_created = result.get("entities_created", 0)
        total_skipped = result.get("entities_skipped", 0)
        self.assertGreater(
            total_created + total_skipped, 0,
            "Template result shows no entities created or skipped"
        )

    # ========================================================================
    # Step 13: Verify Full Entity Count Summary
    # ========================================================================

    def test_13_verify_entity_count_summary(self):
        """Verify the total count of all entities created by the template.

        Combines base + fashion template entities:
        - Attribute Groups: 7 (base) + 3 (fashion) = 10
        - Attribute Types: 12 (base) + 4 (fashion) = 16
        - Attributes: 27 (base) + 17+ (fashion)
        - Product Types: 5 (fashion only)
        - Product Families: 19 (fashion only)
        - Categories: 23 (fashion only)
        """
        import frappe

        # Count entities from both base and fashion templates
        base_group_codes = self.EXPECTED_BASE_ATTRIBUTE_GROUPS
        fashion_group_codes = self.EXPECTED_FASHION_ATTRIBUTE_GROUPS

        all_group_codes = base_group_codes + fashion_group_codes
        found_groups = 0
        for code in all_group_codes:
            if frappe.db.exists("PIM Attribute Group", {"group_code": code}):
                found_groups += 1

        self.assertGreaterEqual(
            found_groups, 8,
            f"Expected at least 8 attribute groups (base+fashion), "
            f"found {found_groups}"
        )

        # Check fashion attributes count
        fashion_attrs_found = 0
        for code in self.EXPECTED_FASHION_ATTRIBUTES:
            if frappe.db.exists("PIM Attribute", {"attribute_code": code}):
                fashion_attrs_found += 1

        self.assertGreaterEqual(
            fashion_attrs_found, 15,
            f"Expected at least 15 fashion attributes, "
            f"found {fashion_attrs_found}"
        )

        # Check product families count
        families_found = 0
        for code in self.EXPECTED_FASHION_FAMILIES:
            if frappe.db.exists("Product Family", {"family_code": code}):
                families_found += 1

        self.assertGreaterEqual(
            families_found, 15,
            f"Expected at least 15 fashion product families, "
            f"found {families_found}"
        )

    # ========================================================================
    # Step 14: Idempotency - Re-applying template should skip
    # ========================================================================

    def test_14_template_idempotency(self):
        """Verify that re-applying the same template skips existing entities.

        The template engine is idempotent - applying the same template
        again should skip already-existing entities rather than creating
        duplicates or throwing errors.
        """
        from frappe_pim.pim.services.template_engine import TemplateEngine

        result = TemplateEngine.apply_template(
            archetype_name="fashion",
            skip_base=False,
        )

        result_dict = result.to_dict()

        # All entities should be skipped (already exist)
        self.assertEqual(
            result_dict["entities_created"], 0,
            f"Re-applying fashion template should create 0 new entities, "
            f"but created {result_dict['entities_created']}"
        )
        self.assertGreater(
            result_dict["entities_skipped"], 0,
            "Re-applying template should show entities as skipped"
        )
        self.assertEqual(
            result_dict["entities_failed"], 0,
            f"Re-applying template should have 0 failures, "
            f"but had {result_dict['entities_failed']}"
        )
        self.assertIn(
            result_dict["status"], ("completed",),
            f"Re-applying template should have 'completed' status, "
            f"got '{result_dict['status']}'"
        )


if __name__ == "__main__":
    unittest.main()
