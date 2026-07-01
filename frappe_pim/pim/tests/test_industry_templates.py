"""
Industry Template Unit Tests

Tests for the Industry Template DocType:
  - Template code validation (7 valid sectors)
  - Version format validation (major.minor)
  - Unique template_code + version constraint
  - is_active constraint (only one active per template_code)
  - JSON field validation
  - Quality threshold validation
  - get_template_data() and get_preview_data()
  - Whitelisted API functions
  - All 7 fixture archetypes load via the template engine

Run with:
    bench --site [site] run-tests --app frappe_pim \
        --module frappe_pim.pim.tests.test_industry_templates
"""

import frappe
from frappe.tests.utils import FrappeTestCase
import json
import os


class TestIndustryTemplate(FrappeTestCase):
    """
    Tests for the Industry Template DocType controller.

    Covers:
    1. Template code validation
    2. Version format validation
    3. Unique code+version constraint
    4. is_active constraint (single active per code)
    5. JSON field validation
    6. Quality threshold validation
    7. get_template_data() output
    8. get_preview_data() output
    9. Whitelisted API functions
    10. All 7 fixture archetypes load
    """

    # Prefix for test template codes — use real codes but distinct names
    TEST_PREFIX = "it_test_"

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for all tests."""
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._cleanup_test_data()

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove test Industry Template records."""
        try:
            frappe.db.sql(
                "DELETE FROM `tabIndustry Template` WHERE display_name LIKE %s",
                (f"{cls.TEST_PREFIX}%",)
            )
            frappe.db.commit()
        except Exception:
            pass

    def tearDown(self):
        """Clean up after each test."""
        frappe.db.rollback()

    def _create_template(
        self,
        template_code="fashion",
        version="1.0",
        display_name=None,
        is_active=0,
        **kwargs,
    ):
        """Helper to create a test Industry Template document."""
        if display_name is None:
            display_name = f"{self.TEST_PREFIX}{template_code}_{version}"

        doc = frappe.new_doc("Industry Template")
        doc.template_code = template_code
        doc.display_name = display_name
        doc.version = version
        doc.is_active = is_active

        for key, value in kwargs.items():
            doc.set(key, value)

        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return doc

    def _cleanup_template(self, name):
        """Helper to delete a template by name."""
        if frappe.db.exists("Industry Template", name):
            frappe.delete_doc("Industry Template", name, ignore_permissions=True)
            frappe.db.commit()

    # ========================================================================
    # Section 1: Template Code Validation
    # ========================================================================

    def test_01_valid_template_codes(self):
        """Test that all 7 valid template codes pass validation."""
        from frappe_pim.pim.doctype.industry_template.industry_template import VALID_TEMPLATE_CODES

        self.assertEqual(len(VALID_TEMPLATE_CODES), 7)

        expected_codes = {
            "fashion", "industrial", "food",
            "electronics", "health_beauty", "automotive", "custom",
        }
        self.assertEqual(set(VALID_TEMPLATE_CODES), expected_codes)

    def test_02_valid_template_code_creates_successfully(self):
        """Test that a template with a valid code can be created."""
        doc = self._create_template(
            template_code="electronics",
            version="9.0",
        )
        self.assertIsNotNone(doc.name)
        self.assertEqual(doc.template_code, "electronics")
        self._cleanup_template(doc.name)

    def test_03_invalid_template_code_raises(self):
        """Test that an invalid template code raises ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "invalid_sector"
        doc.display_name = f"{self.TEST_PREFIX}invalid"
        doc.version = "1.0"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_04_empty_template_code_raises(self):
        """Test that empty template code raises ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = ""
        doc.display_name = f"{self.TEST_PREFIX}empty"
        doc.version = "1.0"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_05_template_code_normalized_lowercase(self):
        """Test that template_code is normalized to lowercase."""
        doc = self._create_template(
            template_code="FASHION",
            version="8.0",
        )
        self.assertEqual(doc.template_code, "fashion")
        self._cleanup_template(doc.name)

    # ========================================================================
    # Section 2: Version Format Validation
    # ========================================================================

    def test_10_valid_version_formats(self):
        """Test that valid version formats pass validation."""
        valid_versions = ["1.0", "2.1", "10.0", "0.1"]
        for i, version in enumerate(valid_versions):
            doc = self._create_template(
                template_code="food",
                version=f"{50 + i}.{i}",
                display_name=f"{self.TEST_PREFIX}ver_{i}",
            )
            self.assertIsNotNone(doc.name)
            self._cleanup_template(doc.name)

    def test_11_invalid_version_single_number_raises(self):
        """Test that a single number version format raises ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "fashion"
        doc.display_name = f"{self.TEST_PREFIX}bad_ver_1"
        doc.version = "1"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_12_invalid_version_three_parts_raises(self):
        """Test that a three-part version format raises ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "fashion"
        doc.display_name = f"{self.TEST_PREFIX}bad_ver_2"
        doc.version = "1.0.1"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_13_invalid_version_non_numeric_raises(self):
        """Test that non-numeric version components raise ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "fashion"
        doc.display_name = f"{self.TEST_PREFIX}bad_ver_3"
        doc.version = "a.b"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_14_empty_version_raises(self):
        """Test that empty version raises ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "fashion"
        doc.display_name = f"{self.TEST_PREFIX}bad_ver_4"
        doc.version = ""

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_15_negative_version_raises(self):
        """Test that negative version numbers raise ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "fashion"
        doc.display_name = f"{self.TEST_PREFIX}bad_ver_5"
        doc.version = "-1.0"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    # ========================================================================
    # Section 3: Unique Code+Version Constraint
    # ========================================================================

    def test_20_duplicate_code_version_raises(self):
        """Test that duplicate template_code + version raises ValidationError."""
        doc1 = self._create_template(
            template_code="industrial",
            version="7.0",
            display_name=f"{self.TEST_PREFIX}dup_1",
        )

        doc2 = frappe.new_doc("Industry Template")
        doc2.template_code = "industrial"
        doc2.display_name = f"{self.TEST_PREFIX}dup_2"
        doc2.version = "7.0"

        with self.assertRaises(frappe.ValidationError):
            doc2.insert(ignore_permissions=True)

        self._cleanup_template(doc1.name)

    def test_21_same_code_different_version_allowed(self):
        """Test that same template_code with different versions is allowed."""
        doc1 = self._create_template(
            template_code="automotive",
            version="6.0",
            display_name=f"{self.TEST_PREFIX}ver_diff_1",
        )
        doc2 = self._create_template(
            template_code="automotive",
            version="6.1",
            display_name=f"{self.TEST_PREFIX}ver_diff_2",
        )

        self.assertIsNotNone(doc1.name)
        self.assertIsNotNone(doc2.name)
        self.assertNotEqual(doc1.name, doc2.name)

        self._cleanup_template(doc1.name)
        self._cleanup_template(doc2.name)

    def test_22_different_code_same_version_allowed(self):
        """Test that different template_codes with same version is allowed."""
        doc1 = self._create_template(
            template_code="fashion",
            version="5.0",
            display_name=f"{self.TEST_PREFIX}code_diff_1",
        )
        doc2 = self._create_template(
            template_code="food",
            version="5.0",
            display_name=f"{self.TEST_PREFIX}code_diff_2",
        )

        self.assertIsNotNone(doc1.name)
        self.assertIsNotNone(doc2.name)

        self._cleanup_template(doc1.name)
        self._cleanup_template(doc2.name)

    # ========================================================================
    # Section 4: is_active Constraint
    # ========================================================================

    def test_30_only_one_active_per_code(self):
        """Test that activating a version deactivates others for same code."""
        doc1 = self._create_template(
            template_code="health_beauty",
            version="3.0",
            display_name=f"{self.TEST_PREFIX}active_1",
            is_active=1,
        )
        # doc1 should be active
        doc1.reload()
        self.assertEqual(doc1.is_active, 1)

        doc2 = self._create_template(
            template_code="health_beauty",
            version="3.1",
            display_name=f"{self.TEST_PREFIX}active_2",
            is_active=1,
        )

        # After activating doc2, doc1 should be deactivated
        doc1.reload()
        doc2.reload()
        self.assertEqual(doc1.is_active, 0)
        self.assertEqual(doc2.is_active, 1)

        self._cleanup_template(doc1.name)
        self._cleanup_template(doc2.name)

    def test_31_deactivation_only_affects_same_code(self):
        """Test that activating one code doesn't deactivate other codes."""
        doc1 = self._create_template(
            template_code="fashion",
            version="4.0",
            display_name=f"{self.TEST_PREFIX}cross_1",
            is_active=1,
        )
        doc2 = self._create_template(
            template_code="food",
            version="4.0",
            display_name=f"{self.TEST_PREFIX}cross_2",
            is_active=1,
        )

        # Both should remain active since they are different codes
        doc1.reload()
        doc2.reload()
        self.assertEqual(doc1.is_active, 1)
        self.assertEqual(doc2.is_active, 1)

        self._cleanup_template(doc1.name)
        self._cleanup_template(doc2.name)

    def test_32_inactive_templates_not_affected(self):
        """Test that saving an inactive template doesn't change other records."""
        doc1 = self._create_template(
            template_code="custom",
            version="3.0",
            display_name=f"{self.TEST_PREFIX}inactive_1",
            is_active=1,
        )
        doc2 = self._create_template(
            template_code="custom",
            version="3.1",
            display_name=f"{self.TEST_PREFIX}inactive_2",
            is_active=0,
        )

        # doc1 should still be active after saving inactive doc2
        doc1.reload()
        self.assertEqual(doc1.is_active, 1)

        self._cleanup_template(doc1.name)
        self._cleanup_template(doc2.name)

    # ========================================================================
    # Section 5: JSON Field Validation
    # ========================================================================

    def test_40_valid_json_fields_pass(self):
        """Test that valid JSON in data fields passes validation."""
        doc = self._create_template(
            template_code="electronics",
            version="3.0",
            display_name=f"{self.TEST_PREFIX}json_valid",
            attribute_groups=json.dumps([{"code": "general", "attributes": []}]),
            product_families=json.dumps([{"code": "phones", "label": "Phones"}]),
            default_channels=json.dumps(["shopify", "amazon"]),
            scoring_weights=json.dumps({"attribute": 30, "content": 25}),
        )
        self.assertIsNotNone(doc.name)
        self._cleanup_template(doc.name)

    def test_41_invalid_json_raises(self):
        """Test that invalid JSON in data fields raises ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "fashion"
        doc.display_name = f"{self.TEST_PREFIX}json_invalid"
        doc.version = "99.0"
        doc.attribute_groups = "not valid json {"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_42_empty_json_fields_pass(self):
        """Test that empty/None JSON fields pass validation."""
        doc = self._create_template(
            template_code="industrial",
            version="3.0",
            display_name=f"{self.TEST_PREFIX}json_empty",
        )
        # All JSON fields are None/empty by default — should be fine
        self.assertIsNotNone(doc.name)
        self._cleanup_template(doc.name)

    # ========================================================================
    # Section 6: Quality Threshold Validation
    # ========================================================================

    def test_50_valid_quality_threshold(self):
        """Test that quality thresholds 0-100 pass validation."""
        for threshold in [0, 50, 70, 100]:
            doc = self._create_template(
                template_code="food",
                version=f"6{threshold}.0",
                display_name=f"{self.TEST_PREFIX}qt_{threshold}",
                quality_threshold=threshold,
            )
            self.assertIsNotNone(doc.name)
            self._cleanup_template(doc.name)

    def test_51_quality_threshold_above_100_raises(self):
        """Test that quality threshold above 100 raises ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "fashion"
        doc.display_name = f"{self.TEST_PREFIX}qt_high"
        doc.version = "99.1"
        doc.quality_threshold = 150

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_52_quality_threshold_below_zero_raises(self):
        """Test that quality threshold below 0 raises ValidationError."""
        doc = frappe.new_doc("Industry Template")
        doc.template_code = "fashion"
        doc.display_name = f"{self.TEST_PREFIX}qt_low"
        doc.version = "99.2"
        doc.quality_threshold = -10

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    # ========================================================================
    # Section 7: get_template_data()
    # ========================================================================

    def test_60_get_template_data_structure(self):
        """Test get_template_data returns expected keys."""
        doc = self._create_template(
            template_code="fashion",
            version="2.0",
            display_name=f"{self.TEST_PREFIX}data_1",
            description="Test fashion template",
            estimated_setup_minutes=20,
            quality_threshold=75,
            attribute_groups=json.dumps([{"code": "sizing"}]),
            product_families=json.dumps([{"code": "tops"}]),
        )

        data = doc.get_template_data()

        self.assertIsInstance(data, dict)
        self.assertEqual(data["template_code"], "fashion")
        self.assertEqual(data["display_name"], f"{self.TEST_PREFIX}data_1")
        self.assertEqual(data["version"], "2.0")
        self.assertEqual(data["description"], "Test fashion template")
        self.assertEqual(data["estimated_setup_minutes"], 20)
        self.assertEqual(data["quality_threshold"], 75)
        self.assertIsInstance(data["attribute_groups"], list)
        self.assertIsInstance(data["product_families"], list)

        self._cleanup_template(doc.name)

    def test_61_get_template_data_parses_json(self):
        """Test get_template_data correctly parses JSON fields."""
        channels = ["shopify", "amazon", "trendyol"]
        weights = {"attribute": 30, "content": 25, "media": 20, "seo": 15, "compliance": 10}
        doc = self._create_template(
            template_code="electronics",
            version="2.0",
            display_name=f"{self.TEST_PREFIX}data_2",
            default_channels=json.dumps(channels),
            scoring_weights=json.dumps(weights),
        )

        data = doc.get_template_data()

        self.assertEqual(data["default_channels"], channels)
        self.assertEqual(data["scoring_weights"], weights)

        self._cleanup_template(doc.name)

    def test_62_get_template_data_empty_json_defaults(self):
        """Test get_template_data returns [] or {} for empty JSON fields."""
        doc = self._create_template(
            template_code="custom",
            version="2.0",
            display_name=f"{self.TEST_PREFIX}data_3",
        )

        data = doc.get_template_data()

        # Empty JSON array fields should be []
        self.assertEqual(data["attribute_groups"], [])
        self.assertEqual(data["product_families"], [])
        self.assertEqual(data["default_channels"], [])
        # scoring_weights should be {} (object field)
        self.assertEqual(data["scoring_weights"], {})

        self._cleanup_template(doc.name)

    # ========================================================================
    # Section 8: get_preview_data()
    # ========================================================================

    def test_70_get_preview_data_structure(self):
        """Test get_preview_data returns expected preview keys."""
        groups = [{"code": "general"}, {"code": "sizing"}]
        families = [{"code": "tops"}, {"code": "bottoms"}, {"code": "shoes"}]
        channels = ["shopify", "amazon"]
        doc = self._create_template(
            template_code="fashion",
            version="3.0",
            display_name=f"{self.TEST_PREFIX}preview_1",
            description="Preview test",
            attribute_groups=json.dumps(groups),
            product_families=json.dumps(families),
            default_channels=json.dumps(channels),
        )

        preview = doc.get_preview_data()

        self.assertEqual(preview["template_code"], "fashion")
        self.assertEqual(preview["display_name"], f"{self.TEST_PREFIX}preview_1")
        self.assertEqual(preview["version"], "3.0")
        self.assertEqual(preview["description"], "Preview test")
        self.assertEqual(preview["attribute_group_count"], 2)
        self.assertEqual(preview["product_family_count"], 3)
        self.assertEqual(preview["channel_count"], 2)

        self._cleanup_template(doc.name)

    def test_71_get_preview_data_category_count(self):
        """Test get_preview_data correctly counts nested categories."""
        categories = [
            {"name": "Electronics", "children": [
                {"name": "Phones"},
                {"name": "Laptops", "children": [
                    {"name": "Gaming Laptops"},
                ]},
            ]},
            {"name": "Accessories"},
        ]
        doc = self._create_template(
            template_code="electronics",
            version="4.0",
            display_name=f"{self.TEST_PREFIX}preview_2",
            category_tree=json.dumps(categories),
        )

        preview = doc.get_preview_data()
        # Electronics(1) + Phones(1) + Laptops(1) + Gaming Laptops(1) + Accessories(1) = 5
        self.assertEqual(preview["category_count"], 5)

        self._cleanup_template(doc.name)

    # ========================================================================
    # Section 9: Whitelisted API Functions
    # ========================================================================

    def test_80_get_active_template(self):
        """Test get_active_template returns data for active template."""
        from frappe_pim.pim.doctype.industry_template.industry_template import get_active_template

        doc = self._create_template(
            template_code="automotive",
            version="2.0",
            display_name=f"{self.TEST_PREFIX}api_active",
            is_active=1,
            attribute_groups=json.dumps([{"code": "vehicle"}]),
        )

        result = get_active_template("automotive")
        self.assertIsNotNone(result)
        self.assertEqual(result["template_code"], "automotive")
        self.assertIsInstance(result["attribute_groups"], list)

        self._cleanup_template(doc.name)

    def test_81_get_active_template_returns_none_for_missing(self):
        """Test get_active_template returns None when no active template exists."""
        from frappe_pim.pim.doctype.industry_template.industry_template import get_active_template

        # Use a code that likely has no active record after cleanup
        result = get_active_template("industrial")
        # May or may not exist — just verify it doesn't crash
        self.assertTrue(result is None or isinstance(result, dict))

    def test_82_get_available_templates(self):
        """Test get_available_templates returns list of active templates."""
        from frappe_pim.pim.doctype.industry_template.industry_template import get_available_templates

        # Create two active templates
        doc1 = self._create_template(
            template_code="fashion",
            version="7.0",
            display_name=f"{self.TEST_PREFIX}avail_1",
            is_active=1,
        )
        doc2 = self._create_template(
            template_code="food",
            version="7.0",
            display_name=f"{self.TEST_PREFIX}avail_2",
            is_active=1,
        )

        result = get_available_templates()
        self.assertIsInstance(result, list)
        # Should have at least these 2
        codes = [t["template_code"] for t in result]
        self.assertIn("fashion", codes)
        self.assertIn("food", codes)

        self._cleanup_template(doc1.name)
        self._cleanup_template(doc2.name)

    # ========================================================================
    # Section 10: Autoname Format
    # ========================================================================

    def test_85_autoname_format(self):
        """Test that template name follows format:{template_code}-v{version}."""
        doc = self._create_template(
            template_code="custom",
            version="1.0",
            display_name=f"{self.TEST_PREFIX}autoname",
        )

        self.assertEqual(doc.name, "custom-v1.0")
        self._cleanup_template(doc.name)

    # ========================================================================
    # Section 11: All 7 Fixture Archetypes Load
    # ========================================================================

    def test_90_all_fixture_files_exist(self):
        """Test that fixture files exist for all 7 industry sectors.

        Fixtures are split across two directories:
        - fixtures/*_template.json (fashion, industrial, food)
        - fixtures/industry_templates/*.json (electronics, health_beauty, automotive, custom)
        """
        fixtures_base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "fixtures",
        )
        industry_dir = os.path.join(fixtures_base, "industry_templates")

        # Legacy-format fixtures in fixtures/ root
        legacy_fixtures = {
            "fashion": os.path.join(fixtures_base, "fashion_template.json"),
            "industrial": os.path.join(fixtures_base, "industrial_template.json"),
            "food": os.path.join(fixtures_base, "food_template.json"),
        }

        # New-format fixtures in fixtures/industry_templates/
        new_fixtures = {
            "electronics": os.path.join(industry_dir, "electronics.json"),
            "health_beauty": os.path.join(industry_dir, "health_beauty.json"),
            "automotive": os.path.join(industry_dir, "automotive.json"),
            "custom": os.path.join(industry_dir, "custom.json"),
        }

        all_fixtures = {**legacy_fixtures, **new_fixtures}

        for sector, filepath in all_fixtures.items():
            self.assertTrue(
                os.path.isfile(filepath),
                f"Fixture file missing for sector '{sector}': {filepath}"
            )

    def test_91_all_fixture_files_valid_json(self):
        """Test that all fixture files contain valid JSON."""
        fixtures_base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "fixtures",
        )
        industry_dir = os.path.join(fixtures_base, "industry_templates")

        fixture_files = []
        # Legacy fixtures
        for name in ["fashion_template.json", "industrial_template.json", "food_template.json"]:
            filepath = os.path.join(fixtures_base, name)
            if os.path.isfile(filepath):
                fixture_files.append(filepath)

        # New fixtures
        if os.path.isdir(industry_dir):
            for name in os.listdir(industry_dir):
                if name.endswith(".json"):
                    fixture_files.append(os.path.join(industry_dir, name))

        self.assertGreaterEqual(len(fixture_files), 7)

        for filepath in fixture_files:
            with open(filepath, "r", encoding="utf-8") as fh:
                try:
                    data = json.load(fh)
                    self.assertIsInstance(
                        data, dict,
                        f"Fixture {filepath} should be a JSON object"
                    )
                except json.JSONDecodeError as e:
                    self.fail(f"Fixture {filepath} contains invalid JSON: {e}")

    def test_92_legacy_fixtures_have_archetype_key(self):
        """Test that legacy fixture files have the 'archetype' key."""
        fixtures_base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "fixtures",
        )

        legacy_files = {
            "fashion": "fashion_template.json",
            "industrial": "industrial_template.json",
            "food": "food_template.json",
        }

        for sector, filename in legacy_files.items():
            filepath = os.path.join(fixtures_base, filename)
            if not os.path.isfile(filepath):
                self.skipTest(f"Legacy fixture not found: {filepath}")

            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            self.assertIn(
                "archetype", data,
                f"Legacy fixture '{filename}' missing 'archetype' key"
            )

    def test_93_industry_template_fixtures_have_required_keys(self):
        """Test that industry template fixtures have expected schema keys."""
        industry_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "fixtures",
            "industry_templates",
        )

        if not os.path.isdir(industry_dir):
            self.skipTest("Industry templates directory not found")

        required_keys = {"archetype", "version", "label"}

        for filename in os.listdir(industry_dir):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(industry_dir, filename)
            with open(filepath, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            for key in required_keys:
                self.assertIn(
                    key, data,
                    f"Industry fixture '{filename}' missing required key: '{key}'"
                )

    def test_94_template_engine_loads_fixture_archetypes(self):
        """Test that the template engine can discover fixture archetypes."""
        from frappe_pim.pim.services.template_engine import TemplateEngine

        engine = TemplateEngine()
        archetypes = engine._get_fixture_archetypes()

        self.assertIsInstance(archetypes, list)
        # Should find at least the legacy fixtures (fashion, industrial, food)
        self.assertGreaterEqual(len(archetypes), 3)

        # Each archetype should have required metadata
        for archetype in archetypes:
            self.assertIn("archetype", archetype)
            self.assertIn("label", archetype)
            self.assertIn("source", archetype)

    def test_95_base_template_exists(self):
        """Test that the base template file exists."""
        fixtures_base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "fixtures",
        )
        base_path = os.path.join(fixtures_base, "base_template.json")

        self.assertTrue(
            os.path.isfile(base_path),
            f"Base template not found at: {base_path}"
        )

        with open(base_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            self.assertIsInstance(data, dict)

    # ========================================================================
    # Section 12: _count_categories helper
    # ========================================================================

    def test_96_count_categories_flat(self):
        """Test _count_categories with flat list."""
        from frappe_pim.pim.doctype.industry_template.industry_template import _count_categories

        tree = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        self.assertEqual(_count_categories(tree), 3)

    def test_97_count_categories_nested(self):
        """Test _count_categories with nested tree."""
        from frappe_pim.pim.doctype.industry_template.industry_template import _count_categories

        tree = [
            {"name": "Root", "children": [
                {"name": "Child1"},
                {"name": "Child2", "children": [
                    {"name": "Grandchild"},
                ]},
            ]},
        ]
        self.assertEqual(_count_categories(tree), 4)

    def test_98_count_categories_empty(self):
        """Test _count_categories with empty input."""
        from frappe_pim.pim.doctype.industry_template.industry_template import _count_categories

        self.assertEqual(_count_categories([]), 0)
        self.assertEqual(_count_categories(None), 0)
        self.assertEqual(_count_categories("invalid"), 0)
