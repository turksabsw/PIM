"""Patch: Initialize Tenant Config singleton with default values.

Ensures the Tenant Config SingleType record exists with sensible defaults
for a fresh PIM installation. Since Tenant Config is issingle=1, Frappe
stores its data in the tabSingles table. This patch sets default values
for onboarding status, feature flags, language, workflow, and JSON fields.

All operations are idempotent — safe to run multiple times.

This patch runs during `bench migrate` for v1.0 installations.
"""

import frappe
from frappe import _


def execute():
    """Main patch entry point.

    Performs the following setup steps:
    1. Initialize Tenant Config with default scalar values
    2. Set default feature flags
    3. Initialize JSON array/object fields to empty defaults
    4. Set default integration settings
    """
    _initialize_tenant_config()


def _initialize_tenant_config():
    """Initialize the Tenant Config singleton with default values.

    Uses frappe.db.set_single_value to set individual fields, bypassing
    the reqd validation on fields like company_name (which the user will
    fill during the onboarding wizard). Only sets values that are currently
    empty/null to preserve any existing configuration.

    Silently skips if the DocType doesn't exist yet (first install).
    """
    if not frappe.db.exists("DocType", "Tenant Config"):
        return

    try:
        # Check if already configured (skip if onboarding is past initial state)
        existing_status = frappe.db.get_single_value(
            "Tenant Config", "onboarding_status"
        )
        if existing_status and existing_status not in ("not_started", ""):
            return

        _set_default_scalars()
        _set_default_feature_flags()
        _set_default_integrations()
        _initialize_json_fields()

        frappe.db.commit()

    except Exception:
        frappe.log_error(
            title="PIM Patch: Failed to initialize Tenant Config",
            message=frappe.get_traceback(),
        )


def _set_default_scalars():
    """Set default scalar field values if not already set."""
    defaults = {
        "onboarding_status": "not_started",
        "onboarding_current_step": 0,
        "primary_language": "tr",
        "workflow_complexity": "standard",
        "quality_threshold": 70,
        "notify_on_status_change": 1,
    }

    for field, value in defaults.items():
        current = frappe.db.get_single_value("Tenant Config", field)
        if not current:
            frappe.db.set_single_value("Tenant Config", field, value)


def _set_default_feature_flags():
    """Set default feature flag values if not already configured.

    Feature flags control which PIM capabilities are active for the tenant.
    Defaults enable core features (variants, scoring, channels, workflow)
    and disable advanced features (translations, AI, bundling, competitor).
    """
    flags = {
        "enable_variants": 1,
        "enable_quality_scoring": 1,
        "enable_channels": 1,
        "enable_workflow": 1,
        "enable_translations": 0,
        "enable_ai": 0,
        "enable_bundling": 0,
        "enable_competitor_tracking": 0,
    }

    for flag, default_value in flags.items():
        current = frappe.db.get_single_value("Tenant Config", flag)
        if current is None or current == "":
            frappe.db.set_single_value("Tenant Config", flag, default_value)


def _set_default_integrations():
    """Set default integration settings.

    Enables ERPNext bidirectional sync by default since this is a
    Frappe/ERPNext-native PIM module.
    """
    integration_defaults = {
        "enable_erp_sync": 1,
        "erp_type": "erpnext",
        "sync_direction": "bidirectional",
    }

    for field, value in integration_defaults.items():
        current = frappe.db.get_single_value("Tenant Config", field)
        if not current:
            frappe.db.set_single_value("Tenant Config", field, value)


def _initialize_json_fields():
    """Ensure JSON fields have proper empty defaults.

    JSON array fields default to '[]' and JSON object fields default
    to '{}'. This prevents null/None issues when parsing these fields
    in the controller or API layer.
    """
    array_fields = (
        "existing_systems",
        "pain_points",
        "variant_axes",
        "custom_families",
        "attribute_groups",
        "removed_template_attrs",
        "custom_attributes",
        "category_data",
        "brand_names",
        "selected_channels",
        "additional_languages",
        "ai_use_cases",
        "compliance_standards",
        "onboarding_step_data",
    )

    object_fields = (
        "scoring_weights",
    )

    for field in array_fields:
        current = frappe.db.get_single_value("Tenant Config", field)
        if not current:
            frappe.db.set_single_value("Tenant Config", field, "[]")

    for field in object_fields:
        current = frappe.db.get_single_value("Tenant Config", field)
        if not current:
            frappe.db.set_single_value("Tenant Config", field, "{}")
