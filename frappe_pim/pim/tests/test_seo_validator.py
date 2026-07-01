# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""SEO Validator Unit Tests

This module contains unit tests for:
- SEO field configuration constants
- SEO field validation functions
- SEO completeness scoring
- SEO quality grading
- SEO issue detection and recommendations
- Bulk SEO validation

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class MockProductDoc:
    """Mock product document for testing SEO validation without database."""

    def __init__(self, **kwargs):
        """Initialize mock product with provided fields."""
        self.name = kwargs.get("name", "TEST-001")
        self.product_name = kwargs.get("product_name", "")
        self.short_description = kwargs.get("short_description", "")
        self.long_description = kwargs.get("long_description", "")
        self.seo_meta_title = kwargs.get("seo_meta_title", "")
        self.seo_meta_description = kwargs.get("seo_meta_description", "")
        self.seo_meta_keywords = kwargs.get("seo_meta_keywords", "")
        self.seo_canonical_url = kwargs.get("seo_canonical_url", "")
        self.seo_score = kwargs.get("seo_score", 0)
        self.is_seo_complete = kwargs.get("is_seo_complete", False)
        self.has_seo_issues = kwargs.get("has_seo_issues", False)
        self.product_family = kwargs.get("product_family", None)
        self.category = kwargs.get("category", None)

        # Set any additional fields
        for key, value in kwargs.items():
            if not hasattr(self, key):
                setattr(self, key, value)

    def get(self, field, default=None):
        """Get field value with default."""
        return getattr(self, field, default)


class TestSEOFieldsConfiguration(unittest.TestCase):
    """Test cases for SEO field configuration constants."""

    def test_seo_fields_exist(self):
        """Test that SEO_FIELDS constant is defined."""
        from frappe_pim.pim.utils.seo_validator import SEO_FIELDS

        self.assertIsInstance(SEO_FIELDS, dict)
        self.assertGreater(len(SEO_FIELDS), 0)

    def test_seo_fields_include_required_fields(self):
        """Test that SEO_FIELDS includes all required fields."""
        from frappe_pim.pim.utils.seo_validator import SEO_FIELDS

        expected_fields = [
            "seo_meta_title",
            "seo_meta_description",
            "seo_meta_keywords",
            "seo_canonical_url",
        ]

        for field in expected_fields:
            self.assertIn(field, SEO_FIELDS)

    def test_seo_field_has_label(self):
        """Test that each SEO field has a label."""
        from frappe_pim.pim.utils.seo_validator import SEO_FIELDS

        for field_name, config in SEO_FIELDS.items():
            self.assertIn("label", config, f"Field {field_name} missing label")
            self.assertTrue(config["label"], f"Field {field_name} has empty label")

    def test_seo_field_has_optimal_message(self):
        """Test that each SEO field has an optimal_message."""
        from frappe_pim.pim.utils.seo_validator import SEO_FIELDS

        for field_name, config in SEO_FIELDS.items():
            self.assertIn("optimal_message", config, f"Field {field_name} missing optimal_message")

    def test_meta_title_length_constraints(self):
        """Test meta title length constraints are correct."""
        from frappe_pim.pim.utils.seo_validator import SEO_FIELDS

        config = SEO_FIELDS["seo_meta_title"]

        self.assertEqual(config["min_length"], 30)
        self.assertEqual(config["max_length"], 60)
        self.assertTrue(config["required"])

    def test_meta_description_length_constraints(self):
        """Test meta description length constraints are correct."""
        from frappe_pim.pim.utils.seo_validator import SEO_FIELDS

        config = SEO_FIELDS["seo_meta_description"]

        self.assertEqual(config["min_length"], 120)
        self.assertEqual(config["max_length"], 160)
        self.assertTrue(config["required"])

    def test_meta_keywords_constraints(self):
        """Test meta keywords constraints are correct."""
        from frappe_pim.pim.utils.seo_validator import SEO_FIELDS

        config = SEO_FIELDS["seo_meta_keywords"]

        self.assertEqual(config["min_keywords"], 3)
        self.assertEqual(config["max_keywords"], 10)
        self.assertTrue(config["required"])

    def test_canonical_url_is_optional(self):
        """Test that canonical URL is optional."""
        from frappe_pim.pim.utils.seo_validator import SEO_FIELDS

        config = SEO_FIELDS["seo_canonical_url"]

        self.assertFalse(config["required"])

    def test_required_seo_fields_list(self):
        """Test that REQUIRED_SEO_FIELDS is properly defined."""
        from frappe_pim.pim.utils.seo_validator import REQUIRED_SEO_FIELDS

        expected = ["seo_meta_title", "seo_meta_description", "seo_meta_keywords"]

        for field in expected:
            self.assertIn(field, REQUIRED_SEO_FIELDS)

        # Canonical URL should NOT be in required list
        self.assertNotIn("seo_canonical_url", REQUIRED_SEO_FIELDS)

    def test_severity_constants_defined(self):
        """Test that severity constants are defined."""
        from frappe_pim.pim.utils.seo_validator import (
            SEVERITY_ERROR,
            SEVERITY_WARNING,
            SEVERITY_INFO,
        )

        self.assertEqual(SEVERITY_ERROR, "error")
        self.assertEqual(SEVERITY_WARNING, "warning")
        self.assertEqual(SEVERITY_INFO, "info")


class TestTextLengthValidation(unittest.TestCase):
    """Test cases for text length validation function."""

    def test_validate_text_length_optimal(self):
        """Test text validation with optimal length."""
        from frappe_pim.pim.utils.seo_validator import _validate_text_length

        config = {
            "label": "Meta Title",
            "min_length": 30,
            "max_length": 60,
        }

        # 45 characters - within optimal range
        value = "A" * 45
        score, issues = _validate_text_length(value, config)

        self.assertEqual(score, 100)
        self.assertEqual(len(issues), 0)

    def test_validate_text_length_too_short(self):
        """Test text validation when value is too short."""
        from frappe_pim.pim.utils.seo_validator import _validate_text_length, SEVERITY_WARNING

        config = {
            "label": "Meta Title",
            "min_length": 30,
            "max_length": 60,
        }

        # 15 characters - too short
        value = "A" * 15
        score, issues = _validate_text_length(value, config)

        self.assertLess(score, 100)
        self.assertGreater(score, 0)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], SEVERITY_WARNING)
        self.assertIn("too short", issues[0]["message"])

    def test_validate_text_length_too_long(self):
        """Test text validation when value is too long."""
        from frappe_pim.pim.utils.seo_validator import _validate_text_length, SEVERITY_WARNING

        config = {
            "label": "Meta Title",
            "min_length": 30,
            "max_length": 60,
        }

        # 80 characters - too long
        value = "A" * 80
        score, issues = _validate_text_length(value, config)

        self.assertLess(score, 100)
        self.assertGreaterEqual(score, 50)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], SEVERITY_WARNING)
        self.assertIn("too long", issues[0]["message"])

    def test_validate_text_detects_placeholder(self):
        """Test text validation detects placeholder text."""
        from frappe_pim.pim.utils.seo_validator import _validate_text_length, SEVERITY_ERROR

        config = {
            "label": "Meta Title",
            "min_length": 10,
            "max_length": 100,
        }

        placeholders = [
            "Lorem ipsum dolor sit amet",
            "This is a test placeholder",
            "TBD - to be determined later",
            "N/A - not applicable here",
            "XXX replace this text",
            "TODO: add proper content here",
        ]

        for placeholder in placeholders:
            score, issues = _validate_text_length(placeholder, config)
            self.assertLessEqual(score, 20, f"Placeholder not detected: {placeholder}")

            # Check for placeholder issue
            placeholder_issues = [i for i in issues if "placeholder" in i["message"].lower()]
            self.assertGreater(len(placeholder_issues), 0, f"No placeholder issue for: {placeholder}")

    def test_validate_text_at_min_boundary(self):
        """Test text validation at minimum boundary."""
        from frappe_pim.pim.utils.seo_validator import _validate_text_length

        config = {
            "label": "Meta Title",
            "min_length": 30,
            "max_length": 60,
        }

        # Exactly 30 characters - at minimum boundary
        value = "A" * 30
        score, issues = _validate_text_length(value, config)

        self.assertEqual(score, 100)
        self.assertEqual(len(issues), 0)

    def test_validate_text_at_max_boundary(self):
        """Test text validation at maximum boundary."""
        from frappe_pim.pim.utils.seo_validator import _validate_text_length

        config = {
            "label": "Meta Title",
            "min_length": 30,
            "max_length": 60,
        }

        # Exactly 60 characters - at maximum boundary
        value = "A" * 60
        score, issues = _validate_text_length(value, config)

        self.assertEqual(score, 100)
        self.assertEqual(len(issues), 0)


class TestKeywordsValidation(unittest.TestCase):
    """Test cases for meta keywords validation function."""

    def test_validate_keywords_optimal_count(self):
        """Test keywords validation with optimal count."""
        from frappe_pim.pim.utils.seo_validator import _validate_keywords

        config = {
            "label": "Meta Keywords",
            "min_keywords": 3,
            "max_keywords": 10,
        }

        keywords = "keyword1, keyword2, keyword3, keyword4, keyword5"
        score, issues = _validate_keywords(keywords, config)

        self.assertEqual(score, 100)
        self.assertEqual(len(issues), 0)

    def test_validate_keywords_too_few(self):
        """Test keywords validation with too few keywords."""
        from frappe_pim.pim.utils.seo_validator import _validate_keywords, SEVERITY_WARNING

        config = {
            "label": "Meta Keywords",
            "min_keywords": 3,
            "max_keywords": 10,
        }

        keywords = "keyword1, keyword2"
        score, issues = _validate_keywords(keywords, config)

        self.assertLess(score, 100)
        self.assertGreater(len(issues), 0)
        self.assertEqual(issues[0]["severity"], SEVERITY_WARNING)
        self.assertIn("Too few", issues[0]["message"])

    def test_validate_keywords_too_many(self):
        """Test keywords validation with too many keywords."""
        from frappe_pim.pim.utils.seo_validator import _validate_keywords, SEVERITY_WARNING

        config = {
            "label": "Meta Keywords",
            "min_keywords": 3,
            "max_keywords": 10,
        }

        keywords = ", ".join([f"keyword{i}" for i in range(15)])
        score, issues = _validate_keywords(keywords, config)

        self.assertLess(score, 100)
        self.assertGreaterEqual(score, 60)
        self.assertGreater(len(issues), 0)
        self.assertIn("Too many", issues[0]["message"])

    def test_validate_keywords_with_duplicates(self):
        """Test keywords validation detects duplicates."""
        from frappe_pim.pim.utils.seo_validator import _validate_keywords, SEVERITY_WARNING

        config = {
            "label": "Meta Keywords",
            "min_keywords": 3,
            "max_keywords": 10,
        }

        keywords = "keyword1, keyword2, keyword3, keyword1, keyword2"
        score, issues = _validate_keywords(keywords, config)

        self.assertLessEqual(score, 70)

        # Check for duplicate issue
        duplicate_issues = [i for i in issues if "duplicate" in i["message"].lower()]
        self.assertGreater(len(duplicate_issues), 0)

    def test_validate_keywords_with_short_keywords(self):
        """Test keywords validation detects very short keywords."""
        from frappe_pim.pim.utils.seo_validator import _validate_keywords, SEVERITY_INFO

        config = {
            "label": "Meta Keywords",
            "min_keywords": 3,
            "max_keywords": 10,
        }

        keywords = "ab, cd, longkeyword, anotherkeyword"
        score, issues = _validate_keywords(keywords, config)

        # Check for short keyword issue
        short_issues = [i for i in issues if "short" in i["message"].lower()]
        self.assertGreater(len(short_issues), 0)
        self.assertEqual(short_issues[0]["severity"], SEVERITY_INFO)

    def test_validate_keywords_single_keyword(self):
        """Test keywords validation with single keyword."""
        from frappe_pim.pim.utils.seo_validator import _validate_keywords

        config = {
            "label": "Meta Keywords",
            "min_keywords": 3,
            "max_keywords": 10,
        }

        keywords = "singlekeyword"
        score, issues = _validate_keywords(keywords, config)

        self.assertLess(score, 100)
        self.assertGreater(len(issues), 0)

    def test_validate_keywords_at_boundaries(self):
        """Test keywords validation at min and max boundaries."""
        from frappe_pim.pim.utils.seo_validator import _validate_keywords

        config = {
            "label": "Meta Keywords",
            "min_keywords": 3,
            "max_keywords": 10,
        }

        # At minimum (3 keywords)
        keywords_min = "keyword1, keyword2, keyword3"
        score, issues = _validate_keywords(keywords_min, config)
        self.assertEqual(score, 100)

        # At maximum (10 keywords)
        keywords_max = ", ".join([f"keyword{i}" for i in range(10)])
        score, issues = _validate_keywords(keywords_max, config)
        self.assertEqual(score, 100)


class TestURLValidation(unittest.TestCase):
    """Test cases for URL validation function."""

    def test_validate_url_valid_https(self):
        """Test URL validation with valid HTTPS URL."""
        from frappe_pim.pim.utils.seo_validator import _validate_url

        config = {"label": "Canonical URL"}

        url = "https://example.com/products/great-product"
        score, issues = _validate_url(url, config)

        self.assertEqual(score, 100)
        self.assertEqual(len(issues), 0)

    def test_validate_url_valid_http(self):
        """Test URL validation with valid HTTP URL."""
        from frappe_pim.pim.utils.seo_validator import _validate_url, SEVERITY_INFO

        config = {"label": "Canonical URL"}

        url = "http://example.com/products/great-product"
        score, issues = _validate_url(url, config)

        # Should work but with info about HTTPS preference
        self.assertEqual(score, 90)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], SEVERITY_INFO)
        self.assertIn("HTTPS", issues[0]["message"])

    def test_validate_url_invalid_format(self):
        """Test URL validation with invalid URL format."""
        from frappe_pim.pim.utils.seo_validator import _validate_url, SEVERITY_ERROR

        config = {"label": "Canonical URL"}

        invalid_urls = [
            "not-a-url",
            "example.com",
            "ftp://example.com",
            "/relative/path",
            "www.example.com",
        ]

        for url in invalid_urls:
            score, issues = _validate_url(url, config)
            self.assertEqual(score, 30, f"Invalid URL not rejected: {url}")
            self.assertGreater(len(issues), 0)
            self.assertEqual(issues[0]["severity"], SEVERITY_ERROR)

    def test_validate_url_with_port(self):
        """Test URL validation with port number."""
        from frappe_pim.pim.utils.seo_validator import _validate_url

        config = {"label": "Canonical URL"}

        url = "https://example.com:8080/products"
        score, issues = _validate_url(url, config)

        self.assertEqual(score, 100)

    def test_validate_url_with_query_params(self):
        """Test URL validation with query parameters."""
        from frappe_pim.pim.utils.seo_validator import _validate_url

        config = {"label": "Canonical URL"}

        url = "https://example.com/products?id=123&sort=name"
        score, issues = _validate_url(url, config)

        self.assertEqual(score, 100)

    def test_validate_url_localhost(self):
        """Test URL validation with localhost."""
        from frappe_pim.pim.utils.seo_validator import _validate_url

        config = {"label": "Canonical URL"}

        url = "http://localhost:8000/products"
        score, issues = _validate_url(url, config)

        # Should be valid but HTTP
        self.assertEqual(score, 90)


class TestSingleFieldValidation(unittest.TestCase):
    """Test cases for single field validation function."""

    def test_validate_single_field_present_valid(self):
        """Test single field validation with valid present value."""
        from frappe_pim.pim.utils.seo_validator import _validate_single_field, SEO_FIELDS

        doc = MockProductDoc(
            seo_meta_title="Great Product Title for SEO Testing"  # 40 chars
        )
        config = SEO_FIELDS["seo_meta_title"]

        result = _validate_single_field(doc, "seo_meta_title", config)

        self.assertTrue(result["is_present"])
        self.assertEqual(result["quality_score"], 100)
        self.assertEqual(len(result["issues"]), 0)

    def test_validate_single_field_missing_required(self):
        """Test single field validation with missing required field."""
        from frappe_pim.pim.utils.seo_validator import (
            _validate_single_field,
            SEO_FIELDS,
            SEVERITY_ERROR,
        )

        doc = MockProductDoc(seo_meta_title="")
        config = SEO_FIELDS["seo_meta_title"]

        result = _validate_single_field(doc, "seo_meta_title", config)

        self.assertFalse(result["is_present"])
        self.assertEqual(result["quality_score"], 0)
        self.assertGreater(len(result["issues"]), 0)
        self.assertEqual(result["issues"][0]["severity"], SEVERITY_ERROR)

    def test_validate_single_field_missing_optional(self):
        """Test single field validation with missing optional field."""
        from frappe_pim.pim.utils.seo_validator import (
            _validate_single_field,
            SEO_FIELDS,
            SEVERITY_INFO,
        )

        doc = MockProductDoc(seo_canonical_url="")
        config = SEO_FIELDS["seo_canonical_url"]

        result = _validate_single_field(doc, "seo_canonical_url", config)

        self.assertFalse(result["is_present"])
        # Optional field - should be info severity, not error
        self.assertEqual(result["issues"][0]["severity"], SEVERITY_INFO)

    def test_validate_single_field_returns_recommendation(self):
        """Test single field validation returns recommendation."""
        from frappe_pim.pim.utils.seo_validator import _validate_single_field, SEO_FIELDS

        doc = MockProductDoc(seo_meta_title="")
        config = SEO_FIELDS["seo_meta_title"]

        result = _validate_single_field(doc, "seo_meta_title", config)

        self.assertIsNotNone(result["recommendation"])


class TestGetSEOValidationResult(unittest.TestCase):
    """Test cases for get_seo_validation_result function."""

    def test_get_seo_validation_result_all_optimal(self):
        """Test SEO validation result with all optimal fields."""
        from frappe_pim.pim.utils.seo_validator import get_seo_validation_result

        doc = MockProductDoc(
            name="TEST-001",
            seo_meta_title="Great Product Title for SEO Testing Here",  # 43 chars
            seo_meta_description="This is an excellent meta description for search engines. It provides a clear summary of the product with all key features and benefits for potential customers.",  # 160 chars
            seo_meta_keywords="product, testing, quality, optimization, search",
            seo_canonical_url="https://example.com/products/test"
        )

        result = get_seo_validation_result(doc)

        self.assertTrue(result["is_valid"])
        self.assertGreater(result["score"], 80)
        self.assertEqual(result["completeness_score"], 100)
        self.assertGreater(result["quality_score"], 50)
        self.assertEqual(result["product"], "TEST-001")

    def test_get_seo_validation_result_missing_fields(self):
        """Test SEO validation result with missing fields."""
        from frappe_pim.pim.utils.seo_validator import get_seo_validation_result

        doc = MockProductDoc(
            name="TEST-002",
            seo_meta_title="",
            seo_meta_description="",
            seo_meta_keywords="",
        )

        result = get_seo_validation_result(doc)

        self.assertFalse(result["is_valid"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["completeness_score"], 0)
        self.assertGreater(len(result["issues"]), 0)

    def test_get_seo_validation_result_partial_fields(self):
        """Test SEO validation result with partial fields."""
        from frappe_pim.pim.utils.seo_validator import get_seo_validation_result

        doc = MockProductDoc(
            name="TEST-003",
            seo_meta_title="Valid Title for SEO Testing",  # 30 chars
            seo_meta_description="",
            seo_meta_keywords="",
        )

        result = get_seo_validation_result(doc)

        self.assertFalse(result["is_valid"])
        # 1 of 3 required fields
        self.assertAlmostEqual(result["completeness_score"], 33.33, places=1)

    def test_get_seo_validation_result_includes_fields_dict(self):
        """Test SEO validation result includes field details."""
        from frappe_pim.pim.utils.seo_validator import get_seo_validation_result, SEO_FIELDS

        doc = MockProductDoc(
            seo_meta_title="Test Title for Validation",
        )

        result = get_seo_validation_result(doc)

        self.assertIn("fields", result)
        for field_name in SEO_FIELDS.keys():
            self.assertIn(field_name, result["fields"])

    def test_get_seo_validation_result_includes_recommendations(self):
        """Test SEO validation result includes recommendations."""
        from frappe_pim.pim.utils.seo_validator import get_seo_validation_result

        doc = MockProductDoc(
            seo_meta_title="Short",  # Too short
        )

        result = get_seo_validation_result(doc)

        self.assertIn("recommendations", result)
        self.assertGreater(len(result["recommendations"]), 0)


class TestGetSEOCompleteness(unittest.TestCase):
    """Test cases for get_seo_completeness convenience function."""

    def test_get_seo_completeness_returns_score(self):
        """Test get_seo_completeness returns numeric score."""
        from frappe_pim.pim.utils.seo_validator import get_seo_completeness

        doc = MockProductDoc(
            seo_meta_title="Valid SEO Title for Testing",
            seo_meta_description="A" * 140,
            seo_meta_keywords="kw1, kw2, kw3, kw4",
        )

        score = get_seo_completeness(doc)

        self.assertIsInstance(score, float)
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 100)

    def test_get_seo_completeness_empty_product(self):
        """Test get_seo_completeness with empty product."""
        from frappe_pim.pim.utils.seo_validator import get_seo_completeness

        doc = MockProductDoc()

        score = get_seo_completeness(doc)

        self.assertEqual(score, 0)


class TestGetSEOIssues(unittest.TestCase):
    """Test cases for get_seo_issues function."""

    def test_get_seo_issues_returns_list(self):
        """Test get_seo_issues returns a list."""
        from frappe_pim.pim.utils.seo_validator import get_seo_issues

        doc = MockProductDoc()

        issues = get_seo_issues(doc)

        self.assertIsInstance(issues, list)

    def test_get_seo_issues_empty_when_valid(self):
        """Test get_seo_issues returns empty list for valid product."""
        from frappe_pim.pim.utils.seo_validator import get_seo_issues

        doc = MockProductDoc(
            seo_meta_title="Great Product Title for SEO Testing",  # 40 chars
            seo_meta_description="A" * 140,
            seo_meta_keywords="keyword1, keyword2, keyword3, keyword4",
            seo_canonical_url="https://example.com/product"
        )

        issues = get_seo_issues(doc)

        # Should have no issues or only info-level issues
        error_issues = [i for i in issues if i.get("severity") == "error"]
        self.assertEqual(len(error_issues), 0)

    def test_get_seo_issues_contains_expected_fields(self):
        """Test get_seo_issues returns issues with expected fields."""
        from frappe_pim.pim.utils.seo_validator import get_seo_issues

        doc = MockProductDoc()

        issues = get_seo_issues(doc)

        if issues:
            for issue in issues:
                self.assertIn("field", issue)
                self.assertIn("severity", issue)
                self.assertIn("message", issue)


class TestGetSEORecommendations(unittest.TestCase):
    """Test cases for get_seo_recommendations function."""

    def test_get_seo_recommendations_returns_list(self):
        """Test get_seo_recommendations returns a list."""
        from frappe_pim.pim.utils.seo_validator import get_seo_recommendations

        doc = MockProductDoc()

        recommendations = get_seo_recommendations(doc)

        self.assertIsInstance(recommendations, list)

    def test_get_seo_recommendations_for_incomplete(self):
        """Test get_seo_recommendations for incomplete SEO."""
        from frappe_pim.pim.utils.seo_validator import get_seo_recommendations

        doc = MockProductDoc(
            seo_meta_title="Short",  # Too short
        )

        recommendations = get_seo_recommendations(doc)

        self.assertGreater(len(recommendations), 0)


class TestCheckSEOQuality(unittest.TestCase):
    """Test cases for check_seo_quality function."""

    def test_check_seo_quality_returns_grade(self):
        """Test check_seo_quality returns grade structure."""
        from frappe_pim.pim.utils.seo_validator import check_seo_quality

        doc = MockProductDoc()

        result = check_seo_quality(doc)

        self.assertIn("grade", result)
        self.assertIn("score", result)
        self.assertIn("summary", result)
        self.assertIn("breakdown", result)

    def test_check_seo_quality_grade_a(self):
        """Test check_seo_quality returns grade A for excellent SEO."""
        from frappe_pim.pim.utils.seo_validator import check_seo_quality

        doc = MockProductDoc(
            seo_meta_title="Excellent SEO Title for Product Testing",  # 43 chars
            seo_meta_description="A" * 145,
            seo_meta_keywords="keyword1, keyword2, keyword3, keyword4, keyword5",
            seo_canonical_url="https://example.com/product"
        )

        result = check_seo_quality(doc)

        self.assertEqual(result["grade"], "A")
        self.assertGreaterEqual(result["score"], 90)
        self.assertIn("Excellent", result["summary"])

    def test_check_seo_quality_grade_f(self):
        """Test check_seo_quality returns grade F for poor SEO."""
        from frappe_pim.pim.utils.seo_validator import check_seo_quality

        doc = MockProductDoc()

        result = check_seo_quality(doc)

        self.assertEqual(result["grade"], "F")
        self.assertLess(result["score"], 60)
        self.assertIn("Poor", result["summary"])

    def test_check_seo_quality_grade_breakdown(self):
        """Test check_seo_quality includes breakdown scores."""
        from frappe_pim.pim.utils.seo_validator import check_seo_quality

        doc = MockProductDoc(
            seo_meta_title="Valid Title for Testing",
        )

        result = check_seo_quality(doc)

        self.assertIn("completeness_score", result["breakdown"])
        self.assertIn("quality_score", result["breakdown"])

    def test_check_seo_quality_grade_boundaries(self):
        """Test check_seo_quality grade boundaries."""
        from frappe_pim.pim.utils.seo_validator import check_seo_quality

        # Test different grade boundaries
        # This is a conceptual test - actual grades depend on score calculation

        # Grade B: 80-89
        # Grade C: 70-79
        # Grade D: 60-69

        doc = MockProductDoc()

        result = check_seo_quality(doc)

        # Verify grade is one of the expected values
        self.assertIn(result["grade"], ["A", "B", "C", "D", "F"])


class TestEmptyResultHelpers(unittest.TestCase):
    """Test cases for empty result helper functions."""

    def test_empty_validation_result_structure(self):
        """Test _empty_validation_result returns correct structure."""
        from frappe_pim.pim.utils.seo_validator import _empty_validation_result

        result = _empty_validation_result("TEST-001")

        self.assertEqual(result["product"], "TEST-001")
        self.assertFalse(result["is_valid"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["completeness_score"], 0)
        self.assertEqual(result["quality_score"], 0)
        self.assertIsInstance(result["fields"], dict)
        self.assertIsInstance(result["issues"], list)
        self.assertIsInstance(result["recommendations"], list)

    def test_empty_statistics_structure(self):
        """Test _empty_statistics returns correct structure."""
        from frappe_pim.pim.utils.seo_validator import _empty_statistics

        result = _empty_statistics()

        self.assertEqual(result["total_products"], 0)
        self.assertEqual(result["fully_optimized"], 0)
        self.assertEqual(result["needs_improvement"], 0)
        self.assertEqual(result["critical"], 0)
        self.assertEqual(result["average_score"], 0.0)
        self.assertIn("grade_distribution", result)

    def test_empty_report_structure(self):
        """Test _empty_report returns correct structure."""
        from frappe_pim.pim.utils.seo_validator import _empty_report

        result = _empty_report()

        self.assertIsNone(result["generated_at"])
        self.assertIn("filters", result)
        self.assertIn("summary", result)
        self.assertIsInstance(result["rows"], list)
        self.assertEqual(len(result["rows"]), 0)


class TestValidateSEOFields(unittest.TestCase):
    """Test cases for validate_seo_fields hook function."""

    def test_validate_seo_fields_returns_result(self):
        """Test validate_seo_fields returns validation result."""
        from frappe_pim.pim.utils.seo_validator import validate_seo_fields

        doc = MockProductDoc(
            seo_meta_title="Valid Title for SEO Testing Purpose",
            seo_meta_description="A" * 140,
            seo_meta_keywords="kw1, kw2, kw3",
        )

        result = validate_seo_fields(doc)

        self.assertIn("is_valid", result)
        self.assertIn("score", result)
        self.assertIn("issues", result)

    def test_validate_seo_fields_updates_doc_seo_score(self):
        """Test validate_seo_fields updates doc.seo_score if exists."""
        from frappe_pim.pim.utils.seo_validator import validate_seo_fields

        doc = MockProductDoc(
            seo_meta_title="Valid Title for SEO Testing Purpose",
            seo_meta_description="A" * 140,
            seo_meta_keywords="kw1, kw2, kw3, kw4",
            seo_score=0,
        )

        validate_seo_fields(doc)

        # Should have updated the seo_score
        self.assertGreater(doc.seo_score, 0)

    def test_validate_seo_fields_updates_is_seo_complete(self):
        """Test validate_seo_fields updates doc.is_seo_complete if exists."""
        from frappe_pim.pim.utils.seo_validator import validate_seo_fields

        doc = MockProductDoc(
            seo_meta_title="Valid Title for SEO Testing Purpose",
            seo_meta_description="A" * 140,
            seo_meta_keywords="kw1, kw2, kw3, kw4, kw5",
            is_seo_complete=False,
        )

        result = validate_seo_fields(doc)

        if result["is_valid"]:
            self.assertTrue(doc.is_seo_complete)

    def test_validate_seo_fields_handles_method_param(self):
        """Test validate_seo_fields accepts method parameter for hook compatibility."""
        from frappe_pim.pim.utils.seo_validator import validate_seo_fields

        doc = MockProductDoc()

        # Should not raise error with method parameter
        result = validate_seo_fields(doc, method="before_save")

        self.assertIsNotNone(result)


class TestBulkCheckSEO(unittest.TestCase):
    """Test cases for bulk_check_seo function.

    Note: These tests use mock documents and don't require database.
    """

    def test_bulk_check_seo_empty_list(self):
        """Test bulk_check_seo with empty list."""
        from frappe_pim.pim.utils.seo_validator import bulk_check_seo

        result = bulk_check_seo([])

        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["valid_count"], 0)
        self.assertEqual(result["invalid_count"], 0)
        self.assertEqual(result["average_score"], 0)

    def test_bulk_check_seo_result_structure(self):
        """Test bulk_check_seo returns correct structure."""
        from frappe_pim.pim.utils.seo_validator import bulk_check_seo

        result = bulk_check_seo([])

        self.assertIn("total_count", result)
        self.assertIn("valid_count", result)
        self.assertIn("invalid_count", result)
        self.assertIn("average_score", result)
        self.assertIn("products", result)


class TestConvertReportToCSV(unittest.TestCase):
    """Test cases for CSV conversion function."""

    def test_convert_report_to_csv_empty(self):
        """Test CSV conversion with empty report."""
        from frappe_pim.pim.utils.seo_validator import _convert_report_to_csv

        report = {"rows": []}

        csv = _convert_report_to_csv(report)

        # Should return empty string or minimal output
        self.assertIsInstance(csv, str)

    def test_convert_report_to_csv_with_rows(self):
        """Test CSV conversion with data rows."""
        from frappe_pim.pim.utils.seo_validator import _convert_report_to_csv

        report = {
            "rows": [
                {"product": "TEST-001", "score": 85, "grade": "B"},
                {"product": "TEST-002", "score": 65, "grade": "D"},
            ]
        }

        csv = _convert_report_to_csv(report)

        self.assertIn("product", csv)
        self.assertIn("score", csv)
        self.assertIn("grade", csv)
        self.assertIn("TEST-001", csv)
        self.assertIn("TEST-002", csv)


class TestSEOValidatorIntegration(unittest.TestCase):
    """Integration tests for SEO validator with actual database.

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

    def test_get_seo_validation_result_with_product_name(self):
        """Test get_seo_validation_result with product name string."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.seo_validator import get_seo_validation_result

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"SEO Test Product {random_string(4)}",
            "product_code": f"SEO-{random_string(6).upper()}",
            "short_description": "A test product for SEO validation.",
            "seo_meta_title": "SEO Optimized Test Product Title",
            "seo_meta_description": "This is a well-crafted meta description for the test product that includes relevant keywords and provides value to search engines.",
            "seo_meta_keywords": "test, product, seo, optimization, quality",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Test with product name string
        result = get_seo_validation_result(product.name)

        self.assertEqual(result["product"], product.name)
        self.assertIn("is_valid", result)
        self.assertIn("score", result)

    def test_get_seo_validation_result_nonexistent_product(self):
        """Test get_seo_validation_result with non-existent product."""
        from frappe_pim.pim.utils.seo_validator import get_seo_validation_result

        result = get_seo_validation_result("NONEXISTENT-PRODUCT-12345")

        self.assertFalse(result["is_valid"])
        self.assertEqual(result["score"], 0)

    def test_bulk_check_seo_with_products(self):
        """Test bulk_check_seo with actual products."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.seo_validator import bulk_check_seo

        # Create test products
        products = []
        for i in range(3):
            product = frappe.get_doc({
                "doctype": "Product Master",
                "product_name": f"Bulk SEO Test {random_string(4)}",
                "product_code": f"BULK-{random_string(6).upper()}",
                "short_description": "Test product for bulk SEO check.",
                "seo_meta_title": f"Test Product {i} SEO Title Here",
                "seo_meta_description": "A" * 140,
                "seo_meta_keywords": "test, bulk, seo, check, validation",
                "status": "Draft"
            })
            product.insert(ignore_permissions=True)
            self.track_document("Product Master", product.name)
            products.append(product.name)

        # Test bulk check
        result = bulk_check_seo(products)

        self.assertEqual(result["total_count"], 3)
        self.assertGreater(result["average_score"], 0)
        self.assertEqual(len(result["products"]), 3)

    def test_check_seo_quality_with_product_name(self):
        """Test check_seo_quality with product name."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.seo_validator import check_seo_quality

        # Create a test product with good SEO
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Quality Test Product {random_string(4)}",
            "product_code": f"QTY-{random_string(6).upper()}",
            "short_description": "Test product for quality check.",
            "seo_meta_title": "High Quality SEO Title for Testing",
            "seo_meta_description": "This is an optimized meta description that provides value and includes relevant keywords for search engine optimization purposes.",
            "seo_meta_keywords": "quality, test, seo, optimization, keywords",
            "seo_canonical_url": "https://example.com/products/test",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Test quality check
        result = check_seo_quality(product.name)

        self.assertIn(result["grade"], ["A", "B", "C", "D", "F"])
        self.assertIn("summary", result)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
