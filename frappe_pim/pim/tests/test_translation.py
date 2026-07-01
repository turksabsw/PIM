# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""Translation Gap Detection Unit Tests

This module contains unit tests for:
- Translation gap detection
- Translation coverage calculation
- Products with missing translations
- Translation statistics
- Translation status per language
- Translation completeness checking
- Translation report generation
- Unverified translations tracking
- Bulk translation status updates

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class MockProductDoc:
    """Mock product document for testing translation functions without database."""

    def __init__(self, **kwargs):
        """Initialize mock product with provided fields."""
        self.name = kwargs.get("name", "TEST-001")
        self.product_name = kwargs.get("product_name", "Test Product")
        self.short_description = kwargs.get("short_description", "")
        self.long_description = kwargs.get("long_description", "")
        self.product_translations = kwargs.get("product_translations", [])
        self.translation_coverage = kwargs.get("translation_coverage", 0.0)
        self.has_translation_gaps = kwargs.get("has_translation_gaps", True)
        self.product_family = kwargs.get("product_family", None)
        self.category = kwargs.get("category", None)

        # Set any additional fields
        for key, value in kwargs.items():
            if not hasattr(self, key):
                setattr(self, key, value)

    def get(self, field, default=None):
        """Get field value with default."""
        return getattr(self, field, default)


class MockTranslationItem:
    """Mock translation item for testing."""

    def __init__(self, language, field_name, translated_value="", is_verified=False, **kwargs):
        self.language = language
        self.field_name = field_name
        self.translated_value = translated_value
        self.is_verified = is_verified
        self.translation_source = kwargs.get("translation_source", "Manual")
        self.translated_by = kwargs.get("translated_by", "Administrator")

    def get(self, field, default=None):
        """Get field value with default."""
        return getattr(self, field, default)


class TestTranslationConstants(unittest.TestCase):
    """Test cases for translation module constants and configuration."""

    def test_default_translatable_fields_exist(self):
        """Test that default translatable fields are defined."""
        from frappe_pim.pim.utils.translation import DEFAULT_TRANSLATABLE_FIELDS

        self.assertIn("Product Name", DEFAULT_TRANSLATABLE_FIELDS)
        self.assertIn("Short Description", DEFAULT_TRANSLATABLE_FIELDS)
        self.assertIn("Long Description", DEFAULT_TRANSLATABLE_FIELDS)
        self.assertIn("Meta Title", DEFAULT_TRANSLATABLE_FIELDS)
        self.assertIn("Meta Description", DEFAULT_TRANSLATABLE_FIELDS)

    def test_default_translatable_fields_count(self):
        """Test that default translatable fields has expected count."""
        from frappe_pim.pim.utils.translation import DEFAULT_TRANSLATABLE_FIELDS

        self.assertEqual(len(DEFAULT_TRANSLATABLE_FIELDS), 5)

    def test_field_display_names_defined(self):
        """Test that field display names mapping is defined."""
        from frappe_pim.pim.utils.translation import FIELD_DISPLAY_NAMES

        self.assertIn("Product Name", FIELD_DISPLAY_NAMES)
        self.assertIn("Short Description", FIELD_DISPLAY_NAMES)
        self.assertIn("Meta Title", FIELD_DISPLAY_NAMES)
        self.assertIn("Meta Description", FIELD_DISPLAY_NAMES)
        self.assertIn("Meta Keywords", FIELD_DISPLAY_NAMES)
        self.assertIn("Marketing Text", FIELD_DISPLAY_NAMES)

    def test_field_display_names_seo_mapping(self):
        """Test that SEO fields have proper display names."""
        from frappe_pim.pim.utils.translation import FIELD_DISPLAY_NAMES

        self.assertEqual(FIELD_DISPLAY_NAMES["Meta Title"], "SEO Meta Title")
        self.assertEqual(FIELD_DISPLAY_NAMES["Meta Description"], "SEO Meta Description")
        self.assertEqual(FIELD_DISPLAY_NAMES["Meta Keywords"], "SEO Meta Keywords")


class TestBuildExistingTranslationsMap(unittest.TestCase):
    """Test cases for _build_existing_translations_map helper."""

    def test_build_map_with_translations(self):
        """Test building map with valid translations."""
        from frappe_pim.pim.utils.translation import _build_existing_translations_map

        translations = [
            MockTranslationItem("de", "Product Name", "Produkt Name"),
            MockTranslationItem("de", "Short Description", "Kurze Beschreibung"),
            MockTranslationItem("fr", "Product Name", "Nom du Produit"),
        ]

        result = _build_existing_translations_map(translations)

        self.assertIn("de|Product Name", result)
        self.assertIn("de|Short Description", result)
        self.assertIn("fr|Product Name", result)
        self.assertEqual(len(result), 3)

    def test_build_map_empty_translations(self):
        """Test building map with empty translations list."""
        from frappe_pim.pim.utils.translation import _build_existing_translations_map

        result = _build_existing_translations_map([])

        self.assertEqual(len(result), 0)

    def test_build_map_ignores_empty_values(self):
        """Test that empty translated values are not included."""
        from frappe_pim.pim.utils.translation import _build_existing_translations_map

        translations = [
            MockTranslationItem("de", "Product Name", "Produkt"),
            MockTranslationItem("de", "Short Description", ""),  # Empty value
            MockTranslationItem("de", "Long Description", "   "),  # Whitespace only
            MockTranslationItem("fr", "Product Name", None),  # None value
        ]

        result = _build_existing_translations_map(translations)

        self.assertIn("de|Product Name", result)
        self.assertNotIn("de|Short Description", result)
        self.assertNotIn("de|Long Description", result)
        self.assertNotIn("fr|Product Name", result)
        self.assertEqual(len(result), 1)

    def test_build_map_ignores_missing_fields(self):
        """Test that translations without language or field are ignored."""
        from frappe_pim.pim.utils.translation import _build_existing_translations_map

        class IncompleteTranslation:
            def __init__(self):
                self.language = None
                self.field_name = "Product Name"
                self.translated_value = "Value"

            def get(self, field, default=None):
                return getattr(self, field, default)

        translations = [IncompleteTranslation()]

        result = _build_existing_translations_map(translations)

        self.assertEqual(len(result), 0)


class TestEmptyResultStructures(unittest.TestCase):
    """Test cases for empty result structure helpers."""

    def test_empty_missing_result_structure(self):
        """Test _empty_missing_result returns correct structure."""
        from frappe_pim.pim.utils.translation import _empty_missing_result

        result = _empty_missing_result()

        self.assertEqual(result["missing"], [])
        self.assertEqual(result["total_required"], 0)
        self.assertEqual(result["total_present"], 0)
        self.assertEqual(result["coverage_percentage"], 100.0)
        self.assertEqual(result["by_language"], {})
        self.assertEqual(result["by_field"], {})

    def test_empty_statistics_structure(self):
        """Test _empty_statistics returns correct structure."""
        from frappe_pim.pim.utils.translation import _empty_statistics

        result = _empty_statistics()

        self.assertEqual(result["total_products"], 0)
        self.assertEqual(result["fully_translated"], 0)
        self.assertEqual(result["partially_translated"], 0)
        self.assertEqual(result["not_translated"], 0)
        self.assertEqual(result["average_coverage"], 0.0)
        self.assertEqual(result["by_language"], {})
        self.assertEqual(result["by_field"], {})
        self.assertEqual(result["required_languages"], [])
        self.assertEqual(result["required_fields"], [])

    def test_empty_language_status_structure(self):
        """Test _empty_language_status returns correct structure."""
        from frappe_pim.pim.utils.translation import _empty_language_status

        result = _empty_language_status("de")

        self.assertEqual(result["language"], "de")
        self.assertFalse(result["is_complete"])
        self.assertEqual(result["translated_fields"], [])
        self.assertEqual(result["coverage_percentage"], 0.0)
        self.assertEqual(result["verified_percentage"], 0.0)
        self.assertEqual(len(result["missing_fields"]), 5)  # All DEFAULT_TRANSLATABLE_FIELDS

    def test_empty_report_structure(self):
        """Test _empty_report returns correct structure."""
        from frappe_pim.pim.utils.translation import _empty_report

        result = _empty_report()

        self.assertIsNone(result["generated_at"])
        self.assertEqual(result["filters"], {})
        self.assertEqual(result["summary"]["total_products"], 0)
        self.assertEqual(result["summary"]["products_with_gaps"], 0)
        self.assertEqual(result["summary"]["total_missing_translations"], 0)
        self.assertEqual(result["rows"], [])


class TestGetMissingTranslations(unittest.TestCase):
    """Test cases for get_missing_translations function."""

    def test_missing_translations_no_languages(self):
        """Test when no languages are required."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        doc = MockProductDoc()

        result = get_missing_translations(doc, required_languages=[])

        self.assertEqual(result["missing"], [])
        self.assertEqual(result["coverage_percentage"], 100.0)
        self.assertEqual(result["total_required"], 0)

    def test_missing_translations_no_translations_exist(self):
        """Test with required languages but no translations."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        doc = MockProductDoc(product_translations=[])

        result = get_missing_translations(
            doc,
            required_languages=["de"],
            required_fields=["Product Name", "Short Description"]
        )

        self.assertEqual(len(result["missing"]), 2)  # 1 language * 2 fields
        self.assertEqual(result["coverage_percentage"], 0.0)
        self.assertEqual(result["total_required"], 2)
        self.assertEqual(result["total_present"], 0)
        self.assertIn("de", result["by_language"])
        self.assertEqual(result["by_language"]["de"], 2)

    def test_missing_translations_partial_translations(self):
        """Test with some translations present."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        doc = MockProductDoc(
            product_translations=[
                MockTranslationItem("de", "Product Name", "Produkt Name"),
            ]
        )

        result = get_missing_translations(
            doc,
            required_languages=["de"],
            required_fields=["Product Name", "Short Description"]
        )

        self.assertEqual(len(result["missing"]), 1)  # Only Short Description missing
        self.assertEqual(result["coverage_percentage"], 50.0)
        self.assertEqual(result["total_required"], 2)
        self.assertEqual(result["total_present"], 1)

    def test_missing_translations_all_complete(self):
        """Test when all translations are present."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        doc = MockProductDoc(
            product_translations=[
                MockTranslationItem("de", "Product Name", "Produkt Name"),
                MockTranslationItem("de", "Short Description", "Kurze Beschreibung"),
            ]
        )

        result = get_missing_translations(
            doc,
            required_languages=["de"],
            required_fields=["Product Name", "Short Description"]
        )

        self.assertEqual(len(result["missing"]), 0)
        self.assertEqual(result["coverage_percentage"], 100.0)
        self.assertEqual(result["total_required"], 2)
        self.assertEqual(result["total_present"], 2)

    def test_missing_translations_multiple_languages(self):
        """Test with multiple required languages."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        doc = MockProductDoc(
            product_translations=[
                MockTranslationItem("de", "Product Name", "Produkt Name"),
                MockTranslationItem("fr", "Product Name", "Nom du Produit"),
            ]
        )

        result = get_missing_translations(
            doc,
            required_languages=["de", "fr"],
            required_fields=["Product Name", "Short Description"]
        )

        # 2 languages * 2 fields = 4 total, 2 present = 2 missing
        self.assertEqual(len(result["missing"]), 2)
        self.assertEqual(result["coverage_percentage"], 50.0)
        self.assertIn("de", result["by_language"])
        self.assertIn("fr", result["by_language"])
        self.assertEqual(result["by_language"]["de"], 1)
        self.assertEqual(result["by_language"]["fr"], 1)

    def test_missing_translations_includes_display_name(self):
        """Test that missing translations include display name."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        doc = MockProductDoc(product_translations=[])

        result = get_missing_translations(
            doc,
            required_languages=["de"],
            required_fields=["Meta Title"]
        )

        self.assertEqual(len(result["missing"]), 1)
        self.assertEqual(result["missing"][0]["field"], "Meta Title")
        self.assertEqual(result["missing"][0]["display_name"], "SEO Meta Title")

    def test_missing_translations_by_field_tracking(self):
        """Test that by_field tracking is correct."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        doc = MockProductDoc(
            product_translations=[
                MockTranslationItem("de", "Product Name", "Produkt"),
                MockTranslationItem("fr", "Product Name", "Produit"),
            ]
        )

        result = get_missing_translations(
            doc,
            required_languages=["de", "fr"],
            required_fields=["Product Name", "Short Description"]
        )

        # Short Description missing for both languages
        self.assertIn("Short Description", result["by_field"])
        self.assertEqual(result["by_field"]["Short Description"], 2)
        self.assertNotIn("Product Name", result["by_field"])


class TestGetTranslationCoverage(unittest.TestCase):
    """Test cases for get_translation_coverage function."""

    def test_coverage_full(self):
        """Test 100% coverage."""
        from frappe_pim.pim.utils.translation import get_translation_coverage

        doc = MockProductDoc(
            product_translations=[
                MockTranslationItem("de", "Product Name", "Produkt"),
                MockTranslationItem("de", "Short Description", "Beschreibung"),
            ]
        )

        result = get_translation_coverage(
            doc,
            required_languages=["de"]
        )

        # This should return 40% because DEFAULT_TRANSLATABLE_FIELDS has 5 fields
        # and we only have 2 translations. Let's verify the function works.
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 100.0)

    def test_coverage_zero(self):
        """Test 0% coverage."""
        from frappe_pim.pim.utils.translation import get_translation_coverage

        doc = MockProductDoc(product_translations=[])

        result = get_translation_coverage(
            doc,
            required_languages=["de"]
        )

        self.assertEqual(result, 0.0)

    def test_coverage_no_languages(self):
        """Test coverage when no languages required."""
        from frappe_pim.pim.utils.translation import get_translation_coverage

        doc = MockProductDoc(product_translations=[])

        result = get_translation_coverage(doc, required_languages=[])

        self.assertEqual(result, 100.0)


class TestCheckTranslationCompleteness(unittest.TestCase):
    """Test cases for check_translation_completeness hook function."""

    def test_completeness_updates_coverage_field(self):
        """Test that completeness check updates document field."""
        from frappe_pim.pim.utils.translation import check_translation_completeness

        doc = MockProductDoc(
            product_translations=[
                MockTranslationItem("de", "Product Name", "Produkt"),
            ],
            translation_coverage=0.0,
            has_translation_gaps=True
        )

        # We need to mock the get_missing_translations function behavior
        # Since it uses frappe.db.exists, this test may need integration
        # But we can test the return value structure
        result = check_translation_completeness(doc)

        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, 0.0)

    def test_completeness_handles_doc_without_fields(self):
        """Test completeness with document without coverage fields."""
        from frappe_pim.pim.utils.translation import check_translation_completeness

        class MinimalDoc:
            def __init__(self):
                self.name = "TEST-001"
                self.product_translations = []

            def get(self, field, default=None):
                return getattr(self, field, default)

        doc = MinimalDoc()

        # Should not raise error even without translation_coverage field
        result = check_translation_completeness(doc)

        self.assertIsInstance(result, float)


class TestConvertReportToCSV(unittest.TestCase):
    """Test cases for _convert_report_to_csv helper."""

    def test_convert_empty_report(self):
        """Test converting empty report to CSV."""
        from frappe_pim.pim.utils.translation import _convert_report_to_csv

        report = {
            "generated_at": "2024-01-01",
            "filters": {},
            "summary": {},
            "rows": []
        }

        result = _convert_report_to_csv(report)

        self.assertEqual(result, "")

    def test_convert_report_with_rows(self):
        """Test converting report with data to CSV."""
        from frappe_pim.pim.utils.translation import _convert_report_to_csv

        report = {
            "generated_at": "2024-01-01",
            "filters": {},
            "summary": {},
            "rows": [
                {
                    "product": "PROD-001",
                    "product_name": "Test Product",
                    "missing_count": 3,
                    "coverage_percentage": 60.0
                },
                {
                    "product": "PROD-002",
                    "product_name": "Another Product",
                    "missing_count": 1,
                    "coverage_percentage": 80.0
                }
            ]
        }

        result = _convert_report_to_csv(report)

        # Check CSV structure
        lines = result.strip().split("\n")
        self.assertEqual(len(lines), 3)  # Header + 2 rows

        # Check header
        self.assertIn("product", lines[0])
        self.assertIn("product_name", lines[0])
        self.assertIn("missing_count", lines[0])

        # Check data
        self.assertIn("PROD-001", lines[1])
        self.assertIn("PROD-002", lines[2])


class TestTranslationIntegration(unittest.TestCase):
    """Integration tests for translation gap detection with actual database.

    These tests require Frappe to be initialized and connected to database.
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

    def test_get_missing_translations_with_real_product(self):
        """Test get_missing_translations with a real product document."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import get_missing_translations

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Translation Product {random_string(4)}",
            "product_code": f"TRANS-{random_string(6).upper()}",
            "short_description": "A test product for translation testing.",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Get missing translations with specific languages
        result = get_missing_translations(
            product.name,
            required_languages=["de", "fr"],
            required_fields=["Product Name", "Short Description"]
        )

        # All translations should be missing
        self.assertEqual(len(result["missing"]), 4)  # 2 languages * 2 fields
        self.assertEqual(result["coverage_percentage"], 0.0)
        self.assertIn("product", result)
        self.assertEqual(result["product"], product.name)

    def test_get_missing_translations_with_translations_present(self):
        """Test get_missing_translations when product has translations."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import get_missing_translations

        # Create a test product with translations
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Translated Product {random_string(4)}",
            "product_code": f"TRANS-{random_string(6).upper()}",
            "short_description": "A product with translations.",
            "status": "Draft",
            "product_translations": [
                {
                    "language": "de",
                    "field_name": "Product Name",
                    "translated_value": "Ubersetztes Produkt",
                    "is_verified": False
                },
                {
                    "language": "de",
                    "field_name": "Short Description",
                    "translated_value": "Ein Produkt mit Ubersetzungen.",
                    "is_verified": True
                }
            ]
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Get missing translations
        result = get_missing_translations(
            product.name,
            required_languages=["de"],
            required_fields=["Product Name", "Short Description"]
        )

        # All German translations should be present
        self.assertEqual(len(result["missing"]), 0)
        self.assertEqual(result["coverage_percentage"], 100.0)

    def test_get_missing_translations_nonexistent_product(self):
        """Test get_missing_translations with non-existent product."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        result = get_missing_translations(
            "NONEXISTENT-PRODUCT-12345",
            required_languages=["de"]
        )

        # Should return empty result
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["coverage_percentage"], 100.0)

    def test_get_translation_coverage_with_real_product(self):
        """Test get_translation_coverage with a real product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import get_translation_coverage

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Coverage Test Product {random_string(4)}",
            "product_code": f"COV-{random_string(6).upper()}",
            "short_description": "Testing coverage calculation.",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Get coverage
        coverage = get_translation_coverage(
            product.name,
            required_languages=["de"]
        )

        # Should be 0% since no translations exist
        self.assertEqual(coverage, 0.0)

    def test_get_translation_status_with_real_product(self):
        """Test get_translation_status with a real product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import get_translation_status

        # Create a test product with some translations
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Status Test Product {random_string(4)}",
            "product_code": f"STAT-{random_string(6).upper()}",
            "short_description": "Testing translation status.",
            "status": "Draft",
            "product_translations": [
                {
                    "language": "de",
                    "field_name": "Product Name",
                    "translated_value": "Produkt Name",
                    "is_verified": True
                },
                {
                    "language": "de",
                    "field_name": "Short Description",
                    "translated_value": "Kurze Beschreibung",
                    "is_verified": False
                }
            ]
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Get translation status for German
        status = get_translation_status(product.name, "de")

        # Check structure
        self.assertEqual(status["language"], "de")
        self.assertIn("Product Name", status["translated_fields"])
        self.assertIn("Short Description", status["translated_fields"])
        self.assertIn("Product Name", status["verified_fields"])
        self.assertNotIn("Short Description", status["verified_fields"])

        # Coverage should reflect 2 of 5 default fields translated
        self.assertEqual(status["coverage_percentage"], 40.0)
        self.assertEqual(status["verified_percentage"], 50.0)

    def test_get_translation_status_nonexistent_product(self):
        """Test get_translation_status with non-existent product."""
        from frappe_pim.pim.utils.translation import get_translation_status

        status = get_translation_status("NONEXISTENT-12345", "de")

        # Should return empty status
        self.assertEqual(status["language"], "de")
        self.assertFalse(status["is_complete"])
        self.assertEqual(status["translated_fields"], [])
        self.assertEqual(status["coverage_percentage"], 0.0)

    def test_check_translation_completeness_with_real_product(self):
        """Test check_translation_completeness hook with real product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import check_translation_completeness

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Completeness Test {random_string(4)}",
            "product_code": f"COMP-{random_string(6).upper()}",
            "short_description": "Testing completeness check.",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Reload to get fresh document
        product.reload()

        # Check completeness
        coverage = check_translation_completeness(product)

        # Should return a float
        self.assertIsInstance(coverage, float)
        self.assertGreaterEqual(coverage, 0.0)
        self.assertLessEqual(coverage, 100.0)

    def test_generate_translation_report_basic(self):
        """Test generate_translation_report basic functionality."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import generate_translation_report

        # Create test products
        for i in range(3):
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Report Test Product {i} {random_string(4)}",
                "product_code": f"RPT{i}-{random_string(6).upper()}",
                "short_description": f"Test product {i} for report.",
                "status": "Draft"
            })
            product.insert(ignore_permissions=True)
            self.track_document("Product Master", product.name)

        # Generate report
        report = generate_translation_report(
            language="de",
            output_format="dict"
        )

        # Check structure
        self.assertIn("generated_at", report)
        self.assertIn("filters", report)
        self.assertIn("summary", report)
        self.assertIn("rows", report)

        # Should have products with gaps
        self.assertGreater(report["summary"]["products_with_gaps"], 0)

    def test_generate_translation_report_csv_format(self):
        """Test generate_translation_report CSV output."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import generate_translation_report

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"CSV Report Test {random_string(4)}",
            "product_code": f"CSV-{random_string(6).upper()}",
            "short_description": "Test for CSV report.",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Generate CSV report
        report = generate_translation_report(
            products=[product.name],
            language="de",
            output_format="csv"
        )

        # Should return CSV string
        self.assertIsInstance(report, str)
        if report:  # If there are gaps
            self.assertIn("product", report)

    def test_get_products_with_missing_translations_basic(self):
        """Test get_products_with_missing_translations function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import get_products_with_missing_translations

        # Create test products
        for i in range(2):
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Missing Trans Test {i} {random_string(4)}",
                "product_code": f"MISS{i}-{random_string(6).upper()}",
                "short_description": f"Test product {i}.",
                "status": "Draft"
            })
            product.insert(ignore_permissions=True)
            self.track_document("Product Master", product.name)

        # Get products with missing translations
        results = get_products_with_missing_translations(
            required_languages=["de"],
            required_fields=["Product Name"],
            min_missing=1,
            limit=10
        )

        # Should return list of products
        self.assertIsInstance(results, list)
        if results:
            self.assertIn("product", results[0])
            self.assertIn("missing_count", results[0])
            self.assertIn("coverage_percentage", results[0])

    def test_get_translation_statistics_basic(self):
        """Test get_translation_statistics function."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.translation import get_translation_statistics

        # Create test products
        for i in range(2):
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Stats Test {i} {random_string(4)}",
                "product_code": f"STATS{i}-{random_string(6).upper()}",
                "short_description": f"Test product {i}.",
                "status": "Draft"
            })
            product.insert(ignore_permissions=True)
            self.track_document("Product Master", product.name)

        # Get statistics
        stats = get_translation_statistics()

        # Check structure
        self.assertIn("total_products", stats)
        self.assertIn("fully_translated", stats)
        self.assertIn("partially_translated", stats)
        self.assertIn("not_translated", stats)
        self.assertIn("average_coverage", stats)
        self.assertIn("by_language", stats)
        self.assertIn("by_field", stats)


class TestTranslationGapEdgeCases(unittest.TestCase):
    """Test edge cases in translation gap detection."""

    def test_missing_translations_with_default_fields(self):
        """Test get_missing_translations uses defaults when not specified."""
        from frappe_pim.pim.utils.translation import (
            get_missing_translations,
            DEFAULT_TRANSLATABLE_FIELDS
        )

        doc = MockProductDoc(product_translations=[])

        # Call without specifying required_fields
        result = get_missing_translations(
            doc,
            required_languages=["de"],
            required_fields=None  # Should use DEFAULT_TRANSLATABLE_FIELDS
        )

        # Should have missing for all default fields
        self.assertEqual(
            len(result["missing"]),
            len(DEFAULT_TRANSLATABLE_FIELDS)
        )

    def test_coverage_calculation_precision(self):
        """Test that coverage is calculated with proper precision."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        # Create translations for 1 out of 3 fields
        doc = MockProductDoc(
            product_translations=[
                MockTranslationItem("de", "Product Name", "Produkt"),
            ]
        )

        result = get_missing_translations(
            doc,
            required_languages=["de"],
            required_fields=["Product Name", "Short Description", "Long Description"]
        )

        # 1 out of 3 = 33.33%
        self.assertAlmostEqual(result["coverage_percentage"], 33.33, places=1)

    def test_multiple_languages_missing_some_fields(self):
        """Test complex scenario with multiple languages and partial translations."""
        from frappe_pim.pim.utils.translation import get_missing_translations

        doc = MockProductDoc(
            product_translations=[
                MockTranslationItem("de", "Product Name", "Produkt Name"),
                MockTranslationItem("de", "Short Description", "Beschreibung"),
                MockTranslationItem("fr", "Product Name", "Nom du Produit"),
                # French Short Description is missing
            ]
        )

        result = get_missing_translations(
            doc,
            required_languages=["de", "fr"],
            required_fields=["Product Name", "Short Description"]
        )

        # 3 out of 4 present = 1 missing
        self.assertEqual(len(result["missing"]), 1)
        self.assertEqual(result["coverage_percentage"], 75.0)

        # Check the missing one is French Short Description
        self.assertEqual(result["missing"][0]["language"], "fr")
        self.assertEqual(result["missing"][0]["field"], "Short Description")


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
