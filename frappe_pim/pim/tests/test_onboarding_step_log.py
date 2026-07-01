"""
Onboarding Step Log Unit Tests

Tests for the Onboarding Step Log DocType:
  - Audit trail creation via create_step_log API
  - Timestamp auto-setting (completed_at on complete/skip)
  - Time spent calculation (started_at to completed_at)
  - Form data storage and retrieval (JSON field)
  - Validation errors storage (JSON field)
  - Step ID validation (valid step identifiers)
  - Step number validation (1-12 range)
  - Action validation (completed, skipped, saved)
  - get_step_logs retrieval with filters

Run with:
    bench --site [site] run-tests --app frappe_pim \
        --module frappe_pim.pim.tests.test_onboarding_step_log
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_to_date
import json


class TestOnboardingStepLog(FrappeTestCase):
    """
    Tests for the Onboarding Step Log DocType controller and API.

    Covers:
    1. Audit trail creation (direct DocType insert)
    2. Audit trail creation via create_step_log API
    3. Timestamp auto-setting
    4. Time spent calculation
    5. Form data storage (JSON)
    6. Validation errors storage (JSON)
    7. Step ID validation
    8. Step number validation
    9. Action validation
    10. get_step_logs retrieval
    """

    TEST_USER = "step_log_test@example.com"

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
        """Remove any test step log records."""
        try:
            frappe.db.sql(
                "DELETE FROM `tabOnboarding Step Log` WHERE user LIKE %s",
                ("step_log_test%",)
            )
            frappe.db.commit()
        except Exception:
            pass

    def tearDown(self):
        """Clean up after each test."""
        frappe.db.rollback()

    def _create_step_log(
        self,
        step_id="company_info",
        step_number=1,
        action="completed",
        user=None,
        **kwargs,
    ):
        """Helper to create a test Onboarding Step Log document."""
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = user or self.TEST_USER
        doc.step_id = step_id
        doc.step_number = step_number
        doc.action = action

        for key, value in kwargs.items():
            doc.set(key, value)

        doc.flags.ignore_links = True
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return doc

    # ========================================================================
    # Section 1: Audit Trail Creation (Direct DocType)
    # ========================================================================

    def test_01_create_step_log_basic(self):
        """Test creating a basic step log entry."""
        doc = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="completed",
        )

        self.assertIsNotNone(doc.name)
        self.assertEqual(doc.user, self.TEST_USER)
        self.assertEqual(doc.step_id, "company_info")
        self.assertEqual(doc.step_number, 1)
        self.assertEqual(doc.action, "completed")

    def test_02_create_step_log_with_all_fields(self):
        """Test creating a step log with all optional fields."""
        started = now_datetime()
        form_data = json.dumps({"company_name": "Test Corp", "size": "1-10"})
        errors = json.dumps([{"field": "company_name", "error": "required"}])

        doc = self._create_step_log(
            step_id="industry_selection",
            step_number=2,
            action="saved",
            form_data=form_data,
            started_at=started,
            time_spent_seconds=45,
            validation_errors=errors,
        )

        self.assertIsNotNone(doc.name)
        self.assertEqual(doc.step_id, "industry_selection")
        self.assertEqual(doc.step_number, 2)
        self.assertEqual(doc.action, "saved")
        self.assertIsNotNone(doc.started_at)
        self.assertEqual(doc.time_spent_seconds, 45)

    def test_03_multiple_logs_for_same_step(self):
        """Test that multiple log entries can be created for the same step."""
        doc1 = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="saved",
            user="step_log_test_multi@example.com",
        )
        doc2 = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="completed",
            user="step_log_test_multi@example.com",
        )

        self.assertNotEqual(doc1.name, doc2.name)
        self.assertEqual(doc1.step_id, doc2.step_id)

    def test_04_log_uses_hash_autoname(self):
        """Test that step log names are auto-generated hashes."""
        doc = self._create_step_log(
            step_id="product_structure",
            step_number=3,
            action="completed",
        )
        # hash autoname generates random alphanumeric names
        self.assertIsNotNone(doc.name)
        self.assertGreater(len(doc.name), 0)

    # ========================================================================
    # Section 2: Audit Trail Creation via API
    # ========================================================================

    def test_10_create_step_log_api(self):
        """Test create_step_log whitelisted function."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import create_step_log

        result = create_step_log(
            step_id="company_info",
            step_number=1,
            action="completed",
        )

        self.assertIsInstance(result, dict)
        self.assertIn("name", result)
        self.assertEqual(result["step_id"], "company_info")
        self.assertEqual(result["step_number"], 1)
        self.assertEqual(result["action"], "completed")
        self.assertEqual(result["user"], frappe.session.user)

    def test_11_create_step_log_api_with_form_data(self):
        """Test create_step_log API with form data."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import create_step_log

        form_data = json.dumps({
            "industry": "fashion",
            "sub_vertical": "luxury",
        })

        result = create_step_log(
            step_id="industry_selection",
            step_number=2,
            action="completed",
            form_data=form_data,
        )

        self.assertIsNotNone(result["name"])
        self.assertEqual(result["step_id"], "industry_selection")

        # Verify form data was stored
        doc = frappe.get_doc("Onboarding Step Log", result["name"])
        stored_data = json.loads(doc.form_data)
        self.assertEqual(stored_data["industry"], "fashion")

    def test_12_create_step_log_api_with_timing(self):
        """Test create_step_log API with started_at and time_spent."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import create_step_log

        started = str(now_datetime())

        result = create_step_log(
            step_id="channel_setup",
            step_number=4,
            action="completed",
            started_at=started,
            time_spent_seconds=120,
        )

        self.assertEqual(result["time_spent_seconds"], 120)
        self.assertIsNotNone(result["started_at"])

    def test_13_create_step_log_api_completed_at_auto_set(self):
        """Test that completed_at is auto-set when action is completed."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import create_step_log

        result = create_step_log(
            step_id="workflow_preferences",
            step_number=5,
            action="completed",
        )

        self.assertIsNotNone(result["completed_at"])

    def test_14_create_step_log_api_with_validation_errors(self):
        """Test create_step_log API with validation errors JSON."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import create_step_log

        errors = json.dumps([
            {"field": "quality_threshold", "message": "Must be 0-100"},
        ])

        result = create_step_log(
            step_id="compliance",
            step_number=11,
            action="saved",
            validation_errors=errors,
        )

        doc = frappe.get_doc("Onboarding Step Log", result["name"])
        stored_errors = json.loads(doc.validation_errors)
        self.assertEqual(len(stored_errors), 1)
        self.assertEqual(stored_errors[0]["field"], "quality_threshold")

    # ========================================================================
    # Section 3: Timestamp Auto-Setting
    # ========================================================================

    def test_20_completed_at_auto_set_on_completed(self):
        """Test that completed_at is auto-set when action is 'completed'."""
        doc = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="completed",
            user="step_log_test_ts1@example.com",
        )

        self.assertIsNotNone(doc.completed_at)

    def test_21_completed_at_auto_set_on_skipped(self):
        """Test that completed_at is auto-set when action is 'skipped'."""
        doc = self._create_step_log(
            step_id="compliance",
            step_number=11,
            action="skipped",
            user="step_log_test_ts2@example.com",
        )

        self.assertIsNotNone(doc.completed_at)

    def test_22_completed_at_not_set_on_saved(self):
        """Test that completed_at is NOT auto-set when action is 'saved'."""
        doc = self._create_step_log(
            step_id="industry_selection",
            step_number=2,
            action="saved",
            user="step_log_test_ts3@example.com",
        )

        self.assertIsNone(doc.completed_at)

    def test_23_completed_at_not_overwritten(self):
        """Test that existing completed_at is not overwritten."""
        original_time = "2026-01-15 10:30:00"

        doc = self._create_step_log(
            step_id="product_structure",
            step_number=3,
            action="completed",
            completed_at=original_time,
            user="step_log_test_ts4@example.com",
        )

        self.assertEqual(str(doc.completed_at), "2026-01-15 10:30:00")

    # ========================================================================
    # Section 4: Time Spent Calculation
    # ========================================================================

    def test_30_time_spent_calculated_from_timestamps(self):
        """Test time_spent_seconds is calculated from started_at and completed_at."""
        started = now_datetime()
        completed = add_to_date(started, seconds=90)

        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_time1@example.com"
        doc.step_id = "company_info"
        doc.step_number = 1
        doc.action = "completed"
        doc.started_at = started
        doc.completed_at = completed
        doc.flags.ignore_links = True
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        self.assertEqual(doc.time_spent_seconds, 90)

    def test_31_time_spent_not_overwritten_if_already_set(self):
        """Test time_spent_seconds is not recalculated if already provided."""
        started = now_datetime()
        completed = add_to_date(started, seconds=90)

        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_time2@example.com"
        doc.step_id = "industry_selection"
        doc.step_number = 2
        doc.action = "completed"
        doc.started_at = started
        doc.completed_at = completed
        doc.time_spent_seconds = 45  # Manually set different value
        doc.flags.ignore_links = True
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Should keep the manually set value
        self.assertEqual(doc.time_spent_seconds, 45)

    def test_32_time_spent_not_set_without_both_timestamps(self):
        """Test time_spent_seconds not set when missing started_at or completed_at."""
        doc = self._create_step_log(
            step_id="channel_setup",
            step_number=4,
            action="saved",
            user="step_log_test_time3@example.com",
        )

        # saved action doesn't set completed_at, so time_spent should be None/0
        self.assertFalse(doc.time_spent_seconds)

    # ========================================================================
    # Section 5: Form Data Storage
    # ========================================================================

    def test_40_form_data_stores_json(self):
        """Test that form_data stores valid JSON string."""
        form_data = {
            "company_name": "Acme Corp",
            "company_size": "51-200",
            "existing_systems": ["erp", "spreadsheets"],
        }

        doc = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="completed",
            form_data=json.dumps(form_data),
            user="step_log_test_fd1@example.com",
        )

        stored = json.loads(doc.form_data)
        self.assertEqual(stored["company_name"], "Acme Corp")
        self.assertEqual(stored["company_size"], "51-200")
        self.assertIsInstance(stored["existing_systems"], list)
        self.assertEqual(len(stored["existing_systems"]), 2)

    def test_41_form_data_stores_nested_objects(self):
        """Test that form_data handles nested JSON objects."""
        form_data = {
            "scoring_weights": {
                "attribute": 30,
                "content": 25,
                "media": 20,
                "seo": 15,
                "compliance": 10,
            },
            "channels": [
                {"id": "shopify", "primary": True},
                {"id": "amazon", "primary": False},
            ],
        }

        doc = self._create_step_log(
            step_id="channel_setup",
            step_number=4,
            action="completed",
            form_data=json.dumps(form_data),
            user="step_log_test_fd2@example.com",
        )

        stored = json.loads(doc.form_data)
        self.assertEqual(stored["scoring_weights"]["attribute"], 30)
        self.assertEqual(len(stored["channels"]), 2)
        self.assertTrue(stored["channels"][0]["primary"])

    def test_42_form_data_empty_is_valid(self):
        """Test that None/empty form_data is allowed."""
        doc = self._create_step_log(
            step_id="compliance",
            step_number=11,
            action="skipped",
            user="step_log_test_fd3@example.com",
        )

        self.assertFalse(doc.form_data)

    def test_43_form_data_persists_after_reload(self):
        """Test that form_data persists after doc reload."""
        form_data = json.dumps({"key": "value", "count": 42})

        doc = self._create_step_log(
            step_id="product_structure",
            step_number=3,
            action="completed",
            form_data=form_data,
            user="step_log_test_fd4@example.com",
        )

        doc.reload()
        stored = json.loads(doc.form_data)
        self.assertEqual(stored["key"], "value")
        self.assertEqual(stored["count"], 42)

    # ========================================================================
    # Section 6: Validation Errors Storage
    # ========================================================================

    def test_45_validation_errors_stores_json(self):
        """Test that validation_errors stores valid JSON."""
        errors = [
            {"field": "company_name", "message": "Required field"},
            {"field": "company_size", "message": "Invalid selection"},
        ]

        doc = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="saved",
            validation_errors=json.dumps(errors),
            user="step_log_test_ve1@example.com",
        )

        stored = json.loads(doc.validation_errors)
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["field"], "company_name")

    # ========================================================================
    # Section 7: Step ID Validation
    # ========================================================================

    def test_50_valid_step_ids(self):
        """Test that all valid step IDs pass validation."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import VALID_STEP_IDS

        for i, step_id in enumerate(VALID_STEP_IDS):
            doc = self._create_step_log(
                step_id=step_id,
                step_number=min(i + 1, 12),
                action="completed",
                user=f"step_log_test_sid{i}@example.com",
            )
            self.assertEqual(doc.step_id, step_id)

    def test_51_invalid_step_id_raises(self):
        """Test that an invalid step_id raises ValidationError."""
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_sid_bad@example.com"
        doc.step_id = "nonexistent_step"
        doc.step_number = 1
        doc.action = "completed"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    # ========================================================================
    # Section 8: Step Number Validation
    # ========================================================================

    def test_60_valid_step_numbers(self):
        """Test that step numbers 1-12 pass validation."""
        for num in [1, 6, 12]:
            doc = self._create_step_log(
                step_id="company_info",
                step_number=num,
                action="completed",
                user=f"step_log_test_sn{num}@example.com",
            )
            self.assertEqual(doc.step_number, num)

    def test_61_step_number_zero_raises(self):
        """Test that step number 0 raises ValidationError."""
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_sn_bad1@example.com"
        doc.step_id = "company_info"
        doc.step_number = 0
        doc.action = "completed"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_62_step_number_above_12_raises(self):
        """Test that step number > 12 raises ValidationError."""
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_sn_bad2@example.com"
        doc.step_id = "company_info"
        doc.step_number = 13
        doc.action = "completed"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_63_step_number_negative_raises(self):
        """Test that negative step number raises ValidationError."""
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_sn_bad3@example.com"
        doc.step_id = "company_info"
        doc.step_number = -1
        doc.action = "completed"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    # ========================================================================
    # Section 9: Action Validation
    # ========================================================================

    def test_70_valid_actions(self):
        """Test that all valid actions pass validation."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import VALID_ACTIONS

        self.assertEqual(set(VALID_ACTIONS), {"completed", "skipped", "saved"})

        for i, action in enumerate(VALID_ACTIONS):
            doc = self._create_step_log(
                step_id="company_info",
                step_number=1,
                action=action,
                user=f"step_log_test_act{i}@example.com",
            )
            self.assertEqual(doc.action, action)

    def test_71_invalid_action_raises(self):
        """Test that an invalid action raises ValidationError."""
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_act_bad@example.com"
        doc.step_id = "company_info"
        doc.step_number = 1
        doc.action = "invalid_action"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    # ========================================================================
    # Section 10: get_step_logs Retrieval
    # ========================================================================

    def test_80_get_step_logs_returns_user_logs(self):
        """Test get_step_logs returns logs for the specified user."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import get_step_logs

        user = "step_log_test_get1@example.com"

        # Create a few logs
        self._create_step_log(
            step_id="company_info", step_number=1,
            action="completed", user=user,
        )
        self._create_step_log(
            step_id="industry_selection", step_number=2,
            action="completed", user=user,
        )

        logs = get_step_logs(user=user)
        self.assertIsInstance(logs, list)
        self.assertGreaterEqual(len(logs), 2)

        # All returned logs should belong to the user
        for log in logs:
            self.assertEqual(log["user"], user)

    def test_81_get_step_logs_filter_by_step(self):
        """Test get_step_logs filters by step_id."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import get_step_logs

        user = "step_log_test_get2@example.com"

        self._create_step_log(
            step_id="company_info", step_number=1,
            action="completed", user=user,
        )
        self._create_step_log(
            step_id="industry_selection", step_number=2,
            action="completed", user=user,
        )

        logs = get_step_logs(user=user, step_id="company_info")
        self.assertIsInstance(logs, list)
        self.assertGreaterEqual(len(logs), 1)

        for log in logs:
            self.assertEqual(log["step_id"], "company_info")

    def test_82_get_step_logs_returns_expected_fields(self):
        """Test get_step_logs returns expected field keys."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import get_step_logs

        user = "step_log_test_get3@example.com"

        self._create_step_log(
            step_id="product_structure", step_number=3,
            action="completed", user=user,
        )

        logs = get_step_logs(user=user)
        self.assertGreaterEqual(len(logs), 1)

        log = logs[0]
        expected_fields = [
            "name", "user", "step_id", "step_number",
            "action", "started_at", "completed_at",
            "time_spent_seconds", "creation",
        ]
        for field in expected_fields:
            self.assertIn(field, log, f"get_step_logs missing field: {field}")

    def test_83_get_step_logs_ordered_by_creation_desc(self):
        """Test get_step_logs returns logs in descending creation order."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import get_step_logs

        user = "step_log_test_get4@example.com"

        self._create_step_log(
            step_id="company_info", step_number=1,
            action="completed", user=user,
        )
        self._create_step_log(
            step_id="industry_selection", step_number=2,
            action="completed", user=user,
        )

        logs = get_step_logs(user=user)
        if len(logs) >= 2:
            # Most recent should be first
            self.assertGreaterEqual(
                str(logs[0]["creation"]),
                str(logs[1]["creation"]),
            )

    def test_84_get_step_logs_empty_for_unknown_user(self):
        """Test get_step_logs returns empty list for unknown user."""
        from frappe_pim.pim.doctype.onboarding_step_log.onboarding_step_log import get_step_logs

        logs = get_step_logs(user="nonexistent_user_xyz@example.com")
        self.assertIsInstance(logs, list)
        self.assertEqual(len(logs), 0)

    # ========================================================================
    # Section 11: JSON Field Validation
    # ========================================================================

    def test_90_invalid_form_data_json_raises(self):
        """Test that invalid JSON in form_data raises ValidationError."""
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_json1@example.com"
        doc.step_id = "company_info"
        doc.step_number = 1
        doc.action = "completed"
        doc.form_data = "invalid json {"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    def test_91_invalid_validation_errors_json_raises(self):
        """Test that invalid JSON in validation_errors raises ValidationError."""
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = "step_log_test_json2@example.com"
        doc.step_id = "company_info"
        doc.step_number = 1
        doc.action = "saved"
        doc.validation_errors = "not valid json"

        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)

    # ========================================================================
    # Section 12: Creation Timestamp
    # ========================================================================

    def test_95_creation_timestamp_set(self):
        """Test that creation timestamp is automatically set by Frappe."""
        doc = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="completed",
            user="step_log_test_ctime@example.com",
        )

        self.assertIsNotNone(doc.creation)

    def test_96_multiple_actions_same_step_creates_audit_trail(self):
        """Test creating a full audit trail: saved -> saved -> completed."""
        user = "step_log_test_trail@example.com"

        # First save (partial data)
        doc1 = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="saved",
            form_data=json.dumps({"company_name": "Draft"}),
            user=user,
        )

        # Second save (more data)
        doc2 = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="saved",
            form_data=json.dumps({"company_name": "Updated", "size": "11-50"}),
            user=user,
        )

        # Final completion
        doc3 = self._create_step_log(
            step_id="company_info",
            step_number=1,
            action="completed",
            form_data=json.dumps({"company_name": "Final Corp", "size": "11-50"}),
            user=user,
        )

        # All three should exist as separate audit entries
        self.assertNotEqual(doc1.name, doc2.name)
        self.assertNotEqual(doc2.name, doc3.name)

        # saved entries should not have completed_at
        self.assertIsNone(doc1.completed_at)
        self.assertIsNone(doc2.completed_at)
        # completed entry should have completed_at
        self.assertIsNotNone(doc3.completed_at)
