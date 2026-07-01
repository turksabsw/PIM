"""
Industry Template Controller

Manages versioned industry sector templates for the PIM onboarding wizard.
Each template defines a complete industry configuration including attribute
groups, product families, channels, compliance modules, scoring weights,
category trees, and demo products.

Key constraints:
- Unique together: template_code + version
- Only one is_active = 1 per template_code
- JSON fields are validated on save
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Dict, List, Optional, Any
import json


# Valid template codes for industry sectors
VALID_TEMPLATE_CODES = (
    "fashion",
    "industrial",
    "food",
    "electronics",
    "health_beauty",
    "automotive",
    "custom",
)

# Fields that store JSON data
JSON_DATA_FIELDS = (
    "attribute_groups",
    "product_families",
    "default_channels",
    "coming_soon_channels",
    "compliance_modules",
    "scoring_weights",
    "default_languages",
    "category_tree",
    "demo_products",
)


class IndustryTemplate(Document):

    def validate(self):
        self.validate_template_code()
        self.validate_version_format()
        self.validate_unique_code_version()
        self.validate_json_fields()
        self.validate_quality_threshold()

    def validate_template_code(self):
        """Ensure template_code is a recognized sector identifier."""
        if not self.template_code:
            frappe.throw(
                _("Template Code is required"),
                title=_("Missing Template Code")
            )

        # Normalize to lowercase
        self.template_code = self.template_code.strip().lower()

        if self.template_code not in VALID_TEMPLATE_CODES:
            frappe.throw(
                _("Invalid template code: {0}. Valid codes are: {1}").format(
                    self.template_code, ", ".join(VALID_TEMPLATE_CODES)
                ),
                title=_("Invalid Template Code")
            )

    def validate_version_format(self):
        """Ensure version follows a valid format (e.g., 1.0, 2.0, 1.1)."""
        if not self.version:
            frappe.throw(
                _("Version is required"),
                title=_("Missing Version")
            )

        self.version = self.version.strip()

        # Basic version format validation (major.minor)
        parts = self.version.split(".")
        if len(parts) != 2:
            frappe.throw(
                _("Version must be in major.minor format (e.g., 1.0, 2.1). Got: {0}").format(
                    self.version
                ),
                title=_("Invalid Version Format")
            )

        try:
            major = int(parts[0])
            minor = int(parts[1])
            if major < 0 or minor < 0:
                raise ValueError("Negative version numbers")
        except ValueError:
            frappe.throw(
                _("Version components must be non-negative integers. Got: {0}").format(
                    self.version
                ),
                title=_("Invalid Version Format")
            )

    def validate_unique_code_version(self):
        """Ensure template_code + version combination is unique."""
        existing = frappe.db.exists(
            "Industry Template",
            {
                "template_code": self.template_code,
                "version": self.version,
                "name": ("!=", self.name or ""),
            },
        )

        if existing:
            frappe.throw(
                _("An Industry Template with code '{0}' and version '{1}' already exists: {2}").format(
                    self.template_code, self.version, existing
                ),
                title=_("Duplicate Template Version")
            )

    def validate_json_fields(self):
        """Validate that all JSON fields contain valid JSON data."""
        for field in JSON_DATA_FIELDS:
            value = self.get(field)
            if not value:
                continue

            if isinstance(value, (dict, list)):
                # Already parsed — valid
                continue

            if isinstance(value, str):
                try:
                    json.loads(value)
                except (json.JSONDecodeError, TypeError) as e:
                    frappe.throw(
                        _("Field '{0}' contains invalid JSON: {1}").format(
                            field, str(e)
                        ),
                        title=_("Invalid JSON Data")
                    )

    def validate_quality_threshold(self):
        """Ensure quality_threshold is within valid range (0-100)."""
        if self.quality_threshold is not None and self.quality_threshold != 0:
            if self.quality_threshold < 0 or self.quality_threshold > 100:
                frappe.throw(
                    _("Quality Threshold must be between 0 and 100. Got: {0}").format(
                        self.quality_threshold
                    ),
                    title=_("Invalid Quality Threshold")
                )

    def before_save(self):
        """Enforce single active version per template_code."""
        if self.is_active:
            self._deactivate_other_versions()

    def _deactivate_other_versions(self):
        """Deactivate all other versions of the same template_code.

        Ensures only one version is active per template_code at any time.
        """
        frappe.db.sql(
            """
            UPDATE `tabIndustry Template`
            SET is_active = 0
            WHERE template_code = %s
              AND name != %s
              AND is_active = 1
            """,
            (self.template_code, self.name or ""),
        )

    def get_template_data(self) -> Dict[str, Any]:
        """Return the full template data as a dictionary.

        Parses all JSON fields and returns a structured dict suitable
        for template engine consumption.

        Returns:
            Dict with all template configuration data
        """
        data = {
            "template_code": self.template_code,
            "display_name": self.display_name,
            "version": self.version,
            "is_active": bool(self.is_active),
            "description": self.description or "",
            "estimated_setup_minutes": self.estimated_setup_minutes or 15,
            "quality_threshold": self.quality_threshold or 70,
        }

        # Parse JSON fields
        for field in JSON_DATA_FIELDS:
            raw = self.get(field)
            if not raw:
                data[field] = [] if field != "scoring_weights" else {}
            elif isinstance(raw, str):
                try:
                    data[field] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    data[field] = [] if field != "scoring_weights" else {}
            else:
                data[field] = raw

        return data

    def get_preview_data(self) -> Dict[str, Any]:
        """Return a summary for preview/display purposes.

        Returns a lighter version of the template data suitable for
        the onboarding wizard preview panel.

        Returns:
            Dict with preview-friendly template summary
        """
        full_data = self.get_template_data()

        return {
            "template_code": full_data["template_code"],
            "display_name": full_data["display_name"],
            "version": full_data["version"],
            "description": full_data["description"],
            "estimated_setup_minutes": full_data["estimated_setup_minutes"],
            "quality_threshold": full_data["quality_threshold"],
            "attribute_group_count": len(full_data.get("attribute_groups", [])),
            "product_family_count": len(full_data.get("product_families", [])),
            "channel_count": len(full_data.get("default_channels", [])),
            "compliance_module_count": len(full_data.get("compliance_modules", [])),
            "category_count": _count_categories(full_data.get("category_tree", [])),
            "demo_product_count": len(full_data.get("demo_products", [])),
            "default_languages": full_data.get("default_languages", []),
        }


def _count_categories(tree: Any) -> int:
    """Recursively count categories in a tree structure.

    Args:
        tree: List of category dicts, each may have a 'children' key

    Returns:
        Total number of categories in the tree
    """
    if not isinstance(tree, list):
        return 0

    count = 0
    for node in tree:
        count += 1
        if isinstance(node, dict) and "children" in node:
            count += _count_categories(node["children"])

    return count


@frappe.whitelist()
def get_active_template(template_code: str) -> Optional[Dict]:
    """Get the active version of an industry template.

    Args:
        template_code: The sector identifier (e.g., "fashion")

    Returns:
        Dict with the template data, or None if not found
    """
    name = frappe.db.get_value(
        "Industry Template",
        {"template_code": template_code, "is_active": 1},
        "name",
    )

    if not name:
        return None

    doc = frappe.get_doc("Industry Template", name)
    return doc.get_template_data()


@frappe.whitelist()
def get_available_templates() -> List[Dict]:
    """Get all active industry templates for display in the onboarding wizard.

    Returns:
        List of dicts with preview data for each active template
    """
    templates = frappe.get_all(
        "Industry Template",
        filters={"is_active": 1},
        fields=["name"],
        order_by="template_code asc",
    )

    result = []
    for t in templates:
        doc = frappe.get_doc("Industry Template", t.name)
        result.append(doc.get_preview_data())

    return result
