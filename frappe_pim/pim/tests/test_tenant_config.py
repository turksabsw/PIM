"""
Tenant Config Unit Tests

Tests for the Tenant Config SingleType DocType:
  - Singleton CRUD (get_doc, save, reload)
  - JSON field validation (array defaults to "[]", object defaults to "{}")
  - Feature flag defaults and set/get API
  - Onboarding status validation and transitions
  - Industry sector validation
  - Quality threshold validation (0-100 range)
  - Computed attribute count
  - Step data save and retrieval
  - Config summary output

Run with:
    bench --site [site] run-tests --app frappe_pim \
        --module frappe_pim.pim.tests.test_tenant_config
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime
import json


class TestTenantConfig(FrappeTestCase):
    """
    Tests for the Tenant Config SingleType controller.

    Covers:
    1. Singleton access and CRUD
    2. JSON array/object field defaults
    3. Feature flag defaults and API
    4. Onboarding status validation
    5. Industry sector validation
    6. Quality threshold validation
    7. Computed attribute count
    8. Step data persistence
    9. Config summary
    10. Onboarding state transitions
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for all tests."""
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._ensure_tenant_config()

    @classmethod
    def _ensure_tenant_config(cls):
        """Ensure a Tenant Config singleton exists with minimal required fields."""
        try:
            doc = frappe.get_single("Tenant Config")
            # Set minimum required fields if not present
            if not doc.company_name:
                doc.company_name = "Test Company"
            if not doc.company_size:
                doc.company_size = "1-10"
            if not doc.primary_role:
                doc.primary_role = "IT Administrator"
            if not doc.existing_systems:
                doc.existing_systems = '["spreadsheets"]'
            if not doc.selected_industry:
                doc.selected_industry = "fashion"
            if not doc.estimated_sku_count:
                doc.estimated_sku_count = "1-100"
            if not doc.product_family_count:
                doc.product_family_count = "1-5"
            if not doc.data_import_source:
                doc.data_import_source = "manual_entry"
            if not doc.onboarding_status:
                doc.onboarding_status = "not_started"
            doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            pass

    def setUp(self):
        """Reset tenant config to known state before each test."""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test."""
        frappe.db.rollback()

    def _get_config(self):
        """Helper to get the Tenant Config singleton."""
        return frappe.get_single("Tenant Config")

    # ========================================================================
    # Section 1: Singleton CRUD
    # ========================================================================

    def test_01_singleton_exists(self):
        """Test that Tenant Config is a SingleType and can be fetched."""
        doc = self._get_config()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.doctype, "Tenant Config")

    def test_02_singleton_read_write(self):
        """Test basic read and write on the singleton."""
        doc = self._get_config()

        original_name = doc.company_name
        doc.company_name = "TC Test Corp"
        doc.save(ignore_permissions=True)

        # Reload and verify
        doc.reload()
        self.assertEqual(doc.company_name, "TC Test Corp")

        # Restore original
        doc.company_name = original_name or "Test Company"
        doc.save(ignore_permissions=True)

    def test_03_singleton_update_persists(self):
        """Test that updates persist across get_single calls."""
        doc = self._get_config()
        doc.company_website = "https://test-tenant-config.example.com"
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Fetch again independently
        doc2 = frappe.get_single("Tenant Config")
        self.assertEqual(doc2.company_website, "https://test-tenant-config.example.com")

    # ========================================================================
    # Section 2: JSON Field Defaults
    # ========================================================================

    def test_10_json_array_fields_default_to_empty_array(self):
        """Test that all JSON array fields default to '[]' when empty."""
        from frappe_pim.pim.doctype.tenant_config.tenant_config import JSON_ARRAY_FIELDS

        doc = self._get_config()

        # Clear all JSON array fields
        for field in JSON_ARRAY_FIELDS:
            doc.set(field, None)

        # Trigger validation which calls ensure_json_fields
        doc.validate()

        # All should now be "[]"
        for field in JSON_ARRAY_FIELDS:
            value = doc.get(field)
            self.assertEqual(
                value, "[]",
                f"JSON array field '{field}' should default to '[]', got: {value!r}"
            )

    def test_11_json_object_fields_default_to_empty_object(self):
        """Test that JSON object fields default to '{}' when empty."""
        from frappe_pim.pim.doctype.tenant_config.tenant_config import JSON_OBJECT_FIELDS

        doc = self._get_config()

        # Clear all JSON object fields
        for field in JSON_OBJECT_FIELDS:
            doc.set(field, None)

        doc.validate()

        for field in JSON_OBJECT_FIELDS:
            value = doc.get(field)
            self.assertEqual(
                value, "{}",
                f"JSON object field '{field}' should default to '{{}}', got: {value!r}"
            )

    def test_12_json_array_field_accepts_list(self):
        """Test that passing a Python list auto-serializes to JSON string."""
        doc = self._get_config()
        doc.set("variant_axes", ["Size", "Color"])
        doc.validate()

        value = doc.get("variant_axes")
        self.assertIsInstance(value, str)
        parsed = json.loads(value)
        self.assertEqual(parsed, ["Size", "Color"])

    def test_13_json_object_field_accepts_dict(self):
        """Test that passing a Python dict auto-serializes to JSON string."""
        doc = self._get_config()
        doc.set("scoring_weights", {"attribute": 30, "content": 25})
        doc.validate()

        value = doc.get("scoring_weights")
        self.assertIsInstance(value, str)
        parsed = json.loads(value)
        self.assertEqual(parsed, {"attribute": 30, "content": 25})

    def test_14_get_json_field_parses_array(self):
        """Test get_json_field returns parsed list for array fields."""
        doc = self._get_config()
        doc.set("brand_names", json.dumps(["BrandA", "BrandB"]))
        doc.validate()

        result = doc.get_json_field("brand_names")
        self.assertIsInstance(result, list)
        self.assertEqual(result, ["BrandA", "BrandB"])

    def test_15_get_json_field_parses_object(self):
        """Test get_json_field returns parsed dict for object fields."""
        doc = self._get_config()
        doc.set("scoring_weights", json.dumps({"media": 20}))
        doc.validate()

        result = doc.get_json_field("scoring_weights")
        self.assertIsInstance(result, dict)
        self.assertEqual(result, {"media": 20})

    def test_16_get_json_field_returns_default_for_empty(self):
        """Test get_json_field returns [] or {} for empty fields."""
        doc = self._get_config()
        doc.set("brand_names", None)
        doc.set("scoring_weights", None)
        doc.validate()

        self.assertEqual(doc.get_json_field("brand_names"), [])
        self.assertEqual(doc.get_json_field("scoring_weights"), {})

    def test_17_set_json_field_serializes(self):
        """Test set_json_field properly serializes Python objects."""
        doc = self._get_config()
        doc.set_json_field("selected_channels", ["shopify", "amazon"])

        raw = doc.get("selected_channels")
        self.assertIsInstance(raw, str)
        parsed = json.loads(raw)
        self.assertEqual(parsed, ["shopify", "amazon"])

    def test_18_json_field_invalid_json_handled(self):
        """Test _parse_json_field handles invalid JSON gracefully."""
        doc = self._get_config()

        # Set invalid JSON string directly
        doc.set("brand_names", "not valid json")

        # _parse_json_field should return default empty list
        result = doc._parse_json_field("brand_names")
        self.assertEqual(result, [])

    # ========================================================================
    # Section 3: Feature Flag Defaults
    # ========================================================================

    def test_20_feature_flag_defaults(self):
        """Test that feature flags have correct default values."""
        from frappe_pim.pim.doctype.tenant_config.tenant_config import FEATURE_FLAGS

        doc = self._get_config()
        flags = doc.get_feature_flags()

        self.assertIsInstance(flags, dict)
        # Should contain all defined flags
        for flag_name in FEATURE_FLAGS:
            self.assertIn(flag_name, flags)

    def test_21_feature_flag_enabled_defaults(self):
        """Test that enable_variants, enable_quality_scoring, enable_channels, enable_workflow default to 1."""
        doc = self._get_config()
        flags = doc.get_feature_flags()

        # These should default to enabled (1/True)
        enabled_by_default = [
            "enable_variants",
            "enable_quality_scoring",
            "enable_channels",
            "enable_workflow",
        ]
        for flag in enabled_by_default:
            # Get from the DocType JSON defaults
            meta = frappe.get_meta("Tenant Config")
            field = meta.get_field(flag)
            self.assertEqual(
                int(field.default or 0), 1,
                f"Feature flag '{flag}' should default to 1 in DocType definition"
            )

    def test_22_feature_flag_disabled_defaults(self):
        """Test that enable_translations, enable_ai, enable_bundling, enable_competitor_tracking default to 0."""
        disabled_by_default = [
            "enable_translations",
            "enable_ai",
            "enable_bundling",
            "enable_competitor_tracking",
        ]
        meta = frappe.get_meta("Tenant Config")
        for flag in disabled_by_default:
            field = meta.get_field(flag)
            self.assertEqual(
                int(field.default or 0), 0,
                f"Feature flag '{flag}' should default to 0 in DocType definition"
            )

    def test_23_set_feature_flags(self):
        """Test set_feature_flags updates multiple flags at once."""
        doc = self._get_config()
        doc.set_feature_flags({
            "enable_ai": True,
            "enable_bundling": True,
        })

        flags = doc.get_feature_flags()
        self.assertTrue(flags["enable_ai"])
        self.assertTrue(flags["enable_bundling"])

    def test_24_set_feature_flags_rejects_unknown(self):
        """Test set_feature_flags throws on unknown flag name."""
        doc = self._get_config()

        with self.assertRaises(frappe.ValidationError):
            doc.set_feature_flags({"nonexistent_flag": True})

    def test_25_set_feature_flags_false_disables(self):
        """Test that setting a flag to False disables it (sets 0)."""
        doc = self._get_config()
        doc.set_feature_flags({"enable_variants": False})

        self.assertEqual(doc.get("enable_variants"), 0)

    # ========================================================================
    # Section 4: Onboarding Status Validation
    # ========================================================================

    def test_30_valid_onboarding_statuses(self):
        """Test that all valid onboarding statuses pass validation."""
        from frappe_pim.pim.doctype.tenant_config.tenant_config import ONBOARDING_STATUSES

        doc = self._get_config()
        for status in ONBOARDING_STATUSES:
            doc.onboarding_status = status
            # Should not raise
            doc.validate_onboarding_status()

    def test_31_invalid_onboarding_status_raises(self):
        """Test that an invalid onboarding status raises ValidationError."""
        doc = self._get_config()
        doc.onboarding_status = "invalid_status"

        with self.assertRaises(frappe.ValidationError):
            doc.validate_onboarding_status()

    def test_32_empty_onboarding_status_defaults(self):
        """Test that empty onboarding status defaults to 'not_started'."""
        doc = self._get_config()
        doc.onboarding_status = None
        # Should not raise - defaults to "not_started" internally
        doc.validate_onboarding_status()

    # ========================================================================
    # Section 5: Industry Sector Validation
    # ========================================================================

    def test_40_valid_industry_sectors(self):
        """Test that all valid industry sectors pass validation."""
        from frappe_pim.pim.doctype.tenant_config.tenant_config import INDUSTRY_SECTORS

        doc = self._get_config()
        original = doc.selected_industry

        for sector in INDUSTRY_SECTORS:
            doc.selected_industry = sector
            if sector == "custom":
                doc.custom_industry_name = "Test Custom"
            else:
                doc.custom_industry_name = None
            # Should not raise
            doc.validate_industry()

        doc.selected_industry = original

    def test_41_invalid_industry_raises(self):
        """Test that an invalid industry sector raises ValidationError."""
        doc = self._get_config()
        doc.selected_industry = "nonexistent_industry"

        with self.assertRaises(frappe.ValidationError):
            doc.validate_industry()

    def test_42_custom_industry_requires_name(self):
        """Test that 'custom' industry requires custom_industry_name."""
        doc = self._get_config()
        doc.selected_industry = "custom"
        doc.custom_industry_name = None

        with self.assertRaises(frappe.ValidationError):
            doc.validate_industry()

    def test_43_custom_industry_with_name_passes(self):
        """Test that 'custom' industry with name passes validation."""
        doc = self._get_config()
        doc.selected_industry = "custom"
        doc.custom_industry_name = "Artisanal Crafts"
        # Should not raise
        doc.validate_industry()

    def test_44_empty_industry_passes(self):
        """Test that empty industry passes validation (only validates if set)."""
        doc = self._get_config()
        doc.selected_industry = None
        # Should not raise — only validates if set
        doc.validate_industry()

    # ========================================================================
    # Section 6: Quality Threshold Validation
    # ========================================================================

    def test_50_valid_quality_thresholds(self):
        """Test that valid quality thresholds (0-100) pass validation."""
        doc = self._get_config()

        for threshold in [0, 1, 50, 70, 99, 100]:
            doc.quality_threshold = threshold
            # Should not raise
            doc.validate_quality_threshold()

    def test_51_quality_threshold_below_zero_raises(self):
        """Test that quality threshold below 0 raises ValidationError."""
        doc = self._get_config()
        doc.quality_threshold = -1

        with self.assertRaises(frappe.ValidationError):
            doc.validate_quality_threshold()

    def test_52_quality_threshold_above_100_raises(self):
        """Test that quality threshold above 100 raises ValidationError."""
        doc = self._get_config()
        doc.quality_threshold = 101

        with self.assertRaises(frappe.ValidationError):
            doc.validate_quality_threshold()

    def test_53_quality_threshold_none_passes(self):
        """Test that None quality threshold passes validation."""
        doc = self._get_config()
        doc.quality_threshold = None
        # Should not raise
        doc.validate_quality_threshold()

    # ========================================================================
    # Section 7: Computed Attribute Count
    # ========================================================================

    def test_60_compute_attribute_count_empty(self):
        """Test computed attribute count with no groups/custom/removed."""
        doc = self._get_config()
        doc.set("attribute_groups", "[]")
        doc.set("custom_attributes", "[]")
        doc.set("removed_template_attrs", "[]")
        doc.compute_attribute_count()

        self.assertEqual(doc.total_attribute_count, 0)

    def test_61_compute_attribute_count_with_groups(self):
        """Test computed attribute count sums attributes from groups."""
        doc = self._get_config()
        groups = [
            {"group_code": "general", "attributes": ["name", "desc", "brand"]},
            {"group_code": "sizing", "attributes": ["width", "height"]},
        ]
        doc.set("attribute_groups", json.dumps(groups))
        doc.set("custom_attributes", "[]")
        doc.set("removed_template_attrs", "[]")
        doc.compute_attribute_count()

        self.assertEqual(doc.total_attribute_count, 5)  # 3 + 2

    def test_62_compute_attribute_count_with_custom(self):
        """Test computed attribute count adds custom attributes."""
        doc = self._get_config()
        doc.set("attribute_groups", "[]")
        doc.set("custom_attributes", json.dumps([
            {"name": "custom_attr_1"},
            {"name": "custom_attr_2"},
        ]))
        doc.set("removed_template_attrs", "[]")
        doc.compute_attribute_count()

        self.assertEqual(doc.total_attribute_count, 2)

    def test_63_compute_attribute_count_subtracts_removed(self):
        """Test computed attribute count subtracts removed template attrs."""
        doc = self._get_config()
        groups = [
            {"group_code": "general", "attributes": ["name", "desc", "brand"]},
        ]
        doc.set("attribute_groups", json.dumps(groups))
        doc.set("custom_attributes", "[]")
        doc.set("removed_template_attrs", json.dumps(["name"]))
        doc.compute_attribute_count()

        self.assertEqual(doc.total_attribute_count, 2)  # 3 - 1

    def test_64_compute_attribute_count_combined(self):
        """Test computed attribute count with all factors combined."""
        doc = self._get_config()
        groups = [
            {"group_code": "general", "attributes": ["a", "b", "c", "d"]},
        ]
        custom = [{"name": "x"}, {"name": "y"}]
        removed = ["c"]
        doc.set("attribute_groups", json.dumps(groups))
        doc.set("custom_attributes", json.dumps(custom))
        doc.set("removed_template_attrs", json.dumps(removed))
        doc.compute_attribute_count()

        self.assertEqual(doc.total_attribute_count, 5)  # 4 + 2 - 1

    # ========================================================================
    # Section 8: Step Data Persistence
    # ========================================================================

    def test_70_save_step_data_creates_entry(self):
        """Test save_step_data adds a new step entry to onboarding_step_data."""
        doc = self._get_config()
        doc.set("onboarding_step_data", "[]")
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        doc.save_step_data("company_info", 1, {"company_name": "Test"})

        doc.reload()
        step_data = doc.get_json_field("onboarding_step_data")
        self.assertIsInstance(step_data, list)
        self.assertEqual(len(step_data), 1)
        self.assertEqual(step_data[0]["step_id"], "company_info")
        self.assertEqual(step_data[0]["step_number"], 1)
        self.assertEqual(step_data[0]["data"]["company_name"], "Test")
        self.assertIn("saved_at", step_data[0])

    def test_71_save_step_data_updates_existing(self):
        """Test save_step_data replaces existing entry for same step."""
        doc = self._get_config()
        doc.set("onboarding_step_data", "[]")
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        # First save
        doc.save_step_data("company_info", 1, {"company_name": "First"})
        # Second save for same step
        doc.save_step_data("company_info", 1, {"company_name": "Updated"})

        doc.reload()
        step_data = doc.get_json_field("onboarding_step_data")
        self.assertEqual(len(step_data), 1)
        self.assertEqual(step_data[0]["data"]["company_name"], "Updated")

    def test_72_save_step_data_updates_current_step(self):
        """Test save_step_data updates onboarding_current_step."""
        doc = self._get_config()
        doc.set("onboarding_step_data", "[]")
        doc.onboarding_current_step = 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        doc.save_step_data("product_structure", 3, {"sku_count": "100"})

        doc.reload()
        self.assertEqual(doc.onboarding_current_step, 3)

    # ========================================================================
    # Section 9: Onboarding State Transitions
    # ========================================================================

    def test_80_mark_onboarding_started(self):
        """Test mark_onboarding_started sets status and timestamp."""
        doc = self._get_config()
        doc.onboarding_status = "not_started"
        doc.onboarding_started_at = None
        doc.onboarding_completed_at = None
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        doc.mark_onboarding_started()
        doc.reload()

        self.assertEqual(doc.onboarding_status, "in_progress")
        self.assertIsNotNone(doc.onboarding_started_at)
        self.assertEqual(doc.onboarding_current_step, 1)

    def test_81_mark_onboarding_completed(self):
        """Test mark_onboarding_completed sets status and timestamp."""
        doc = self._get_config()
        doc.onboarding_status = "in_progress"
        doc.onboarding_completed_at = None
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        doc.mark_onboarding_completed()
        doc.reload()

        self.assertEqual(doc.onboarding_status, "completed")
        self.assertIsNotNone(doc.onboarding_completed_at)

    def test_82_mark_onboarding_skipped(self):
        """Test mark_onboarding_skipped sets status and timestamp."""
        doc = self._get_config()
        doc.onboarding_status = "not_started"
        doc.onboarding_completed_at = None
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        doc.mark_onboarding_skipped()
        doc.reload()

        self.assertEqual(doc.onboarding_status, "skipped")
        self.assertIsNotNone(doc.onboarding_completed_at)

    def test_83_mark_started_when_already_completed_raises(self):
        """Test mark_onboarding_started raises when already completed."""
        doc = self._get_config()
        doc.onboarding_status = "completed"
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        with self.assertRaises(frappe.ValidationError):
            doc.mark_onboarding_started()

    def test_84_update_onboarding_step(self):
        """Test update_onboarding_step sets step number and in_progress status."""
        doc = self._get_config()
        doc.onboarding_status = "not_started"
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        doc.update_onboarding_step(5)
        doc.reload()

        self.assertEqual(doc.onboarding_current_step, 5)
        self.assertEqual(doc.onboarding_status, "in_progress")

    def test_85_update_onboarding_step_invalid_number(self):
        """Test update_onboarding_step rejects step numbers outside 1-12."""
        doc = self._get_config()

        with self.assertRaises(frappe.ValidationError):
            doc.update_onboarding_step(0)

        with self.assertRaises(frappe.ValidationError):
            doc.update_onboarding_step(13)

    # ========================================================================
    # Section 10: Config Summary
    # ========================================================================

    def test_90_config_summary_structure(self):
        """Test get_config_summary returns expected keys."""
        doc = self._get_config()
        summary = doc.get_config_summary()

        expected_keys = [
            "company_name",
            "company_size",
            "selected_industry",
            "industry_template_version",
            "estimated_sku_count",
            "uses_variants",
            "total_attribute_count",
            "primary_channel",
            "primary_language",
            "workflow_complexity",
            "quality_threshold",
            "onboarding_status",
            "onboarding_current_step",
            "feature_flags",
        ]

        for key in expected_keys:
            self.assertIn(key, summary, f"Config summary missing key: {key}")

    def test_91_config_summary_feature_flags_included(self):
        """Test get_config_summary includes feature_flags as dict."""
        doc = self._get_config()
        summary = doc.get_config_summary()

        self.assertIsInstance(summary["feature_flags"], dict)
        self.assertIn("enable_variants", summary["feature_flags"])

    def test_92_config_summary_defaults(self):
        """Test config summary provides sensible defaults for empty fields."""
        doc = self._get_config()
        summary = doc.get_config_summary()

        # These should have default values even if not explicitly set
        self.assertIsNotNone(summary["primary_language"])
        self.assertIsNotNone(summary["workflow_complexity"])
        self.assertIsNotNone(summary["quality_threshold"])
        self.assertIsNotNone(summary["onboarding_status"])

    # ========================================================================
    # Section 11: Before Save Hooks
    # ========================================================================

    def test_95_before_save_sets_started_timestamp(self):
        """Test before_save sets onboarding_started_at when status is in_progress."""
        doc = self._get_config()
        doc.onboarding_status = "in_progress"
        doc.onboarding_started_at = None
        doc.before_save()

        self.assertIsNotNone(doc.onboarding_started_at)

    def test_96_before_save_sets_completed_timestamp(self):
        """Test before_save sets onboarding_completed_at when status is completed."""
        doc = self._get_config()
        doc.onboarding_status = "completed"
        doc.onboarding_completed_at = None
        doc.before_save()

        self.assertIsNotNone(doc.onboarding_completed_at)

    def test_97_before_save_does_not_overwrite_timestamps(self):
        """Test before_save does not overwrite existing timestamps."""
        doc = self._get_config()
        original_time = "2026-01-01 00:00:00"
        doc.onboarding_status = "in_progress"
        doc.onboarding_started_at = original_time
        doc.before_save()

        self.assertEqual(str(doc.onboarding_started_at), original_time)
