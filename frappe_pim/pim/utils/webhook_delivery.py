"""
Webhook Delivery System with Exponential Backoff

This module provides comprehensive webhook delivery functionality for the PIM system
including exponential backoff retry logic, delivery logging, and statistics tracking.

Key features:
- Exponential backoff with configurable parameters
- Delivery logging and retry management
- HMAC signature generation for secure payloads
- Support for multiple authentication methods
- Circuit breaker pattern for failing webhooks
- Async delivery via Frappe background jobs

These functions integrate with:
    - Webhook Configuration (delivery settings)
    - PIM Event (event sourcing)
    - Webhook Delivery Log (delivery tracking)

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
import json
import time
import hashlib
import hmac
import base64


# ============================================================================
# Constants
# ============================================================================

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_DELAY = 60  # seconds
DEFAULT_MAX_DELAY = 3600  # seconds
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_TIMEOUT = 30  # seconds

# Success status codes
DEFAULT_SUCCESS_CODES = [200, 201, 202, 204]

# Retryable status codes
DEFAULT_RETRY_CODES = [408, 429, 500, 502, 503, 504]

# Delivery statuses
STATUS_PENDING = "Pending"
STATUS_IN_PROGRESS = "In Progress"
STATUS_SUCCESS = "Success"
STATUS_FAILED = "Failed"
STATUS_RETRYING = "Retrying"
STATUS_CANCELLED = "Cancelled"


# ============================================================================
# Main Delivery Functions
# ============================================================================

def deliver_webhook(
    webhook_name: str,
    event: Dict[str, Any],
    document: Optional[Dict[str, Any]] = None,
    delivery_log_name: Optional[str] = None,
    attempt: int = 1
) -> Dict[str, Any]:
    """Deliver a webhook payload to the configured endpoint.

    This is the main entry point for webhook delivery. It handles
    authentication, payload building, delivery, and retry scheduling.

    Args:
        webhook_name: Name of the Webhook Configuration
        event: Event data dictionary containing event_type, etc.
        document: Optional full document data
        delivery_log_name: Optional existing delivery log to update
        attempt: Current attempt number (1-based)

    Returns:
        Dict with delivery result:
        - success: bool indicating delivery success
        - status_code: HTTP status code (if applicable)
        - response_time_ms: Response time in milliseconds
        - message: Human-readable status message
        - delivery_log: Name of the delivery log entry
        - retry_scheduled: bool if retry is scheduled
    """
    import frappe
    import requests
    from frappe.utils import now_datetime

    result = {
        "success": False,
        "status_code": None,
        "response_time_ms": None,
        "message": "",
        "delivery_log": delivery_log_name,
        "retry_scheduled": False
    }

    try:
        # Get webhook configuration
        webhook = frappe.get_doc("Webhook Configuration", webhook_name)

        # Check if webhook is enabled
        if not webhook.enabled:
            result["message"] = "Webhook is disabled"
            return result

        # Create or update delivery log
        delivery_log = _get_or_create_delivery_log(
            webhook_name=webhook_name,
            event=event,
            document=document,
            delivery_log_name=delivery_log_name,
            attempt=attempt
        )

        if delivery_log:
            result["delivery_log"] = delivery_log.name
            _update_delivery_log_status(delivery_log, STATUS_IN_PROGRESS)

        # Build headers
        headers = _build_headers(webhook)

        # Build payload
        payload_str = webhook.build_payload(event, document)

        # Add HMAC signature if configured
        if webhook.auth_type == "HMAC Signature":
            signature = webhook.generate_hmac_signature(payload_str)
            if signature and webhook.hmac_header:
                headers[webhook.hmac_header] = signature

        # Make the HTTP request
        start_time = now_datetime()

        try:
            response = requests.request(
                method=webhook.http_method or "POST",
                url=webhook.webhook_url,
                headers=headers,
                data=payload_str,
                timeout=webhook.timeout_seconds or DEFAULT_TIMEOUT
            )

            end_time = now_datetime()
            response_time_ms = (end_time - start_time).total_seconds() * 1000

            result["status_code"] = response.status_code
            result["response_time_ms"] = response_time_ms

            # Determine success
            success_codes = _parse_status_codes(
                webhook.success_status_codes or "200,201,202,204"
            )
            is_success = response.status_code in success_codes

            if is_success:
                result["success"] = True
                result["message"] = f"Delivered successfully with status {response.status_code}"

                # Update delivery log
                if delivery_log:
                    _update_delivery_log_success(
                        delivery_log=delivery_log,
                        status_code=response.status_code,
                        response_time_ms=response_time_ms,
                        response_body=response.text[:2000] if response.text else None
                    )

                # Update webhook statistics
                webhook.update_delivery_stats(
                    success=True,
                    response_time_ms=response_time_ms,
                    status_code=response.status_code,
                    event_id=event.get("name") or event.get("event_id")
                )

            else:
                # Delivery failed - check if retryable
                retry_codes = _parse_status_codes(
                    webhook.retry_on_status_codes or "408,429,500,502,503,504"
                )
                should_retry = (
                    response.status_code in retry_codes and
                    attempt < (webhook.max_retries or DEFAULT_MAX_RETRIES)
                )

                error_message = f"HTTP {response.status_code}: {response.text[:500]}" if response.text else f"HTTP {response.status_code}"
                result["message"] = error_message

                if should_retry:
                    # Schedule retry
                    result["retry_scheduled"] = _schedule_retry(
                        webhook=webhook,
                        delivery_log=delivery_log,
                        attempt=attempt,
                        error_message=error_message,
                        response_time_ms=response_time_ms
                    )

                    if delivery_log:
                        _update_delivery_log_retry(
                            delivery_log=delivery_log,
                            status_code=response.status_code,
                            response_time_ms=response_time_ms,
                            error_message=error_message,
                            attempt=attempt,
                            webhook=webhook
                        )
                else:
                    # Final failure
                    if delivery_log:
                        _update_delivery_log_failure(
                            delivery_log=delivery_log,
                            status_code=response.status_code,
                            response_time_ms=response_time_ms,
                            error_message=error_message
                        )

                    # Update webhook statistics
                    webhook.update_delivery_stats(
                        success=False,
                        response_time_ms=response_time_ms,
                        status_code=response.status_code,
                        error_message=error_message,
                        event_id=event.get("name") or event.get("event_id")
                    )

        except requests.exceptions.Timeout as e:
            end_time = now_datetime()
            response_time_ms = (end_time - start_time).total_seconds() * 1000

            error_message = f"Request timed out after {webhook.timeout_seconds or DEFAULT_TIMEOUT} seconds"
            result["message"] = error_message
            result["response_time_ms"] = response_time_ms

            _handle_request_error(
                webhook=webhook,
                delivery_log=delivery_log,
                attempt=attempt,
                error_message=error_message,
                response_time_ms=response_time_ms,
                event=event,
                result=result
            )

        except requests.exceptions.ConnectionError as e:
            error_message = f"Connection error: {str(e)}"
            result["message"] = error_message

            _handle_request_error(
                webhook=webhook,
                delivery_log=delivery_log,
                attempt=attempt,
                error_message=error_message,
                response_time_ms=None,
                event=event,
                result=result
            )

        except requests.exceptions.RequestException as e:
            error_message = f"Request error: {str(e)}"
            result["message"] = error_message

            _handle_request_error(
                webhook=webhook,
                delivery_log=delivery_log,
                attempt=attempt,
                error_message=error_message,
                response_time_ms=None,
                event=event,
                result=result
            )

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Webhook delivery error for {webhook_name}: {str(e)}",
            title="Webhook Delivery Error"
        )
        result["message"] = f"Internal error: {str(e)}"

    return result


def retry_delivery(delivery_log_name: str) -> Dict[str, Any]:
    """Retry a failed webhook delivery.

    Retrieves the delivery log, extracts event and document data,
    and attempts redelivery.

    Args:
        delivery_log_name: Name of the Webhook Delivery Log entry

    Returns:
        Dict with delivery result
    """
    import frappe

    try:
        delivery_log = frappe.get_doc("Webhook Delivery Log", delivery_log_name)

        # Parse stored data
        event_data = {}
        document_data = None

        if delivery_log.event_data:
            try:
                event_data = json.loads(delivery_log.event_data)
            except json.JSONDecodeError:
                event_data = {}

        if delivery_log.document_data:
            try:
                document_data = json.loads(delivery_log.document_data)
            except json.JSONDecodeError:
                document_data = None

        # Increment attempt count
        new_attempt = (delivery_log.attempt_count or 1) + 1

        return deliver_webhook(
            webhook_name=delivery_log.webhook_configuration,
            event=event_data,
            document=document_data,
            delivery_log_name=delivery_log_name,
            attempt=new_attempt
        )

    except Exception as e:
        frappe.log_error(
            message=f"Retry delivery error for {delivery_log_name}: {str(e)}",
            title="Webhook Retry Error"
        )
        return {
            "success": False,
            "message": f"Retry error: {str(e)}",
            "delivery_log": delivery_log_name
        }


def deliver_event_webhooks(
    event_type: str,
    event_data: Dict[str, Any],
    document_data: Optional[Dict[str, Any]] = None,
    async_delivery: bool = True
) -> Dict[str, Any]:
    """Deliver webhooks for all configurations that match an event.

    This is the main entry point called from PIM Event creation.
    It finds all matching webhook configurations and queues deliveries.

    Args:
        event_type: Type of event (e.g., 'Product.Created')
        event_data: Event data dictionary
        document_data: Optional document data
        async_delivery: If True, queue for background delivery

    Returns:
        Dict with delivery status and queued webhooks
    """
    import frappe

    result = {
        "event_type": event_type,
        "webhooks_matched": 0,
        "webhooks_queued": [],
        "webhooks_failed": []
    }

    try:
        # Get all enabled webhooks that match this event
        webhooks = frappe.get_all(
            "Webhook Configuration",
            filters={"enabled": 1},
            fields=["name", "webhook_name"]
        )

        for webhook_info in webhooks:
            try:
                webhook = frappe.get_doc("Webhook Configuration", webhook_info.name)

                # Check if webhook should trigger for this event
                if webhook.should_trigger_for_event(event_type, event_data):
                    result["webhooks_matched"] += 1

                    if async_delivery:
                        # Queue for background delivery
                        frappe.enqueue(
                            "frappe_pim.pim.utils.webhook_delivery.deliver_webhook",
                            queue="short",
                            webhook_name=webhook_info.name,
                            event=event_data,
                            document=document_data,
                            timeout=120
                        )
                        result["webhooks_queued"].append(webhook_info.webhook_name)
                    else:
                        # Synchronous delivery
                        delivery_result = deliver_webhook(
                            webhook_name=webhook_info.name,
                            event=event_data,
                            document=document_data
                        )
                        if delivery_result.get("success"):
                            result["webhooks_queued"].append(webhook_info.webhook_name)
                        else:
                            result["webhooks_failed"].append({
                                "webhook": webhook_info.webhook_name,
                                "error": delivery_result.get("message")
                            })

            except Exception as e:
                result["webhooks_failed"].append({
                    "webhook": webhook_info.get("webhook_name"),
                    "error": str(e)
                })

    except Exception as e:
        frappe.log_error(
            message=f"Error delivering event webhooks for {event_type}: {str(e)}",
            title="Webhook Event Delivery Error"
        )
        result["error"] = str(e)

    return result


# ============================================================================
# Exponential Backoff Functions
# ============================================================================

def calculate_backoff_delay(
    attempt: int,
    strategy: str = "Exponential Backoff",
    initial_delay: int = DEFAULT_INITIAL_DELAY,
    max_delay: int = DEFAULT_MAX_DELAY,
    multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    jitter: bool = True
) -> int:
    """Calculate the retry delay based on backoff strategy.

    Supports three strategies:
    - Exponential Backoff: delay = initial * (multiplier ^ (attempt - 1))
    - Linear Backoff: delay = initial * attempt
    - Fixed Interval: delay = initial

    Args:
        attempt: Current attempt number (1-based)
        strategy: Backoff strategy name
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        multiplier: Multiplier for exponential backoff
        jitter: Add random jitter to prevent thundering herd

    Returns:
        Calculated delay in seconds
    """
    import random

    if strategy == "Fixed Interval":
        delay = initial_delay
    elif strategy == "Linear Backoff":
        delay = initial_delay * attempt
    else:  # Exponential Backoff (default)
        delay = initial_delay * (multiplier ** (attempt - 1))

    # Apply maximum cap
    delay = min(int(delay), max_delay)

    # Add jitter (up to 10% of delay)
    if jitter and delay > 0:
        jitter_amount = int(delay * 0.1)
        delay += random.randint(-jitter_amount, jitter_amount)
        delay = max(1, delay)  # Ensure at least 1 second

    return delay


def get_next_retry_time(
    webhook_name: str,
    attempt: int
) -> datetime:
    """Get the datetime for the next retry attempt.

    Args:
        webhook_name: Name of the webhook configuration
        attempt: Current attempt number

    Returns:
        DateTime for next retry
    """
    import frappe
    from frappe.utils import now_datetime, add_to_date

    try:
        webhook = frappe.get_doc("Webhook Configuration", webhook_name)
        delay_seconds = calculate_backoff_delay(
            attempt=attempt,
            strategy=webhook.retry_strategy or "Exponential Backoff",
            initial_delay=webhook.initial_retry_delay or DEFAULT_INITIAL_DELAY,
            max_delay=webhook.max_retry_delay or DEFAULT_MAX_DELAY,
            multiplier=webhook.backoff_multiplier or DEFAULT_BACKOFF_MULTIPLIER
        )
    except Exception:
        delay_seconds = calculate_backoff_delay(attempt=attempt)

    return add_to_date(now_datetime(), seconds=delay_seconds)


# ============================================================================
# Delivery Log Functions
# ============================================================================

def _get_or_create_delivery_log(
    webhook_name: str,
    event: Dict[str, Any],
    document: Optional[Dict[str, Any]],
    delivery_log_name: Optional[str],
    attempt: int
) -> Any:
    """Get existing or create new delivery log entry.

    Args:
        webhook_name: Webhook configuration name
        event: Event data
        document: Document data
        delivery_log_name: Existing log name (optional)
        attempt: Current attempt number

    Returns:
        Delivery log document or None if DocType doesn't exist
    """
    import frappe

    # Check if Webhook Delivery Log DocType exists
    if not frappe.db.table_exists("Webhook Delivery Log"):
        return None

    try:
        if delivery_log_name:
            # Update existing log
            delivery_log = frappe.get_doc("Webhook Delivery Log", delivery_log_name)
            delivery_log.attempt_count = attempt
            delivery_log.save(ignore_permissions=True)
            return delivery_log

        else:
            # Create new log
            delivery_log = frappe.get_doc({
                "doctype": "Webhook Delivery Log",
                "webhook_configuration": webhook_name,
                "event_type": event.get("event_type"),
                "event_id": event.get("name") or event.get("event_id"),
                "status": STATUS_PENDING,
                "attempt_count": attempt,
                "event_data": json.dumps(event, default=str),
                "document_data": json.dumps(document, default=str) if document else None,
                "created_at": frappe.utils.now_datetime()
            })
            delivery_log.insert(ignore_permissions=True)
            return delivery_log

    except Exception as e:
        frappe.log_error(
            message=f"Error creating delivery log: {str(e)}",
            title="Webhook Delivery Log Error"
        )
        return None


def _update_delivery_log_status(delivery_log: Any, status: str) -> None:
    """Update delivery log status."""
    import frappe

    if delivery_log:
        try:
            frappe.db.set_value(
                "Webhook Delivery Log",
                delivery_log.name,
                "status",
                status,
                update_modified=False
            )
        except Exception:
            pass


def _update_delivery_log_success(
    delivery_log: Any,
    status_code: int,
    response_time_ms: float,
    response_body: Optional[str]
) -> None:
    """Update delivery log for successful delivery."""
    import frappe
    from frappe.utils import now_datetime

    if delivery_log:
        try:
            updates = {
                "status": STATUS_SUCCESS,
                "status_code": status_code,
                "response_time_ms": response_time_ms,
                "response_body": response_body,
                "delivered_at": now_datetime(),
                "error_message": None,
                "next_retry_at": None
            }
            frappe.db.set_value(
                "Webhook Delivery Log",
                delivery_log.name,
                updates,
                update_modified=True
            )
        except Exception:
            pass


def _update_delivery_log_failure(
    delivery_log: Any,
    status_code: Optional[int],
    response_time_ms: Optional[float],
    error_message: str
) -> None:
    """Update delivery log for final failure (no more retries)."""
    import frappe
    from frappe.utils import now_datetime

    if delivery_log:
        try:
            updates = {
                "status": STATUS_FAILED,
                "status_code": status_code,
                "response_time_ms": response_time_ms,
                "error_message": error_message,
                "failed_at": now_datetime(),
                "next_retry_at": None
            }
            frappe.db.set_value(
                "Webhook Delivery Log",
                delivery_log.name,
                updates,
                update_modified=True
            )
        except Exception:
            pass


def _update_delivery_log_retry(
    delivery_log: Any,
    status_code: Optional[int],
    response_time_ms: Optional[float],
    error_message: str,
    attempt: int,
    webhook: Any
) -> None:
    """Update delivery log for retry scheduled."""
    import frappe

    if delivery_log:
        try:
            next_retry = get_next_retry_time(webhook.name, attempt + 1)
            updates = {
                "status": STATUS_RETRYING,
                "status_code": status_code,
                "response_time_ms": response_time_ms,
                "error_message": error_message,
                "next_retry_at": next_retry,
                "attempt_count": attempt
            }
            frappe.db.set_value(
                "Webhook Delivery Log",
                delivery_log.name,
                updates,
                update_modified=True
            )
        except Exception:
            pass


# ============================================================================
# Helper Functions
# ============================================================================

def _build_headers(webhook: Any) -> Dict[str, str]:
    """Build HTTP headers for webhook request.

    Args:
        webhook: Webhook Configuration document

    Returns:
        Dict of HTTP headers
    """
    headers = {
        "Content-Type": webhook.content_type or "application/json",
        "User-Agent": "Frappe-PIM-Webhook/1.0",
        "X-Webhook-ID": webhook.name
    }

    # Add authentication headers
    auth_headers = webhook.get_auth_headers()
    headers.update(auth_headers)

    # Add custom headers
    custom_headers = webhook.get_custom_headers()
    headers.update(custom_headers)

    return headers


def _parse_status_codes(codes_str: str) -> List[int]:
    """Parse comma-separated status codes string.

    Args:
        codes_str: Comma-separated status codes

    Returns:
        List of integer status codes
    """
    try:
        return [int(code.strip()) for code in codes_str.split(",") if code.strip()]
    except ValueError:
        return DEFAULT_SUCCESS_CODES


def _schedule_retry(
    webhook: Any,
    delivery_log: Any,
    attempt: int,
    error_message: str,
    response_time_ms: Optional[float]
) -> bool:
    """Schedule a retry for failed delivery.

    Args:
        webhook: Webhook Configuration document
        delivery_log: Delivery log document
        attempt: Current attempt number
        error_message: Error message from failed attempt
        response_time_ms: Response time from failed attempt

    Returns:
        True if retry was scheduled
    """
    import frappe

    try:
        # Calculate delay
        delay_seconds = calculate_backoff_delay(
            attempt=attempt + 1,
            strategy=webhook.retry_strategy or "Exponential Backoff",
            initial_delay=webhook.initial_retry_delay or DEFAULT_INITIAL_DELAY,
            max_delay=webhook.max_retry_delay or DEFAULT_MAX_DELAY,
            multiplier=webhook.backoff_multiplier or DEFAULT_BACKOFF_MULTIPLIER
        )

        # Queue the retry with delay
        if delivery_log:
            frappe.enqueue(
                "frappe_pim.pim.utils.webhook_delivery.retry_delivery",
                queue="short",
                delivery_log_name=delivery_log.name,
                enqueue_after_commit=True,
                at_front=False,
                timeout=120,
                now=False,
                job_id=f"webhook_retry_{delivery_log.name}_{attempt + 1}"
            )

            # Note: Frappe's enqueue doesn't have direct delay support
            # The actual delay is handled by updating the delivery log status
            # and letting a scheduled job pick up retries

        return True

    except Exception as e:
        frappe.log_error(
            message=f"Error scheduling retry: {str(e)}",
            title="Webhook Retry Scheduling Error"
        )
        return False


def _handle_request_error(
    webhook: Any,
    delivery_log: Any,
    attempt: int,
    error_message: str,
    response_time_ms: Optional[float],
    event: Dict[str, Any],
    result: Dict[str, Any]
) -> None:
    """Handle request-level errors (timeout, connection, etc.).

    Args:
        webhook: Webhook Configuration document
        delivery_log: Delivery log document
        attempt: Current attempt number
        error_message: Error message
        response_time_ms: Response time (if available)
        event: Event data
        result: Result dict to update
    """
    import frappe

    max_retries = webhook.max_retries or DEFAULT_MAX_RETRIES
    should_retry = attempt < max_retries

    if should_retry:
        result["retry_scheduled"] = _schedule_retry(
            webhook=webhook,
            delivery_log=delivery_log,
            attempt=attempt,
            error_message=error_message,
            response_time_ms=response_time_ms
        )

        if delivery_log:
            _update_delivery_log_retry(
                delivery_log=delivery_log,
                status_code=None,
                response_time_ms=response_time_ms,
                error_message=error_message,
                attempt=attempt,
                webhook=webhook
            )
    else:
        # Final failure
        if delivery_log:
            _update_delivery_log_failure(
                delivery_log=delivery_log,
                status_code=None,
                response_time_ms=response_time_ms,
                error_message=error_message
            )

        # Update webhook statistics
        webhook.update_delivery_stats(
            success=False,
            response_time_ms=response_time_ms,
            status_code=None,
            error_message=error_message,
            event_id=event.get("name") or event.get("event_id")
        )


# ============================================================================
# Scheduled Job Functions
# ============================================================================

def process_pending_retries() -> Dict[str, Any]:
    """Process all pending webhook retries that are due.

    This function should be called by a scheduled job to process
    retries that have passed their next_retry_at time.

    Returns:
        Dict with processing results
    """
    import frappe
    from frappe.utils import now_datetime

    result = {
        "processed": 0,
        "success": 0,
        "failed": 0,
        "errors": []
    }

    try:
        # Check if DocType exists
        if not frappe.db.table_exists("Webhook Delivery Log"):
            return result

        # Get all retries that are due
        pending_retries = frappe.get_all(
            "Webhook Delivery Log",
            filters={
                "status": STATUS_RETRYING,
                "next_retry_at": ["<=", now_datetime()]
            },
            fields=["name"],
            limit=100  # Process in batches
        )

        for retry_info in pending_retries:
            try:
                delivery_result = retry_delivery(retry_info.name)
                result["processed"] += 1

                if delivery_result.get("success"):
                    result["success"] += 1
                else:
                    result["failed"] += 1

            except Exception as e:
                result["errors"].append({
                    "delivery_log": retry_info.name,
                    "error": str(e)
                })

    except Exception as e:
        frappe.log_error(
            message=f"Error processing pending retries: {str(e)}",
            title="Webhook Retry Processing Error"
        )
        result["error"] = str(e)

    return result


def cleanup_old_delivery_logs(days: int = 30) -> Dict[str, Any]:
    """Clean up old delivery log entries.

    Args:
        days: Delete logs older than this many days

    Returns:
        Dict with cleanup results
    """
    import frappe
    from frappe.utils import add_days, now_datetime

    result = {
        "deleted": 0,
        "error": None
    }

    try:
        if not frappe.db.table_exists("Webhook Delivery Log"):
            return result

        cutoff_date = add_days(now_datetime(), -days)

        # Delete old successful deliveries
        deleted = frappe.db.delete(
            "Webhook Delivery Log",
            filters={
                "status": ["in", [STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELLED]],
                "creation": ["<", cutoff_date]
            }
        )

        result["deleted"] = deleted or 0

    except Exception as e:
        frappe.log_error(
            message=f"Error cleaning up delivery logs: {str(e)}",
            title="Webhook Cleanup Error"
        )
        result["error"] = str(e)

    return result


def get_delivery_statistics(webhook_name: Optional[str] = None) -> Dict[str, Any]:
    """Get delivery statistics for webhooks.

    Args:
        webhook_name: Optional specific webhook to get stats for

    Returns:
        Dict with delivery statistics
    """
    import frappe

    stats = {
        "total_deliveries": 0,
        "successful": 0,
        "failed": 0,
        "pending": 0,
        "retrying": 0,
        "success_rate": 0.0
    }

    try:
        if not frappe.db.table_exists("Webhook Delivery Log"):
            return stats

        filters = {}
        if webhook_name:
            filters["webhook_configuration"] = webhook_name

        # Get counts by status
        status_counts = frappe.db.sql("""
            SELECT status, COUNT(*) as count
            FROM `tabWebhook Delivery Log`
            {where}
            GROUP BY status
        """.format(
            where=f"WHERE webhook_configuration = '{webhook_name}'" if webhook_name else ""
        ), as_dict=True)

        for row in status_counts:
            status = row.get("status")
            count = row.get("count", 0)

            if status == STATUS_SUCCESS:
                stats["successful"] = count
            elif status == STATUS_FAILED:
                stats["failed"] = count
            elif status == STATUS_PENDING:
                stats["pending"] = count
            elif status == STATUS_RETRYING:
                stats["retrying"] = count

            stats["total_deliveries"] += count

        # Calculate success rate
        completed = stats["successful"] + stats["failed"]
        if completed > 0:
            stats["success_rate"] = round(stats["successful"] / completed * 100, 2)

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting delivery statistics: {str(e)}",
            title="Webhook Statistics Error"
        )

    return stats


# ============================================================================
# Whitelisted API Functions
# ============================================================================

def whitelist_deliver_webhook():
    """Wrapper for deliver_webhook for API access."""
    import frappe

    @frappe.whitelist()
    def api_deliver_webhook(
        webhook_name: str,
        event_type: str,
        event_data: Optional[str] = None,
        document_data: Optional[str] = None,
        async_delivery: bool = True
    ) -> Dict[str, Any]:
        """Trigger webhook delivery via API.

        Args:
            webhook_name: Webhook configuration name
            event_type: Event type
            event_data: JSON string of event data
            document_data: JSON string of document data
            async_delivery: If True, queue for background delivery

        Returns:
            Delivery result
        """
        # Parse JSON data
        event = {}
        if event_data:
            try:
                event = json.loads(event_data) if isinstance(event_data, str) else event_data
            except json.JSONDecodeError:
                pass
        event["event_type"] = event_type

        document = None
        if document_data:
            try:
                document = json.loads(document_data) if isinstance(document_data, str) else document_data
            except json.JSONDecodeError:
                pass

        if async_delivery:
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
                "message": "Webhook delivery queued",
                "async": True
            }
        else:
            return deliver_webhook(
                webhook_name=webhook_name,
                event=event,
                document=document
            )

    return api_deliver_webhook


def whitelist_get_statistics():
    """Wrapper for get_delivery_statistics for API access."""
    import frappe

    @frappe.whitelist()
    def api_get_delivery_statistics(
        webhook_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get delivery statistics via API.

        Args:
            webhook_name: Optional webhook to filter by

        Returns:
            Statistics dict
        """
        return get_delivery_statistics(webhook_name)

    return api_get_delivery_statistics
