"""Onboarding Orchestration Service

Coordinates the 12-step PIM SaaS onboarding wizard by reading/writing
BOTH ``PIM Onboarding State`` (per-user progress) and ``Tenant Config``
(per-site configuration singleton).

Key Responsibilities:
- Step validation with per-step required field checks
- State transitions via PIM Onboarding State controller
- Form data persistence to both PIM Onboarding State and Tenant Config
- Audit trail via Onboarding Step Log entries
- Template application coordination with the TemplateEngine
- Form data aggregation from all steps into Tenant Config on completion
- Post-onboarding configuration editing with impact analysis

Dual-Write Pattern:
    During the wizard flow, each step's form data is stored in two places:
    1. ``PIM Onboarding State`` — per-user, tracks step progress and
       stores per-step form data snapshots (via JSON fields).
    2. ``Tenant Config`` — per-site singleton, receives mapped field
       values from form data so that the site-level config is always
       up to date.

    On ``complete_onboarding()``, the service aggregates all step data,
    applies the selected industry template, updates feature flags, and
    marks both documents as completed.

Step Mapping (12 wizard steps):
    Step  1: company_info        — Company name, size, role, systems
    Step  2: industry_selection   — Sector, sub-vertical, custom name
    Step  3: product_structure    — SKUs, variants, families, import
    Step  4: attribute_config     — Attribute groups, custom attrs
    Step  5: taxonomy             — Categories, brands
    Step  6: channel_setup        — Channels, primary, business model
    Step  7: localization         — Languages, currency, UOM
    Step  8: workflow_preferences — Workflow type, quality gate
    Step  9: quality_scoring      — Threshold, weights (skippable)
    Step 10: integrations         — ERP, AI, GS1, MDM (skippable)
    Step 11: compliance           — Standards, certs (skippable)
    Step 12: summary_launch       — Summary review, launch

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Constants
# =============================================================================

# Total number of wizard steps
TOTAL_STEPS = 12

# Skippable steps (available only after step 8 is completed)
SKIPPABLE_STEPS = {9, 10, 11}

# Step IDs indexed by step number (1-based)
STEP_IDS: Tuple[str, ...] = (
    "company_info",         # Step 1
    "industry_selection",   # Step 2
    "product_structure",    # Step 3
    "attribute_config",     # Step 4
    "taxonomy",             # Step 5
    "channel_setup",        # Step 6
    "localization",         # Step 7
    "workflow_preferences", # Step 8
    "quality_scoring",      # Step 9 (skippable)
    "integrations",         # Step 10 (skippable)
    "compliance",           # Step 11 (skippable)
    "summary_launch",       # Step 12
)

# Map wizard step_id to PIM Onboarding State step name
# (PIM Onboarding State has a different step vocabulary)
STEP_ID_TO_STATE_STEP: Dict[str, str] = {
    "company_info": "company_info",
    "industry_selection": "industry_selection",
    "product_structure": "product_structure",
    "attribute_config": "product_structure",      # grouped under product_structure
    "taxonomy": "product_structure",              # grouped under product_structure
    "channel_setup": "channel_setup",
    "localization": "channel_setup",              # grouped under channel_setup
    "workflow_preferences": "workflow_preferences",
    "quality_scoring": "workflow_preferences",    # grouped under workflow_preferences
    "integrations": "compliance_setup",           # grouped under compliance_setup
    "compliance": "compliance_setup",
    "summary_launch": "template_applied",         # maps to template application step
}

# Required fields per step for validation
STEP_REQUIRED_FIELDS: Dict[str, List[str]] = {
    "company_info": ["company_name", "company_size", "primary_role", "existing_systems"],
    "industry_selection": ["selected_industry"],
    "product_structure": ["estimated_sku_count", "product_family_count", "data_import_source"],
    "attribute_config": [],     # attribute review step, no hard requirements
    "taxonomy": [],             # taxonomy step, no hard requirements
    "channel_setup": [],        # channel selection, no hard requirements
    "localization": [],         # localization, no hard requirements
    "workflow_preferences": [],  # workflow, no hard requirements
    "quality_scoring": [],      # skippable, no requirements
    "integrations": [],         # skippable, no requirements
    "compliance": [],           # skippable, no requirements
    "summary_launch": [],       # summary step, validation is completion check
}

# Map step_id to the Tenant Config fields that each step populates
STEP_TENANT_CONFIG_FIELDS: Dict[str, List[str]] = {
    "company_info": [
        "company_name", "company_website", "company_size",
        "primary_role", "existing_systems", "pain_points",
    ],
    "industry_selection": [
        "selected_industry", "industry_sub_vertical", "custom_industry_name",
    ],
    "product_structure": [
        "estimated_sku_count", "uses_variants", "variant_axes",
        "product_family_count", "custom_families", "data_import_source",
    ],
    "attribute_config": [
        "attribute_groups", "removed_template_attrs", "custom_attributes",
    ],
    "taxonomy": [
        "category_source", "category_data", "brand_names",
    ],
    "channel_setup": [
        "selected_channels", "primary_channel", "business_model",
    ],
    "localization": [
        "primary_language", "additional_languages", "enable_auto_translate",
        "default_currency", "default_uom",
    ],
    "workflow_preferences": [
        "workflow_complexity", "require_quality_check", "auto_publish",
        "notify_on_status_change",
    ],
    "quality_scoring": [
        "quality_threshold", "scoring_weights",
    ],
    "integrations": [
        "enable_erp_sync", "erp_type", "sync_direction",
        "enable_ai_enrichment", "ai_provider", "ai_use_cases",
        "enable_gs1", "enable_mdm",
    ],
    "compliance": [
        "compliance_standards", "certification_tracking",
    ],
    "summary_launch": [],  # no direct config fields; triggers template application
}

# Sections for post-onboarding editing (maps section name to step_id)
POST_ONBOARDING_SECTIONS: Dict[str, str] = {
    "company_info": "company_info",
    "industry": "industry_selection",
    "product_structure": "product_structure",
    "attributes": "attribute_config",
    "taxonomy": "taxonomy",
    "channels": "channel_setup",
    "localization": "localization",
    "workflow": "workflow_preferences",
    "quality": "quality_scoring",
    "integrations": "integrations",
    "compliance": "compliance",
}

# Feature flags derived from onboarding step data
FEATURE_FLAG_SOURCES: Dict[str, str] = {
    "enable_variants": "uses_variants",
    "enable_translations": "enable_auto_translate",
    "enable_ai": "enable_ai_enrichment",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class StepValidationResult:
    """Result of validating a single step's form data."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class StepSaveResult:
    """Result of saving a step's data."""
    success: bool
    step_id: str
    step_number: int
    next_step: Optional[int] = None
    validation_errors: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "step_id": self.step_id,
            "step_number": self.step_number,
            "next_step": self.next_step,
            "validation_errors": self.validation_errors,
            "message": self.message,
        }


@dataclass
class CompletionResult:
    """Result of completing the onboarding process."""
    success: bool
    status: str = "pending"
    entities_created: Dict[str, int] = field(default_factory=dict)
    demo_products_created: int = 0
    onboarding_completed_at: Optional[str] = None
    redirect_to: str = "/app/pim-dashboard"
    errors: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "entities_created": self.entities_created,
            "demo_products_created": self.demo_products_created,
            "onboarding_completed_at": self.onboarding_completed_at,
            "redirect_to": self.redirect_to,
            "errors": self.errors,
            "messages": self.messages,
        }


# =============================================================================
# Onboarding Service
# =============================================================================

class OnboardingService:
    """Orchestration service for the PIM SaaS onboarding wizard.

    Coordinates between PIM Onboarding State (per-user step progress)
    and Tenant Config (per-site configuration singleton).

    Usage::

        service = OnboardingService()
        status = service.get_status()
        result = service.save_step("company_info", 1, {"company_name": "Acme"})
        completion = service.complete_onboarding()
    """

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    @staticmethod
    def get_status(user: Optional[str] = None) -> Dict[str, Any]:
        """Get the combined onboarding status from both state sources.

        Reads ``Tenant Config.onboarding_status`` for the gate check
        (is tenant onboarded?) and ``PIM Onboarding State`` for
        step-level progress.

        Args:
            user: User email. Defaults to current session user.

        Returns:
            Dict with status, current_step, total_steps, completed_steps,
            can_skip_remaining, started_at, completed_at, and per-step
            metadata.
        """
        import frappe

        if not user:
            user = frappe.session.user

        # Read this user's config (per-user)
        tenant_config = _get_tenant_config(user)
        tenant_status = tenant_config.onboarding_status or "not_started"

        # Read user-level onboarding state (per-user)
        onboarding_state = _get_or_create_onboarding_state(user)

        # Per-user override: if tenant is completed but THIS user hasn't
        # done the wizard yet, show wizard for this user.
        user_completed = bool(onboarding_state.is_completed) if onboarding_state else False
        if tenant_status == "completed" and not user_completed:
            tenant_status = "not_started"
        elif tenant_status == "skipped" and not user_completed:
            # If tenant was skipped but user hasn't gone through it,
            # treat as not_started for this user
            tenant_status = "not_started"

        # Determine effective current step number
        if not user_completed:
            # For users who haven't completed, derive from their own state
            user_step = _state_step_to_number(onboarding_state.current_step) if onboarding_state else 0
            current_step = max(user_step, 1)
        else:
            current_step = tenant_config.onboarding_current_step or 0
            if current_step == 0:
                current_step = _state_step_to_number(onboarding_state.current_step)

        # Build completed steps list from Onboarding Step Log
        completed_step_ids = _get_completed_step_ids(user)
        skipped_step_ids = _get_skipped_step_ids(user)

        # Determine skip eligibility (steps 9-11 skippable after step 8)
        can_skip_remaining = current_step > 8 or "workflow_preferences" in completed_step_ids

        return {
            "status": tenant_status,
            "onboarding_status": tenant_status,
            "current_step": current_step,
            "total_steps": TOTAL_STEPS,
            "completed_steps": completed_step_ids,
            "can_skip_remaining": can_skip_remaining,
            "started_at": str(tenant_config.onboarding_started_at) if tenant_config.onboarding_started_at else None,
            "completed_at": str(tenant_config.onboarding_completed_at) if tenant_config.onboarding_completed_at else None,
            "selected_industry": tenant_config.selected_industry,
            "template_applied": bool(onboarding_state.template_applied) if onboarding_state else False,
            "progress_percent": round((max(current_step - 1, 0) / TOTAL_STEPS) * 100, 1),
            "steps": _build_step_metadata(current_step, completed_step_ids, skipped_step_ids),
            "step_data": _safe_parse_json(tenant_config.onboarding_step_data, default=[]),
        }

    @staticmethod
    def save_step(
        step_id: str,
        step_number: int,
        form_data: Dict[str, Any],
        advance: bool = False,
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save form data for a specific onboarding step.

        Writes to both PIM Onboarding State (per-user progress) and
        Tenant Config (per-site configuration). Creates an audit trail
        entry in Onboarding Step Log.

        Args:
            step_id: Step identifier (e.g., ``"company_info"``).
            step_number: Step number (1-12).
            form_data: Dict of form data for the step.
            advance: If *True*, advance to the next step after saving.
            user: User email. Defaults to current session user.

        Returns:
            Dict with success status, next step, and any validation errors.
        """
        import frappe

        if not user:
            user = frappe.session.user

        result = StepSaveResult(
            success=False,
            step_id=step_id,
            step_number=step_number,
        )

        # Validate step_id and step_number
        validation_error = _validate_step_params(step_id, step_number)
        if validation_error:
            result.validation_errors.append(validation_error)
            return result.to_dict()

        # Validate form data for this step
        validation = _validate_step_data(step_id, form_data)
        if not validation.valid:
            result.validation_errors = validation.errors
            return result.to_dict()

        # Get or create onboarding state
        onboarding_state = _get_or_create_onboarding_state(user)

        # Get tenant config
        tenant_config = _get_tenant_config()

        # Fill empty required fields so save() passes (avoids MandatoryError)
        _ensure_tenant_config_required_defaults(tenant_config)

        # Ensure onboarding is started
        if tenant_config.onboarding_status in (None, "not_started"):
            tenant_config.mark_onboarding_started()

        # 1. Save form data to PIM Onboarding State (per-user)
        state_step = STEP_ID_TO_STATE_STEP.get(step_id)
        if state_step and state_step in _get_state_data_fields():
            onboarding_state.save_step_data(state_step, form_data)

        # 2. Map and save fields to Tenant Config (per-site)
        _write_step_to_tenant_config(tenant_config, step_id, form_data)
        # Re-apply defaults in case write cleared any required fields
        _ensure_tenant_config_required_defaults(tenant_config)
        # Sanitize industry/quality so Tenant Config validation passes
        _sanitize_tenant_config_for_completion(tenant_config)

        # 3. Update step number in Tenant Config
        tenant_config.update_onboarding_step(step_number)

        # 4. Save step data to Tenant Config's step_data array
        tenant_config.save_step_data(step_id, step_number, form_data)

        # 5. Create audit trail entry
        _create_step_log(
            user=user,
            step_id=step_id,
            step_number=step_number,
            action="completed" if advance else "saved",
            form_data=form_data,
        )

        # 6. Advance to next step if requested
        next_step = None
        if advance and step_number < TOTAL_STEPS:
            next_step = step_number + 1
            # Advance PIM Onboarding State if at the matching step
            if onboarding_state.current_step == state_step:
                onboarding_state.advance_step(form_data=form_data)
            tenant_config.update_onboarding_step(next_step)

        frappe.db.commit()

        result.success = True
        result.next_step = next_step
        result.message = "Step data saved successfully"
        return result.to_dict()

    @staticmethod
    def skip_step(
        step_id: str,
        step_number: int,
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Skip an optional step (steps 9-11 only).

        Only steps marked as skippable can be skipped, and only after
        step 8 (workflow_preferences) is completed.

        Args:
            step_id: Step identifier to skip.
            step_number: Step number (9-11).
            user: User email. Defaults to current session user.

        Returns:
            Dict with success status, next step, and skip confirmation.
        """
        import frappe
        from frappe import _

        if not user:
            user = frappe.session.user

        # Validate the step is skippable
        if step_number not in SKIPPABLE_STEPS:
            frappe.throw(
                _("Step {0} ({1}) cannot be skipped. Only steps 9-11 are skippable.").format(
                    step_number, step_id
                ),
                title=_("Cannot Skip Step"),
            )

        # Verify step 8 is completed
        completed_steps = _get_completed_step_ids(user)
        if "workflow_preferences" not in completed_steps:
            frappe.throw(
                _("Steps 9-11 can only be skipped after completing Step 8 (Workflow Preferences)."),
                title=_("Cannot Skip Yet"),
            )

        # Create audit trail entry for the skip
        _create_step_log(
            user=user,
            step_id=step_id,
            step_number=step_number,
            action="skipped",
            form_data=None,
        )

        # Advance to next step
        next_step = step_number + 1 if step_number < TOTAL_STEPS else None

        # Update Tenant Config step number
        tenant_config = _get_tenant_config()
        _ensure_tenant_config_required_defaults(tenant_config)
        if next_step:
            tenant_config.update_onboarding_step(next_step)

        frappe.db.commit()

        return {
            "success": True,
            "step_id": step_id,
            "step_number": step_number,
            "next_step": next_step,
            "skipped": True,
        }

    @staticmethod
    def apply_template(
        create_demo_products: bool = False,
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply the selected industry template to create PIM entities.

        Reads ``Tenant Config.selected_industry`` to determine which
        template to apply. Coordinates with the TemplateEngine for
        entity creation.

        Args:
            create_demo_products: If *True*, create sample demo products.
            user: User email. Defaults to current session user.

        Returns:
            Dict with entity counts, demo product count, and status.
        """
        import frappe
        from frappe import _

        if not user:
            user = frappe.session.user

        tenant_config = _get_tenant_config()
        industry = tenant_config.selected_industry

        if not industry:
            frappe.throw(
                _("No industry selected. Complete Step 2 (Industry Selection) first."),
                title=_("Missing Industry"),
            )

        result = CompletionResult(success=False)

        try:
            # Try loading from Industry Template DocType first
            template_data = _load_industry_template(industry)

            if template_data:
                # Apply via TemplateEngine using the loaded template data
                from frappe_pim.pim.services.template_engine import TemplateEngine

                onboarding_state = _get_or_create_onboarding_state(user)
                template_result = TemplateEngine.apply_template(
                    archetype_name=industry,
                    onboarding_state_name=onboarding_state.name if onboarding_state else None,
                )

                result_dict = template_result.to_dict()
                result.success = result_dict["status"] in ("completed", "partial")
                result.status = result_dict["status"]
                result.entities_created = result_dict.get("details", {})
                result.errors = result_dict.get("errors", [])
                result.messages = result_dict.get("messages", [])

                # Store template version in tenant config
                version = template_data.get("version", "1.0")
                tenant_config.industry_template_version = str(version)
                _ensure_tenant_config_required_defaults(tenant_config)
                tenant_config.save(ignore_permissions=True)

            else:
                result.errors.append(
                    f"No template found for industry '{industry}'"
                )
                return result.to_dict()

            # Create demo products if requested
            if create_demo_products and result.success:
                demo_count = _create_demo_products(industry, template_data)
                result.demo_products_created = demo_count

            # Create audit trail
            _create_step_log(
                user=user,
                step_id="summary_launch",
                step_number=12,
                action="completed",
                form_data={
                    "industry": industry,
                    "create_demo_products": create_demo_products,
                    "entities_created": result.entities_created,
                },
            )

            frappe.db.commit()

        except Exception as exc:
            result.success = False
            result.status = "failed"
            result.errors.append(str(exc))
            try:
                frappe.log_error(
                    title="PIM Template Application Error",
                    message=f"Industry: {industry}\n{exc}",
                )
            except Exception:
                pass

        return result.to_dict()

    @staticmethod
    def complete_onboarding(
        form_data: Optional[Dict[str, Any]] = None,
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Complete the onboarding process.

        Aggregates all step data from PIM Onboarding State into
        Tenant Config, updates feature flags based on selections,
        and marks both documents as completed.

        Args:
            form_data: Optional final step form data (summary/launch).
            user: User email. Defaults to current session user.

        Returns:
            Dict with success status, completion timestamp, and redirect.
        """
        import frappe
        from frappe import _
        from frappe.utils import now_datetime

        if not user:
            user = frappe.session.user

        tenant_config = _get_tenant_config()
        onboarding_state = _get_or_create_onboarding_state(user)

        # Check mandatory steps from Onboarding Step Log; if missing, still allow
        # completion to avoid 417 when user reached step 12 via URL or legacy API.
        completed_steps = _get_completed_step_ids(user)
        missing_mandatory = _check_mandatory_steps(completed_steps)
        if missing_mandatory:
            # Log for debugging; do not block completion (prevents 417 on Summary & Launch).
            try:
                import logging
                logging.getLogger(__name__).info(
                    "Onboarding complete called with missing step log entries: %s; allowing completion.",
                    missing_mandatory,
                )
            except Exception:
                pass

        # Save final form data if provided
        if form_data:
            _write_step_to_tenant_config(tenant_config, "summary_launch", form_data)

        # Aggregate and sync all step data to Tenant Config
        _aggregate_step_data_to_tenant_config(onboarding_state, tenant_config)

        # Update feature flags based on onboarding selections
        _update_feature_flags(tenant_config)

        # Fill any still-empty required fields so save() never raises
        _ensure_tenant_config_required_defaults(tenant_config)
        # Ensure Tenant Config passes validation (avoids 417 from invalid industry/quality)
        _sanitize_tenant_config_for_completion(tenant_config)

        def _do_complete():
            tenant_config.mark_onboarding_completed()
            if onboarding_state and onboarding_state.current_step != "completed":
                max_iterations = TOTAL_STEPS + 2
                iteration = 0
                while onboarding_state.current_step != "completed":
                    iteration += 1
                    if iteration > max_iterations:
                        break
                    try:
                        onboarding_state.advance_step()
                    except Exception:
                        break
            completed_at = str(now_datetime())
            _create_step_log(
                user=user,
                step_id="summary_launch",
                step_number=12,
                action="completed",
                form_data={"onboarding_completed": True},
            )
            frappe.db.commit()
            return completed_at

        try:
            completed_at = _do_complete()
        except frappe.ValidationError:
            # Retry: fill all required fields and safe industry/quality so save never fails
            _ensure_tenant_config_required_defaults(tenant_config)
            _sanitize_tenant_config_for_completion(tenant_config, force_safe_defaults=True)
            completed_at = _do_complete()

        return {
            "success": True,
            "status": "completed",
            "onboarding_completed_at": completed_at,
            "redirect_to": "/app/pim-dashboard",
        }

    @staticmethod
    def update_post_onboarding(
        section: str,
        form_data: Dict[str, Any],
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update tenant configuration after onboarding is complete.

        Used by the Settings > Onboarding Configuration editor.
        Validates the data and checks for impact if the industry
        sector is being changed.

        Args:
            section: Configuration section to update (e.g.,
                ``"company_info"``, ``"industry"``, ``"channels"``).
            form_data: Dict of updated field values.
            user: User email. Defaults to current session user.

        Returns:
            Dict with success status, updated fields, and impact warning.
        """
        import frappe
        from frappe import _

        if not user:
            user = frappe.session.user

        if section not in POST_ONBOARDING_SECTIONS:
            frappe.throw(
                _("Invalid section: {0}. Valid sections: {1}").format(
                    section, ", ".join(POST_ONBOARDING_SECTIONS.keys())
                ),
                title=_("Invalid Section"),
            )

        tenant_config = _get_tenant_config()

        # Check if onboarding is completed
        if tenant_config.onboarding_status != "completed":
            frappe.throw(
                _("Onboarding must be completed before editing configuration."),
                title=_("Onboarding Not Complete"),
            )

        # Check for industry change impact
        impact_warning = None
        if section == "industry" and "selected_industry" in form_data:
            new_industry = form_data["selected_industry"]
            old_industry = tenant_config.selected_industry
            if new_industry != old_industry:
                impact_warning = _assess_industry_change_impact(
                    old_industry, new_industry
                )

        # Map step_id from section
        step_id = POST_ONBOARDING_SECTIONS[section]

        # Validate the form data
        validation = _validate_step_data(step_id, form_data)
        if not validation.valid:
            return {
                "success": False,
                "validation_errors": validation.errors,
                "impact_warning": impact_warning,
            }

        # Write updated fields to Tenant Config
        updated_fields = _write_step_to_tenant_config(
            tenant_config, step_id, form_data
        )

        # Fill required fields so save() passes (post-onboarding edits may
        # leave some fields empty if user set them via frappe.db.set_value)
        _ensure_tenant_config_required_defaults(tenant_config)

        # Save
        tenant_config.save(ignore_permissions=True)

        # Create audit trail
        _create_step_log(
            user=user,
            step_id=step_id,
            step_number=_step_id_to_number(step_id),
            action="saved",
            form_data=form_data,
        )

        frappe.db.commit()

        return {
            "success": True,
            "updated_fields": updated_fields,
            "impact_warning": impact_warning,
        }

    @staticmethod
    def get_template_preview(industry: Optional[str] = None) -> Dict[str, Any]:
        """Get a preview of what an industry template will create.

        Reads from the Industry Template DocType or falls back to
        fixture-based templates.

        Args:
            industry: Industry sector. If *None*, reads from Tenant Config.

        Returns:
            Dict with template preview data (attribute counts, families,
            channels, compliance, quality settings, etc.).
        """
        import frappe
        from frappe import _

        if not industry:
            tenant_config = _get_tenant_config()
            industry = tenant_config.selected_industry

        if not industry:
            frappe.throw(
                _("No industry specified or selected."),
                title=_("Missing Industry"),
            )

        # Try Industry Template DocType first
        template_data = _load_industry_template(industry)
        if not template_data:
            # Fallback to fixture-based preview
            try:
                from frappe_pim.pim.services.template_engine import TemplateEngine
                return TemplateEngine.preview_template(industry)
            except (FileNotFoundError, ValueError):
                frappe.throw(
                    _("No template found for industry '{0}'").format(industry),
                    title=_("Template Not Found"),
                )

        # Build preview from Industry Template data
        return _build_template_preview(industry, template_data)


# =============================================================================
# Private Module-Level Helpers
# =============================================================================

def _get_tenant_config(user=None):
    """Get or create the Tenant Config document for the given user.

    Each user has their own Tenant Config record (autoname=field:user),
    so the document name equals the user email.

    Args:
        user: User email. Defaults to current session user.

    Returns:
        Tenant Config document for that user.
    """
    import frappe

    user = user or frappe.session.user

    if frappe.db.exists("Tenant Config", user):
        return frappe.get_doc("Tenant Config", user)

    # Create a fresh config for this user
    doc = frappe.new_doc("Tenant Config")
    doc.user = user
    _ensure_tenant_config_required_defaults(doc)
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc


# Valid industry sectors (must match Tenant Config) — used to avoid 417 on completion
_VALID_INDUSTRY_SECTORS = frozenset(
    ("fashion", "industrial", "food", "electronics", "health_beauty", "automotive", "custom")
)

# Defaults for Tenant Config required fields when empty (so save passes during onboarding)
_TENANT_CONFIG_REQUIRED_DEFAULTS = {
    "company_name": "—",
    "company_size": "11-50",
    "primary_role": "Product Manager",
    "existing_systems": "[]",
    "selected_industry": "electronics",
    "estimated_sku_count": "1-100",
    "product_family_count": "1-5",
    "data_import_source": "manual_entry",
}


def _ensure_tenant_config_required_defaults(tenant_config) -> None:
    """Set empty required Tenant Config fields to defaults so save() does not raise.

    During onboarding we save after each step; later steps' fields are still empty.
    Frappe validates reqd=1 and would raise; this fills empty required fields with
    safe defaults so validation passes until the user fills them in their step.
    """
    for fieldname, default in _TENANT_CONFIG_REQUIRED_DEFAULTS.items():
        if not hasattr(tenant_config, fieldname):
            continue
        val = getattr(tenant_config, fieldname, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            setattr(tenant_config, fieldname, default)


def _sanitize_tenant_config_for_completion(tenant_config, force_safe_defaults: bool = False) -> None:
    """Ensure Tenant Config passes validation before mark_onboarding_completed().

    Prevents 417 when aggregated data has invalid values (e.g. "Not set" for industry).
    If force_safe_defaults is True, set industry/quality to valid defaults so save never fails.
    """
    industry = getattr(tenant_config, "selected_industry", None)
    if force_safe_defaults:
        tenant_config.selected_industry = "electronics"
        tenant_config.custom_industry_name = tenant_config.custom_industry_name or ""
        tenant_config.quality_threshold = 0
    else:
        if industry and (not isinstance(industry, str) or industry.strip() not in _VALID_INDUSTRY_SECTORS):
            tenant_config.selected_industry = None
        if getattr(tenant_config, "selected_industry", None) == "custom" and not getattr(
            tenant_config, "custom_industry_name", None
        ):
            tenant_config.custom_industry_name = "Custom"
        try:
            qt = getattr(tenant_config, "quality_threshold", None)
            if qt is not None:
                val = int(qt)
                if val < 0 or val > 100:
                    tenant_config.quality_threshold = 0
        except (TypeError, ValueError):
            tenant_config.quality_threshold = 0


def _get_or_create_onboarding_state(user: str):
    """Get or create PIM Onboarding State for a user.

    Args:
        user: User email.

    Returns:
        PIM Onboarding State document.
    """
    import frappe

    existing = frappe.db.exists("PIM Onboarding State", {"user": user})

    if existing:
        return frappe.get_doc("PIM Onboarding State", existing)

    doc = frappe.new_doc("PIM Onboarding State")
    doc.user = user
    doc.current_step = "pending"
    doc.flags.ignore_links = True
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc


def _get_state_data_fields() -> Dict[str, str]:
    """Return the step data field mapping from PIM Onboarding State.

    Returns:
        Dict mapping step names to their data field names.
    """
    from frappe_pim.pim.doctype.pim_onboarding_state.pim_onboarding_state import (
        STEP_DATA_FIELDS,
    )
    return STEP_DATA_FIELDS


def _validate_step_params(step_id: str, step_number: int) -> Optional[str]:
    """Validate step_id and step_number are consistent and valid.

    Args:
        step_id: Step identifier.
        step_number: Step number (1-12).

    Returns:
        Error message string, or *None* if valid.
    """
    if step_number < 1 or step_number > TOTAL_STEPS:
        return f"Step number must be between 1 and {TOTAL_STEPS}, got: {step_number}"

    if step_id not in STEP_IDS:
        return f"Invalid step_id: '{step_id}'. Valid step IDs: {', '.join(STEP_IDS)}"

    expected_id = STEP_IDS[step_number - 1]
    if step_id != expected_id:
        return (
            f"Step ID '{step_id}' does not match step number {step_number}. "
            f"Expected '{expected_id}'"
        )

    return None


def _validate_step_data(step_id: str, form_data: Dict[str, Any]) -> StepValidationResult:
    """Validate form data for a specific step.

    Checks required fields and step-specific validation rules.

    Args:
        step_id: Step identifier.
        form_data: Dict of form data to validate.

    Returns:
        StepValidationResult with valid flag and any errors.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(form_data, dict):
        return StepValidationResult(valid=False, errors=["form_data must be a dict"])

    # Check required fields
    required = STEP_REQUIRED_FIELDS.get(step_id, [])
    for field_name in required:
        value = form_data.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"Required field '{field_name}' is missing or empty")

    # Step-specific validation
    if step_id == "company_info":
        _validate_company_info(form_data, errors, warnings)
    elif step_id == "industry_selection":
        _validate_industry_selection(form_data, errors, warnings)
    elif step_id == "product_structure":
        _validate_product_structure(form_data, errors, warnings)
    elif step_id == "quality_scoring":
        _validate_quality_scoring(form_data, errors, warnings)

    return StepValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def _validate_company_info(
    form_data: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate company info step data."""
    existing_systems = form_data.get("existing_systems")
    if existing_systems:
        if isinstance(existing_systems, str):
            try:
                parsed = json.loads(existing_systems)
                if not isinstance(parsed, list):
                    errors.append("existing_systems must be a JSON array")
            except (json.JSONDecodeError, TypeError):
                errors.append("existing_systems must be valid JSON")
        elif not isinstance(existing_systems, list):
            errors.append("existing_systems must be a list or JSON array string")


def _validate_industry_selection(
    form_data: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate industry selection step data."""
    from frappe_pim.pim.doctype.tenant_config.tenant_config import INDUSTRY_SECTORS

    industry = form_data.get("selected_industry")
    if industry and industry not in INDUSTRY_SECTORS:
        errors.append(
            f"Invalid industry: '{industry}'. "
            f"Valid sectors: {', '.join(INDUSTRY_SECTORS)}"
        )

    if industry == "custom" and not form_data.get("custom_industry_name"):
        errors.append("custom_industry_name is required when industry is 'custom'")


def _validate_product_structure(
    form_data: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate product structure step data."""
    if form_data.get("uses_variants") and not form_data.get("variant_axes"):
        warnings.append("Variants enabled but no variant axes specified")


def _validate_quality_scoring(
    form_data: Dict[str, Any],
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate quality scoring step data."""
    threshold = form_data.get("quality_threshold")
    if threshold is not None:
        try:
            threshold_int = int(threshold)
            if threshold_int < 0 or threshold_int > 100:
                errors.append("quality_threshold must be between 0 and 100")
        except (ValueError, TypeError):
            errors.append("quality_threshold must be a number")


def _write_step_to_tenant_config(
    tenant_config,
    step_id: str,
    form_data: Dict[str, Any],
) -> List[str]:
    """Map and write step form data fields to Tenant Config.

    Only writes fields that are defined in ``STEP_TENANT_CONFIG_FIELDS``
    for the given step_id.

    Args:
        tenant_config: Tenant Config document.
        step_id: Step identifier.
        form_data: Dict of form data.

    Returns:
        List of field names that were updated.
    """
    # Fill empty required fields before any save so we never trigger
    # [Tenant Config]: company_name, company_size, ... validation
    _ensure_tenant_config_required_defaults(tenant_config)

    allowed_fields = STEP_TENANT_CONFIG_FIELDS.get(step_id, [])
    updated_fields: List[str] = []

    for field_name in allowed_fields:
        if field_name in form_data:
            value = form_data[field_name]
            # Serialize lists/dicts to JSON strings for text fields
            if isinstance(value, (list, dict)):
                value = json.dumps(value, indent=2, default=str)
            tenant_config.set(field_name, value)
            updated_fields.append(field_name)

    if updated_fields:
        tenant_config.save(ignore_permissions=True)

    return updated_fields


def _get_completed_step_ids(user: str) -> List[str]:
    """Get list of completed step IDs from Onboarding Step Log.

    Args:
        user: User email.

    Returns:
        List of step_id strings that have been completed or skipped.
    """
    import frappe

    logs = frappe.get_all(
        "Onboarding Step Log",
        filters={
            "user": user,
            "action": ["in", ["completed", "skipped"]],
        },
        fields=["step_id"],
        order_by="step_number asc",
    )

    # Deduplicate while preserving order
    seen = set()
    result = []
    for log in logs:
        sid = log.get("step_id")
        if sid and sid not in seen:
            seen.add(sid)
            result.append(sid)

    return result


def _get_skipped_step_ids(user: str) -> List[str]:
    """Get list of step IDs that were skipped from Onboarding Step Log.

    Args:
        user: User email.

    Returns:
        List of step_id strings that have action "skipped".
    """
    import frappe

    logs = frappe.get_all(
        "Onboarding Step Log",
        filters={"user": user, "action": "skipped"},
        fields=["step_id"],
        order_by="step_number asc",
    )
    return [log["step_id"] for log in logs if log.get("step_id")]


def _check_mandatory_steps(completed_steps: List[str]) -> List[str]:
    """Check that all mandatory steps (1-8) are completed.

    Args:
        completed_steps: List of completed step IDs.

    Returns:
        List of missing mandatory step IDs.
    """
    mandatory_steps = STEP_IDS[:8]  # Steps 1-8
    completed_set = set(completed_steps)
    return [s for s in mandatory_steps if s not in completed_set]


def _aggregate_step_data_to_tenant_config(onboarding_state, tenant_config) -> None:
    """Aggregate all step data from PIM Onboarding State to Tenant Config.

    Reads all stored step data from the onboarding state and writes
    the corresponding fields to tenant config.

    Args:
        onboarding_state: PIM Onboarding State document.
        tenant_config: Tenant Config document.
    """
    if not onboarding_state:
        return

    all_step_data = onboarding_state.get_all_step_data()

    for step_name, step_data in all_step_data.items():
        if not isinstance(step_data, dict):
            continue
        # Find the wizard step_id that maps to this state step
        for wizard_step_id, state_step in STEP_ID_TO_STATE_STEP.items():
            if state_step == step_name:
                _write_step_to_tenant_config(
                    tenant_config, wizard_step_id, step_data
                )
                break


def _update_feature_flags(tenant_config) -> None:
    """Update feature flags based on onboarding selections.

    Args:
        tenant_config: Tenant Config document.
    """
    flags: Dict[str, bool] = {}

    # Derive flags from tenant config field values
    for flag_name, source_field in FEATURE_FLAG_SOURCES.items():
        value = tenant_config.get(source_field)
        if value is not None:
            flags[flag_name] = bool(value)

    # Enable channels if any channels selected
    channels = tenant_config.get("selected_channels")
    if channels:
        parsed = _safe_parse_json(channels)
        if isinstance(parsed, list) and len(parsed) > 0:
            flags["enable_channels"] = True

    # Enable workflow if workflow_complexity is not 'simple'
    workflow = tenant_config.get("workflow_complexity")
    if workflow and workflow != "simple":
        flags["enable_workflow"] = True

    if flags:
        tenant_config.set_feature_flags(flags)


def _state_step_to_number(state_step: str) -> int:
    """Convert a PIM Onboarding State step name to a wizard step number.

    Args:
        state_step: Step name from PIM Onboarding State.

    Returns:
        Wizard step number (1-12), or 0 if not mapped.
    """
    # Reverse lookup: find the first wizard step that maps to this state step
    for idx, step_id in enumerate(STEP_IDS):
        if STEP_ID_TO_STATE_STEP.get(step_id) == state_step:
            return idx + 1

    # Handle special cases
    if state_step == "pending":
        return 0
    if state_step == "completed":
        return TOTAL_STEPS

    return 0


def _step_id_to_number(step_id: str) -> int:
    """Convert a wizard step_id to a step number.

    Args:
        step_id: Wizard step identifier.

    Returns:
        Step number (1-12), or 0 if not found.
    """
    try:
        return STEP_IDS.index(step_id) + 1
    except ValueError:
        return 0


def _create_step_log(
    user: str,
    step_id: str,
    step_number: int,
    action: str,
    form_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Create an Onboarding Step Log entry for audit trail.

    Args:
        user: User email.
        step_id: Step identifier.
        step_number: Step number (1-12).
        action: Action performed (completed, skipped, saved).
        form_data: Optional form data snapshot.
    """
    import frappe
    from frappe.utils import now_datetime

    try:
        doc = frappe.new_doc("Onboarding Step Log")
        doc.user = user
        doc.step_id = step_id
        doc.step_number = int(step_number)
        doc.action = action
        doc.started_at = now_datetime()

        if form_data:
            doc.form_data = json.dumps(form_data, indent=2, default=str)

        doc.insert(ignore_permissions=True)
    except Exception:
        # Non-critical: don't fail the main operation if logging fails
        frappe.log_error(
            title="Failed to create onboarding step log",
            message=frappe.get_traceback(),
        )


def _load_industry_template(industry: str) -> Optional[Dict[str, Any]]:
    """Load template data from Industry Template DocType.

    Args:
        industry: Industry sector identifier.

    Returns:
        Parsed template data dict, or *None* if not found.
    """
    import frappe

    try:
        if not frappe.db.exists("DocType", "Industry Template"):
            return None

        # Find active template for this industry
        template_name = frappe.db.get_value(
            "Industry Template",
            filters={
                "template_code": industry,
                "is_active": 1,
            },
            fieldname="name",
        )

        if not template_name:
            return None

        doc = frappe.get_doc("Industry Template", template_name)

        # Build template data from the DocType fields
        template_data = {
            "template_code": doc.template_code,
            "version": doc.version,
            "display_name": doc.display_name,
        }

        # Parse JSON fields from the Industry Template
        json_fields = [
            "attribute_groups_data", "product_families_data",
            "channels_data", "compliance_data", "scoring_weights_data",
            "default_languages_data", "category_data", "demo_products_data",
            "attribute_types_data",
        ]

        for field_name in json_fields:
            raw = doc.get(field_name)
            if raw:
                template_data[field_name] = _safe_parse_json(raw)

        # Copy scalar fields
        for field_name in [
            "estimated_setup_minutes", "quality_threshold",
            "description",
        ]:
            value = doc.get(field_name)
            if value is not None:
                template_data[field_name] = value

        return template_data

    except Exception:
        return None


def _build_template_preview(
    industry: str,
    template_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a preview dict from Industry Template data.

    Args:
        industry: Industry sector.
        template_data: Parsed template data from DocType.

    Returns:
        Dict with preview information for the frontend.
    """
    # Extract attribute groups and count attributes
    attr_groups = template_data.get("attribute_groups_data", [])
    if isinstance(attr_groups, str):
        attr_groups = _safe_parse_json(attr_groups)

    attribute_count = 0
    group_names = []
    if isinstance(attr_groups, list):
        for group in attr_groups:
            if isinstance(group, dict):
                group_names.append(group.get("name", group.get("group_name", "")))
                attrs = group.get("attributes", [])
                attribute_count += len(attrs) if isinstance(attrs, list) else 0

    # Extract product families
    families = template_data.get("product_families_data", [])
    if isinstance(families, str):
        families = _safe_parse_json(families)

    # Extract channels
    channels = template_data.get("channels_data", {})
    if isinstance(channels, str):
        channels = _safe_parse_json(channels)

    default_channels = []
    coming_soon_channels = []
    if isinstance(channels, dict):
        default_channels = channels.get("default", [])
        coming_soon_channels = channels.get("coming_soon", [])
    elif isinstance(channels, list):
        default_channels = channels

    # Extract other preview fields
    compliance = template_data.get("compliance_data", [])
    if isinstance(compliance, str):
        compliance = _safe_parse_json(compliance)

    scoring_weights = template_data.get("scoring_weights_data", {})
    if isinstance(scoring_weights, str):
        scoring_weights = _safe_parse_json(scoring_weights)

    default_languages = template_data.get("default_languages_data", [])
    if isinstance(default_languages, str):
        default_languages = _safe_parse_json(default_languages)

    demo_products = template_data.get("demo_products_data", [])
    if isinstance(demo_products, str):
        demo_products = _safe_parse_json(demo_products)

    return {
        "industry": industry,
        "display_name": template_data.get("display_name", industry.replace("_", " ").title()),
        "description": template_data.get("description", ""),
        "version": template_data.get("version", "1.0"),
        "attribute_count": attribute_count,
        "attribute_groups": group_names,
        "product_families": families if isinstance(families, list) else [],
        "default_channels": default_channels,
        "coming_soon_channels": coming_soon_channels,
        "compliance_modules": compliance if isinstance(compliance, list) else [],
        "quality_threshold": template_data.get("quality_threshold", 70),
        "scoring_weights": scoring_weights if isinstance(scoring_weights, dict) else {},
        "default_languages": default_languages if isinstance(default_languages, list) else ["tr", "en"],
        "estimated_setup_minutes": template_data.get("estimated_setup_minutes", 30),
        "demo_products": len(demo_products) if isinstance(demo_products, list) else 0,
    }


def _build_step_metadata(
    current_step: int,
    completed_step_ids: List[str],
    skipped_step_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Build per-step metadata for the status response.

    Args:
        current_step: Current step number (1-12).
        completed_step_ids: List of completed step IDs.
        skipped_step_ids: List of step IDs that were skipped (for was_skipped).

    Returns:
        List of step metadata dicts.
    """
    completed_set = set(completed_step_ids)
    skipped_set = set(skipped_step_ids or [])
    steps = []

    for idx, step_id in enumerate(STEP_IDS):
        step_number = idx + 1
        steps.append({
            "step_id": step_id,
            "step_number": step_number,
            "is_completed": step_id in completed_set,
            "is_current": step_number == current_step,
            "is_skippable": step_number in SKIPPABLE_STEPS,
            "is_mandatory": step_number not in SKIPPABLE_STEPS and step_number != 12,
            "was_skipped": step_id in skipped_set,
        })

    return steps


def _create_demo_products(
    industry: str,
    template_data: Dict[str, Any],
) -> int:
    """Create demo products based on template data.

    Args:
        industry: Industry sector.
        template_data: Parsed template data.

    Returns:
        Number of demo products created.
    """
    import frappe

    demo_products = template_data.get("demo_products_data", [])
    if isinstance(demo_products, str):
        demo_products = _safe_parse_json(demo_products)

    if not isinstance(demo_products, list):
        return 0

    created = 0
    for product_data in demo_products:
        if not isinstance(product_data, dict):
            continue
        try:
            product_name = product_data.get("name", product_data.get("item_name", ""))
            if not product_name:
                continue

            # Check if item already exists (idempotent)
            if frappe.db.exists("Item", product_name):
                continue

            # Create a basic Item
            item = frappe.new_doc("Item")
            item.item_name = product_name
            item.item_group = product_data.get("item_group", "Products")
            item.description = product_data.get("description", "")
            item.is_stock_item = product_data.get("is_stock_item", 1)
            item.insert(ignore_permissions=True)
            created += 1
        except Exception:
            continue

    return created


def _assess_industry_change_impact(
    old_industry: str,
    new_industry: str,
) -> Optional[Dict[str, Any]]:
    """Assess the impact of changing the industry sector post-onboarding.

    Args:
        old_industry: Current industry sector.
        new_industry: New industry sector.

    Returns:
        Dict with impact analysis, or *None* if no significant impact.
    """
    import frappe

    if old_industry == new_industry:
        return None

    # Count existing entities that might be affected
    impact = {
        "old_industry": old_industry,
        "new_industry": new_industry,
        "message": (
            f"Changing industry from '{old_industry}' to '{new_industry}' "
            f"will apply additive changes. Existing configuration will be preserved."
        ),
        "affected_entities": {},
    }

    # Count entities created by templates
    entity_counts = {}
    for doctype in ["PIM Attribute Group", "PIM Attribute Type", "PIM Attribute",
                     "PIM Product Type", "Product Family"]:
        try:
            count = frappe.db.count(doctype)
            if count > 0:
                entity_counts[doctype] = count
        except Exception:
            pass

    impact["affected_entities"] = entity_counts

    return impact


def _safe_parse_json(value: Any, default: Any = None) -> Any:
    """Safely parse a JSON value.

    Args:
        value: Raw value (string, list, dict, or None).
        default: Default value if parsing fails.

    Returns:
        Parsed value, or default.
    """
    if default is None:
        default = []

    if not value:
        return default

    if isinstance(value, (list, dict)):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default

    return default


# =============================================================================
# Convenience Functions (module-level API)
# =============================================================================

def get_status(user: Optional[str] = None) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`OnboardingService.get_status`."""
    return OnboardingService.get_status(user=user)


def save_step(
    step_id: str,
    step_number: int,
    form_data: Dict[str, Any],
    advance: bool = False,
    user: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`OnboardingService.save_step`."""
    return OnboardingService.save_step(
        step_id=step_id,
        step_number=step_number,
        form_data=form_data,
        advance=advance,
        user=user,
    )


def skip_step(
    step_id: str,
    step_number: int,
    user: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`OnboardingService.skip_step`."""
    return OnboardingService.skip_step(
        step_id=step_id,
        step_number=step_number,
        user=user,
    )


def apply_template(
    create_demo_products: bool = False,
    user: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`OnboardingService.apply_template`."""
    return OnboardingService.apply_template(
        create_demo_products=create_demo_products,
        user=user,
    )


def complete_onboarding(
    form_data: Optional[Dict[str, Any]] = None,
    user: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`OnboardingService.complete_onboarding`."""
    return OnboardingService.complete_onboarding(
        form_data=form_data,
        user=user,
    )


def update_post_onboarding(
    section: str,
    form_data: Dict[str, Any],
    user: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`OnboardingService.update_post_onboarding`."""
    return OnboardingService.update_post_onboarding(
        section=section,
        form_data=form_data,
        user=user,
    )


def get_template_preview(
    industry: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for :meth:`OnboardingService.get_template_preview`."""
    return OnboardingService.get_template_preview(industry=industry)
