"""
Test Golden Record merge with Survivorship Rules
Tests the MDM Golden Record pattern including merge operations, survivorship rule application,
field provenance tracking, and conflict resolution.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime
import json


class TestSurvivorshipRule(FrappeTestCase):
    """Tests for Survivorship Rule DocType"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for all tests"""
        super().setUpClass()
        cls._cleanup_test_data()
        cls._create_test_source_systems()

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove any test data from previous runs"""
        # Delete test golden records first (due to foreign key)
        frappe.db.sql(
            "DELETE FROM `tabGolden Record Source` WHERE parent IN "
            "(SELECT name FROM `tabGolden Record` WHERE record_title LIKE 'Test%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabGolden Record` WHERE record_title LIKE 'Test%'"
        )
        # Delete test survivorship rules
        frappe.db.sql(
            "DELETE FROM `tabSource Priority Item` WHERE parent IN "
            "(SELECT name FROM `tabSurvivorship Rule` WHERE rule_code LIKE 'test-%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabSurvivorship Rule` WHERE rule_code LIKE 'test-%'"
        )
        # Delete test source systems
        frappe.db.sql(
            "DELETE FROM `tabSource System` WHERE system_code LIKE 'test-%'"
        )
        frappe.db.commit()

    @classmethod
    def _create_test_source_systems(cls):
        """Create test source systems for survivorship testing"""
        cls.source_erp = frappe.get_doc({
            "doctype": "Source System",
            "system_name": "Test ERP System",
            "system_code": "test-erp",
            "system_type": "ERP",
            "enabled": 1,
            "priority": 1,
            "confidence_level": 95
        })
        cls.source_erp.insert(ignore_permissions=True)

        cls.source_ecom = frappe.get_doc({
            "doctype": "Source System",
            "system_name": "Test E-Commerce",
            "system_code": "test-ecom",
            "system_type": "E-Commerce",
            "enabled": 1,
            "priority": 2,
            "confidence_level": 80
        })
        cls.source_ecom.insert(ignore_permissions=True)

        cls.source_manual = frappe.get_doc({
            "doctype": "Source System",
            "system_name": "Test Manual Entry",
            "system_code": "test-manual",
            "system_type": "Manual Entry",
            "enabled": 1,
            "priority": 3,
            "confidence_level": 70
        })
        cls.source_manual.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()

    def _create_survivorship_rule(self, rule_code, rule_type="Most Recent", **kwargs):
        """Helper to create a test survivorship rule"""
        doc = frappe.get_doc({
            "doctype": "Survivorship Rule",
            "rule_name": kwargs.get("rule_name", f"Test Rule {rule_code}"),
            "rule_code": rule_code,
            "rule_type": rule_type,
            "enabled": kwargs.get("enabled", 1),
            "is_default": kwargs.get("is_default", 0),
            "applies_to": kwargs.get("applies_to", "All Fields"),
            "specific_fields": kwargs.get("specific_fields"),
            "field_pattern": kwargs.get("field_pattern"),
            "tiebreaker_rule": kwargs.get("tiebreaker_rule", "Most Recent"),
            "prefer_non_empty": kwargs.get("prefer_non_empty", 1),
            "trim_whitespace": kwargs.get("trim_whitespace", 1),
            "min_confidence_threshold": kwargs.get("min_confidence_threshold", 0),
            "authoritative_source": kwargs.get("authoritative_source"),
            "allow_fallback": kwargs.get("allow_fallback", 1),
            "fallback_rule_type": kwargs.get("fallback_rule_type"),
        })
        doc.insert(ignore_permissions=True)
        return doc

    def test_survivorship_rule_creation(self):
        """Test basic survivorship rule creation"""
        rule = self._create_survivorship_rule("test-basic")

        self.assertTrue(rule.name)
        self.assertEqual(rule.rule_code, "test-basic")
        self.assertEqual(rule.rule_type, "Most Recent")
        self.assertEqual(rule.enabled, 1)

    def test_survivorship_rule_code_validation(self):
        """Test rule_code must be valid slug format"""
        # Valid code
        rule = self._create_survivorship_rule("test-valid-code")
        self.assertEqual(rule.rule_code, "test-valid-code")

        # Invalid code with uppercase should fail
        with self.assertRaises(frappe.ValidationError):
            self._create_survivorship_rule("TEST-INVALID")

    def test_survivorship_rule_types(self):
        """Test all survivorship rule types can be created"""
        rule_types = [
            "Source Priority",
            "Most Recent",
            "Highest Confidence",
            "Authoritative Source",
            "Most Complete",
        ]

        for idx, rule_type in enumerate(rule_types):
            extra_kwargs = {}
            if rule_type == "Source Priority":
                # Create rule first, then add source priorities
                rule = frappe.get_doc({
                    "doctype": "Survivorship Rule",
                    "rule_name": f"Test {rule_type}",
                    "rule_code": f"test-type-{idx}",
                    "rule_type": rule_type,
                    "enabled": 1,
                    "applies_to": "All Fields",
                    "source_priorities": [
                        {
                            "source_system": self.source_erp.name,
                            "rank": 1
                        },
                        {
                            "source_system": self.source_ecom.name,
                            "rank": 2
                        }
                    ]
                })
                rule.insert(ignore_permissions=True)
            elif rule_type == "Authoritative Source":
                extra_kwargs["authoritative_source"] = self.source_erp.name
                extra_kwargs["allow_fallback"] = 1
                extra_kwargs["fallback_rule_type"] = "Most Recent"
                rule = self._create_survivorship_rule(
                    f"test-type-{idx}",
                    rule_type=rule_type,
                    **extra_kwargs
                )
            else:
                rule = self._create_survivorship_rule(
                    f"test-type-{idx}",
                    rule_type=rule_type
                )

            self.assertEqual(rule.rule_type, rule_type)

    def test_default_rule_uniqueness(self):
        """Test only one default rule can exist"""
        rule1 = self._create_survivorship_rule(
            "test-default-1",
            is_default=1
        )
        self.assertEqual(rule1.is_default, 1)

        # Creating second default should fail
        with self.assertRaises(frappe.ValidationError):
            self._create_survivorship_rule(
                "test-default-2",
                is_default=1
            )

    def test_applies_to_field_all_fields(self):
        """Test applies_to_field for 'All Fields' scope"""
        rule = self._create_survivorship_rule(
            "test-all-fields",
            applies_to="All Fields"
        )

        self.assertTrue(rule.applies_to_field("product_name"))
        self.assertTrue(rule.applies_to_field("description"))
        self.assertTrue(rule.applies_to_field("any_field"))

    def test_applies_to_field_specific_fields(self):
        """Test applies_to_field for 'Specific Fields' scope"""
        rule = self._create_survivorship_rule(
            "test-specific-fields",
            applies_to="Specific Fields",
            specific_fields="product_name, description, short_description"
        )

        self.assertTrue(rule.applies_to_field("product_name"))
        self.assertTrue(rule.applies_to_field("description"))
        self.assertFalse(rule.applies_to_field("sku"))
        self.assertFalse(rule.applies_to_field("price"))

    def test_applies_to_field_pattern(self):
        """Test applies_to_field for 'Field Pattern' scope"""
        rule = self._create_survivorship_rule(
            "test-field-pattern",
            applies_to="Field Pattern",
            field_pattern=r"^attr_.*"
        )

        self.assertTrue(rule.applies_to_field("attr_color"))
        self.assertTrue(rule.applies_to_field("attr_size"))
        self.assertFalse(rule.applies_to_field("product_name"))
        self.assertFalse(rule.applies_to_field("description"))

    def test_apply_most_recent_rule(self):
        """Test Most Recent survivorship rule selects newest value"""
        rule = self._create_survivorship_rule(
            "test-most-recent",
            rule_type="Most Recent"
        )

        field_values = [
            {
                "value": "Old Name",
                "source_system": "test-manual",
                "timestamp": "2024-01-01 10:00:00",
                "confidence": 70
            },
            {
                "value": "New Name",
                "source_system": "test-ecom",
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 80
            },
            {
                "value": "Oldest Name",
                "source_system": "test-erp",
                "timestamp": "2023-12-01 10:00:00",
                "confidence": 95
            }
        ]

        winner = rule.apply_rule(field_values)

        self.assertEqual(winner["value"], "New Name")
        self.assertEqual(winner["source_system"], "test-ecom")

    def test_apply_highest_confidence_rule(self):
        """Test Highest Confidence survivorship rule selects most confident value"""
        rule = self._create_survivorship_rule(
            "test-highest-confidence",
            rule_type="Highest Confidence"
        )

        field_values = [
            {
                "value": "Low Confidence",
                "source_system": "test-manual",
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 70
            },
            {
                "value": "Medium Confidence",
                "source_system": "test-ecom",
                "timestamp": "2024-01-10 10:00:00",
                "confidence": 80
            },
            {
                "value": "High Confidence",
                "source_system": "test-erp",
                "timestamp": "2024-01-05 10:00:00",
                "confidence": 95
            }
        ]

        winner = rule.apply_rule(field_values)

        self.assertEqual(winner["value"], "High Confidence")
        self.assertEqual(winner["confidence"], 95)

    def test_apply_source_priority_rule(self):
        """Test Source Priority survivorship rule selects by priority rank"""
        rule = frappe.get_doc({
            "doctype": "Survivorship Rule",
            "rule_name": "Test Source Priority",
            "rule_code": "test-source-priority",
            "rule_type": "Source Priority",
            "enabled": 1,
            "applies_to": "All Fields",
            "source_priorities": [
                {"source_system": self.source_erp.name, "rank": 1},
                {"source_system": self.source_ecom.name, "rank": 2},
                {"source_system": self.source_manual.name, "rank": 3}
            ]
        })
        rule.insert(ignore_permissions=True)

        field_values = [
            {
                "value": "Manual Value",
                "source_system": self.source_manual.name,
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 100
            },
            {
                "value": "E-Commerce Value",
                "source_system": self.source_ecom.name,
                "timestamp": "2024-01-10 10:00:00",
                "confidence": 90
            },
            {
                "value": "ERP Value",
                "source_system": self.source_erp.name,
                "timestamp": "2024-01-05 10:00:00",
                "confidence": 80
            }
        ]

        winner = rule.apply_rule(field_values)

        # ERP has rank 1 (highest priority), should win regardless of timestamp/confidence
        self.assertEqual(winner["value"], "ERP Value")
        self.assertEqual(winner["source_system"], self.source_erp.name)

    def test_apply_most_complete_rule(self):
        """Test Most Complete survivorship rule selects longest/most complete value"""
        rule = self._create_survivorship_rule(
            "test-most-complete",
            rule_type="Most Complete"
        )

        field_values = [
            {
                "value": "Short",
                "source_system": "test-erp",
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 95
            },
            {
                "value": "This is a much longer and more complete description with details",
                "source_system": "test-ecom",
                "timestamp": "2024-01-10 10:00:00",
                "confidence": 80
            },
            {
                "value": "Medium length text",
                "source_system": "test-manual",
                "timestamp": "2024-01-05 10:00:00",
                "confidence": 70
            }
        ]

        winner = rule.apply_rule(field_values)

        # Longest value wins
        self.assertEqual(winner["source_system"], "test-ecom")
        self.assertIn("longer and more complete", winner["value"])

    def test_apply_authoritative_source_rule(self):
        """Test Authoritative Source survivorship rule selects from authoritative source"""
        rule = self._create_survivorship_rule(
            "test-authoritative",
            rule_type="Authoritative Source",
            authoritative_source=self.source_erp.name,
            allow_fallback=1,
            fallback_rule_type="Most Recent"
        )

        field_values = [
            {
                "value": "Authoritative Value",
                "source_system": self.source_erp.name,
                "timestamp": "2024-01-01 10:00:00",
                "confidence": 80
            },
            {
                "value": "Other Value",
                "source_system": self.source_ecom.name,
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 100
            }
        ]

        winner = rule.apply_rule(field_values)

        # Authoritative source wins even with older timestamp and lower confidence
        self.assertEqual(winner["value"], "Authoritative Value")
        self.assertEqual(winner["source_system"], self.source_erp.name)

    def test_authoritative_source_fallback(self):
        """Test fallback when authoritative source has no value"""
        rule = self._create_survivorship_rule(
            "test-authoritative-fallback",
            rule_type="Authoritative Source",
            authoritative_source=self.source_erp.name,
            allow_fallback=1,
            fallback_rule_type="Most Recent"
        )

        # Authoritative source has empty value
        field_values = [
            {
                "value": "",  # Empty
                "source_system": self.source_erp.name,
                "timestamp": "2024-01-01 10:00:00",
                "confidence": 95
            },
            {
                "value": "Older Value",
                "source_system": self.source_manual.name,
                "timestamp": "2024-01-05 10:00:00",
                "confidence": 70
            },
            {
                "value": "Newer Value",
                "source_system": self.source_ecom.name,
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 80
            }
        ]

        winner = rule.apply_rule(field_values)

        # Should fallback to Most Recent rule since authoritative has empty value
        self.assertEqual(winner["value"], "Newer Value")

    def test_tiebreaker_most_recent(self):
        """Test tie-breaker using Most Recent"""
        rule = self._create_survivorship_rule(
            "test-tiebreaker-recent",
            rule_type="Highest Confidence",
            tiebreaker_rule="Most Recent"
        )

        # Same confidence - tie should be broken by most recent
        field_values = [
            {
                "value": "Old Value",
                "source_system": "test-erp",
                "timestamp": "2024-01-01 10:00:00",
                "confidence": 90
            },
            {
                "value": "New Value",
                "source_system": "test-ecom",
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 90
            }
        ]

        winner = rule.apply_rule(field_values)

        self.assertEqual(winner["value"], "New Value")

    def test_tiebreaker_longest_value(self):
        """Test tie-breaker using Longest Value"""
        rule = self._create_survivorship_rule(
            "test-tiebreaker-longest",
            rule_type="Highest Confidence",
            tiebreaker_rule="Longest Value"
        )

        field_values = [
            {
                "value": "Short",
                "source_system": "test-erp",
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 90
            },
            {
                "value": "This is a longer description",
                "source_system": "test-ecom",
                "timestamp": "2024-01-01 10:00:00",
                "confidence": 90
            }
        ]

        winner = rule.apply_rule(field_values)

        self.assertEqual(winner["value"], "This is a longer description")

    def test_prefer_non_empty_values(self):
        """Test prefer_non_empty setting filters out empty values"""
        rule = self._create_survivorship_rule(
            "test-prefer-non-empty",
            rule_type="Most Recent",
            prefer_non_empty=1
        )

        # Most recent has empty value
        field_values = [
            {
                "value": "",
                "source_system": "test-ecom",
                "timestamp": "2024-01-15 10:00:00",
                "confidence": 90
            },
            {
                "value": "Older but has value",
                "source_system": "test-erp",
                "timestamp": "2024-01-01 10:00:00",
                "confidence": 80
            }
        ]

        winner = rule.apply_rule(field_values)

        # Should prefer non-empty value even though it's older
        self.assertEqual(winner["value"], "Older but has value")

    def test_single_value_returns_immediately(self):
        """Test single value returns without applying rules"""
        rule = self._create_survivorship_rule(
            "test-single-value",
            rule_type="Most Recent"
        )

        field_values = [
            {
                "value": "Only Value",
                "source_system": "test-erp",
                "timestamp": "2024-01-01 10:00:00",
                "confidence": 80
            }
        ]

        winner = rule.apply_rule(field_values)

        self.assertEqual(winner["value"], "Only Value")

    def test_empty_values_returns_none(self):
        """Test empty values list returns None"""
        rule = self._create_survivorship_rule(
            "test-empty-values",
            rule_type="Most Recent"
        )

        winner = rule.apply_rule([])

        self.assertIsNone(winner)


class TestGoldenRecord(FrappeTestCase):
    """Tests for Golden Record DocType"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for all tests"""
        super().setUpClass()
        cls._cleanup_test_data()
        cls._create_test_fixtures()

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests"""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove any test data from previous runs"""
        frappe.db.sql(
            "DELETE FROM `tabGolden Record Source` WHERE parent IN "
            "(SELECT name FROM `tabGolden Record` WHERE record_title LIKE 'Test%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabGolden Record` WHERE record_title LIKE 'Test%'"
        )
        frappe.db.sql(
            "DELETE FROM `tabSource Priority Item` WHERE parent IN "
            "(SELECT name FROM `tabSurvivorship Rule` WHERE rule_code LIKE 'test-%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabSurvivorship Rule` WHERE rule_code LIKE 'test-%'"
        )
        frappe.db.sql(
            "DELETE FROM `tabSource System` WHERE system_code LIKE 'test-%'"
        )
        frappe.db.commit()

    @classmethod
    def _create_test_fixtures(cls):
        """Create test fixtures for golden record tests"""
        # Create source systems
        cls.source_erp = frappe.get_doc({
            "doctype": "Source System",
            "system_name": "Test ERP",
            "system_code": "test-erp-gr",
            "system_type": "ERP",
            "enabled": 1,
            "priority": 1,
            "confidence_level": 95
        })
        cls.source_erp.insert(ignore_permissions=True)

        cls.source_ecom = frappe.get_doc({
            "doctype": "Source System",
            "system_name": "Test E-Commerce",
            "system_code": "test-ecom-gr",
            "system_type": "E-Commerce",
            "enabled": 1,
            "priority": 2,
            "confidence_level": 80
        })
        cls.source_ecom.insert(ignore_permissions=True)

        # Create survivorship rules
        cls.rule_most_recent = frappe.get_doc({
            "doctype": "Survivorship Rule",
            "rule_name": "Test Most Recent GR",
            "rule_code": "test-most-recent-gr",
            "rule_type": "Most Recent",
            "enabled": 1,
            "is_default": 1,
            "applies_to": "All Fields",
            "prefer_non_empty": 1
        })
        cls.rule_most_recent.insert(ignore_permissions=True)

        cls.rule_source_priority = frappe.get_doc({
            "doctype": "Survivorship Rule",
            "rule_name": "Test Source Priority GR",
            "rule_code": "test-source-priority-gr",
            "rule_type": "Source Priority",
            "enabled": 1,
            "applies_to": "All Fields",
            "source_priorities": [
                {"source_system": cls.source_erp.name, "rank": 1},
                {"source_system": cls.source_ecom.name, "rank": 2}
            ]
        })
        cls.rule_source_priority.insert(ignore_permissions=True)

        cls.rule_highest_confidence = frappe.get_doc({
            "doctype": "Survivorship Rule",
            "rule_name": "Test Highest Confidence GR",
            "rule_code": "test-highest-conf-gr",
            "rule_type": "Highest Confidence",
            "enabled": 1,
            "applies_to": "All Fields"
        })
        cls.rule_highest_confidence.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up after each test"""
        # Delete golden records created in this test
        frappe.db.sql(
            "DELETE FROM `tabGolden Record Source` WHERE parent IN "
            "(SELECT name FROM `tabGolden Record` WHERE record_title LIKE 'Test GR%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabGolden Record` WHERE record_title LIKE 'Test GR%'"
        )
        frappe.db.commit()

    def _create_golden_record(self, title="Test GR", **kwargs):
        """Helper to create a test golden record"""
        doc = frappe.get_doc({
            "doctype": "Golden Record",
            "record_title": title,
            "record_type": kwargs.get("record_type", "Product"),
            "status": kwargs.get("status", "Draft"),
            "survivorship_rule": kwargs.get("survivorship_rule"),
            "use_default_rule": kwargs.get("use_default_rule", 1),
        })
        doc.insert(ignore_permissions=True)
        return doc

    def test_golden_record_creation(self):
        """Test basic golden record creation"""
        gr = self._create_golden_record(title="Test GR Creation")

        self.assertTrue(gr.name)
        self.assertEqual(gr.record_title, "Test GR Creation")
        self.assertEqual(gr.record_type, "Product")
        self.assertEqual(gr.status, "Draft")
        self.assertEqual(gr.source_count, 0)

    def test_golden_record_with_survivorship_rule(self):
        """Test golden record with explicit survivorship rule"""
        gr = self._create_golden_record(
            title="Test GR With Rule",
            survivorship_rule=self.rule_source_priority.name
        )

        self.assertEqual(gr.survivorship_rule, self.rule_source_priority.name)

    def test_get_survivorship_rule_doc_explicit(self):
        """Test get_survivorship_rule_doc returns explicit rule"""
        gr = self._create_golden_record(
            title="Test GR Explicit Rule",
            survivorship_rule=self.rule_source_priority.name
        )

        rule_doc = gr.get_survivorship_rule_doc()

        self.assertIsNotNone(rule_doc)
        self.assertEqual(rule_doc.name, self.rule_source_priority.name)

    def test_get_survivorship_rule_doc_default(self):
        """Test get_survivorship_rule_doc returns default rule"""
        gr = self._create_golden_record(
            title="Test GR Default Rule",
            use_default_rule=1
        )

        rule_doc = gr.get_survivorship_rule_doc()

        self.assertIsNotNone(rule_doc)
        self.assertEqual(rule_doc.is_default, 1)

    def test_merge_source_record_first_source(self):
        """Test merging first source record sets all values"""
        gr = self._create_golden_record(
            title="Test GR First Merge",
            survivorship_rule=self.rule_most_recent.name
        )

        source_data = {
            "product_name": "Test Product",
            "sku": "TEST-001",
            "description": "Test description"
        }

        result = gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data=source_data
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["fields_updated"]), 3)
        self.assertIn("product_name", result["fields_updated"])
        self.assertIn("sku", result["fields_updated"])
        self.assertIn("description", result["fields_updated"])

        # Verify merged data
        gr.reload()
        merged_data = frappe.parse_json(gr.merged_data)
        self.assertEqual(merged_data["product_name"], "Test Product")
        self.assertEqual(merged_data["sku"], "TEST-001")

    def test_merge_source_record_with_conflicts(self):
        """Test merging second source with conflicting values"""
        gr = self._create_golden_record(
            title="Test GR Conflicts",
            survivorship_rule=self.rule_most_recent.name
        )

        # First merge
        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={
                "product_name": "ERP Name",
                "sku": "TEST-001"
            }
        )

        # Second merge with conflicting product_name
        result = gr.merge_source_record(
            source_system=self.source_ecom.name,
            source_record_id="ECOM-001",
            source_data={
                "product_name": "E-Commerce Name",  # Conflict!
                "description": "New description"  # New field
            }
        )

        self.assertTrue(result["success"])
        self.assertGreater(len(result["conflicts"]), 0)

        # Find the product_name conflict
        product_name_conflict = None
        for conflict in result["conflicts"]:
            if conflict["field"] == "product_name":
                product_name_conflict = conflict
                break

        self.assertIsNotNone(product_name_conflict)
        self.assertEqual(product_name_conflict["old_value"], "ERP Name")
        self.assertEqual(product_name_conflict["new_value"], "E-Commerce Name")

    def test_merge_with_source_priority_rule(self):
        """Test merge uses source priority rule correctly"""
        gr = self._create_golden_record(
            title="Test GR Source Priority Merge",
            survivorship_rule=self.rule_source_priority.name
        )

        # Merge lower priority source first (E-Commerce, rank 2)
        gr.merge_source_record(
            source_system=self.source_ecom.name,
            source_record_id="ECOM-001",
            source_data={
                "product_name": "E-Commerce Name",
                "price": "99.99"
            }
        )

        # Merge higher priority source second (ERP, rank 1)
        result = gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={
                "product_name": "ERP Name"  # Should win due to higher priority
            }
        )

        # ERP should win the conflict
        gr.reload()
        merged_data = frappe.parse_json(gr.merged_data)
        self.assertEqual(merged_data["product_name"], "ERP Name")

        # Check conflict resolution
        conflict = next(
            (c for c in result["conflicts"] if c["field"] == "product_name"),
            None
        )
        if conflict:
            self.assertEqual(conflict["winner"], "new")  # ERP (new) wins

    def test_field_provenance_tracking(self):
        """Test field provenance is tracked correctly"""
        gr = self._create_golden_record(
            title="Test GR Provenance",
            survivorship_rule=self.rule_most_recent.name
        )

        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={
                "product_name": "Test Product",
                "sku": "TEST-001"
            }
        )

        gr.reload()
        provenance = frappe.parse_json(gr.field_provenance)

        # Check provenance for product_name
        self.assertIn("product_name", provenance)
        self.assertEqual(provenance["product_name"]["source_system"], self.source_erp.name)
        self.assertEqual(provenance["product_name"]["source_record_id"], "ERP-001")
        self.assertIn("timestamp", provenance["product_name"])

    def test_merge_history_tracking(self):
        """Test merge history is tracked"""
        gr = self._create_golden_record(
            title="Test GR History",
            survivorship_rule=self.rule_most_recent.name
        )

        # First merge
        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={"product_name": "Product 1"}
        )

        # Second merge
        gr.merge_source_record(
            source_system=self.source_ecom.name,
            source_record_id="ECOM-001",
            source_data={"sku": "SKU-001"}
        )

        gr.reload()
        history = frappe.parse_json(gr.merge_history)

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["source_system"], self.source_erp.name)
        self.assertEqual(history[1]["source_system"], self.source_ecom.name)
        self.assertEqual(gr.total_merges, 2)

    def test_source_records_child_table(self):
        """Test source records child table is populated"""
        gr = self._create_golden_record(
            title="Test GR Source Records",
            survivorship_rule=self.rule_most_recent.name
        )

        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={"product_name": "Product 1"},
            merge_notes="Test merge"
        )

        gr.reload()

        self.assertEqual(len(gr.source_records), 1)
        self.assertEqual(gr.source_records[0].source_system, self.source_erp.name)
        self.assertEqual(gr.source_records[0].source_record_id, "ERP-001")
        self.assertEqual(gr.source_records[0].merge_notes, "Test merge")

    def test_source_count_updates(self):
        """Test source count is updated after merges"""
        gr = self._create_golden_record(
            title="Test GR Source Count",
            survivorship_rule=self.rule_most_recent.name
        )

        self.assertEqual(gr.source_count, 0)

        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={"product_name": "Product 1"}
        )

        gr.reload()
        self.assertEqual(gr.source_count, 1)

        gr.merge_source_record(
            source_system=self.source_ecom.name,
            source_record_id="ECOM-001",
            source_data={"sku": "SKU-001"}
        )

        gr.reload()
        self.assertEqual(gr.source_count, 2)

    def test_quality_score_calculation(self):
        """Test quality score is calculated"""
        gr = self._create_golden_record(
            title="Test GR Quality Score",
            survivorship_rule=self.rule_most_recent.name
        )

        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={
                "product_name": "Product",
                "sku": "SKU-001",
                "description": "Description"
            }
        )

        gr.reload()

        # Quality score should be > 0 after merge
        self.assertGreater(gr.quality_score, 0)

    def test_unmerge_source_record(self):
        """Test unmerging a source record"""
        gr = self._create_golden_record(
            title="Test GR Unmerge",
            survivorship_rule=self.rule_most_recent.name
        )

        # Merge two sources
        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={"product_name": "ERP Name", "sku": "SKU-001"}
        )

        gr.merge_source_record(
            source_system=self.source_ecom.name,
            source_record_id="ECOM-001",
            source_data={"description": "E-Commerce Desc"}
        )

        gr.reload()
        self.assertEqual(gr.source_count, 2)

        # Unmerge the ERP source
        result = gr.unmerge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001"
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["remaining_sources"], 1)

        gr.reload()
        self.assertEqual(gr.source_count, 1)
        self.assertEqual(gr.source_records[0].source_system, self.source_ecom.name)

    def test_unmerge_nonexistent_source_fails(self):
        """Test unmerging nonexistent source raises error"""
        gr = self._create_golden_record(
            title="Test GR Unmerge Fail",
            survivorship_rule=self.rule_most_recent.name
        )

        with self.assertRaises(frappe.ValidationError):
            gr.unmerge_source_record(
                source_system=self.source_erp.name,
                source_record_id="DOES-NOT-EXIST"
            )

    def test_get_merged_value(self):
        """Test get_merged_value returns correct field value"""
        gr = self._create_golden_record(
            title="Test GR Get Value",
            survivorship_rule=self.rule_most_recent.name
        )

        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={"product_name": "Test Product", "sku": "TEST-001"}
        )

        gr.reload()

        self.assertEqual(gr.get_merged_value("product_name"), "Test Product")
        self.assertEqual(gr.get_merged_value("sku"), "TEST-001")
        self.assertIsNone(gr.get_merged_value("nonexistent_field"))

    def test_get_field_provenance(self):
        """Test get_field_provenance returns correct provenance info"""
        gr = self._create_golden_record(
            title="Test GR Get Provenance",
            survivorship_rule=self.rule_most_recent.name
        )

        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={"product_name": "Test Product"}
        )

        gr.reload()

        prov = gr.get_field_provenance("product_name")

        self.assertIsNotNone(prov)
        self.assertEqual(prov["source_system"], self.source_erp.name)
        self.assertEqual(prov["source_record_id"], "ERP-001")

        # Nonexistent field returns None
        self.assertIsNone(gr.get_field_provenance("nonexistent_field"))

    def test_cannot_delete_active_golden_record_with_sources(self):
        """Test active golden record with sources cannot be deleted"""
        gr = self._create_golden_record(
            title="Test GR No Delete",
            status="Active",
            survivorship_rule=self.rule_most_recent.name
        )

        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={"product_name": "Test Product"}
        )

        gr.reload()
        gr.status = "Active"
        gr.save()

        with self.assertRaises(frappe.ValidationError):
            gr.delete()

    def test_mark_reviewed(self):
        """Test mark_reviewed updates review fields"""
        gr = self._create_golden_record(
            title="Test GR Review",
            survivorship_rule=self.rule_most_recent.name
        )

        gr.review_required = 1
        gr.save()

        gr.mark_reviewed(notes="Reviewed and approved")

        gr.reload()

        self.assertEqual(gr.review_required, 0)
        self.assertIsNotNone(gr.last_reviewed_at)
        self.assertIsNotNone(gr.last_reviewed_by)
        self.assertEqual(gr.review_notes, "Reviewed and approved")

    def test_match_keys_validation(self):
        """Test match_keys must be valid JSON"""
        gr = self._create_golden_record(title="Test GR Match Keys")

        # Valid JSON
        gr.match_keys = json.dumps({"sku": "TEST-001", "gtin": "1234567890123"})
        gr.save()  # Should not raise

        # Invalid JSON should fail
        gr.match_keys = "not valid json"
        with self.assertRaises(frappe.ValidationError):
            gr.save()

    def test_null_values_not_merged(self):
        """Test null values in source data are skipped"""
        gr = self._create_golden_record(
            title="Test GR Null Skip",
            survivorship_rule=self.rule_most_recent.name
        )

        gr.merge_source_record(
            source_system=self.source_erp.name,
            source_record_id="ERP-001",
            source_data={
                "product_name": "Test Product",
                "sku": None,  # Should be skipped
                "description": ""  # Empty string is NOT null, should be included
            }
        )

        gr.reload()
        merged_data = frappe.parse_json(gr.merged_data)

        self.assertEqual(merged_data["product_name"], "Test Product")
        self.assertNotIn("sku", merged_data)  # Null was skipped


class TestGoldenRecordAPI(FrappeTestCase):
    """Tests for Golden Record API functions"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        super().setUpClass()
        cls._cleanup_test_data()
        cls._create_test_fixtures()

    @classmethod
    def tearDownClass(cls):
        """Clean up after tests"""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove test data"""
        frappe.db.sql(
            "DELETE FROM `tabGolden Record Source` WHERE parent IN "
            "(SELECT name FROM `tabGolden Record` WHERE record_title LIKE 'API Test%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabGolden Record` WHERE record_title LIKE 'API Test%'"
        )
        frappe.db.sql(
            "DELETE FROM `tabSource Priority Item` WHERE parent IN "
            "(SELECT name FROM `tabSurvivorship Rule` WHERE rule_code LIKE 'test-api-%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabSurvivorship Rule` WHERE rule_code LIKE 'test-api-%'"
        )
        frappe.db.sql(
            "DELETE FROM `tabSource System` WHERE system_code LIKE 'test-api-%'"
        )
        frappe.db.commit()

    @classmethod
    def _create_test_fixtures(cls):
        """Create test fixtures"""
        cls.source_system = frappe.get_doc({
            "doctype": "Source System",
            "system_name": "API Test Source",
            "system_code": "test-api-source",
            "system_type": "ERP",
            "enabled": 1,
            "priority": 1,
            "confidence_level": 90
        })
        cls.source_system.insert(ignore_permissions=True)

        cls.rule = frappe.get_doc({
            "doctype": "Survivorship Rule",
            "rule_name": "API Test Rule",
            "rule_code": "test-api-rule",
            "rule_type": "Most Recent",
            "enabled": 1,
            "is_default": 1,
            "applies_to": "All Fields"
        })
        cls.rule.insert(ignore_permissions=True)

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.sql(
            "DELETE FROM `tabGolden Record Source` WHERE parent IN "
            "(SELECT name FROM `tabGolden Record` WHERE record_title LIKE 'API Test%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabGolden Record` WHERE record_title LIKE 'API Test%'"
        )
        frappe.db.commit()

    def test_get_golden_records(self):
        """Test get_golden_records API"""
        from frappe_pim.pim.doctype.golden_record.golden_record import get_golden_records

        # Create test golden records
        gr1 = frappe.get_doc({
            "doctype": "Golden Record",
            "record_title": "API Test GR 1",
            "record_type": "Product",
            "status": "Active"
        })
        gr1.insert(ignore_permissions=True)

        gr2 = frappe.get_doc({
            "doctype": "Golden Record",
            "record_title": "API Test GR 2",
            "record_type": "Supplier",
            "status": "Draft"
        })
        gr2.insert(ignore_permissions=True)

        # Get all
        results = get_golden_records()
        self.assertGreaterEqual(len(results), 2)

        # Filter by type
        results = get_golden_records(record_type="Product")
        self.assertTrue(all(r["record_type"] == "Product" for r in results if r["record_title"].startswith("API Test")))

        # Filter by status
        results = get_golden_records(status="Active")
        self.assertTrue(all(r["status"] == "Active" for r in results if r["record_title"].startswith("API Test")))

    def test_merge_into_golden_record_api(self):
        """Test merge_into_golden_record API"""
        from frappe_pim.pim.doctype.golden_record.golden_record import merge_into_golden_record

        gr = frappe.get_doc({
            "doctype": "Golden Record",
            "record_title": "API Test GR Merge",
            "record_type": "Product",
            "status": "Draft"
        })
        gr.insert(ignore_permissions=True)

        result = merge_into_golden_record(
            golden_record=gr.name,
            source_system=self.source_system.name,
            source_record_id="API-001",
            source_data={"product_name": "API Product", "sku": "API-SKU-001"}
        )

        self.assertTrue(result["success"])
        self.assertIn("product_name", result["fields_updated"])

    def test_create_golden_record_from_source_api(self):
        """Test create_golden_record_from_source API"""
        from frappe_pim.pim.doctype.golden_record.golden_record import create_golden_record_from_source

        result = create_golden_record_from_source(
            record_title="API Test GR Created",
            record_type="Product",
            source_system=self.source_system.name,
            source_record_id="NEW-001",
            source_data={"product_name": "New Product", "sku": "NEW-SKU"}
        )

        self.assertIn("golden_record", result)
        self.assertIn("merge_result", result)
        self.assertTrue(result["merge_result"]["success"])

        # Verify created
        gr = frappe.get_doc("Golden Record", result["golden_record"])
        self.assertEqual(gr.record_title, "API Test GR Created")

    def test_get_golden_record_provenance_api(self):
        """Test get_golden_record_provenance API"""
        from frappe_pim.pim.doctype.golden_record.golden_record import (
            get_golden_record_provenance,
            merge_into_golden_record
        )

        gr = frappe.get_doc({
            "doctype": "Golden Record",
            "record_title": "API Test GR Provenance",
            "record_type": "Product",
            "status": "Draft"
        })
        gr.insert(ignore_permissions=True)

        merge_into_golden_record(
            golden_record=gr.name,
            source_system=self.source_system.name,
            source_record_id="PROV-001",
            source_data={"product_name": "Provenance Test"}
        )

        result = get_golden_record_provenance(gr.name)

        self.assertIn("merged_data", result)
        self.assertIn("field_provenance", result)
        self.assertIn("source_records", result)
        self.assertEqual(len(result["source_records"]), 1)


class TestSurvivorshipRuleAPI(FrappeTestCase):
    """Tests for Survivorship Rule API functions"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        super().setUpClass()
        cls._cleanup_test_data()
        cls._create_test_fixtures()

    @classmethod
    def tearDownClass(cls):
        """Clean up after tests"""
        super().tearDownClass()
        cls._cleanup_test_data()

    @classmethod
    def _cleanup_test_data(cls):
        """Remove test data"""
        frappe.db.sql(
            "DELETE FROM `tabSource Priority Item` WHERE parent IN "
            "(SELECT name FROM `tabSurvivorship Rule` WHERE rule_code LIKE 'test-sr-api-%')"
        )
        frappe.db.sql(
            "DELETE FROM `tabSurvivorship Rule` WHERE rule_code LIKE 'test-sr-api-%'"
        )
        frappe.db.commit()

    @classmethod
    def _create_test_fixtures(cls):
        """Create test fixtures"""
        cls.rule = frappe.get_doc({
            "doctype": "Survivorship Rule",
            "rule_name": "SR API Test Rule",
            "rule_code": "test-sr-api-rule",
            "rule_type": "Most Recent",
            "enabled": 1,
            "is_default": 1,
            "applies_to": "All Fields"
        })
        cls.rule.insert(ignore_permissions=True)

    def test_get_survivorship_rules(self):
        """Test get_survivorship_rules API"""
        from frappe_pim.pim.doctype.survivorship_rule.survivorship_rule import get_survivorship_rules

        results = get_survivorship_rules(enabled_only=True)

        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(all(r.get("enabled") for r in results))

    def test_get_default_rule(self):
        """Test get_default_rule API"""
        from frappe_pim.pim.doctype.survivorship_rule.survivorship_rule import get_default_rule

        result = get_default_rule()

        self.assertIsNotNone(result)
        self.assertEqual(result["is_default"], 1)

    def test_apply_survivorship_rule_api(self):
        """Test apply_survivorship_rule API"""
        from frappe_pim.pim.doctype.survivorship_rule.survivorship_rule import apply_survivorship_rule

        field_values = [
            {"value": "Old", "source_system": "sys1", "timestamp": "2024-01-01", "confidence": 80},
            {"value": "New", "source_system": "sys2", "timestamp": "2024-01-15", "confidence": 80}
        ]

        result = apply_survivorship_rule(self.rule.name, field_values)

        self.assertIsNotNone(result)
        self.assertEqual(result["value"], "New")  # Most Recent wins

    def test_test_survivorship_rule_api(self):
        """Test test_survivorship_rule API (dry run)"""
        from frappe_pim.pim.doctype.survivorship_rule.survivorship_rule import test_survivorship_rule

        test_values = [
            {"value": "First", "source_system": "sys1", "timestamp": "2024-01-01", "confidence": 80},
            {"value": "Second", "source_system": "sys2", "timestamp": "2024-01-15", "confidence": 90}
        ]

        result = test_survivorship_rule(self.rule.name, test_values)

        self.assertIn("rule_name", result)
        self.assertIn("rule_type", result)
        self.assertIn("winning_value", result)
        self.assertIn("explanation", result)
