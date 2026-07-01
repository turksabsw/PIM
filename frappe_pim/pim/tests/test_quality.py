# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""Product Data Quality and Completeness Scoring Unit Tests

This module contains unit tests for:
- Completeness score calculation
- Channel-specific scoring rules
- Gap analysis and remediation
- Field validation against requirements
- Data quality metrics

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class TestCompletenessScoreCalculation(unittest.TestCase):
    """Test cases for completeness score calculation."""

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

    def test_calculate_score_full_product(self):
        """Test completeness score for fully filled product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_score

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Complete Product {random_string(4)}",
            "product_code": f"COMP-{random_string(6).upper()}",
            "short_description": "This is a complete product with all core fields filled",
            "status": "Active"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        score = calculate_score(doc)

        # With all 3 core fields filled, should be 100%
        self.assertEqual(score, 100.0)

    def test_calculate_score_partial_product(self):
        """Test completeness score for partially filled product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_score

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Partial Product {random_string(4)}",
            "product_code": f"PART-{random_string(6).upper()}",
            # Missing short_description
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        score = calculate_score(doc)

        # 2/3 core fields = 66.67%
        self.assertAlmostEqual(score, 66.67, delta=0.1)

    def test_calculate_score_minimal_product(self):
        """Test completeness score for minimal product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_score

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Minimal Product {random_string(4)}",
            "product_code": f"MIN-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        score = calculate_score(doc)

        # Only 2 fields (name, code) without description = 66.67%
        self.assertLess(score, 100.0)

    def test_calculate_score_with_family_attributes(self):
        """Test completeness score with family-required attributes."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_score

        # Create attribute
        attr = frappe.get_doc({
            "doctype": "PIM Attribute",
            "attribute_code": f"req_attr_{random_string(6).lower()}",
            "attribute_name": f"Required Attr {random_string(4)}",
            "data_type": "Text"
        })
        attr.insert(ignore_permissions=True)
        self.track_document("PIM Attribute", attr.name)

        # Create family with required attribute
        family = frappe.get_doc({
            "doctype": "Product Family",
            "family_name": f"Test Family {random_string(4)}",
            "is_group": 0,
            "attributes": [{
                "attribute": attr.name,
                "is_required_in_family": 1
            }]
        })
        family.insert(ignore_permissions=True)
        self.track_document("Product Family", family.name)

        # Create product without attribute value
        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Family Product {random_string(4)}",
            "product_code": f"FAM-{random_string(6).upper()}",
            "short_description": "Product with family",
            "product_family": family.name,
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        score = calculate_score(doc)

        # 3 core + 1 attr = 4 total, 3 filled = 75%
        self.assertAlmostEqual(score, 75.0, delta=0.1)


class TestChannelSpecificScoring(unittest.TestCase):
    """Test cases for channel-specific completeness scoring."""

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

    def test_channel_score_amazon(self):
        """Test Amazon channel-specific score."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_channel_specific_score

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Amazon Product {random_string(4)}",
            "product_code": f"AMZ-{random_string(6).upper()}",
            "short_description": "Amazon product description for bullet points",
            "status": "Active"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = calculate_channel_specific_score(doc.name, "amazon")

        self.assertIn("score", result)
        self.assertIn("is_channel_ready", result)
        self.assertIn("missing_fields", result)
        self.assertIn("channel_name", result)
        self.assertEqual(result["channel_name"], "Amazon")

    def test_channel_score_shopify(self):
        """Test Shopify channel-specific score."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_channel_specific_score

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Shopify Product {random_string(4)}",
            "product_code": f"SHOP-{random_string(6).upper()}",
            "short_description": "Shopify product description",
            "status": "Active"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = calculate_channel_specific_score(doc.name, "shopify")

        self.assertIn("score", result)
        self.assertEqual(result["channel_name"], "Shopify")

    def test_channel_score_google_merchant(self):
        """Test Google Merchant Center channel-specific score."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_channel_specific_score

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Google Product {random_string(4)}",
            "product_code": f"GOOG-{random_string(6).upper()}",
            "short_description": "Google shopping product description",
            "status": "Active"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = calculate_channel_specific_score(doc.name, "google_merchant")

        self.assertIn("score", result)
        self.assertEqual(result["channel_name"], "Google Merchant Center")

    def test_multi_channel_scores(self):
        """Test multi-channel scoring."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import calculate_multi_channel_scores

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Multi Channel Product {random_string(4)}",
            "product_code": f"MULTI-{random_string(6).upper()}",
            "short_description": "Product for multiple channels",
            "status": "Active"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = calculate_multi_channel_scores(
            doc.name,
            channel_codes=["amazon", "shopify", "woocommerce"]
        )

        self.assertIn("channels", result)
        self.assertIn("ready_channels", result)
        self.assertIn("not_ready_channels", result)
        self.assertIn("readiness_percentage", result)
        self.assertEqual(len(result["channels"]), 3)


class TestGapAnalysis(unittest.TestCase):
    """Test cases for gap analysis functionality."""

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

    def test_gap_analysis_amazon(self):
        """Test gap analysis for Amazon channel."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import gap_analysis

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Gap Analysis Product {random_string(4)}",
            "product_code": f"GAP-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = gap_analysis(doc.name, "amazon")

        self.assertEqual(result.channel_code, "amazon")
        self.assertEqual(result.channel_name, "Amazon")
        self.assertIsInstance(result.score, float)
        self.assertIsInstance(result.critical_gaps, list)
        self.assertIsInstance(result.required_gaps, list)
        self.assertIsInstance(result.recommended_gaps, list)

    def test_gap_analysis_multi_channel(self):
        """Test gap analysis across multiple channels."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import gap_analysis_multi_channel

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Multi Gap Product {random_string(4)}",
            "product_code": f"MGAP-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = gap_analysis_multi_channel(
            doc.name,
            channel_codes=["amazon", "shopify"]
        )

        self.assertIn("channels", result)
        self.assertIn("summary", result)
        self.assertEqual(result["summary"]["total_channels"], 2)

    def test_gap_analysis_to_dict(self):
        """Test GapAnalysisResult.to_dict method."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import gap_analysis

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Dict Test Product {random_string(4)}",
            "product_code": f"DICT-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = gap_analysis(doc.name, "amazon")
        result_dict = result.to_dict()

        self.assertIsInstance(result_dict, dict)
        self.assertIn("channel_code", result_dict)
        self.assertIn("score", result_dict)
        self.assertIn("critical_gaps", result_dict)


class TestRemediationPlan(unittest.TestCase):
    """Test cases for remediation plan generation."""

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

    def test_get_remediation_plan(self):
        """Test remediation plan generation."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import get_remediation_plan

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Remediation Product {random_string(4)}",
            "product_code": f"REM-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        plan = get_remediation_plan(doc.name, "amazon")

        self.assertIn("product_name", plan)
        self.assertIn("channels_analyzed", plan)
        self.assertIn("total_steps", plan)
        self.assertIn("blocking_steps", plan)
        self.assertIn("steps", plan)
        self.assertIsInstance(plan["steps"], list)

    def test_remediation_plan_priority_order(self):
        """Test that remediation steps are ordered by priority."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import get_remediation_plan

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Priority Product {random_string(4)}",
            "product_code": f"PRIO-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        plan = get_remediation_plan(doc.name, "amazon")

        if len(plan["steps"]) > 1:
            # Verify first steps are critical
            for step in plan["steps"][:3]:
                if step["importance"] == "critical":
                    self.assertTrue(step["blocking"])


class TestChannelRequirements(unittest.TestCase):
    """Test cases for channel requirement definitions."""

    def test_get_channel_requirements_amazon(self):
        """Test getting Amazon channel requirements."""
        from frappe_pim.pim.utils.completeness import get_channel_requirements

        req = get_channel_requirements("amazon")

        self.assertEqual(req.channel_code, "amazon")
        self.assertEqual(req.channel_name, "Amazon")
        self.assertTrue(req.gtin_required)
        self.assertTrue(req.category_required)
        self.assertGreater(len(req.core_fields), 0)

    def test_get_channel_requirements_shopify(self):
        """Test getting Shopify channel requirements."""
        from frappe_pim.pim.utils.completeness import get_channel_requirements

        req = get_channel_requirements("shopify")

        self.assertEqual(req.channel_code, "shopify")
        self.assertEqual(req.channel_name, "Shopify")
        self.assertFalse(req.gtin_required)

    def test_get_channel_requirements_unknown(self):
        """Test getting requirements for unknown channel returns default."""
        from frappe_pim.pim.utils.completeness import get_channel_requirements

        req = get_channel_requirements("unknown_channel_xyz")

        self.assertEqual(req.channel_code, "default")

    def test_list_supported_channels(self):
        """Test listing supported channels."""
        from frappe_pim.pim.utils.completeness import list_supported_channels

        channels = list_supported_channels()

        self.assertIsInstance(channels, list)
        self.assertIn("amazon", channels)
        self.assertIn("shopify", channels)
        self.assertIn("woocommerce", channels)
        self.assertNotIn("default", channels)

    def test_channel_requirements_critical_fields(self):
        """Test getting critical fields from requirements."""
        from frappe_pim.pim.utils.completeness import get_channel_requirements

        req = get_channel_requirements("amazon")
        critical = req.get_critical_fields()

        self.assertIsInstance(critical, list)
        self.assertIn("product_name", critical)
        self.assertIn("gtin", critical)

    def test_channel_requirements_all_required_fields(self):
        """Test getting all required fields from requirements."""
        from frappe_pim.pim.utils.completeness import get_channel_requirements

        req = get_channel_requirements("amazon")
        required = req.get_all_required_fields()

        self.assertIsInstance(required, list)
        self.assertGreater(len(required), len(req.get_critical_fields()))


class TestFieldImportanceEnum(unittest.TestCase):
    """Test cases for FieldImportance enum."""

    def test_field_importance_values(self):
        """Test FieldImportance enum values."""
        from frappe_pim.pim.utils.completeness import FieldImportance

        self.assertEqual(FieldImportance.CRITICAL.value, "critical")
        self.assertEqual(FieldImportance.REQUIRED.value, "required")
        self.assertEqual(FieldImportance.RECOMMENDED.value, "recommended")
        self.assertEqual(FieldImportance.OPTIONAL.value, "optional")


class TestFieldRequirementDataClass(unittest.TestCase):
    """Test cases for FieldRequirement data class."""

    def test_field_requirement_creation(self):
        """Test creating FieldRequirement."""
        from frappe_pim.pim.utils.completeness import FieldRequirement, FieldImportance

        req = FieldRequirement(
            field_name="product_name",
            importance=FieldImportance.CRITICAL,
            min_length=1,
            max_length=200,
            description="Product title",
            remediation="Add a product title"
        )

        self.assertEqual(req.field_name, "product_name")
        self.assertEqual(req.importance, FieldImportance.CRITICAL)
        self.assertEqual(req.min_length, 1)
        self.assertEqual(req.max_length, 200)

    def test_field_requirement_to_dict(self):
        """Test FieldRequirement.to_dict method."""
        from frappe_pim.pim.utils.completeness import FieldRequirement, FieldImportance

        req = FieldRequirement(
            field_name="sku",
            importance=FieldImportance.REQUIRED,
            description="Stock keeping unit"
        )

        req_dict = req.to_dict()

        self.assertIsInstance(req_dict, dict)
        self.assertIn("field_name", req_dict)
        self.assertIn("importance", req_dict)
        self.assertEqual(req_dict["importance"], "required")


class TestGapItemDataClass(unittest.TestCase):
    """Test cases for GapItem data class."""

    def test_gap_item_creation(self):
        """Test creating GapItem."""
        from frappe_pim.pim.utils.completeness import GapItem, FieldImportance

        gap = GapItem(
            field_name="gtin",
            importance=FieldImportance.CRITICAL,
            current_value=None,
            requirement="Valid GTIN required",
            remediation="Add a valid GTIN barcode",
            score_impact=5.0
        )

        self.assertEqual(gap.field_name, "gtin")
        self.assertEqual(gap.importance, FieldImportance.CRITICAL)
        self.assertIsNone(gap.current_value)
        self.assertEqual(gap.score_impact, 5.0)

    def test_gap_item_to_dict(self):
        """Test GapItem.to_dict method."""
        from frappe_pim.pim.utils.completeness import GapItem, FieldImportance

        gap = GapItem(
            field_name="brand",
            importance=FieldImportance.REQUIRED,
            remediation="Add brand name"
        )

        gap_dict = gap.to_dict()

        self.assertIsInstance(gap_dict, dict)
        self.assertIn("field_name", gap_dict)
        self.assertIn("importance", gap_dict)
        self.assertEqual(gap_dict["importance"], "required")


class TestHelperFunctions(unittest.TestCase):
    """Test cases for completeness helper functions."""

    def test_has_field_value_string(self):
        """Test _has_field_value with string value."""
        from frappe_pim.pim.utils.completeness import _has_field_value

        class MockDoc:
            def get(self, field):
                return {"name": "Test", "empty": "", "whitespace": "   "}.get(field)

        doc = MockDoc()

        self.assertTrue(_has_field_value(doc, "name"))
        self.assertFalse(_has_field_value(doc, "empty"))
        self.assertFalse(_has_field_value(doc, "whitespace"))

    def test_has_field_value_none(self):
        """Test _has_field_value with None."""
        from frappe_pim.pim.utils.completeness import _has_field_value

        class MockDoc:
            def get(self, field):
                return None

        doc = MockDoc()

        self.assertFalse(_has_field_value(doc, "field"))

    def test_has_field_value_number(self):
        """Test _has_field_value with numeric values."""
        from frappe_pim.pim.utils.completeness import _has_field_value

        class MockDoc:
            def get(self, field):
                return {"zero": 0, "number": 42, "float": 3.14}.get(field)

        doc = MockDoc()

        self.assertTrue(_has_field_value(doc, "zero"))
        self.assertTrue(_has_field_value(doc, "number"))
        self.assertTrue(_has_field_value(doc, "float"))

    def test_check_field_value_valid(self):
        """Test _check_field_value with valid value."""
        from frappe_pim.pim.utils.completeness import (
            _check_field_value,
            FieldRequirement,
            FieldImportance
        )

        req = FieldRequirement(
            field_name="title",
            importance=FieldImportance.REQUIRED,
            min_length=5,
            max_length=100
        )

        self.assertTrue(_check_field_value("Test Product Title", req))

    def test_check_field_value_too_short(self):
        """Test _check_field_value with too short value."""
        from frappe_pim.pim.utils.completeness import (
            _check_field_value,
            FieldRequirement,
            FieldImportance
        )

        req = FieldRequirement(
            field_name="title",
            importance=FieldImportance.REQUIRED,
            min_length=10
        )

        self.assertFalse(_check_field_value("Hi", req))

    def test_check_field_value_too_long(self):
        """Test _check_field_value with too long value."""
        from frappe_pim.pim.utils.completeness import (
            _check_field_value,
            FieldRequirement,
            FieldImportance
        )

        req = FieldRequirement(
            field_name="title",
            importance=FieldImportance.REQUIRED,
            max_length=10
        )

        self.assertFalse(_check_field_value("This is a very long title", req))

    def test_has_eav_value(self):
        """Test _has_eav_value with different value types."""
        from frappe_pim.pim.utils.completeness import _has_eav_value

        # Text value
        self.assertTrue(_has_eav_value({"value_text": "Test"}))

        # Integer value
        self.assertTrue(_has_eav_value({"value_int": 42}))

        # Float value
        self.assertTrue(_has_eav_value({"value_float": 3.14}))

        # Boolean value
        self.assertTrue(_has_eav_value({"value_boolean": True}))
        self.assertTrue(_has_eav_value({"value_boolean": False}))

        # Empty
        self.assertFalse(_has_eav_value({}))
        self.assertFalse(_has_eav_value({"value_text": ""}))
        self.assertFalse(_has_eav_value({"value_text": "   "}))


class TestAPIFunctions(unittest.TestCase):
    """Test cases for API wrapper functions."""

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

    def test_api_calculate_channel_score(self):
        """Test api_calculate_channel_score function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import api_calculate_channel_score

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"API Score Test {random_string(4)}",
            "product_code": f"API-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = api_calculate_channel_score(doc.name, "amazon")

        self.assertIsInstance(result, dict)
        self.assertIn("score", result)

    def test_api_gap_analysis(self):
        """Test api_gap_analysis function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import api_gap_analysis

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"API Gap Test {random_string(4)}",
            "product_code": f"APIGAP-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = api_gap_analysis(doc.name, "shopify")

        self.assertIsInstance(result, dict)
        self.assertIn("channel_code", result)

    def test_api_multi_channel_scores(self):
        """Test api_multi_channel_scores function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import api_multi_channel_scores

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"API Multi Test {random_string(4)}",
            "product_code": f"APIMULTI-{random_string(6).upper()}",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        result = api_multi_channel_scores(doc.name, "amazon,shopify")

        self.assertIsInstance(result, dict)
        self.assertIn("channels", result)

    def test_api_list_channel_requirements(self):
        """Test api_list_channel_requirements function."""
        from frappe_pim.pim.utils.completeness import api_list_channel_requirements

        result = api_list_channel_requirements()

        self.assertIsInstance(result, dict)
        self.assertIn("channels", result)
        self.assertIsInstance(result["channels"], list)

    def test_api_get_channel_requirements(self):
        """Test api_get_channel_requirements function."""
        from frappe_pim.pim.utils.completeness import api_get_channel_requirements

        result = api_get_channel_requirements("amazon")

        self.assertIsInstance(result, dict)
        self.assertIn("channel_code", result)
        self.assertEqual(result["channel_code"], "amazon")


class TestCompletenessSummary(unittest.TestCase):
    """Test cases for completeness summary function."""

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

    def test_get_completeness_summary(self):
        """Test get_completeness_summary function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.completeness import get_completeness_summary

        doc = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Summary Test {random_string(4)}",
            "product_code": f"SUM-{random_string(6).upper()}",
            "short_description": "Test description",
            "status": "Draft"
        })
        doc.insert(ignore_permissions=True)
        self.track_document("Product Master", doc.name)

        summary = get_completeness_summary(doc.name)

        self.assertIn("product_name", summary)
        self.assertIn("score", summary)
        self.assertIn("total_required", summary)
        self.assertIn("total_filled", summary)
        self.assertIn("core_fields", summary)
        self.assertIn("missing_core", summary)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
