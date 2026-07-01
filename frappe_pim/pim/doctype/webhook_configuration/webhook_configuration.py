"""
Webhook Configuration Controller
Manages webhook configurations for PIM event delivery with retry and tracking
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List, Dict, Any
import re
import json
import hashlib
import hmac
import base64


class WebhookConfiguration(Document):
    def validate(self):
        self.validate_webhook_url()
        self.validate_auth_config()
        self.validate_retry_config()
        self.validate_custom_headers()
        self.validate_payload_template()
        self.validate_status_codes()
        self.validate_event_triggers()

    def validate_webhook_url(self):
        """Validate webhook URL format"""
        if not self.webhook_url:
            frappe.throw(
                _("Webhook URL is required"),
                title=_("Missing URL")
            )

        # Must start with http:// or https://
        if not self.webhook_url.startswith(('http://', 'https://')):
            frappe.throw(
                _("Webhook URL must start with http:// or https://"),
                title=_("Invalid URL")
            )

        # Basic URL validation
        url_pattern = re.compile(
            r'^https?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$', re.IGNORECASE
        )
        if not url_pattern.match(self.webhook_url):
            frappe.throw(
                _("Invalid webhook URL format"),
                title=_("Invalid URL")
            )

    def validate_auth_config(self):
        """Validate authentication configuration based on type"""
        if self.auth_type == "API Key":
            if not self.api_key_header:
                frappe.throw(
                    _("API Key Header Name is required for API Key authentication"),
                    title=_("Missing Configuration")
                )
            if not self.api_key:
                frappe.throw(
                    _("API Key is required for API Key authentication"),
                    title=_("Missing Configuration")
                )

        elif self.auth_type == "Bearer Token":
            if not self.api_key:
                frappe.throw(
                    _("Token is required for Bearer Token authentication"),
                    title=_("Missing Configuration")
                )

        elif self.auth_type == "Basic Auth":
            if not self.basic_auth_username or not self.basic_auth_password:
                frappe.throw(
                    _("Username and Password are required for Basic Auth"),
                    title=_("Missing Configuration")
                )

        elif self.auth_type == "HMAC Signature":
            if not self.hmac_secret:
                frappe.throw(
                    _("HMAC Secret is required for HMAC Signature authentication"),
                    title=_("Missing Configuration")
                )
            if not self.hmac_header:
                frappe.throw(
                    _("HMAC Header Name is required for HMAC Signature authentication"),
                    title=_("Missing Configuration")
                )

    def validate_retry_config(self):
        """Validate retry configuration"""
        if self.max_retries is not None and self.max_retries < 0:
            frappe.throw(
                _("Max Retries cannot be negative"),
                title=_("Invalid Configuration")
            )

        if self.max_retries is not None and self.max_retries > 10:
            frappe.throw(
                _("Max Retries cannot exceed 10"),
                title=_("Invalid Configuration")
            )

        if self.initial_retry_delay is not None and self.initial_retry_delay < 1:
            frappe.throw(
                _("Initial Retry Delay must be at least 1 second"),
                title=_("Invalid Configuration")
            )

        if self.max_retry_delay is not None and self.max_retry_delay < self.initial_retry_delay:
            frappe.throw(
                _("Max Retry Delay cannot be less than Initial Retry Delay"),
                title=_("Invalid Configuration")
            )

        if self.backoff_multiplier is not None and self.backoff_multiplier < 1.0:
            frappe.throw(
                _("Backoff Multiplier must be at least 1.0"),
                title=_("Invalid Configuration")
            )

        if self.timeout_seconds is not None:
            if self.timeout_seconds < 1:
                frappe.throw(
                    _("Request Timeout must be at least 1 second"),
                    title=_("Invalid Configuration")
                )
            if self.timeout_seconds > 120:
                frappe.throw(
                    _("Request Timeout cannot exceed 120 seconds"),
                    title=_("Invalid Configuration")
                )

    def validate_custom_headers(self):
        """Validate custom headers JSON"""
        if self.custom_headers:
            try:
                headers = json.loads(self.custom_headers)
                if not isinstance(headers, dict):
                    frappe.throw(
                        _("Custom Headers must be a JSON object"),
                        title=_("Invalid JSON")
                    )
                # Validate all values are strings
                for key, value in headers.items():
                    if not isinstance(key, str) or not isinstance(value, str):
                        frappe.throw(
                            _("Custom Headers keys and values must be strings"),
                            title=_("Invalid JSON")
                        )
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Custom Headers must be valid JSON: {0}").format(str(e)),
                    title=_("Invalid JSON")
                )

    def validate_payload_template(self):
        """Validate Jinja2 payload template"""
        if self.payload_format == "Custom Template" and self.payload_template:
            try:
                from jinja2 import Environment, BaseLoader, TemplateSyntaxError
                env = Environment(loader=BaseLoader())
                env.parse(self.payload_template)
            except TemplateSyntaxError as e:
                frappe.throw(
                    _("Invalid Jinja2 template: {0}").format(str(e)),
                    title=_("Template Error")
                )

    def validate_status_codes(self):
        """Validate status code configurations"""
        if self.retry_on_status_codes:
            codes = self._parse_status_codes(self.retry_on_status_codes)
            if not codes:
                frappe.throw(
                    _("Invalid retry status codes format. Use comma-separated integers."),
                    title=_("Invalid Configuration")
                )

        if self.success_status_codes:
            codes = self._parse_status_codes(self.success_status_codes)
            if not codes:
                frappe.throw(
                    _("Invalid success status codes format. Use comma-separated integers."),
                    title=_("Invalid Configuration")
                )

    def _parse_status_codes(self, codes_str: str) -> List[int]:
        """Parse comma-separated status codes"""
        try:
            return [int(code.strip()) for code in codes_str.split(",") if code.strip()]
        except ValueError:
            return []

    def validate_event_triggers(self):
        """Ensure at least one event trigger is enabled"""
        triggers = [
            self.trigger_on_product_created,
            self.trigger_on_product_updated,
            self.trigger_on_product_deleted,
            self.trigger_on_product_published,
            self.trigger_on_product_unpublished,
            self.trigger_on_asset_created,
            self.trigger_on_golden_record_merged,
            self.trigger_on_taxonomy_changed,
            self.trigger_on_custom_event
        ]
        if not any(triggers):
            frappe.throw(
                _("At least one event trigger must be enabled"),
                title=_("No Event Triggers")
            )

    def before_save(self):
        """Prepare data before saving"""
        self.calculate_success_rate()

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        # Check for pending deliveries
        pending_count = frappe.db.count(
            "Webhook Delivery Log",
            filters={"webhook_configuration": self.name, "status": ["in", ["Pending", "Retrying"]]}
        ) if frappe.db.table_exists("Webhook Delivery Log") else 0

        if pending_count > 0:
            frappe.msgprint(
                _("Warning: {0} pending delivery(ies) for this webhook will be cancelled.").format(pending_count),
                title=_("Pending Deliveries"),
                indicator="yellow"
            )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:webhook:{self.name}")
            frappe.cache().delete_key("pim:all_webhooks")
            frappe.cache().delete_key("pim:active_webhooks")
        except Exception:
            pass

    def calculate_success_rate(self):
        """Calculate success rate from delivery statistics"""
        if self.total_deliveries and self.total_deliveries > 0:
            self.success_rate = (self.successful_deliveries or 0) / self.total_deliveries * 100
        else:
            self.success_rate = 0

    def get_enabled_triggers(self) -> List[str]:
        """Get list of enabled event triggers"""
        triggers = []
        trigger_mapping = {
            "trigger_on_product_created": "Product.Created",
            "trigger_on_product_updated": "Product.Updated",
            "trigger_on_product_deleted": "Product.Deleted",
            "trigger_on_product_published": "Product.Published",
            "trigger_on_product_unpublished": "Product.Unpublished",
            "trigger_on_asset_created": "Asset.Created",
            "trigger_on_golden_record_merged": "GoldenRecord.Merged",
            "trigger_on_taxonomy_changed": "Taxonomy.Changed"
        }

        for field, event_type in trigger_mapping.items():
            if getattr(self, field, False):
                triggers.append(event_type)

        # Add custom event types
        if self.trigger_on_custom_event and self.custom_event_types:
            custom_types = [t.strip() for t in self.custom_event_types.split(",") if t.strip()]
            triggers.extend(custom_types)

        return triggers

    def should_trigger_for_event(self, event_type: str, event_data: Optional[Dict] = None) -> bool:
        """Check if this webhook should trigger for a given event

        Args:
            event_type: The type of event (e.g., 'Product.Created')
            event_data: Optional event data for filter matching

        Returns:
            True if webhook should trigger, False otherwise
        """
        if not self.enabled:
            return False

        # Check if event type matches enabled triggers
        enabled_triggers = self.get_enabled_triggers()
        if event_type not in enabled_triggers:
            return False

        # Apply filters if event_data is provided
        if event_data:
            # Filter by channel
            if self.filter_by_channel and self.channels:
                allowed_channels = [c.strip() for c in self.channels.split(",")]
                event_channel = event_data.get("channel")
                if event_channel and event_channel not in allowed_channels:
                    return False

            # Filter by product type
            if self.filter_by_product_type and self.product_types:
                allowed_types = [t.strip() for t in self.product_types.split(",")]
                event_type_val = event_data.get("product_type")
                if event_type_val and event_type_val not in allowed_types:
                    return False

            # Filter by product family
            if self.filter_by_product_family and self.product_families:
                allowed_families = [f.strip() for f in self.product_families.split(",")]
                event_family = event_data.get("product_family")
                if event_family and event_family not in allowed_families:
                    return False

        return True

    def get_auth_headers(self) -> Dict[str, str]:
        """Build authentication headers for webhook request"""
        headers = {}

        if self.auth_type == "API Key":
            headers[self.api_key_header] = self.get_password("api_key")

        elif self.auth_type == "Bearer Token":
            headers["Authorization"] = f"Bearer {self.get_password('api_key')}"

        elif self.auth_type == "Basic Auth":
            credentials = f"{self.basic_auth_username}:{self.get_password('basic_auth_password')}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    def get_custom_headers(self) -> Dict[str, str]:
        """Get parsed custom headers"""
        if self.custom_headers:
            try:
                return json.loads(self.custom_headers)
            except json.JSONDecodeError:
                return {}
        return {}

    def generate_hmac_signature(self, payload: str) -> str:
        """Generate HMAC signature for payload

        Args:
            payload: The JSON payload string

        Returns:
            HMAC signature string
        """
        if self.auth_type != "HMAC Signature" or not self.hmac_secret:
            return ""

        secret = self.get_password("hmac_secret").encode()
        payload_bytes = payload.encode()

        algorithm_map = {
            "SHA256": hashlib.sha256,
            "SHA384": hashlib.sha384,
            "SHA512": hashlib.sha512
        }

        hash_func = algorithm_map.get(self.hmac_algorithm, hashlib.sha256)
        signature = hmac.new(secret, payload_bytes, hash_func).hexdigest()

        return signature

    def build_payload(self, event: Dict[str, Any], document: Optional[Dict] = None) -> str:
        """Build webhook payload based on configuration

        Args:
            event: Event data dictionary
            document: Optional full document data

        Returns:
            JSON string payload
        """
        if self.payload_format == "Raw Event Data":
            return json.dumps(event, default=str)

        elif self.payload_format == "Custom Template" and self.payload_template:
            from jinja2 import Environment, BaseLoader
            env = Environment(loader=BaseLoader())
            template = env.from_string(self.payload_template)

            context = {
                "event": event,
                "document": document or {},
                "user": frappe.session.user,
                "timestamp": frappe.utils.now_datetime().isoformat(),
                "webhook_name": self.webhook_name
            }

            return template.render(**context)

        else:
            # Standard format
            payload = {
                "webhook_id": self.name,
                "event_type": event.get("event_type"),
                "event_id": event.get("name") or event.get("event_id"),
                "timestamp": frappe.utils.now_datetime().isoformat()
            }

            if self.include_metadata:
                payload["metadata"] = {
                    "user": event.get("user") or frappe.session.user,
                    "source_system": event.get("source_system"),
                    "correlation_id": event.get("correlation_id"),
                    "triggered_by": "Frappe PIM"
                }

            if self.include_full_document and document:
                payload["document"] = document
            elif self.include_changed_fields_only and event.get("changed_fields"):
                payload["changed_fields"] = event.get("changed_fields")

            if self.include_related_data and document:
                payload["related_data"] = self._get_related_data(document)

            return json.dumps(payload, default=str)

    def _get_related_data(self, document: Dict) -> Dict:
        """Get related data for a document (attributes, classifications, etc.)"""
        related = {}
        doctype = document.get("doctype")
        name = document.get("name")

        if doctype == "Product Master" and name:
            try:
                # Get product attributes
                attributes = frappe.get_all(
                    "Product Attribute Value",
                    filters={"parent": name},
                    fields=["attribute", "value", "locale", "channel"]
                )
                related["attributes"] = attributes

                # Get classifications
                classifications = frappe.get_all(
                    "Product Classification",
                    filters={"parent": name},
                    fields=["taxonomy", "taxonomy_node", "is_primary"]
                )
                related["classifications"] = classifications
            except Exception:
                pass

        return related

    def get_retry_delay(self, attempt: int) -> int:
        """Calculate retry delay based on strategy and attempt number

        Args:
            attempt: Current retry attempt (1-based)

        Returns:
            Delay in seconds before next retry
        """
        initial = self.initial_retry_delay or 60
        max_delay = self.max_retry_delay or 3600

        if self.retry_strategy == "Fixed Interval":
            return initial

        elif self.retry_strategy == "Linear Backoff":
            delay = initial * attempt
            return min(delay, max_delay)

        else:  # Exponential Backoff (default)
            multiplier = self.backoff_multiplier or 2.0
            delay = initial * (multiplier ** (attempt - 1))
            return min(int(delay), max_delay)

    def update_delivery_stats(
        self,
        success: bool,
        response_time_ms: Optional[float] = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None,
        event_id: Optional[str] = None
    ):
        """Update delivery statistics after a webhook delivery attempt

        Args:
            success: Whether the delivery was successful
            response_time_ms: Response time in milliseconds
            status_code: HTTP status code from response
            error_message: Error message if failed
            event_id: ID of the event that triggered this delivery
        """
        updates = {
            "total_deliveries": (self.total_deliveries or 0) + 1,
            "last_delivery_at": frappe.utils.now_datetime(),
            "last_status_code": status_code,
            "last_event_id": event_id
        }

        if success:
            updates["successful_deliveries"] = (self.successful_deliveries or 0) + 1
            updates["consecutive_failures"] = 0
            updates["last_delivery_status"] = "Success"
            updates["last_error_message"] = None

            # Update average response time
            if response_time_ms is not None:
                current_avg = self.average_response_time or 0
                current_count = self.successful_deliveries or 0
                new_avg = ((current_avg * current_count) + response_time_ms) / (current_count + 1)
                updates["average_response_time"] = new_avg
                updates["last_response_time"] = response_time_ms
        else:
            updates["failed_deliveries"] = (self.failed_deliveries or 0) + 1
            updates["consecutive_failures"] = (self.consecutive_failures or 0) + 1
            updates["last_delivery_status"] = "Failed"
            updates["last_error_message"] = error_message

            # Check if webhook should be auto-disabled
            if (self.disable_on_consecutive_failures and
                self.disable_on_consecutive_failures > 0 and
                updates["consecutive_failures"] >= self.disable_on_consecutive_failures):
                updates["enabled"] = 0
                frappe.msgprint(
                    _("Webhook '{0}' has been automatically disabled after {1} consecutive failures").format(
                        self.webhook_name, updates["consecutive_failures"]
                    ),
                    title=_("Webhook Disabled"),
                    indicator="red"
                )

        # Calculate new success rate
        total = updates["total_deliveries"]
        successful = updates.get("successful_deliveries", self.successful_deliveries or 0)
        updates["success_rate"] = (successful / total * 100) if total > 0 else 0

        frappe.db.set_value("Webhook Configuration", self.name, updates, update_modified=False)

    @frappe.whitelist()
    def test_webhook(self) -> Dict[str, Any]:
        """Test the webhook configuration by sending a test payload

        Returns:
            Dict with success status and response details
        """
        import requests
        from frappe.utils import now_datetime

        test_payload = {
            "webhook_id": self.name,
            "event_type": "Test",
            "event_id": f"test-{frappe.generate_hash(length=8)}",
            "timestamp": now_datetime().isoformat(),
            "metadata": {
                "message": "This is a test webhook delivery from Frappe PIM",
                "triggered_by": frappe.session.user
            }
        }

        # Build headers
        headers = {
            "Content-Type": self.content_type or "application/json",
            "User-Agent": "Frappe-PIM-Webhook/1.0"
        }
        headers.update(self.get_auth_headers())
        headers.update(self.get_custom_headers())

        payload_str = json.dumps(test_payload, default=str)

        # Add HMAC signature if configured
        if self.auth_type == "HMAC Signature":
            signature = self.generate_hmac_signature(payload_str)
            headers[self.hmac_header] = signature

        try:
            start_time = frappe.utils.now_datetime()

            response = requests.request(
                method=self.http_method or "POST",
                url=self.webhook_url,
                headers=headers,
                data=payload_str,
                timeout=self.timeout_seconds or 30
            )

            end_time = frappe.utils.now_datetime()
            response_time_ms = (end_time - start_time).total_seconds() * 1000

            success_codes = self._parse_status_codes(self.success_status_codes or "200,201,202,204")

            return {
                "success": response.status_code in success_codes,
                "status_code": response.status_code,
                "response_time_ms": response_time_ms,
                "response_body": response.text[:1000] if response.text else None,
                "message": _("Test webhook delivered successfully") if response.status_code in success_codes
                          else _("Test webhook delivery failed with status {0}").format(response.status_code)
            }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "message": _("Request timed out after {0} seconds").format(self.timeout_seconds or 30)
            }
        except requests.exceptions.ConnectionError as e:
            return {
                "success": False,
                "message": _("Connection error: {0}").format(str(e))
            }
        except Exception as e:
            return {
                "success": False,
                "message": _("Error: {0}").format(str(e))
            }

    @frappe.whitelist()
    def reset_statistics(self):
        """Reset all delivery statistics"""
        updates = {
            "total_deliveries": 0,
            "successful_deliveries": 0,
            "failed_deliveries": 0,
            "consecutive_failures": 0,
            "success_rate": 0,
            "average_response_time": None,
            "last_delivery_at": None,
            "last_delivery_status": None,
            "last_status_code": None,
            "last_response_time": None,
            "last_error_message": None,
            "last_event_id": None
        }

        frappe.db.set_value("Webhook Configuration", self.name, updates)
        frappe.msgprint(_("Statistics have been reset"), indicator="green")

        return {"success": True}


# API Functions

@frappe.whitelist()
def get_webhooks(enabled_only: bool = True) -> List[Dict[str, Any]]:
    """Get all webhook configurations

    Args:
        enabled_only: If True, return only enabled webhooks
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1

    return frappe.get_all(
        "Webhook Configuration",
        filters=filters,
        fields=[
            "name", "webhook_name", "webhook_url", "enabled",
            "auth_type", "last_delivery_status", "success_rate",
            "total_deliveries", "successful_deliveries", "failed_deliveries",
            "consecutive_failures", "last_delivery_at"
        ],
        order_by="webhook_name asc"
    )


@frappe.whitelist()
def get_webhooks_for_event(event_type: str, event_data: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get webhooks that should trigger for a specific event

    Args:
        event_type: The type of event (e.g., 'Product.Created')
        event_data: Optional JSON string of event data for filtering
    """
    # Parse event data if provided
    data = {}
    if event_data:
        try:
            data = json.loads(event_data) if isinstance(event_data, str) else event_data
        except json.JSONDecodeError:
            data = {}

    # Get all enabled webhooks
    webhooks = frappe.get_all(
        "Webhook Configuration",
        filters={"enabled": 1},
        fields=["name"]
    )

    matching = []
    for webhook in webhooks:
        doc = frappe.get_doc("Webhook Configuration", webhook.name)
        if doc.should_trigger_for_event(event_type, data):
            matching.append({
                "name": doc.name,
                "webhook_name": doc.webhook_name,
                "webhook_url": doc.webhook_url
            })

    return matching


@frappe.whitelist()
def trigger_webhook(
    webhook_name: str,
    event_type: str,
    event_data: Optional[str] = None,
    document_data: Optional[str] = None,
    async_delivery: bool = True
) -> Dict[str, Any]:
    """Trigger a webhook delivery

    Args:
        webhook_name: Name of the webhook configuration
        event_type: Type of event
        event_data: JSON string of event data
        document_data: JSON string of document data
        async_delivery: If True, queue for background delivery

    Returns:
        Dict with delivery status or job info
    """
    doc = frappe.get_doc("Webhook Configuration", webhook_name)

    if not doc.enabled:
        return {"success": False, "message": _("Webhook is disabled")}

    # Parse data
    event = json.loads(event_data) if event_data else {}
    event["event_type"] = event_type

    document = json.loads(document_data) if document_data else None

    if async_delivery:
        # Queue for background delivery
        frappe.enqueue(
            "frappe_pim.pim.utils.webhook_delivery.deliver_webhook",
            queue="short",
            webhook_name=webhook_name,
            event=event,
            document=document,
            timeout=120
        )
        return {
            "success": True,
            "message": _("Webhook delivery queued"),
            "async": True
        }
    else:
        # Synchronous delivery (for testing)
        from frappe_pim.pim.utils.webhook_delivery import deliver_webhook
        return deliver_webhook(webhook_name, event, document)


@frappe.whitelist()
def get_webhook_statistics(webhook_name: Optional[str] = None) -> Dict[str, Any]:
    """Get webhook delivery statistics

    Args:
        webhook_name: Optional specific webhook name. If not provided, returns aggregate stats.
    """
    if webhook_name:
        doc = frappe.get_doc("Webhook Configuration", webhook_name)
        return {
            "webhook_name": doc.webhook_name,
            "total_deliveries": doc.total_deliveries or 0,
            "successful_deliveries": doc.successful_deliveries or 0,
            "failed_deliveries": doc.failed_deliveries or 0,
            "success_rate": doc.success_rate or 0,
            "consecutive_failures": doc.consecutive_failures or 0,
            "average_response_time_ms": doc.average_response_time or 0,
            "last_delivery_at": doc.last_delivery_at,
            "last_delivery_status": doc.last_delivery_status
        }
    else:
        # Aggregate statistics
        stats = frappe.db.sql("""
            SELECT
                COUNT(*) as total_webhooks,
                SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) as enabled_webhooks,
                SUM(total_deliveries) as total_deliveries,
                SUM(successful_deliveries) as successful_deliveries,
                SUM(failed_deliveries) as failed_deliveries,
                AVG(success_rate) as avg_success_rate,
                AVG(average_response_time) as avg_response_time
            FROM `tabWebhook Configuration`
        """, as_dict=True)

        return stats[0] if stats else {}


@frappe.whitelist()
def bulk_enable_webhooks(webhooks: str, enable: bool = True) -> Dict[str, Any]:
    """Enable or disable multiple webhooks

    Args:
        webhooks: JSON string of list of webhook names
        enable: If True, enable; if False, disable
    """
    if isinstance(webhooks, str):
        webhooks = json.loads(webhooks)

    for webhook_name in webhooks:
        frappe.db.set_value(
            "Webhook Configuration",
            webhook_name,
            "enabled",
            1 if enable else 0,
            update_modified=True
        )

    frappe.db.commit()
    return {"success": True, "updated": len(webhooks)}


@frappe.whitelist()
def get_delivery_log(
    webhook_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get webhook delivery log entries

    Args:
        webhook_name: Optional filter by webhook
        status: Optional filter by status (Pending, Success, Failed, Retrying)
        limit: Maximum number of entries to return
    """
    filters = {}
    if webhook_name:
        filters["webhook_configuration"] = webhook_name
    if status:
        filters["status"] = status

    try:
        return frappe.get_all(
            "Webhook Delivery Log",
            filters=filters,
            fields=[
                "name", "webhook_configuration", "event_type", "event_id",
                "status", "attempt_count", "status_code", "response_time_ms",
                "error_message", "created_at", "delivered_at", "next_retry_at"
            ],
            order_by="creation desc",
            limit_page_length=limit
        )
    except Exception:
        # Webhook Delivery Log may not exist yet
        return []


@frappe.whitelist()
def retry_failed_deliveries(webhook_name: str) -> Dict[str, Any]:
    """Retry all failed deliveries for a webhook

    Args:
        webhook_name: Webhook configuration name
    """
    try:
        failed_logs = frappe.get_all(
            "Webhook Delivery Log",
            filters={
                "webhook_configuration": webhook_name,
                "status": "Failed"
            },
            fields=["name", "event_data", "document_data"]
        )

        queued = 0
        for log in failed_logs:
            frappe.enqueue(
                "frappe_pim.pim.utils.webhook_delivery.retry_delivery",
                queue="short",
                delivery_log_name=log.name,
                timeout=120
            )
            queued += 1

        return {
            "success": True,
            "message": _("{0} failed deliveries queued for retry").format(queued),
            "queued": queued
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }
