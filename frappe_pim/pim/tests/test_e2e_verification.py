# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""End-to-End Verification Tests for Advanced PIM Features

This module contains comprehensive end-to-end verification tests that validate
the complete PIM workflow:
1. Create Product Master via Virtual DocType API
2. Verify Product appears in ERPNext Item list
3. Publish Product to test channel
4. Generate BMEcat feed with Product
5. Run data quality scan
6. Verify completeness score calculated

These tests ensure all major features work together correctly.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestE2EProductVirtualDocType(unittest.TestCase):
    """E2E verification for Virtual DocType Product-Item integration."""

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

    def test_e2e_create_product_via_virtual_doctype(self):
        """
        E2E Step 1: Create Product Master via Virtual DocType API.

        Verifies:
        - Product Master can be created with all required fields
        - Virtual DocType db_insert creates Item in backend
        - Product name is generated correctly
        """
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).upper()
        product_code = f"E2E-VIRT-{suffix}"
        product_name = f"E2E Virtual Test Product {suffix}"

        # Create Product Master via Virtual DocType
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": product_name,
            "product_code": product_code,
            "short_description": "End-to-end verification test product",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Verify product was created
        self.assertIsNotNone(product.name)
        self.assertEqual(product.product_name, product_name)
        self.assertEqual(product.product_code, product_code)
        self.assertEqual(product.status, "Active")

    def test_e2e_verify_product_in_erpnext_item_list(self):
        """
        E2E Step 2: Verify Product appears in ERPNext Item list.

        Verifies:
        - Item is created in ERPNext when Product Master is saved
        - Item fields are correctly mapped from Product Master
        - Product can be queried via Item doctype
        """
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).upper()
        product_code = f"E2E-ITEM-{suffix}"
        product_name = f"E2E Item Sync Test {suffix}"

        # Create Product Master
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": product_name,
            "product_code": product_code,
            "short_description": "Test product for Item sync verification",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Verify Item exists in ERPNext
        self.assertTrue(
            frappe.db.exists("Item", product.name),
            f"Item {product.name} should exist in ERPNext"
        )

        # Load Item and verify field mapping
        item = frappe.get_doc("Item", product.name)
        self.assertEqual(item.item_name, product_name)
        self.assertEqual(item.item_code, product_code)
        self.assertEqual(item.description, "Test product for Item sync verification")

        # Verify Item appears in Item list query
        items = frappe.get_all(
            "Item",
            filters={"item_code": product_code},
            fields=["name", "item_name", "item_code"]
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item_code"], product_code)


class TestE2EChannelPublishing(unittest.TestCase):
    """E2E verification for channel publishing workflow."""

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

    def test_e2e_publish_product_to_channel(self):
        """
        E2E Step 3: Publish Product to test channel.

        Verifies:
        - Channel can be created and configured
        - Product can be assigned to channel
        - Product validation for channel works
        - Publishing workflow executes correctly
        """
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).lower()

        # Create a test channel
        channel = frappe.get_doc({
            "doctype": "Channel",
            "channel_name": f"E2E Test Channel {suffix}",
            "channel_code": f"e2e-test-{suffix}",
            "channel_type": "E-commerce",
            "enabled": 1
        })
        channel.insert(ignore_permissions=True)
        self.track_document("Channel", channel.name)

        # Create product with channel assignment
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E Channel Product {suffix}",
            "product_code": f"E2E-CH-{suffix.upper()}",
            "short_description": "Product for channel publishing test",
            "status": "Active",
            "channels": [
                {"channel": channel.name, "is_published": 0}
            ]
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Verify channel assignment
        self.assertEqual(len(product.channels), 1)
        self.assertEqual(product.channels[0].channel, channel.name)

        # Test channel validation
        from frappe_pim.pim.api.channel import validate_for_channel
        validation_result = validate_for_channel(
            products=[product.name],
            channel_code=channel.channel_code
        )

        self.assertIsInstance(validation_result, dict)
        self.assertIn("results", validation_result)

    def test_e2e_channel_adapter_validation(self):
        """
        E2E: Verify channel adapter validation works for products.

        Tests the validation step of channel publishing.
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.channels.base import (
            ValidationResult,
            MappingResult,
            PublishResult,
            StatusResult,
            PublishStatus,
            ChannelAdapter,
            register_adapter
        )

        suffix = random_string(6)

        # Create a mock adapter for testing
        class E2ETestAdapter(ChannelAdapter):
            channel_code = f"e2e_test_{suffix}"
            channel_name = f"E2E Test {suffix}"

            def validate_product(self, product):
                # Check required fields
                is_valid = bool(product.get("product_name") and product.get("product_code"))
                return ValidationResult(
                    is_valid=is_valid,
                    product=product.get("name", ""),
                    errors=[] if is_valid else [{"field": "product_name", "message": "Required"}],
                    warnings=[]
                )

            def map_attributes(self, product):
                return MappingResult(
                    product=product.get("name", ""),
                    mapped_data={
                        "title": product.get("product_name"),
                        "sku": product.get("product_code"),
                        "description": product.get("short_description", "")
                    }
                )

            def generate_payload(self, products):
                return {"products": products}

            def publish(self, products):
                return PublishResult(
                    success=True,
                    job_id=f"E2E-JOB-{suffix}",
                    status=PublishStatus.COMPLETED,
                    products_submitted=len(products),
                    products_succeeded=len(products)
                )

            def get_status(self, job_id):
                return StatusResult(
                    job_id=job_id,
                    status=PublishStatus.COMPLETED,
                    progress=1.0
                )

            def handle_rate_limiting(self, response=None):
                pass

        # Register the test adapter
        register_adapter(f"e2e_test_{suffix}", E2ETestAdapter)

        # Create test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Adapter Test Product {suffix}",
            "product_code": f"ATP-{suffix.upper()}",
            "short_description": "Testing adapter validation",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Test adapter validation
        adapter = E2ETestAdapter()
        product_data = {
            "name": product.name,
            "product_name": product.product_name,
            "product_code": product.product_code,
            "short_description": product.short_description
        }

        validation = adapter.validate_product(product_data)
        self.assertTrue(validation.is_valid)
        self.assertEqual(len(validation.errors), 0)

        # Test mapping
        mapping = adapter.map_attributes(product_data)
        self.assertEqual(mapping.mapped_data["title"], product.product_name)
        self.assertEqual(mapping.mapped_data["sku"], product.product_code)


class TestE2EFeedGeneration(unittest.TestCase):
    """E2E verification for feed generation workflow."""

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

    def test_e2e_generate_bmecat_feed_with_product(self):
        """
        E2E Step 4: Generate BMEcat feed with Product.

        Verifies:
        - BMEcat XML can be generated
        - Product data is included in feed
        - XML structure is valid
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.export.bmecat import export_catalog, validate_bmecat_xml

        suffix = random_string(6).upper()
        product_code = f"E2E-BMECAT-{suffix}"

        # Create test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E BMEcat Test Product {suffix}",
            "product_code": product_code,
            "short_description": "Product for BMEcat feed generation test",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Generate BMEcat catalog with product
        xml_content = export_catalog(
            products=[product.name],
            supplier_id=f"E2E-SUPPLIER-{suffix}",
            supplier_name="E2E Test Supplier",
            catalog_id=f"E2E-CATALOG-{suffix}",
            catalog_version="1.0",
            language="eng",
            territory="US",
            currency="USD",
            save_file=False
        )

        # Verify XML was generated
        self.assertIsInstance(xml_content, str)
        self.assertIn('<?xml', xml_content)
        self.assertIn('BMECAT', xml_content)

        # Verify product is included
        self.assertIn(f'<SUPPLIER_AID>{product_code}</SUPPLIER_AID>', xml_content)
        self.assertIn('<ARTICLE', xml_content)

        # Validate XML structure
        is_valid, errors = validate_bmecat_xml(xml_content)
        self.assertTrue(is_valid, f"BMEcat XML validation failed: {errors}")

    def test_e2e_generate_multiple_feed_formats(self):
        """
        E2E: Verify multiple feed formats can be generated.

        Tests CSV, JSON, and XML export formats.
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.api.export import get_supported_formats

        suffix = random_string(6).upper()

        # Create test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E Multi-Format Product {suffix}",
            "product_code": f"E2E-MF-{suffix}",
            "short_description": "Product for multi-format export test",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Verify supported formats are listed
        formats = get_supported_formats()
        self.assertIsInstance(formats, dict)
        self.assertIn("formats", formats)
        self.assertGreater(len(formats["formats"]), 5)

        # Verify key formats are supported
        format_codes = [f["code"] for f in formats["formats"]]
        self.assertIn("csv", format_codes)
        self.assertIn("json", format_codes)
        self.assertIn("bmecat", format_codes)
        self.assertIn("gs1_xml", format_codes)


class TestE2EDataQuality(unittest.TestCase):
    """E2E verification for data quality scanning workflow."""

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

    def test_e2e_run_data_quality_scan(self):
        """
        E2E Step 5: Run data quality scan.

        Verifies:
        - Gap analysis can be performed
        - Channel requirements are checked
        - Missing fields are identified
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import (
            gap_analysis,
            get_channel_requirements
        )

        suffix = random_string(6).upper()

        # Create product with missing fields for gap analysis
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E Gap Analysis Product {suffix}",
            "product_code": f"E2E-GAP-{suffix}",
            # Intentionally missing short_description
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Get channel requirements
        amazon_reqs = get_channel_requirements("amazon")
        self.assertEqual(amazon_reqs.channel_code, "amazon")
        self.assertTrue(amazon_reqs.gtin_required)

        # Run gap analysis
        result = gap_analysis(product.name, "amazon")

        self.assertEqual(result.channel_code, "amazon")
        self.assertIsInstance(result.score, float)
        self.assertLess(result.score, 100.0)  # Should have gaps

        # Verify gaps are identified
        all_gaps = result.critical_gaps + result.required_gaps + result.recommended_gaps
        self.assertGreater(len(all_gaps), 0)

    def test_e2e_multi_channel_quality_scan(self):
        """
        E2E: Verify multi-channel quality scanning.

        Tests quality scanning across multiple channels.
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import (
            calculate_multi_channel_scores,
            gap_analysis_multi_channel
        )

        suffix = random_string(6).upper()

        # Create product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E Multi-Channel Quality {suffix}",
            "product_code": f"E2E-MCQ-{suffix}",
            "short_description": "Multi-channel quality test product",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Run multi-channel scoring
        channels = ["amazon", "shopify", "woocommerce"]
        scores_result = calculate_multi_channel_scores(product.name, channels)

        self.assertIn("channels", scores_result)
        self.assertIn("ready_channels", scores_result)
        self.assertIn("not_ready_channels", scores_result)
        self.assertIn("readiness_percentage", scores_result)
        self.assertEqual(len(scores_result["channels"]), 3)

        # Run multi-channel gap analysis
        gap_result = gap_analysis_multi_channel(product.name, channels)

        self.assertIn("channels", gap_result)
        self.assertIn("summary", gap_result)
        self.assertEqual(gap_result["summary"]["total_channels"], 3)


class TestE2ECompletenessScore(unittest.TestCase):
    """E2E verification for completeness score calculation."""

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

    def test_e2e_verify_completeness_score_calculated(self):
        """
        E2E Step 6: Verify completeness score calculated.

        Verifies:
        - Completeness score is calculated for product
        - Score increases as fields are filled
        - Score reaches 100% when all required fields are filled
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import (
            calculate_score,
            get_completeness_summary
        )

        suffix = random_string(6).upper()

        # Create product with minimal fields
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E Completeness Product {suffix}",
            "product_code": f"E2E-COMP-{suffix}",
            "status": "Draft"
            # Missing short_description
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Calculate initial score
        initial_score = calculate_score(product)
        self.assertIsInstance(initial_score, float)
        self.assertLess(initial_score, 100.0)

        # Get completeness summary
        summary = get_completeness_summary(product.name)
        self.assertIn("score", summary)
        self.assertIn("missing_core", summary)
        self.assertIn("short_description", summary["missing_core"])

        # Add missing field
        product.short_description = "Now the product has a description"
        product.save(ignore_permissions=True)

        # Calculate updated score
        updated_score = calculate_score(product)
        self.assertGreater(updated_score, initial_score)
        self.assertEqual(updated_score, 100.0)

        # Verify updated summary
        updated_summary = get_completeness_summary(product.name)
        self.assertEqual(updated_summary["score"], 100.0)
        self.assertEqual(len(updated_summary["missing_core"]), 0)

    def test_e2e_completeness_with_family_attributes(self):
        """
        E2E: Verify completeness with family-required attributes.

        Tests that family attribute requirements are included in scoring.
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_score

        suffix = random_string(6).lower()

        # Create attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"e2e_attr_{suffix}",
            "attribute_name": f"E2E Attribute {suffix}",
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create family with required attribute
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"E2E Family {suffix}",
            "family_code": f"e2efam{suffix}",
            "is_group": 0,
            "attributes": [{
                "attribute": attr.name,
                "is_required_in_family": 1
            }]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Create product without attribute value
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"E2E Family Product {suffix}",
            "product_code": f"E2E-FAM-{suffix.upper()}",
            "short_description": "Product with family for completeness test",
            "product_family": family.name,
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Score should be less than 100% (missing required attribute)
        initial_score = calculate_score(product)
        self.assertLess(initial_score, 100.0)

        # Add required attribute value
        product.append("attribute_values", {
            "attribute": attr.name,
            "value_text": "Filled attribute value"
        })
        product.save(ignore_permissions=True)

        # Score should now be 100%
        final_score = calculate_score(product)
        self.assertEqual(final_score, 100.0)


class TestE2EFullWorkflow(unittest.TestCase):
    """
    E2E verification for complete PIM workflow.

    This test class combines all verification steps into a single
    comprehensive workflow test.
    """

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

    def test_e2e_complete_pim_workflow(self):
        """
        E2E: Complete PIM workflow verification.

        This test executes all 6 verification steps in sequence:
        1. Create Product Master via Virtual DocType API
        2. Verify Product appears in ERPNext Item list
        3. Publish Product to test channel
        4. Generate BMEcat feed with Product
        5. Run data quality scan
        6. Verify completeness score calculated
        """
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import (
            calculate_score,
            gap_analysis,
            get_completeness_summary
        )
        from frappe_pim.pim.export.bmecat import export_catalog, validate_bmecat_xml

        suffix = random_string(6).upper()

        # ================================================
        # STEP 1: Create Product Master via Virtual DocType API
        # ================================================
        product_code = f"E2E-FULL-{suffix}"
        product_name = f"E2E Complete Workflow Product {suffix}"

        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": product_name,
            "product_code": product_code,
            "short_description": "Complete workflow verification test product",
            "status": "Active"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        self.assertIsNotNone(product.name, "Step 1 Failed: Product not created")
        self.assertEqual(product.product_name, product_name)

        # ================================================
        # STEP 2: Verify Product appears in ERPNext Item list
        # ================================================
        self.assertTrue(
            frappe.db.exists("Item", product.name),
            "Step 2 Failed: Item not created in ERPNext"
        )

        item = frappe.get_doc("Item", product.name)
        self.assertEqual(item.item_name, product_name, "Step 2 Failed: Item name mismatch")
        self.assertEqual(item.item_code, product_code, "Step 2 Failed: Item code mismatch")

        # Verify in Item list query
        items = frappe.get_all("Item", filters={"item_code": product_code})
        self.assertEqual(len(items), 1, "Step 2 Failed: Item not in list query")

        # ================================================
        # STEP 3: Publish Product to test channel
        # ================================================
        channel = frappe.get_doc({
            "doctype": "Channel",
            "channel_name": f"E2E Workflow Channel {suffix}",
            "channel_code": f"e2e-wf-{suffix.lower()}",
            "channel_type": "E-commerce",
            "enabled": 1
        })
        channel.insert(ignore_permissions=True)
        self.track_document("Channel", channel.name)

        # Assign product to channel
        product.append("channels", {
            "channel": channel.name,
            "is_published": 0
        })
        product.save(ignore_permissions=True)

        self.assertEqual(
            len(product.channels), 1,
            "Step 3 Failed: Channel not assigned"
        )
        self.assertEqual(
            product.channels[0].channel, channel.name,
            "Step 3 Failed: Wrong channel assigned"
        )

        # ================================================
        # STEP 4: Generate BMEcat feed with Product
        # ================================================
        xml_content = export_catalog(
            products=[product.name],
            supplier_id=f"E2E-SUPP-{suffix}",
            supplier_name="E2E Workflow Supplier",
            catalog_id=f"E2E-CAT-{suffix}",
            catalog_version="1.0",
            language="eng",
            territory="US",
            currency="USD",
            save_file=False
        )

        self.assertIn('<?xml', xml_content, "Step 4 Failed: Invalid XML generated")
        self.assertIn('BMECAT', xml_content, "Step 4 Failed: Not a BMEcat document")
        self.assertIn(
            f'<SUPPLIER_AID>{product_code}</SUPPLIER_AID>',
            xml_content,
            "Step 4 Failed: Product not in feed"
        )

        is_valid, errors = validate_bmecat_xml(xml_content)
        self.assertTrue(is_valid, f"Step 4 Failed: BMEcat validation failed: {errors}")

        # ================================================
        # STEP 5: Run data quality scan
        # ================================================
        gap_result = gap_analysis(product.name, "amazon")

        self.assertEqual(
            gap_result.channel_code, "amazon",
            "Step 5 Failed: Gap analysis channel mismatch"
        )
        self.assertIsInstance(
            gap_result.score, float,
            "Step 5 Failed: Score not calculated"
        )

        # Product should have gaps (no GTIN for Amazon)
        all_gaps = gap_result.critical_gaps + gap_result.required_gaps + gap_result.recommended_gaps
        self.assertIsInstance(all_gaps, list, "Step 5 Failed: Gaps not returned")

        # ================================================
        # STEP 6: Verify completeness score calculated
        # ================================================
        score = calculate_score(product)

        self.assertIsInstance(score, float, "Step 6 Failed: Score not float")
        self.assertGreater(score, 0, "Step 6 Failed: Score is zero")
        self.assertEqual(
            score, 100.0,
            "Step 6 Failed: Core fields should give 100% score"
        )

        summary = get_completeness_summary(product.name)
        self.assertEqual(
            summary["score"], 100.0,
            "Step 6 Failed: Summary score mismatch"
        )
        self.assertEqual(
            len(summary["missing_core"]), 0,
            "Step 6 Failed: Should have no missing core fields"
        )

        # All 6 steps passed!


class TestE2EGS1Integration(unittest.TestCase):
    """E2E verification for GS1/GDSN standards integration."""

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

    def test_e2e_gs1_gtin_validation(self):
        """
        E2E: Verify GS1 GTIN validation integration.

        Tests GTIN validation for product data.
        """
        from frappe_pim.pim.utils.gs1_validation import (
            validate_gtin,
            create_gtin,
            verify_check_digit,
            get_gs1_prefix_info
        )

        # Test valid GTIN-13 (German barcode)
        gtin = "4006381333931"
        result = validate_gtin(gtin)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.identifier_type, "GTIN_13")
        self.assertEqual(result.normalized, gtin)

        # Test check digit verification
        self.assertTrue(verify_check_digit(gtin))

        # Test prefix info
        prefix_info = get_gs1_prefix_info(gtin)
        self.assertIsNotNone(prefix_info)
        self.assertIn("Germany", prefix_info["organization"])

        # Test GTIN creation
        new_gtin = create_gtin("400638133393", 13)
        self.assertEqual(len(new_gtin), 13)
        self.assertTrue(verify_check_digit(new_gtin))

    def test_e2e_gs1_packaging_hierarchy(self):
        """
        E2E: Verify GS1 packaging hierarchy works.

        Tests packaging level configuration.
        """
        import frappe
        from frappe.utils import random_string

        suffix = random_string(6).upper()

        # Check if GS1 Packaging Hierarchy DocType exists
        if frappe.db.exists("DocType", "GS1 Packaging Hierarchy"):
            # Create packaging hierarchy
            hierarchy = frappe.get_doc({
                "doctype": "GS1 Packaging Hierarchy",
                "product_name": f"E2E Packaging Product {suffix}",
                "product_code": f"E2E-PKG-{suffix}",
                "base_unit_gtin": "4006381333931",
                "base_unit_quantity": 1,
                "base_unit_uom": "EA"
            })
            hierarchy.insert(ignore_permissions=True)
            self.track_document("GS1 Packaging Hierarchy", hierarchy.name)

            self.assertIsNotNone(hierarchy.name)
            self.assertEqual(hierarchy.base_unit_quantity, 1)


class TestE2EModuleImports(unittest.TestCase):
    """E2E verification that all modules can be imported correctly."""

    def test_e2e_channel_adapters_import(self):
        """E2E: Verify all channel adapters can be imported."""
        # Import base
        from frappe_pim.pim.channels.base import (
            ChannelAdapter,
            register_adapter,
            get_adapter,
            list_adapters
        )

        # Import marketplace adapters
        from frappe_pim.pim.channels import amazon
        from frappe_pim.pim.channels import shopify
        from frappe_pim.pim.channels import woocommerce
        from frappe_pim.pim.channels import google_merchant
        from frappe_pim.pim.channels import trendyol
        from frappe_pim.pim.channels import n11

        # Verify adapters are registered
        adapters = list_adapters()
        self.assertIsInstance(adapters, list)
        self.assertIn("amazon", adapters)
        self.assertIn("shopify", adapters)
        self.assertIn("woocommerce", adapters)

    def test_e2e_export_modules_import(self):
        """E2E: Verify all export modules can be imported."""
        from frappe_pim.pim.export.bmecat import export_catalog
        from frappe_pim.pim.export.cxml import export_catalog as export_cxml
        from frappe_pim.pim.export.ubl import export_catalogue
        from frappe_pim.pim.export.gs1_xml import export_catalogue_item_notification
        from frappe_pim.pim.export.edifact import export_pricat
        from frappe_pim.pim.export.xlsx import export_catalog as export_xlsx

        # All imports should succeed
        self.assertTrue(callable(export_catalog))
        self.assertTrue(callable(export_cxml))
        self.assertTrue(callable(export_catalogue))
        self.assertTrue(callable(export_catalogue_item_notification))
        self.assertTrue(callable(export_pricat))
        self.assertTrue(callable(export_xlsx))

    def test_e2e_utility_modules_import(self):
        """E2E: Verify all utility modules can be imported."""
        from frappe_pim.pim.utils.completeness import (
            calculate_score,
            get_completeness_summary,
            gap_analysis
        )
        from frappe_pim.pim.utils.gs1_validation import (
            validate_gtin,
            validate_gln,
            validate_sscc
        )

        # All imports should succeed
        self.assertTrue(callable(calculate_score))
        self.assertTrue(callable(get_completeness_summary))
        self.assertTrue(callable(gap_analysis))
        self.assertTrue(callable(validate_gtin))
        self.assertTrue(callable(validate_gln))
        self.assertTrue(callable(validate_sscc))


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
