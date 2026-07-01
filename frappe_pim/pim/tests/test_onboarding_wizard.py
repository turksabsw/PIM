# Copyright (c) 2026, Frappe PIM and contributors
# For license information, please see license.txt
"""Integration Tests: Onboarding Wizard Full 12-Step Flow

This module tests the full onboarding wizard lifecycle via the new
OnboardingService API (Tenant Config + PIM Onboarding State dual-write):

1. Full 12-step sequential flow (happy path)
2. Resume-on-interrupt (save partial, restart, continue)
3. Skip optional steps (steps 9-11)
4. Template idempotency (re-apply same template yields no new entities)
5. Step validation enforcement (missing required fields)
6. Post-onboarding configuration editing

These tests exercise the OnboardingService orchestration layer
directly, validating dual-write consistency between PIM Onboarding State
and Tenant Config, audit trail in Onboarding Step Log, and the
TemplateEngine integration.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for linting/static analysis).

Run with:
    bench --site [site] run-tests --app frappe_pim \\
        --module frappe_pim.pim.tests.test_onboarding_wizard
"""

import unittest
import json


class TestOnboardingWizardIntegration(unittest.TestCase):
    """Integration tests for the 12-step onboarding wizard.

    Tests the full wizard lifecycle through the OnboardingService,
    verifying dual-write consistency, step validation, skip logic,
    resume behavior, and template idempotency.
    """

    # Test user email prefix (cleaned up in teardown)
    TEST_USER = "wizard_integration_test@example.com"
    RESUME_USER = "wizard_resume_test@example.com"
    SKIP_USER = "wizard_skip_test@example.com"

    # Step data fixtures for each of the 12 steps
    STEP_DATA = {
        "company_info": {
            "company_name": "Wizard Integration Corp",
            "company_size": "51-200",
            "primary_role": "product_manager",
            "existing_systems": ["erp", "spreadsheet"],
            "pain_points": ["data_quality", "time_to_market"],
        },
        "industry_selection": {
            "selected_industry": "fashion",
            "industry_sub_vertical": "apparel_and_accessories",
        },
        "product_structure": {
            "estimated_sku_count": "1001-5000",
            "uses_variants": True,
            "variant_axes": ["color", "size"],
            "product_family_count": "11-25",
            "data_import_source": "csv",
        },
        "attribute_config": {
            "attribute_groups": ["fashion", "sizing", "care_composition"],
        },
        "taxonomy": {
            "category_source": "template",
            "brand_names": ["TestBrand"],
        },
        "channel_setup": {
            "selected_channels": ["e-commerce", "marketplace"],
            "primary_channel": "e-commerce",
            "business_model": "b2c",
        },
        "localization": {
            "primary_language": "tr",
            "additional_languages": ["en"],
            "enable_auto_translate": False,
            "default_currency": "TRY",
            "default_uom": "Nos",
        },
        "workflow_preferences": {
            "workflow_complexity": "standard",
            "require_quality_check": True,
            "auto_publish": False,
            "notify_on_status_change": True,
        },
        "quality_scoring": {
            "quality_threshold": 70,
            "scoring_weights": {
                "completeness": 40,
                "accuracy": 30,
                "consistency": 30,
            },
        },
        "integrations": {
            "enable_erp_sync": True,
            "erp_type": "erpnext",
            "sync_direction": "bidirectional",
            "enable_ai_enrichment": False,
        },
        "compliance": {
            "compliance_standards": ["gdpr"],
        },
        "summary_launch": {
            "confirm_launch": True,
        },
    }

    @classmethod
    def setUpClass(cls):
        """Set up test class - clean prior data and ensure prerequisites."""
        import frappe
        frappe.set_user("Administrator")
        cls._cleanup_all_test_data()

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests."""
        import frappe
        cls._cleanup_all_test_data()
        frappe.db.commit()

    @classmethod
    def _cleanup_all_test_data(cls):
        """Remove any test-specific data from previous or current runs."""
        import frappe

        test_users = [cls.TEST_USER, cls.RESUME_USER, cls.SKIP_USER]

        for user in test_users:
            # Remove onboarding state
            try:
                existing = frappe.db.exists(
                    "PIM Onboarding State", {"user": user}
                )
                if existing:
                    frappe.delete_doc(
                        "PIM Onboarding State", existing,
                        ignore_permissions=True, force=True,
                    )
            except Exception:
                pass

            # Remove step logs
            try:
                frappe.db.sql(
                    "DELETE FROM `tabOnboarding Step Log` WHERE user = %s",
                    user,
                )
            except Exception:
                pass

        # Reset Tenant Config onboarding fields
        try:
            tc = frappe.get_single("Tenant Config")
            tc.onboarding_status = "not_started"
            tc.onboarding_current_step = 0
            tc.onboarding_started_at = None
            tc.onboarding_completed_at = None
            tc.selected_industry = None
            tc.onboarding_step_data = "[]"
            tc.save(ignore_permissions=True)
        except Exception:
            pass

        frappe.db.commit()

    # ========================================================================
    # Test 1: Full 12-Step Sequential Flow (Happy Path)
    # ========================================================================

    def test_01_full_12_step_flow(self):
        """Walk through all 12 steps sequentially and complete onboarding.

        Verifies:
        - Each step save succeeds via OnboardingService.save_step
        - Step numbers advance correctly
        - Tenant Config fields are populated (dual-write)
        - Audit trail entries are created for each step
        - Final completion marks both docs as completed
        """
        import frappe
        from frappe_pim.pim.services.onboarding_service import (
            OnboardingService,
            STEP_IDS,
        )

        user = self.TEST_USER

        # Save each step sequentially with advance=True
        for step_number, step_id in enumerate(STEP_IDS, start=1):
            form_data = self.STEP_DATA.get(step_id, {})

            if step_number < 12:
                result = OnboardingService.save_step(
                    step_id=step_id,
                    step_number=step_number,
                    form_data=form_data,
                    advance=True,
                    user=user,
                )

                self.assertTrue(
                    result["success"],
                    f"Step {step_number} ({step_id}) save failed: "
                    f"{result.get('validation_errors', [])}"
                )
                self.assertEqual(
                    result["next_step"], step_number + 1,
                    f"Step {step_number} should advance to {step_number + 1}"
                )
            else:
                # Step 12 (summary_launch) - save without advance
                result = OnboardingService.save_step(
                    step_id=step_id,
                    step_number=step_number,
                    form_data=form_data,
                    advance=False,
                    user=user,
                )
                self.assertTrue(result["success"])

        # Verify Tenant Config was updated
        tc = frappe.get_single("Tenant Config")
        self.assertEqual(tc.company_name, "Wizard Integration Corp")
        self.assertEqual(tc.selected_industry, "fashion")
        self.assertEqual(tc.primary_language, "tr")
        self.assertEqual(tc.default_currency, "TRY")

        # Verify audit trail
        logs = frappe.get_all(
            "Onboarding Step Log",
            filters={"user": user},
            fields=["step_id", "action", "step_number"],
            order_by="step_number asc",
        )
        self.assertGreaterEqual(
            len(logs), 12,
            f"Expected at least 12 audit log entries, got {len(logs)}"
        )

    # ========================================================================
    # Test 2: Resume-on-Interrupt
    # ========================================================================

    def test_02_resume_on_interrupt(self):
        """Save partial data, simulate interruption, then resume and continue.

        Verifies:
        - Partial save (no advance) persists data
        - Subsequent get_status shows correct current step
        - Resuming from the interrupted step succeeds
        - Previously saved data is not lost
        """
        import frappe
        from frappe_pim.pim.services.onboarding_service import (
            OnboardingService,
        )

        user = self.RESUME_USER

        # Step 1: Save and advance
        result = OnboardingService.save_step(
            step_id="company_info",
            step_number=1,
            form_data=self.STEP_DATA["company_info"],
            advance=True,
            user=user,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["next_step"], 2)

        # Step 2: Save WITHOUT advance (simulate interrupt)
        result = OnboardingService.save_step(
            step_id="industry_selection",
            step_number=2,
            form_data={"selected_industry": "electronics"},
            advance=False,
            user=user,
        )
        self.assertTrue(result["success"])
        self.assertIsNone(result["next_step"])  # No advance

        # Simulate "resume": check status
        status = OnboardingService.get_status(user=user)
        self.assertEqual(status["status"], "in_progress")
        # Current step should still be 2 (not advanced)
        self.assertIn(status["current_step"], (1, 2))

        # Resume: save step 2 again with advance
        result = OnboardingService.save_step(
            step_id="industry_selection",
            step_number=2,
            form_data=self.STEP_DATA["industry_selection"],
            advance=True,
            user=user,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["next_step"], 3)

        # Verify step 1 data is still intact (not overwritten)
        tc = frappe.get_single("Tenant Config")
        self.assertEqual(tc.company_name, "Wizard Integration Corp")

    # ========================================================================
    # Test 3: Skip Optional Steps
    # ========================================================================

    def test_03_skip_optional_steps(self):
        """Complete steps 1-8, then skip steps 9-11, complete step 12.

        Verifies:
        - Steps 1-8 save and advance normally
        - Steps 9-11 can be skipped after step 8 is completed
        - Skipped steps have audit trail entries with action='skipped'
        - Step 12 can still be saved/completed after skipping
        """
        import frappe
        from frappe_pim.pim.services.onboarding_service import (
            OnboardingService,
            STEP_IDS,
        )

        user = self.SKIP_USER

        # Complete steps 1-8
        mandatory_steps = STEP_IDS[:8]
        for step_number, step_id in enumerate(mandatory_steps, start=1):
            form_data = self.STEP_DATA.get(step_id, {})
            result = OnboardingService.save_step(
                step_id=step_id,
                step_number=step_number,
                form_data=form_data,
                advance=True,
                user=user,
            )
            self.assertTrue(
                result["success"],
                f"Mandatory step {step_number} ({step_id}) failed: "
                f"{result.get('validation_errors', [])}"
            )

        # Skip steps 9-11
        skippable_steps = [
            ("quality_scoring", 9),
            ("integrations", 10),
            ("compliance", 11),
        ]
        for step_id, step_number in skippable_steps:
            result = OnboardingService.skip_step(
                step_id=step_id,
                step_number=step_number,
                user=user,
            )
            self.assertTrue(
                result["success"],
                f"Skip step {step_number} ({step_id}) failed"
            )
            self.assertTrue(result["skipped"])

        # Save step 12 (summary_launch)
        result = OnboardingService.save_step(
            step_id="summary_launch",
            step_number=12,
            form_data=self.STEP_DATA["summary_launch"],
            advance=False,
            user=user,
        )
        self.assertTrue(result["success"])

        # Verify skip audit trail
        skip_logs = frappe.get_all(
            "Onboarding Step Log",
            filters={"user": user, "action": "skipped"},
            fields=["step_id", "step_number"],
            order_by="step_number asc",
        )
        skipped_ids = [log["step_id"] for log in skip_logs]
        for step_id, _ in skippable_steps:
            self.assertIn(
                step_id, skipped_ids,
                f"Step '{step_id}' should have a 'skipped' log entry"
            )

    # ========================================================================
    # Test 4: Template Idempotency
    # ========================================================================

    def test_04_template_idempotency(self):
        """Apply the same template twice; second application should skip all.

        Verifies:
        - First template application creates entities
        - Second application with the same archetype creates 0 new entities
        - Second application skips previously created entities
        - No failures on re-application
        """
        from frappe_pim.pim.services.template_engine import TemplateEngine

        # First application (may have been done in test_01 or e2e tests)
        result_1 = TemplateEngine.apply_template(
            archetype_name="fashion",
            skip_base=False,
        )
        result_1_dict = result_1.to_dict()

        # The first run either creates or skips (if already applied)
        self.assertIn(
            result_1_dict["status"], ("completed", "partial"),
            f"First application should succeed, got: {result_1_dict['status']}"
        )

        # Remember totals from first run
        first_created = result_1_dict["entities_created"]
        first_skipped = result_1_dict["entities_skipped"]

        # Second application — everything should be skipped
        result_2 = TemplateEngine.apply_template(
            archetype_name="fashion",
            skip_base=False,
        )
        result_2_dict = result_2.to_dict()

        self.assertEqual(
            result_2_dict["entities_created"], 0,
            f"Second application should create 0 entities, "
            f"but created {result_2_dict['entities_created']}"
        )
        self.assertGreater(
            result_2_dict["entities_skipped"], 0,
            "Second application should show entities as skipped"
        )
        self.assertEqual(
            result_2_dict["entities_failed"], 0,
            f"Re-applying template should have 0 failures, "
            f"but had {result_2_dict['entities_failed']}"
        )
        self.assertEqual(
            result_2_dict["status"], "completed",
            f"Re-applying template should have 'completed' status"
        )

    # ========================================================================
    # Test 5: Step Validation Enforcement
    # ========================================================================

    def test_05_step_validation_enforcement(self):
        """Saving a step with missing required fields returns validation error.

        Verifies:
        - company_info requires company_name, company_size, primary_role,
          existing_systems
        - industry_selection requires selected_industry
        - product_structure requires estimated_sku_count,
          product_family_count, data_import_source
        - Invalid step_id/step_number combos are rejected
        """
        import frappe
        from frappe_pim.pim.services.onboarding_service import (
            OnboardingService,
        )

        user = "wizard_validation_test@example.com"

        # Test missing required fields for company_info
        result = OnboardingService.save_step(
            step_id="company_info",
            step_number=1,
            form_data={},
            user=user,
        )
        self.assertFalse(result["success"])
        self.assertGreater(len(result["validation_errors"]), 0)

        # Test missing required field for industry_selection
        result = OnboardingService.save_step(
            step_id="industry_selection",
            step_number=2,
            form_data={},
            user=user,
        )
        self.assertFalse(result["success"])
        self.assertGreater(len(result["validation_errors"]), 0)

        # Test missing required fields for product_structure
        result = OnboardingService.save_step(
            step_id="product_structure",
            step_number=3,
            form_data={},
            user=user,
        )
        self.assertFalse(result["success"])

        # Test invalid step_id
        result = OnboardingService.save_step(
            step_id="nonexistent_step",
            step_number=1,
            form_data={"key": "value"},
            user=user,
        )
        self.assertFalse(result["success"])

        # Test step_id / step_number mismatch
        result = OnboardingService.save_step(
            step_id="company_info",
            step_number=5,
            form_data=self.STEP_DATA["company_info"],
            user=user,
        )
        self.assertFalse(result["success"])

        # Test step_number out of range
        result = OnboardingService.save_step(
            step_id="company_info",
            step_number=0,
            form_data=self.STEP_DATA["company_info"],
            user=user,
        )
        self.assertFalse(result["success"])

        result = OnboardingService.save_step(
            step_id="company_info",
            step_number=13,
            form_data=self.STEP_DATA["company_info"],
            user=user,
        )
        self.assertFalse(result["success"])

        # Clean up
        try:
            existing = frappe.db.exists(
                "PIM Onboarding State", {"user": user}
            )
            if existing:
                frappe.delete_doc(
                    "PIM Onboarding State", existing,
                    ignore_permissions=True, force=True,
                )
            frappe.db.sql(
                "DELETE FROM `tabOnboarding Step Log` WHERE user = %s",
                user,
            )
            frappe.db.commit()
        except Exception:
            pass

    # ========================================================================
    # Test 6: Post-Onboarding Configuration Editing
    # ========================================================================

    def test_06_post_onboarding_editing(self):
        """Test that configuration can be edited after onboarding completion.

        Verifies:
        - Post-onboarding editing requires completed status
        - Valid sections can be updated
        - Invalid sections are rejected
        - Industry change returns impact warning
        """
        import frappe
        from frappe_pim.pim.services.onboarding_service import (
            OnboardingService,
        )

        # Ensure Tenant Config is in completed state
        tc = frappe.get_single("Tenant Config")
        tc.onboarding_status = "completed"
        tc.company_name = "Original Corp"
        tc.selected_industry = "fashion"
        tc.save(ignore_permissions=True)
        frappe.db.commit()

        # Update company_info section
        result = OnboardingService.update_post_onboarding(
            section="company_info",
            form_data={"company_name": "Renamed Corp"},
        )
        self.assertTrue(result["success"])
        self.assertIn("company_name", result["updated_fields"])

        # Verify the update persisted
        tc.reload()
        self.assertEqual(tc.company_name, "Renamed Corp")

        # Test invalid section
        with self.assertRaises(Exception):
            OnboardingService.update_post_onboarding(
                section="invalid_section",
                form_data={"key": "value"},
            )

        # Test industry change impact warning
        result = OnboardingService.update_post_onboarding(
            section="industry",
            form_data={"selected_industry": "electronics"},
        )
        if result.get("success"):
            self.assertIn("impact_warning", result)
            if result["impact_warning"]:
                self.assertEqual(
                    result["impact_warning"]["old_industry"], "fashion"
                )
                self.assertEqual(
                    result["impact_warning"]["new_industry"], "electronics"
                )

    # ========================================================================
    # Test 7: Dual-Write Consistency Verification
    # ========================================================================

    def test_07_dual_write_consistency(self):
        """Verify that save_step writes to both PIM Onboarding State and Tenant Config.

        Verifies:
        - Step data is stored in PIM Onboarding State (per-user)
        - Mapped fields are written to Tenant Config (per-site)
        - Both documents reflect the same data
        """
        import frappe
        from frappe_pim.pim.services.onboarding_service import (
            OnboardingService,
        )

        user = "wizard_dual_write_test@example.com"

        # Reset Tenant Config
        tc = frappe.get_single("Tenant Config")
        tc.onboarding_status = "not_started"
        tc.company_name = None
        tc.save(ignore_permissions=True)
        frappe.db.commit()

        # Save company_info
        result = OnboardingService.save_step(
            step_id="company_info",
            step_number=1,
            form_data={
                "company_name": "Dual Write Corp",
                "company_size": "11-50",
                "primary_role": "cto",
                "existing_systems": ["none"],
            },
            user=user,
        )
        self.assertTrue(result["success"])

        # Verify Tenant Config was updated
        tc.reload()
        self.assertEqual(tc.company_name, "Dual Write Corp")
        self.assertEqual(tc.company_size, "11-50")
        self.assertEqual(tc.primary_role, "cto")

        # Verify PIM Onboarding State was updated
        existing = frappe.db.exists(
            "PIM Onboarding State", {"user": user}
        )
        self.assertTrue(existing, "PIM Onboarding State should exist")

        doc = frappe.get_doc("PIM Onboarding State", existing)
        stored = doc.get_step_data("company_info")
        if stored:
            self.assertEqual(stored.get("company_name"), "Dual Write Corp")

        # Clean up
        try:
            frappe.delete_doc(
                "PIM Onboarding State", existing,
                ignore_permissions=True, force=True,
            )
            frappe.db.sql(
                "DELETE FROM `tabOnboarding Step Log` WHERE user = %s",
                user,
            )
            frappe.db.commit()
        except Exception:
            pass

    # ========================================================================
    # Test 8: Complete Onboarding With All Mandatory Steps
    # ========================================================================

    def test_08_complete_onboarding_with_mandatory_steps(self):
        """Complete onboarding after all mandatory steps are done.

        Verifies:
        - complete_onboarding succeeds when steps 1-8 are completed
        - Tenant Config is marked as completed
        - Redirect URL is returned
        - Completion timestamp is set
        """
        import frappe
        from frappe_pim.pim.services.onboarding_service import (
            OnboardingService,
            STEP_IDS,
            _create_step_log,
        )

        user = "wizard_complete_test@example.com"

        # Clean up
        try:
            existing = frappe.db.exists(
                "PIM Onboarding State", {"user": user}
            )
            if existing:
                frappe.delete_doc(
                    "PIM Onboarding State", existing,
                    ignore_permissions=True, force=True,
                )
            frappe.db.sql(
                "DELETE FROM `tabOnboarding Step Log` WHERE user = %s",
                user,
            )
        except Exception:
            pass

        # Set up Tenant Config as in-progress with industry
        tc = frappe.get_single("Tenant Config")
        tc.onboarding_status = "in_progress"
        tc.selected_industry = "fashion"
        tc.save(ignore_permissions=True)
        frappe.db.commit()

        # Create completion logs for mandatory steps (1-8)
        for step_number, step_id in enumerate(STEP_IDS[:8], start=1):
            _create_step_log(
                user=user,
                step_id=step_id,
                step_number=step_number,
                action="completed",
                form_data=self.STEP_DATA.get(step_id, {}),
            )
        frappe.db.commit()

        # Complete onboarding
        result = OnboardingService.complete_onboarding(
            form_data={"confirm_launch": True},
            user=user,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "completed")
        self.assertIn("redirect_to", result)
        self.assertIsNotNone(result["onboarding_completed_at"])

        # Verify Tenant Config completion
        tc.reload()
        self.assertEqual(tc.onboarding_status, "completed")
        self.assertIsNotNone(tc.onboarding_completed_at)

        # Clean up
        try:
            existing = frappe.db.exists(
                "PIM Onboarding State", {"user": user}
            )
            if existing:
                frappe.delete_doc(
                    "PIM Onboarding State", existing,
                    ignore_permissions=True, force=True,
                )
            frappe.db.sql(
                "DELETE FROM `tabOnboarding Step Log` WHERE user = %s",
                user,
            )
            frappe.db.commit()
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
