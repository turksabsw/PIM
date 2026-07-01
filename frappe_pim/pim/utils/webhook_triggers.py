"""
Webhook Triggers for PIM Events

This module provides hook handlers that trigger webhook delivery
when PIM documents are created, updated, or deleted.

These functions are called from hooks.py doc_events and integrate with:
    - PIM Event (event sourcing)
    - Webhook Configuration (delivery settings)
    - Webhook Delivery (delivery execution)

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from typing import Optional, Dict, Any, List


# ============================================================================
# Constants
# ============================================================================

# Map DocTypes to their webhook event type prefixes
DOCTYPE_EVENT_PREFIX_MAP = {
    "Product Master": "Product",
    "Product Variant": "ProductVariant",
    "Golden Record": "GoldenRecord",
    "Taxonomy Node": "TaxonomyNode",
    "Attribute": "Attribute",
    "Attribute Group": "AttributeGroup",
    "Product Family": "ProductFamily",
    "Digital Asset": "DigitalAsset",
    "Sales Channel": "SalesChannel",
    "AI Enrichment Job": "AIEnrichment",
}

# Event types
EVENT_CREATED = "Created"
EVENT_UPDATED = "Updated"
EVENT_DELETED = "Deleted"


# ============================================================================
# Webhook Trigger Functions for Document Events
# ============================================================================

def trigger_webhook_on_insert(doc, method: Optional[str] = None) -> None:
    """Trigger webhooks after a PIM document is inserted.

    This function is called from hooks.py doc_events after_insert.
    It queues webhook delivery for all matching webhook configurations.

    Args:
        doc: The Frappe document that was inserted
        method: The hook method name (unused)
    """
    _trigger_webhook_for_event(doc, EVENT_CREATED)


def trigger_webhook_on_update(doc, method: Optional[str] = None) -> None:
    """Trigger webhooks after a PIM document is updated.

    This function is called from hooks.py doc_events on_update.
    It queues webhook delivery for all matching webhook configurations.

    Args:
        doc: The Frappe document that was updated
        method: The hook method name (unused)
    """
    # Skip if document is new (insert event handles this)
    if hasattr(doc, 'is_new') and doc.is_new():
        return

    _trigger_webhook_for_event(doc, EVENT_UPDATED)


def trigger_webhook_on_trash(doc, method: Optional[str] = None) -> None:
    """Trigger webhooks before a PIM document is deleted.

    This function is called from hooks.py doc_events on_trash.
    It queues webhook delivery for all matching webhook configurations.

    Args:
        doc: The Frappe document being deleted
        method: The hook method name (unused)
    """
    _trigger_webhook_for_event(doc, EVENT_DELETED)


# ============================================================================
# PIM Event Webhook Trigger (for PIM Event DocType)
# ============================================================================

def trigger_webhook_on_pim_event_insert(doc, method: Optional[str] = None) -> None:
    """Trigger webhooks when a PIM Event is created.

    This is an alternative approach where webhooks are triggered
    when PIM Events are created rather than on document events directly.
    This ensures webhooks are only sent after successful event creation.

    Args:
        doc: The PIM Event document
        method: The hook method name (unused)
    """
    import frappe

    try:
        # Build event type from PIM Event fields
        event_type = _build_pim_event_type(doc)

        # Build event data from PIM Event
        event_data = _build_event_data_from_pim_event(doc)

        # Build document data if reference exists
        document_data = _get_reference_document_data(doc)

        # Trigger webhook delivery
        _deliver_webhooks_async(
            event_type=event_type,
            event_data=event_data,
            document_data=document_data
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error triggering webhook for PIM Event {doc.name}: {str(e)}",
            title="Webhook Trigger Error"
        )


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _trigger_webhook_for_event(doc, event_type: str) -> None:
    """Internal function to trigger webhooks for a document event.

    Args:
        doc: The Frappe document
        event_type: Event type (Created, Updated, Deleted)
    """
    import frappe

    try:
        # Check if this DocType should trigger webhooks
        if doc.doctype not in DOCTYPE_EVENT_PREFIX_MAP:
            return

        # Build webhook event type (e.g., "Product.Created")
        prefix = DOCTYPE_EVENT_PREFIX_MAP.get(doc.doctype, doc.doctype.replace(" ", ""))
        webhook_event_type = f"{prefix}.{event_type}"

        # Build event data
        event_data = _build_event_data(doc, event_type)

        # Build document data
        document_data = _build_document_data(doc)

        # Trigger webhook delivery
        _deliver_webhooks_async(
            event_type=webhook_event_type,
            event_data=event_data,
            document_data=document_data
        )

    except Exception as e:
        # Log error but don't interrupt document processing
        frappe.log_error(
            message=f"Error triggering webhook for {doc.doctype}/{doc.name}: {str(e)}",
            title="Webhook Trigger Error"
        )


def _build_event_data(doc, event_type: str) -> Dict[str, Any]:
    """Build event data dictionary from a document.

    Args:
        doc: The Frappe document
        event_type: Event type

    Returns:
        Dict containing event metadata
    """
    import frappe
    from frappe.utils import now_datetime

    event_data = {
        "event_type": f"{DOCTYPE_EVENT_PREFIX_MAP.get(doc.doctype, doc.doctype)}.{event_type}",
        "event_timestamp": str(now_datetime()),
        "reference_doctype": doc.doctype,
        "reference_name": doc.name,
        "triggered_by": frappe.session.user if hasattr(frappe, 'session') else "System",
        "trigger_method": "Document Hook"
    }

    # Add doctype-specific identifiers
    if doc.doctype == "Product Master":
        event_data["sku"] = getattr(doc, 'sku', None)
        event_data["product_name"] = getattr(doc, 'product_name', None)
    elif doc.doctype == "Product Variant":
        event_data["variant_sku"] = getattr(doc, 'variant_sku', None)
        event_data["parent_product"] = getattr(doc, 'parent_product', None)
    elif doc.doctype == "Golden Record":
        event_data["entity_type"] = getattr(doc, 'entity_type', None)
        event_data["source_system"] = getattr(doc, 'source_system', None)
    elif doc.doctype == "Taxonomy Node":
        event_data["taxonomy"] = getattr(doc, 'taxonomy', None)
        event_data["node_code"] = getattr(doc, 'node_code', None)

    return event_data


def _build_document_data(doc) -> Dict[str, Any]:
    """Build document data dictionary for webhook payload.

    Args:
        doc: The Frappe document

    Returns:
        Dict containing document fields
    """
    # Exclude internal fields
    exclude_fields = {
        '_comments', '_liked_by', '_user_tags', '_assign',
        '__last_sync_hash', '__islocal', '__unsaved',
        '__run_link_triggers', '_previous_doc'
    }

    try:
        if hasattr(doc, 'as_dict'):
            doc_dict = doc.as_dict()
            return {
                k: v for k, v in doc_dict.items()
                if not k.startswith('_') or k in ('_user_tags',)
                and k not in exclude_fields
            }
        return {}
    except Exception:
        return {"name": doc.name, "doctype": doc.doctype}


def _build_pim_event_type(pim_event_doc) -> str:
    """Build webhook event type from a PIM Event document.

    Args:
        pim_event_doc: The PIM Event document

    Returns:
        Event type string (e.g., "Product.Created")
    """
    reference_doctype = getattr(pim_event_doc, 'reference_doctype', '')
    event_type = getattr(pim_event_doc, 'event_type', 'Unknown')

    # Get prefix from map or generate from doctype
    prefix = DOCTYPE_EVENT_PREFIX_MAP.get(
        reference_doctype,
        reference_doctype.replace(" ", "") if reference_doctype else "Unknown"
    )

    return f"{prefix}.{event_type}"


def _build_event_data_from_pim_event(pim_event_doc) -> Dict[str, Any]:
    """Build event data from a PIM Event document.

    Args:
        pim_event_doc: The PIM Event document

    Returns:
        Dict containing event data
    """
    import json

    event_data = {
        "event_id": pim_event_doc.name,
        "event_type": _build_pim_event_type(pim_event_doc),
        "event_timestamp": str(getattr(pim_event_doc, 'event_timestamp', '')),
        "event_category": getattr(pim_event_doc, 'event_category', ''),
        "reference_doctype": getattr(pim_event_doc, 'reference_doctype', ''),
        "reference_name": getattr(pim_event_doc, 'reference_docname', ''),
        "triggered_by": getattr(pim_event_doc, 'triggered_by', ''),
        "trigger_method": getattr(pim_event_doc, 'trigger_method', ''),
        "severity": getattr(pim_event_doc, 'severity', 'Info'),
        "correlation_id": getattr(pim_event_doc, 'correlation_id', ''),
        "batch_id": getattr(pim_event_doc, 'batch_id', ''),
        "sequence_number": getattr(pim_event_doc, 'sequence_number', 0)
    }

    # Parse changed fields if available
    changed_fields = getattr(pim_event_doc, 'changed_fields', None)
    if changed_fields:
        try:
            event_data["changed_fields"] = json.loads(changed_fields)
        except (json.JSONDecodeError, TypeError):
            event_data["changed_fields"] = []

    return event_data


def _get_reference_document_data(pim_event_doc) -> Optional[Dict[str, Any]]:
    """Get document data from PIM Event reference.

    Args:
        pim_event_doc: The PIM Event document

    Returns:
        Dict containing reference document data, or None
    """
    import frappe
    import json

    # First try to get new_value from PIM Event (contains document snapshot)
    new_value = getattr(pim_event_doc, 'new_value', None)
    if new_value:
        try:
            return json.loads(new_value)
        except (json.JSONDecodeError, TypeError):
            pass

    # Fall back to fetching the reference document
    reference_doctype = getattr(pim_event_doc, 'reference_doctype', '')
    reference_name = getattr(pim_event_doc, 'reference_docname', '')

    if reference_doctype and reference_name:
        try:
            ref_doc = frappe.get_doc(reference_doctype, reference_name)
            return _build_document_data(ref_doc)
        except Exception:
            pass

    return None


def _deliver_webhooks_async(
    event_type: str,
    event_data: Dict[str, Any],
    document_data: Optional[Dict[str, Any]] = None
) -> None:
    """Queue webhook delivery for an event.

    Args:
        event_type: The webhook event type
        event_data: Event metadata
        document_data: Document data for payload
    """
    import frappe

    try:
        # Import here to avoid circular imports
        from frappe_pim.pim.utils.webhook_delivery import deliver_event_webhooks

        # Check if webhook delivery is enabled (site config setting)
        if not frappe.conf.get("pim_webhooks_enabled", True):
            return

        # Queue the webhook delivery
        frappe.enqueue(
            "frappe_pim.pim.utils.webhook_delivery.deliver_event_webhooks",
            queue="short",
            event_type=event_type,
            event_data=event_data,
            document_data=document_data,
            async_delivery=True,
            timeout=120,
            enqueue_after_commit=True
        )

    except ImportError:
        # Webhook delivery module not available
        pass
    except Exception as e:
        frappe.log_error(
            message=f"Error queuing webhook delivery for {event_type}: {str(e)}",
            title="Webhook Queue Error"
        )


# ============================================================================
# Scheduled Job Functions
# ============================================================================

def process_webhook_retries() -> Dict[str, Any]:
    """Process pending webhook delivery retries.

    This function is called by the scheduler to process
    webhooks that need to be retried.

    Returns:
        Dict with processing results
    """
    try:
        from frappe_pim.pim.utils.webhook_delivery import process_pending_retries
        return process_pending_retries()
    except ImportError:
        return {"error": "Webhook delivery module not available"}
    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error processing webhook retries: {str(e)}",
            title="Webhook Retry Error"
        )
        return {"error": str(e)}


def cleanup_webhook_logs(days: int = 30) -> Dict[str, Any]:
    """Clean up old webhook delivery logs.

    Args:
        days: Delete logs older than this many days

    Returns:
        Dict with cleanup results
    """
    try:
        from frappe_pim.pim.utils.webhook_delivery import cleanup_old_delivery_logs
        return cleanup_old_delivery_logs(days=days)
    except ImportError:
        return {"error": "Webhook delivery module not available"}
    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error cleaning up webhook logs: {str(e)}",
            title="Webhook Cleanup Error"
        )
        return {"error": str(e)}
