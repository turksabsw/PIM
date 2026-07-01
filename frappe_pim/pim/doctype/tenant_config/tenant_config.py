"""
Tenant Config Controller
SingleType DocType storing all tenant-level PIM configuration.

One record per Frappe site (multi-tenant isolation by design).
Populated during the 12-step onboarding wizard and editable
post-onboarding via Settings > Onboarding Configuration.

Sections (13):
  Company Information, Industry & Template, Product Structure,
  Attribute Configuration, Taxonomy, Channels, Localization,
  Workflow, Quality & Scoring, Integrations, Compliance,
  Feature Flags, Onboarding Status
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
from typing import Dict, List, Optional, Any
import json


# JSON fields that store arrays — must default to "[]" (never None)
JSON_ARRAY_FIELDS = (
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

# JSON fields that store objects — must default to "{}" (never None)
JSON_OBJECT_FIELDS = (
    "scoring_weights",
)

# Feature flag fields with their default values
FEATURE_FLAGS = {
    "enable_variants": 1,
    "enable_quality_scoring": 1,
    "enable_channels": 1,
    "enable_workflow": 1,
    "enable_translations": 0,
    "enable_ai": 0,
    "enable_bundling": 0,
    "enable_competitor_tracking": 0,
}

# Valid onboarding statuses
ONBOARDING_STATUSES = ("not_started", "in_progress", "completed", "skipped")

# Valid industry sectors
INDUSTRY_SECTORS = (
    "fashion",
    "industrial",
    "food",
    "electronics",
    "health_beauty",
    "automotive",
    "custom",
)


class TenantConfig(Document):

    def validate(self):
        self.ensure_json_fields()
        self.validate_onboarding_status()
        self.validate_industry()
        self.validate_quality_threshold()
        self.compute_attribute_count()

    def ensure_json_fields(self):
        """Ensure JSON fields are never None — use '[]' or '{}' as defaults."""
        for field in JSON_ARRAY_FIELDS:
            value = self.get(field)
            if not value:
                self.set(field, "[]")
            elif isinstance(value, (list, tuple)):
                self.set(field, json.dumps(value, default=str))
        for field in JSON_OBJECT_FIELDS:
            value = self.get(field)
            if not value:
                self.set(field, "{}")
            elif isinstance(value, dict):
                self.set(field, json.dumps(value, default=str))

    def validate_onboarding_status(self):
        """Validate that onboarding_status has a valid value."""
        status = self.onboarding_status or "not_started"
        if status not in ONBOARDING_STATUSES:
            frappe.throw(
                _("Invalid onboarding status: {0}. Valid statuses are: {1}").format(
                    status, ", ".join(ONBOARDING_STATUSES)
                ),
                title=_("Invalid Status")
            )

    def validate_industry(self):
        """Validate selected industry is a known sector."""
        if self.selected_industry and self.selected_industry not in INDUSTRY_SECTORS:
            frappe.throw(
                _("Invalid industry sector: {0}. Valid sectors are: {1}").format(
                    self.selected_industry, ", ".join(INDUSTRY_SECTORS)
                ),
                title=_("Invalid Industry")
            )

        # Require custom_industry_name when sector is 'custom'
        if self.selected_industry == "custom" and not self.custom_industry_name:
            frappe.throw(
                _("Custom Industry Name is required when industry is set to 'custom'"),
                title=_("Missing Custom Industry Name")
            )

    def validate_quality_threshold(self):
        """Ensure quality threshold is within valid range."""
        if self.quality_threshold is not None:
            threshold = int(self.quality_threshold)
            if threshold < 0 or threshold > 100:
                frappe.throw(
                    _("Quality threshold must be between 0 and 100, got: {0}").format(
                        threshold
                    ),
                    title=_("Invalid Quality Threshold")
                )

    def compute_attribute_count(self):
        """Compute total_attribute_count from groups, custom, and removed attributes."""
        group_count = 0
        custom_count = 0
        removed_count = 0

        groups = self._parse_json_field("attribute_groups")
        if isinstance(groups, list):
            for group in groups:
                if isinstance(group, dict):
                    attrs = group.get("attributes", [])
                    group_count += len(attrs) if isinstance(attrs, list) else 0
                else:
                    group_count += 1

        custom_attrs = self._parse_json_field("custom_attributes")
        if isinstance(custom_attrs, list):
            custom_count = len(custom_attrs)

        removed_attrs = self._parse_json_field("removed_template_attrs")
        if isinstance(removed_attrs, list):
            removed_count = len(removed_attrs)

        self.total_attribute_count = group_count + custom_count - removed_count

    def before_save(self):
        """Set timestamps based on onboarding status transitions."""
        if self.onboarding_status == "in_progress" and not self.onboarding_started_at:
            self.onboarding_started_at = now_datetime()

        if self.onboarding_status == "completed" and not self.onboarding_completed_at:
            self.onboarding_completed_at = now_datetime()

    def on_update(self):
        """Post-save hooks — invalidate related caches."""
        self._invalidate_cache()

    # --- Public API methods ---

    def get_feature_flags(self) -> Dict[str, bool]:
        """Get all feature flags as a dict.

        Returns:
            Dict mapping feature flag names to their boolean values
        """
        return {
            flag: bool(self.get(flag))
            for flag in FEATURE_FLAGS
        }

    def set_feature_flags(self, flags: Dict[str, bool]) -> None:
        """Set multiple feature flags at once.

        Args:
            flags: Dict mapping feature flag names to boolean values

        Raises:
            frappe.ValidationError: If an unknown flag is provided
        """
        for flag, value in flags.items():
            if flag not in FEATURE_FLAGS:
                frappe.throw(
                    _("Unknown feature flag: {0}. Valid flags are: {1}").format(
                        flag, ", ".join(FEATURE_FLAGS.keys())
                    ),
                    title=_("Unknown Feature Flag")
                )
            self.set(flag, 1 if value else 0)

    def get_json_field(self, fieldname: str) -> Any:
        """Safely parse and return a JSON field value.

        Args:
            fieldname: Name of the JSON field

        Returns:
            Parsed JSON value (list or dict), or empty list/dict
        """
        if fieldname in JSON_OBJECT_FIELDS:
            return self._parse_json_field(fieldname, default_type="object")
        return self._parse_json_field(fieldname)

    def set_json_field(self, fieldname: str, value: Any) -> None:
        """Safely serialize and set a JSON field value.

        Args:
            fieldname: Name of the JSON field
            value: Python object to serialize (list or dict)
        """
        if isinstance(value, (list, dict)):
            self.set(fieldname, json.dumps(value, indent=2, default=str))
        else:
            self.set(fieldname, value)

    def mark_onboarding_started(self) -> None:
        """Mark onboarding as started for this tenant."""
        if self.onboarding_status == "completed":
            frappe.throw(
                _("Onboarding is already completed for this tenant"),
                title=_("Already Completed")
            )
        self.onboarding_status = "in_progress"
        self.onboarding_started_at = now_datetime()
        self.onboarding_current_step = 1
        self.save(ignore_permissions=True)

    def mark_onboarding_completed(self) -> None:
        """Mark onboarding as completed for this tenant."""
        self.onboarding_status = "completed"
        self.onboarding_completed_at = now_datetime()
        self.save(ignore_permissions=True)

    def mark_onboarding_skipped(self) -> None:
        """Mark onboarding as skipped for this tenant."""
        self.onboarding_status = "skipped"
        self.onboarding_completed_at = now_datetime()
        self.save(ignore_permissions=True)

    def update_onboarding_step(self, step_number: int) -> None:
        """Update the current onboarding step number.

        Args:
            step_number: Step number (1-12)

        Raises:
            frappe.ValidationError: If step number is out of range
        """
        if step_number < 1 or step_number > 12:
            frappe.throw(
                _("Step number must be between 1 and 12, got: {0}").format(
                    step_number
                ),
                title=_("Invalid Step Number")
            )
        self.onboarding_current_step = step_number
        if self.onboarding_status != "in_progress":
            self.onboarding_status = "in_progress"
        self.save(ignore_permissions=True)

    def save_step_data(self, step_id: str, step_number: int, data: Dict) -> None:
        """Save form data for a specific onboarding step.

        Stores a timestamped entry in the onboarding_step_data JSON field.

        Args:
            step_id: Step identifier (e.g., 'company_info')
            step_number: Step number (1-12)
            data: Form data dict to store
        """
        step_data = self._parse_json_field("onboarding_step_data")
        if not isinstance(step_data, list):
            step_data = []

        # Update or append step entry
        entry = {
            "step_id": step_id,
            "step_number": step_number,
            "data": data,
            "saved_at": str(now_datetime()),
        }

        # Replace existing entry for this step if present
        updated = False
        for i, existing in enumerate(step_data):
            if isinstance(existing, dict) and existing.get("step_id") == step_id:
                step_data[i] = entry
                updated = True
                break

        if not updated:
            step_data.append(entry)

        self.set("onboarding_step_data", json.dumps(step_data, indent=2, default=str))
        self.onboarding_current_step = step_number
        self.save(ignore_permissions=True)

    def get_config_summary(self) -> Dict[str, Any]:
        """Get a summary of tenant configuration for API responses.

        Returns:
            Dict with key configuration values
        """
        return {
            "company_name": self.company_name,
            "company_size": self.company_size,
            "selected_industry": self.selected_industry,
            "industry_template_version": self.industry_template_version,
            "estimated_sku_count": self.estimated_sku_count,
            "uses_variants": bool(self.uses_variants),
            "total_attribute_count": self.total_attribute_count or 0,
            "primary_channel": self.primary_channel,
            "primary_language": self.primary_language or "tr",
            "workflow_complexity": self.workflow_complexity or "standard",
            "quality_threshold": self.quality_threshold or 70,
            "onboarding_status": self.onboarding_status or "not_started",
            "onboarding_current_step": self.onboarding_current_step or 0,
            "feature_flags": self.get_feature_flags(),
        }

    # --- Private helpers ---

    def _parse_json_field(self, fieldname: str, default_type: str = "array") -> Any:
        """Safely parse a JSON field value.

        Args:
            fieldname: Name of the field to parse
            default_type: Default type to return ('array' or 'object')

        Returns:
            Parsed value, or empty list/dict as default
        """
        default = {} if default_type == "object" else []
        raw = self.get(fieldname)

        if not raw:
            return default

        if isinstance(raw, (list, dict)):
            return raw

        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return default

        return default

    def _invalidate_cache(self):
        """Invalidate tenant-config-related caches."""
        try:
            from frappe_pim.pim.utils.cache import invalidate_cache
            invalidate_cache("tenant_config", self.name)
        except (ImportError, AttributeError):
            pass
