# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt
"""Product Scoring Unit Tests

This module contains unit tests for:
- Product scoring calculation
- Content completeness scoring
- SEO optimization scoring
- Media scoring
- Translation coverage scoring
- Attribute scoring
- Market performance scoring
- Weighted score calculation

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).
"""

import unittest


class MockProductDoc:
    """Mock product document for testing scoring functions without database."""

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
        self.image = kwargs.get("image", "")
        self.product_media = kwargs.get("product_media", [])
        self.translations = kwargs.get("translations", [])
        self.attributes = kwargs.get("attributes", [])
        self.product_attributes = kwargs.get("product_attributes", [])
        self.product_family = kwargs.get("product_family", None)

        # Set any additional fields
        for key, value in kwargs.items():
            if not hasattr(self, key):
                setattr(self, key, value)

    def get(self, field, default=None):
        """Get field value with default."""
        return getattr(self, field, default)


class MockAttributeValue:
    """Mock attribute value for testing."""

    def __init__(self, attribute, value):
        self.attribute = attribute
        self.attribute_value = value
        self.value = value


class MockMedia:
    """Mock media item for testing."""

    def __init__(self, is_primary=False, file_url=None):
        self.is_primary = is_primary
        self.file_url = file_url or "/files/test.jpg"


class MockTranslation:
    """Mock translation item for testing."""

    def __init__(self, language, field_name, is_verified=False):
        self.language = language
        self.field_name = field_name
        self.is_verified = is_verified


class TestScoringConstants(unittest.TestCase):
    """Test cases for scoring module constants and configuration."""

    def test_default_weights_exist(self):
        """Test that default weights are defined."""
        from frappe_pim.pim.utils.scoring import DEFAULT_WEIGHTS

        self.assertIn("content_weight", DEFAULT_WEIGHTS)
        self.assertIn("media_weight", DEFAULT_WEIGHTS)
        self.assertIn("seo_weight", DEFAULT_WEIGHTS)
        self.assertIn("translation_weight", DEFAULT_WEIGHTS)
        self.assertIn("attribute_weight", DEFAULT_WEIGHTS)
        self.assertIn("market_weight", DEFAULT_WEIGHTS)

    def test_default_weights_sum(self):
        """Test that default weights sum to 100."""
        from frappe_pim.pim.utils.scoring import DEFAULT_WEIGHTS

        total = sum(DEFAULT_WEIGHTS.values())
        self.assertEqual(total, 100)

    def test_required_content_fields_defined(self):
        """Test that required content fields are defined."""
        from frappe_pim.pim.utils.scoring import REQUIRED_CONTENT_FIELDS

        self.assertIn("product_name", REQUIRED_CONTENT_FIELDS)
        self.assertIn("short_description", REQUIRED_CONTENT_FIELDS)
        self.assertIn("long_description", REQUIRED_CONTENT_FIELDS)

    def test_required_seo_fields_defined(self):
        """Test that required SEO fields are defined."""
        from frappe_pim.pim.utils.scoring import REQUIRED_SEO_FIELDS

        self.assertIn("seo_meta_title", REQUIRED_SEO_FIELDS)
        self.assertIn("seo_meta_description", REQUIRED_SEO_FIELDS)
        self.assertIn("seo_meta_keywords", REQUIRED_SEO_FIELDS)

    def test_seo_thresholds_defined(self):
        """Test that SEO threshold constants are defined."""
        from frappe_pim.pim.utils.scoring import (
            SEO_META_TITLE_MAX_LENGTH,
            SEO_META_TITLE_MIN_LENGTH,
            SEO_META_DESCRIPTION_MAX_LENGTH,
            SEO_META_DESCRIPTION_MIN_LENGTH,
        )

        self.assertEqual(SEO_META_TITLE_MAX_LENGTH, 60)
        self.assertEqual(SEO_META_TITLE_MIN_LENGTH, 30)
        self.assertEqual(SEO_META_DESCRIPTION_MAX_LENGTH, 160)
        self.assertEqual(SEO_META_DESCRIPTION_MIN_LENGTH, 120)


class TestContentScoring(unittest.TestCase):
    """Test cases for content scoring calculations."""

    def test_content_score_all_fields_filled(self):
        """Test content score with all fields filled."""
        from frappe_pim.pim.utils.scoring import calculate_content_score

        doc = MockProductDoc(
            product_name="Test Product Name",
            short_description="This is a short description for the product.",
            long_description="This is a much longer description that provides detailed information about the product features and benefits."
        )

        scores = calculate_content_score(doc)

        self.assertIn("completeness", scores)
        self.assertIn("quality", scores)
        self.assertEqual(scores["completeness"], 100.0)
        self.assertGreater(scores["quality"], 0)

    def test_content_score_no_fields_filled(self):
        """Test content score with no fields filled."""
        from frappe_pim.pim.utils.scoring import calculate_content_score

        doc = MockProductDoc()

        scores = calculate_content_score(doc)

        self.assertEqual(scores["completeness"], 0)
        self.assertEqual(scores["quality"], 0)

    def test_content_score_partial_fields(self):
        """Test content score with some fields filled."""
        from frappe_pim.pim.utils.scoring import calculate_content_score

        doc = MockProductDoc(
            product_name="Test Product",
            short_description="",  # Empty
            long_description=""   # Empty
        )

        scores = calculate_content_score(doc)

        # With 1 of 3 core fields filled
        self.assertGreater(scores["completeness"], 0)
        self.assertLess(scores["completeness"], 100)


class TestContentQualityEvaluation(unittest.TestCase):
    """Test cases for content quality evaluation."""

    def test_evaluate_product_name_optimal(self):
        """Test product name quality with optimal length."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        # Optimal length: 5-100 characters
        score = evaluate_content_quality("product_name", "Great Product Name")

        self.assertEqual(score, 100)

    def test_evaluate_product_name_too_short(self):
        """Test product name quality with too short name."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        score = evaluate_content_quality("product_name", "AB")

        self.assertLess(score, 100)

    def test_evaluate_product_name_too_long(self):
        """Test product name quality with too long name."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        long_name = "A" * 120  # Over 100 characters
        score = evaluate_content_quality("product_name", long_name)

        self.assertEqual(score, 80)  # Slightly penalized

    def test_evaluate_short_description_optimal(self):
        """Test short description quality with optimal length."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        # Optimal: 50-300 characters
        desc = "This is a great product description that provides essential details about the product."
        score = evaluate_content_quality("short_description", desc)

        self.assertEqual(score, 100)

    def test_evaluate_short_description_too_short(self):
        """Test short description quality when too short."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        score = evaluate_content_quality("short_description", "Short")

        self.assertLess(score, 100)

    def test_evaluate_long_description_optimal(self):
        """Test long description quality with optimal length."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        # Optimal: 200+ characters
        desc = "A" * 250
        score = evaluate_content_quality("long_description", desc)

        self.assertEqual(score, 100)

    def test_evaluate_content_with_placeholder(self):
        """Test content quality detection of placeholder text."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        # Placeholder text should get low score
        score = evaluate_content_quality("product_name", "Lorem ipsum dolor sit amet")

        self.assertEqual(score, 20)

    def test_evaluate_content_with_tbd(self):
        """Test content quality detection of TBD placeholder."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        score = evaluate_content_quality("short_description", "TBD - to be determined")

        self.assertEqual(score, 20)

    def test_evaluate_content_empty_value(self):
        """Test content quality with empty value."""
        from frappe_pim.pim.utils.scoring import evaluate_content_quality

        score = evaluate_content_quality("product_name", "")
        self.assertEqual(score, 0)

        score = evaluate_content_quality("product_name", None)
        self.assertEqual(score, 0)


class TestSEOScoring(unittest.TestCase):
    """Test cases for SEO scoring calculations."""

    def test_seo_score_all_fields_optimal(self):
        """Test SEO score with all optimal fields."""
        from frappe_pim.pim.utils.scoring import calculate_seo_score

        doc = MockProductDoc(
            seo_meta_title="Great Product - Best Quality Widget for Home",  # 45 chars
            seo_meta_description="Discover our amazing product with premium features. Perfect for home use with long-lasting durability and excellent value for money. Shop now!",  # 145 chars
            seo_meta_keywords="product, widget, home, quality, premium",
            seo_canonical_url="https://example.com/products/great-product"
        )

        scores = calculate_seo_score(doc)

        self.assertIn("overall", scores)
        self.assertIn("meta_title", scores)
        self.assertGreater(scores["overall"], 50)
        self.assertGreater(scores["meta_title"], 50)

    def test_seo_score_no_fields(self):
        """Test SEO score with no fields filled."""
        from frappe_pim.pim.utils.scoring import calculate_seo_score

        doc = MockProductDoc()

        scores = calculate_seo_score(doc)

        self.assertEqual(scores["overall"], 0)
        self.assertEqual(scores["meta_title"], 0)

    def test_meta_title_evaluation_optimal(self):
        """Test meta title evaluation with optimal length."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_title

        # Optimal: 30-60 characters
        title = "Great Product Title for SEO Optimization"  # 41 chars
        score = evaluate_meta_title(title)

        self.assertEqual(score, 100)

    def test_meta_title_evaluation_too_short(self):
        """Test meta title evaluation when too short."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_title

        title = "Short Title"  # 11 chars
        score = evaluate_meta_title(title)

        self.assertLess(score, 100)
        self.assertGreater(score, 0)

    def test_meta_title_evaluation_too_long(self):
        """Test meta title evaluation when too long."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_title

        title = "A" * 80  # 80 chars, over limit
        score = evaluate_meta_title(title)

        self.assertLess(score, 100)
        self.assertGreaterEqual(score, 50)

    def test_meta_title_evaluation_empty(self):
        """Test meta title evaluation with empty value."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_title

        self.assertEqual(evaluate_meta_title(""), 0)
        self.assertEqual(evaluate_meta_title(None), 0)

    def test_meta_description_evaluation_optimal(self):
        """Test meta description evaluation with optimal length."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_description

        # Optimal: 120-160 characters
        desc = "A" * 140
        score = evaluate_meta_description(desc)

        self.assertEqual(score, 100)

    def test_meta_description_evaluation_too_short(self):
        """Test meta description evaluation when too short."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_description

        desc = "A" * 50
        score = evaluate_meta_description(desc)

        self.assertLess(score, 100)
        self.assertGreater(score, 0)

    def test_meta_description_evaluation_too_long(self):
        """Test meta description evaluation when too long."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_description

        desc = "A" * 200
        score = evaluate_meta_description(desc)

        self.assertLess(score, 100)
        self.assertGreaterEqual(score, 50)

    def test_meta_keywords_evaluation_optimal(self):
        """Test meta keywords evaluation with optimal count."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_keywords

        # Optimal: 3-10 keywords
        keywords = "keyword1, keyword2, keyword3, keyword4, keyword5"
        score = evaluate_meta_keywords(keywords)

        self.assertEqual(score, 100)

    def test_meta_keywords_evaluation_single(self):
        """Test meta keywords evaluation with single keyword."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_keywords

        score = evaluate_meta_keywords("single")

        self.assertEqual(score, 50)

    def test_meta_keywords_evaluation_two(self):
        """Test meta keywords evaluation with two keywords."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_keywords

        score = evaluate_meta_keywords("one, two")

        self.assertEqual(score, 70)

    def test_meta_keywords_evaluation_too_many(self):
        """Test meta keywords evaluation with too many keywords."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_keywords

        keywords = ", ".join([f"kw{i}" for i in range(15)])
        score = evaluate_meta_keywords(keywords)

        self.assertLess(score, 100)
        self.assertGreaterEqual(score, 60)

    def test_meta_keywords_evaluation_empty(self):
        """Test meta keywords evaluation with empty value."""
        from frappe_pim.pim.utils.scoring import evaluate_meta_keywords

        self.assertEqual(evaluate_meta_keywords(""), 0)
        self.assertEqual(evaluate_meta_keywords(None), 0)


class TestMediaScoring(unittest.TestCase):
    """Test cases for media scoring calculations."""

    def test_media_score_with_many_images(self):
        """Test media score with many images."""
        from frappe_pim.pim.utils.scoring import calculate_media_score

        doc = MockProductDoc(
            product_media=[
                MockMedia(is_primary=True),
                MockMedia(),
                MockMedia(),
                MockMedia(),
                MockMedia()
            ]
        )

        scores = calculate_media_score(doc)

        self.assertEqual(scores["completeness"], 100)
        self.assertEqual(scores["quality"], 100)

    def test_media_score_with_primary_only(self):
        """Test media score with only primary image."""
        from frappe_pim.pim.utils.scoring import calculate_media_score

        doc = MockProductDoc(
            image="/files/primary.jpg"
        )

        scores = calculate_media_score(doc)

        self.assertEqual(scores["completeness"], 60)
        self.assertEqual(scores["quality"], 50)

    def test_media_score_no_images(self):
        """Test media score with no images."""
        from frappe_pim.pim.utils.scoring import calculate_media_score

        doc = MockProductDoc()

        scores = calculate_media_score(doc)

        self.assertEqual(scores["completeness"], 0)
        self.assertEqual(scores["quality"], 0)

    def test_media_score_three_images(self):
        """Test media score with three images."""
        from frappe_pim.pim.utils.scoring import calculate_media_score

        doc = MockProductDoc(
            product_media=[
                MockMedia(is_primary=True),
                MockMedia(),
                MockMedia()
            ]
        )

        scores = calculate_media_score(doc)

        self.assertEqual(scores["completeness"], 80)
        self.assertEqual(scores["quality"], 80)


class TestTranslationScoring(unittest.TestCase):
    """Test cases for translation scoring calculations."""

    def test_translation_score_no_translations(self):
        """Test translation score when no translations exist."""
        from frappe_pim.pim.utils.scoring import calculate_translation_score

        doc = MockProductDoc()

        scores = calculate_translation_score(doc)

        # If no translations, assume single language is OK
        self.assertEqual(scores["coverage"], 100)
        self.assertEqual(scores["quality"], 100)

    def test_translation_score_with_verified_translations(self):
        """Test translation score with verified translations."""
        from frappe_pim.pim.utils.scoring import calculate_translation_score

        doc = MockProductDoc(
            translations=[
                MockTranslation("de", "product_name", is_verified=True),
                MockTranslation("de", "short_description", is_verified=True),
                MockTranslation("fr", "product_name", is_verified=True),
            ]
        )

        scores = calculate_translation_score(doc)

        # All translations verified
        self.assertEqual(scores["quality"], 100)

    def test_translation_score_with_unverified_translations(self):
        """Test translation score with unverified translations."""
        from frappe_pim.pim.utils.scoring import calculate_translation_score

        doc = MockProductDoc(
            translations=[
                MockTranslation("de", "product_name", is_verified=True),
                MockTranslation("de", "short_description", is_verified=False),
                MockTranslation("fr", "product_name", is_verified=False),
            ]
        )

        scores = calculate_translation_score(doc)

        # 1 of 3 verified = 33.33%
        self.assertAlmostEqual(scores["quality"], 33.33, places=1)


class TestAttributeScoring(unittest.TestCase):
    """Test cases for attribute scoring calculations."""

    def test_attribute_score_no_attributes(self):
        """Test attribute score when no attributes defined."""
        from frappe_pim.pim.utils.scoring import calculate_attribute_score

        doc = MockProductDoc()

        scores = calculate_attribute_score(doc)

        # No attributes required/defined
        self.assertEqual(scores["completeness"], 100)
        self.assertEqual(scores["quality"], 100)

    def test_attribute_score_all_filled(self):
        """Test attribute score with all attributes filled."""
        from frappe_pim.pim.utils.scoring import calculate_attribute_score

        doc = MockProductDoc(
            attributes=[
                MockAttributeValue("color", "Blue"),
                MockAttributeValue("size", "Large"),
                MockAttributeValue("weight", "2.5 kg"),
            ]
        )

        scores = calculate_attribute_score(doc)

        self.assertEqual(scores["completeness"], 100)
        self.assertEqual(scores["quality"], 100)
        self.assertEqual(scores["consistency"], 80)

    def test_attribute_score_with_placeholders(self):
        """Test attribute score with placeholder values."""
        from frappe_pim.pim.utils.scoring import calculate_attribute_score

        doc = MockProductDoc(
            attributes=[
                MockAttributeValue("color", "Blue"),
                MockAttributeValue("size", "N/A"),  # Placeholder
                MockAttributeValue("weight", "TBD"),  # Placeholder
            ]
        )

        scores = calculate_attribute_score(doc)

        self.assertEqual(scores["completeness"], 100)
        # Quality should be lower due to placeholders (1*100 + 2*30) / 3 = 53.33
        self.assertAlmostEqual(scores["quality"], 53.33, places=1)

    def test_attribute_score_partial_filled(self):
        """Test attribute score with some attributes empty."""
        from frappe_pim.pim.utils.scoring import calculate_attribute_score

        doc = MockProductDoc(
            attributes=[
                MockAttributeValue("color", "Blue"),
                MockAttributeValue("size", ""),  # Empty
                MockAttributeValue("weight", None),  # None
            ]
        )

        scores = calculate_attribute_score(doc)

        # 1 of 3 filled
        self.assertAlmostEqual(scores["completeness"], 33.33, places=1)


class TestWeightedScoreCalculation(unittest.TestCase):
    """Test cases for weighted score calculation."""

    def test_weighted_score_all_perfect(self):
        """Test weighted score with all components at 100."""
        from frappe_pim.pim.utils.scoring import calculate_weighted_score, DEFAULT_WEIGHTS

        scores = {
            "content_completeness_score": 100,
            "content_quality_score": 100,
            "media_completeness_score": 100,
            "media_quality_score": 100,
            "seo_score": 100,
            "seo_meta_title_score": 100,
            "translation_coverage_score": 100,
            "translation_quality_score": 100,
            "attribute_completeness_score": 100,
            "attribute_quality_score": 100,
            "data_accuracy_score": 100,
            "data_consistency_score": 100,
            "market_performance_score": 100,
            "customer_satisfaction_score": 100,
            "competitive_position_score": 100,
            "feedback_sentiment_score": 100,
            **DEFAULT_WEIGHTS
        }

        overall = calculate_weighted_score(scores)

        self.assertEqual(overall, 100)

    def test_weighted_score_all_zero(self):
        """Test weighted score with all components at zero."""
        from frappe_pim.pim.utils.scoring import calculate_weighted_score, DEFAULT_WEIGHTS

        scores = {
            "content_completeness_score": 0,
            "content_quality_score": 0,
            "media_completeness_score": 0,
            "media_quality_score": 0,
            "seo_score": 0,
            "seo_meta_title_score": 0,
            "translation_coverage_score": 0,
            "translation_quality_score": 0,
            "attribute_completeness_score": 0,
            "attribute_quality_score": 0,
            "data_accuracy_score": 0,
            "data_consistency_score": 0,
            "market_performance_score": 0,
            "customer_satisfaction_score": 0,
            "competitive_position_score": 0,
            "feedback_sentiment_score": 0,
            **DEFAULT_WEIGHTS
        }

        overall = calculate_weighted_score(scores)

        self.assertEqual(overall, 0)

    def test_weighted_score_mixed(self):
        """Test weighted score with mixed values."""
        from frappe_pim.pim.utils.scoring import calculate_weighted_score, DEFAULT_WEIGHTS

        scores = {
            "content_completeness_score": 80,
            "content_quality_score": 70,
            "media_completeness_score": 60,
            "media_quality_score": 50,
            "seo_score": 90,
            "seo_meta_title_score": 85,
            "translation_coverage_score": 100,
            "translation_quality_score": 100,
            "attribute_completeness_score": 75,
            "attribute_quality_score": 80,
            "data_accuracy_score": 80,
            "data_consistency_score": 80,
            "market_performance_score": 50,
            "customer_satisfaction_score": 60,
            "competitive_position_score": 70,
            "feedback_sentiment_score": 55,
            **DEFAULT_WEIGHTS
        }

        overall = calculate_weighted_score(scores)

        # Should be somewhere between min and max
        self.assertGreater(overall, 0)
        self.assertLess(overall, 100)


class TestDefaultScores(unittest.TestCase):
    """Test cases for default scores function."""

    def test_get_default_scores_structure(self):
        """Test that default scores have correct structure."""
        from frappe_pim.pim.utils.scoring import get_default_scores

        scores = get_default_scores()

        # Check all expected keys
        expected_keys = [
            "overall_score",
            "content_completeness_score",
            "content_quality_score",
            "media_completeness_score",
            "media_quality_score",
            "seo_score",
            "seo_meta_title_score",
            "translation_coverage_score",
            "translation_quality_score",
            "attribute_completeness_score",
            "attribute_quality_score",
            "data_accuracy_score",
            "data_consistency_score",
            "market_performance_score",
            "customer_satisfaction_score",
            "competitive_position_score",
            "feedback_sentiment_score",
            "content_weight",
            "media_weight",
            "seo_weight",
            "translation_weight",
            "attribute_weight",
            "market_weight",
        ]

        for key in expected_keys:
            self.assertIn(key, scores)

    def test_get_default_scores_values_zero(self):
        """Test that default score values are zero."""
        from frappe_pim.pim.utils.scoring import get_default_scores

        scores = get_default_scores()

        # Score fields should be 0
        score_fields = [
            "overall_score",
            "content_completeness_score",
            "content_quality_score",
            "media_completeness_score",
            "media_quality_score",
            "seo_score",
            "seo_meta_title_score",
            "translation_coverage_score",
            "translation_quality_score",
            "attribute_completeness_score",
            "attribute_quality_score",
            "data_accuracy_score",
            "data_consistency_score",
            "market_performance_score",
            "customer_satisfaction_score",
            "competitive_position_score",
            "feedback_sentiment_score",
        ]

        for field in score_fields:
            self.assertEqual(scores[field], 0)

    def test_get_default_scores_weights_preserved(self):
        """Test that default scores include proper weights."""
        from frappe_pim.pim.utils.scoring import get_default_scores, DEFAULT_WEIGHTS

        scores = get_default_scores()

        for weight_key, weight_value in DEFAULT_WEIGHTS.items():
            self.assertEqual(scores[weight_key], weight_value)


class TestScoringConfig(unittest.TestCase):
    """Test cases for scoring configuration."""

    def test_get_scoring_config_structure(self):
        """Test that scoring config has correct structure."""
        from frappe_pim.pim.utils.scoring import get_scoring_config

        config = get_scoring_config()

        self.assertIn("weights", config)
        self.assertIn("thresholds", config)
        self.assertIn("required_content_fields", config)
        self.assertIn("required_seo_fields", config)

    def test_get_scoring_config_weights(self):
        """Test that scoring config includes weights."""
        from frappe_pim.pim.utils.scoring import get_scoring_config, DEFAULT_WEIGHTS

        config = get_scoring_config()

        for key in DEFAULT_WEIGHTS:
            self.assertIn(key, config["weights"])

    def test_get_scoring_config_thresholds(self):
        """Test that scoring config includes SEO thresholds."""
        from frappe_pim.pim.utils.scoring import get_scoring_config

        config = get_scoring_config()

        self.assertIn("seo_meta_title_max_length", config["thresholds"])
        self.assertIn("seo_meta_title_min_length", config["thresholds"])
        self.assertIn("seo_meta_description_max_length", config["thresholds"])
        self.assertIn("seo_meta_description_min_length", config["thresholds"])


class TestMarketScoring(unittest.TestCase):
    """Test cases for market scoring calculations."""

    def test_market_score_returns_defaults(self):
        """Test market score returns default values without data."""
        from frappe_pim.pim.utils.scoring import calculate_market_score

        doc = MockProductDoc()

        scores = calculate_market_score(doc)

        self.assertIn("performance", scores)
        self.assertIn("satisfaction", scores)
        self.assertIn("competitive", scores)
        self.assertIn("sentiment", scores)

        # Default baseline values
        self.assertEqual(scores["performance"], 50)
        self.assertEqual(scores["satisfaction"], 50)
        self.assertEqual(scores["competitive"], 50)
        self.assertEqual(scores["sentiment"], 50)

    def test_market_score_values_in_range(self):
        """Test that market scores are within valid range."""
        from frappe_pim.pim.utils.scoring import calculate_market_score

        doc = MockProductDoc()

        scores = calculate_market_score(doc)

        for key in ["performance", "satisfaction", "competitive", "sentiment"]:
            self.assertGreaterEqual(scores[key], 0)
            self.assertLessEqual(scores[key], 100)


class TestProductScoreIntegration(unittest.TestCase):
    """Integration tests for product scoring with actual database.

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

    def test_calculate_product_score_basic(self):
        """Test calculate_product_score with a real product."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.scoring import calculate_product_score

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Test Product {random_string(4)}",
            "product_code": f"TEST-{random_string(6).upper()}",
            "short_description": "A test product for scoring calculations with adequate description length.",
            "long_description": "This is a detailed long description of the test product. It contains all the necessary information about the product features, benefits, and specifications. The description is long enough to get a good quality score.",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Calculate scores
        scores = calculate_product_score(product.name)

        # Check structure
        self.assertIn("overall_score", scores)
        self.assertIn("content_completeness_score", scores)
        self.assertIn("content_quality_score", scores)

        # Content should have good scores since fields are filled
        self.assertGreater(scores["content_completeness_score"], 0)
        self.assertGreater(scores["content_quality_score"], 0)

    def test_calculate_product_score_with_seo(self):
        """Test calculate_product_score with SEO fields."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.scoring import calculate_product_score

        # Create a test product with SEO data
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"SEO Test Product {random_string(4)}",
            "product_code": f"SEO-{random_string(6).upper()}",
            "short_description": "A test product with SEO optimized content for testing.",
            "long_description": "Detailed product description with all necessary information for comprehensive testing of the scoring system.",
            "seo_meta_title": "SEO Optimized Product Title for Testing",  # 40 chars
            "seo_meta_description": "This is an optimized meta description for the product that is within the optimal length range for SEO purposes and search engine visibility.",  # 150 chars
            "seo_meta_keywords": "seo, product, test, optimization, scoring",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Calculate scores
        scores = calculate_product_score(product.name)

        # SEO scores should be good
        self.assertGreater(scores["seo_score"], 0)
        self.assertGreater(scores["seo_meta_title_score"], 50)

    def test_calculate_product_score_nonexistent_product(self):
        """Test calculate_product_score with non-existent product."""
        from frappe_pim.pim.utils.scoring import calculate_product_score

        # Should return default scores on error
        scores = calculate_product_score("NONEXISTENT-PRODUCT-12345")

        # Should have all fields with zero values
        self.assertEqual(scores["overall_score"], 0)
        self.assertEqual(scores["content_completeness_score"], 0)

    def test_calculate_product_score_with_document_object(self):
        """Test calculate_product_score with document object instead of name."""
        import frappe
        from frappe.utils import random_string
        from frappe_pim.pim.utils.scoring import calculate_product_score

        # Create a test product
        product = frappe.get_doc({
            "doctype": "Product Master",
            "product_name": f"Doc Object Test {random_string(4)}",
            "product_code": f"DOC-{random_string(6).upper()}",
            "short_description": "Testing with document object directly.",
            "status": "Draft"
        })
        product.insert(ignore_permissions=True)
        self.track_document("Product Master", product.name)

        # Pass document object instead of name
        scores = calculate_product_score(product)

        # Should work the same
        self.assertIn("overall_score", scores)
        self.assertGreater(scores["content_completeness_score"], 0)


# Allow module import without running tests
if __name__ == "__main__":
    unittest.main()
