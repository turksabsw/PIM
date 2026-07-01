"""
Channel Controller
Manages distribution channels for product syndication and export
"""

import frappe
from frappe import _
from frappe.model.document import Document
import re


class Channel(Document):
    def validate(self):
        self.validate_channel_code()
        self.validate_connection_settings()

    def validate_channel_code(self):
        """Ensure channel_code is URL-safe slug"""
        if not self.channel_code:
            # Auto-generate from name
            self.channel_code = frappe.scrub(self.channel_name)

        # Must be lowercase, no spaces, alphanumeric with underscores/hyphens
        if not re.match(r'^[a-z][a-z0-9_-]*$', self.channel_code):
            frappe.throw(
                _("Channel Code must start with a letter and contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Channel Code")
            )

    def validate_connection_settings(self):
        """Validate connection settings if base_url is provided"""
        if self.base_url:
            # Basic URL validation
            if not self.base_url.startswith(('http://', 'https://')):
                frappe.throw(
                    _("Base URL must start with http:// or https://"),
                    title=_("Invalid URL")
                )

    def before_save(self):
        """Prepare data before saving"""
        # Ensure sort_order is set
        if self.sort_order is None:
            self.sort_order = self.get_next_sort_order()

        # Generate webhook URL if not set
        if not self.webhook_url and self.channel_code:
            self.webhook_url = self.generate_webhook_url()

        # Update connection status based on settings
        self.update_connection_status()

    def get_next_sort_order(self):
        """Get next available sort order"""
        max_order = frappe.db.sql("""
            SELECT MAX(sort_order) FROM `tabChannel`
        """)
        if max_order and max_order[0][0] is not None:
            return max_order[0][0] + 10
        return 10

    def generate_webhook_url(self):
        """Generate webhook URL for this channel"""
        site_url = frappe.utils.get_url()
        return f"{site_url}/api/method/frappe_pim.pim.api.webhook.handle?channel={self.channel_code}"

    def update_connection_status(self):
        """Update connection status based on configuration"""
        if not self.base_url:
            self.connection_status = "Not Configured"
        elif self.connection_status == "Not Configured" and self.base_url:
            # Will be "Not Configured" until test_connection is called
            pass

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        # Check if any export profiles are using this channel
        profile_count = frappe.db.count("Export Profile", {"channel": self.name})
        if profile_count > 0:
            frappe.throw(
                _("Cannot delete channel '{0}' as it is used by {1} export profile(s). "
                  "Please delete or reassign these profiles first.").format(
                    self.channel_name, profile_count
                ),
                title=_("Channel In Use")
            )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:channel:{self.name}")
            frappe.cache().delete_key("pim:all_channels")
        except Exception:
            pass

    @frappe.whitelist()
    def test_connection(self):
        """Test the connection to this channel"""
        import requests
        from frappe.utils import now_datetime

        if not self.base_url:
            frappe.throw(_("Base URL is not configured"))

        try:
            # Simple GET request to test connectivity
            response = requests.get(
                self.base_url,
                timeout=10,
                headers=self._get_auth_headers()
            )

            self.last_connection_check = now_datetime()

            if response.status_code == 200:
                self.connection_status = "Connected"
                self.error_message = None
            elif response.status_code == 401 or response.status_code == 403:
                self.connection_status = "Authentication Error"
                self.error_message = f"HTTP {response.status_code}: Authentication failed"
            else:
                self.connection_status = "Connection Failed"
                self.error_message = f"HTTP {response.status_code}: {response.reason}"

            self.save()
            return {
                "status": self.connection_status,
                "message": self.error_message or _("Connection successful")
            }

        except requests.exceptions.Timeout:
            self.connection_status = "Connection Failed"
            self.error_message = _("Connection timed out")
            self.last_connection_check = now_datetime()
            self.save()
            return {"status": "Connection Failed", "message": self.error_message}

        except requests.exceptions.RequestException as e:
            self.connection_status = "Connection Failed"
            self.error_message = str(e)
            self.last_connection_check = now_datetime()
            self.save()
            return {"status": "Connection Failed", "message": self.error_message}

    def _get_auth_headers(self):
        """Build authentication headers for API requests"""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.get_password('api_key')}"
        return headers

    @frappe.whitelist()
    def sync_now(self):
        """Trigger immediate synchronization"""
        from frappe.utils import now_datetime

        if self.connection_status != "Connected":
            frappe.throw(_("Cannot sync - channel is not connected"))

        # Enqueue sync job
        frappe.enqueue(
            "frappe_pim.pim.api.export.sync_channel",
            queue="long",
            channel=self.name,
            timeout=3600
        )

        self.db_set("last_sync", now_datetime())

        return {"status": "success", "message": _("Sync job has been queued")}


@frappe.whitelist()
def get_channels(enabled_only=True):
    """Get all channels ordered by sort_order

    Args:
        enabled_only: If True, return only enabled channels
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1

    return frappe.get_all(
        "Channel",
        filters=filters,
        fields=[
            "name", "channel_name", "channel_code", "channel_type",
            "enabled", "connection_status", "sort_order"
        ],
        order_by="sort_order asc"
    )


@frappe.whitelist()
def get_channel_types():
    """Get available channel types"""
    return [
        {"value": "E-Commerce", "label": _("E-Commerce")},
        {"value": "Marketplace", "label": _("Marketplace")},
        {"value": "Social Commerce", "label": _("Social Commerce")},
        {"value": "Retail", "label": _("Retail")},
        {"value": "Wholesale", "label": _("Wholesale")},
        {"value": "B2B Portal", "label": _("B2B Portal")},
        {"value": "Mobile App", "label": _("Mobile App")},
        {"value": "Other", "label": _("Other")}
    ]


@frappe.whitelist()
def bulk_enable_channels(channels, enable=True):
    """Enable or disable multiple channels

    Args:
        channels: JSON string of list of channel names
        enable: If True, enable; if False, disable
    """
    import json
    if isinstance(channels, str):
        channels = json.loads(channels)

    for channel_name in channels:
        frappe.db.set_value(
            "Channel",
            channel_name,
            "enabled",
            1 if enable else 0,
            update_modified=True
        )

    frappe.db.commit()
    return {"success": True, "updated": len(channels)}


@frappe.whitelist()
def reorder_channels(order):
    """Reorder channels based on provided order list

    Args:
        order: JSON string of list of channel names in desired order
    """
    import json
    if isinstance(order, str):
        order = json.loads(order)

    for idx, channel_name in enumerate(order):
        frappe.db.set_value(
            "Channel",
            channel_name,
            "sort_order",
            (idx + 1) * 10,
            update_modified=False
        )

    frappe.db.commit()
    return {"success": True}
