"""
Source System Controller
Manages external data sources for MDM (Master Data Management) in PIM
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List, Dict, Any
import re


class SourceSystem(Document):
    def validate(self):
        self.validate_system_code()
        self.validate_priority()
        self.validate_confidence_level()
        self.validate_authoritative_fields()
        self.validate_connection_config()

    def validate_system_code(self):
        """Ensure system_code is URL-safe slug"""
        if not self.system_code:
            # Auto-generate from system_name
            self.system_code = frappe.scrub(self.system_name)

        # Must be lowercase, no spaces, alphanumeric with underscores/hyphens
        if not re.match(r'^[a-z][a-z0-9_-]*$', self.system_code):
            frappe.throw(
                _("System Code must start with a letter and contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid System Code")
            )

    def validate_priority(self):
        """Ensure priority is a positive integer"""
        if self.priority is not None and self.priority < 1:
            frappe.throw(
                _("Priority must be at least 1 (lower number = higher priority)"),
                title=_("Invalid Priority")
            )

    def validate_confidence_level(self):
        """Ensure confidence level is within valid range"""
        if self.confidence_level is not None:
            if self.confidence_level < 0 or self.confidence_level > 100:
                frappe.throw(
                    _("Confidence Level must be between 0 and 100"),
                    title=_("Invalid Confidence Level")
                )

    def validate_authoritative_fields(self):
        """Validate authoritative fields list if source is authoritative"""
        if self.is_authoritative and not self.authoritative_fields:
            frappe.throw(
                _("Authoritative Fields must be specified when 'Is Authoritative Source' is checked"),
                title=_("Missing Authoritative Fields")
            )

    def validate_connection_config(self):
        """Validate connection configuration based on type"""
        if self.connection_type and self.connection_type in ['REST API', 'SOAP', 'Webhook']:
            if not self.base_url:
                frappe.throw(
                    _("Base URL is required for {0} connection type").format(self.connection_type),
                    title=_("Missing Base URL")
                )
            # Validate URL format
            if self.base_url and not self.base_url.startswith(('http://', 'https://')):
                frappe.throw(
                    _("Base URL must start with http:// or https://"),
                    title=_("Invalid Base URL")
                )

        if self.auth_type == 'API Key' and not self.api_key_field:
            frappe.throw(
                _("API Key Header Name is required for API Key authentication"),
                title=_("Missing API Key Header")
            )

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        # Check if any golden record sources reference this system
        source_count = frappe.db.count("Golden Record Source", {"source_system": self.name})
        if source_count > 0:
            frappe.throw(
                _("Cannot delete source system '{0}' as it is referenced by {1} golden record source(s). "
                  "Please remove the references first.").format(
                    self.system_name, source_count
                ),
                title=_("Source System In Use")
            )

        # Check if any PIM events reference this system
        event_count = frappe.db.count("PIM Event", {"source_system": self.name})
        if event_count > 0:
            frappe.msgprint(
                _("Warning: {0} PIM event(s) reference this source system. "
                  "The events will retain the source system name for audit purposes.").format(event_count),
                title=_("PIM Events Exist"),
                indicator="yellow"
            )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:source_system:{self.name}")
            frappe.cache().delete_key("pim:all_source_systems")
            frappe.cache().delete_key("pim:source_priorities")
        except Exception:
            pass

    def get_authoritative_fields_list(self) -> List[str]:
        """Get list of authoritative field names"""
        if self.authoritative_fields:
            return [field.strip() for field in self.authoritative_fields.split(",")]
        return []

    def is_field_authoritative(self, field_name: str) -> bool:
        """Check if this source is authoritative for a specific field"""
        if not self.is_authoritative:
            return False
        return field_name in self.get_authoritative_fields_list()

    def update_sync_stats(self, records_count: int = 0, error: Optional[str] = None):
        """Update sync statistics after import"""
        updates = {
            "last_sync_at": frappe.utils.now_datetime()
        }
        if error:
            updates["last_error"] = error
        else:
            updates["last_error"] = None
            if records_count > 0:
                current_count = self.records_imported or 0
                updates["records_imported"] = current_count + records_count

        frappe.db.set_value("Source System", self.name, updates, update_modified=False)

    def get_connection_headers(self) -> Dict[str, str]:
        """Get HTTP headers for API connections"""
        headers = {}

        if self.auth_type == "API Key" and self.api_key:
            headers[self.api_key_field] = self.get_password("api_key")
        elif self.auth_type == "Bearer Token" and self.api_key:
            headers["Authorization"] = f"Bearer {self.get_password('api_key')}"
        elif self.auth_type == "Basic Auth" and self.api_key:
            import base64
            credentials = self.get_password("api_key")
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers


@frappe.whitelist()
def get_source_systems(
    enabled_only: bool = True,
    system_type: Optional[str] = None,
    order_by_priority: bool = False
) -> List[Dict[str, Any]]:
    """Get all source systems with optional filters

    Args:
        enabled_only: If True, return only enabled source systems
        system_type: Filter by system type (ERP, PIM, E-Commerce, etc.)
        order_by_priority: If True, order by priority (ascending)
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1
    if system_type:
        filters["system_type"] = system_type

    order_by = "priority asc" if order_by_priority else "system_name asc"

    return frappe.get_all(
        "Source System",
        filters=filters,
        fields=[
            "name", "system_name", "system_code", "system_type",
            "priority", "confidence_level", "enabled", "is_authoritative",
            "last_sync_at", "records_imported"
        ],
        order_by=order_by
    )


@frappe.whitelist()
def get_priority_ordered_sources() -> List[Dict[str, Any]]:
    """Get source systems ordered by priority for survivorship rules

    Returns:
        List of source systems ordered by priority (highest priority first)
    """
    return frappe.get_all(
        "Source System",
        filters={"enabled": 1},
        fields=["name", "system_name", "system_code", "priority", "confidence_level", "is_authoritative"],
        order_by="priority asc"
    )


@frappe.whitelist()
def get_authoritative_source_for_field(field_name: str) -> Optional[Dict[str, Any]]:
    """Get the authoritative source system for a specific field

    Args:
        field_name: Name of the field to check

    Returns:
        Source system that is authoritative for this field, or None
    """
    sources = frappe.get_all(
        "Source System",
        filters={"enabled": 1, "is_authoritative": 1},
        fields=["name", "system_name", "authoritative_fields", "priority", "confidence_level"]
    )

    for source in sources:
        if source.get("authoritative_fields"):
            fields = [f.strip() for f in source["authoritative_fields"].split(",")]
            if field_name in fields:
                return source

    return None


@frappe.whitelist()
def test_connection(source_system: str) -> Dict[str, Any]:
    """Test connection to a source system

    Args:
        source_system: Source System document name

    Returns:
        Dict with success status and message
    """
    doc = frappe.get_doc("Source System", source_system)

    if not doc.connection_type or doc.connection_type == "None":
        return {
            "success": False,
            "message": _("No connection type configured")
        }

    if doc.connection_type not in ["REST API", "SOAP", "Webhook"]:
        return {
            "success": False,
            "message": _("Connection testing is only available for API-based connections")
        }

    if not doc.base_url:
        return {
            "success": False,
            "message": _("Base URL is not configured")
        }

    try:
        import requests
        headers = doc.get_connection_headers()

        response = requests.get(
            doc.base_url,
            headers=headers,
            timeout=10
        )

        if response.status_code in [200, 201, 204]:
            return {
                "success": True,
                "message": _("Connection successful (HTTP {0})").format(response.status_code)
            }
        else:
            return {
                "success": False,
                "message": _("Connection failed with HTTP {0}: {1}").format(
                    response.status_code,
                    response.reason
                )
            }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": _("Connection timed out after 10 seconds")
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "success": False,
            "message": _("Connection error: {0}").format(str(e))
        }
    except Exception as e:
        return {
            "success": False,
            "message": _("Unexpected error: {0}").format(str(e))
        }


@frappe.whitelist()
def apply_survivorship_rules(
    field_values: List[Dict[str, Any]],
    rule_type: str = "source_priority"
) -> Optional[Any]:
    """Apply survivorship rules to select the best value from multiple sources

    Args:
        field_values: List of dicts with 'value', 'source_system', 'timestamp', 'confidence'
        rule_type: Rule type - 'source_priority', 'most_recent', 'highest_confidence'

    Returns:
        The winning value based on the rule
    """
    if not field_values:
        return None

    if len(field_values) == 1:
        return field_values[0].get("value")

    if rule_type == "source_priority":
        # Get priority for each source
        sources_priority = {}
        for item in field_values:
            source = item.get("source_system")
            if source and source not in sources_priority:
                priority = frappe.db.get_value("Source System", source, "priority")
                sources_priority[source] = priority if priority else 999

        # Sort by priority (lower is better)
        sorted_values = sorted(
            field_values,
            key=lambda x: sources_priority.get(x.get("source_system"), 999)
        )
        return sorted_values[0].get("value") if sorted_values else None

    elif rule_type == "most_recent":
        # Sort by timestamp descending
        sorted_values = sorted(
            field_values,
            key=lambda x: x.get("timestamp") or "",
            reverse=True
        )
        return sorted_values[0].get("value") if sorted_values else None

    elif rule_type == "highest_confidence":
        # Sort by confidence descending
        sorted_values = sorted(
            field_values,
            key=lambda x: x.get("confidence") or 0,
            reverse=True
        )
        return sorted_values[0].get("value") if sorted_values else None

    return field_values[0].get("value")
