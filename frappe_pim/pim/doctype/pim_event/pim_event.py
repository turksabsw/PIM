"""
PIM Event Controller
Event sourcing and audit trail for PIM system
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, List, Dict, Any
import json
from datetime import datetime


class PIMEvent(Document):
    def validate(self):
        self.validate_event_timestamp()
        self.validate_reference_document()
        self.validate_json_fields()
        self.set_event_summary()

    def validate_event_timestamp(self):
        """Ensure event_timestamp is set"""
        if not self.event_timestamp:
            self.event_timestamp = frappe.utils.now_datetime()

    def validate_reference_document(self):
        """Validate reference document exists"""
        if self.reference_doctype and self.reference_docname:
            if not frappe.db.exists(self.reference_doctype, self.reference_docname):
                # For deleted events, the document may not exist
                if self.event_type != "Deleted":
                    frappe.throw(
                        _("Reference document {0} {1} does not exist").format(
                            self.reference_doctype, self.reference_docname
                        ),
                        title=_("Invalid Reference")
                    )

    def validate_json_fields(self):
        """Validate JSON fields are valid JSON"""
        json_fields = ['old_value', 'new_value', 'changed_fields', 'event_metadata']
        for field in json_fields:
            value = getattr(self, field, None)
            if value and isinstance(value, str):
                try:
                    json.loads(value)
                except json.JSONDecodeError:
                    frappe.throw(
                        _("Field {0} must contain valid JSON").format(field),
                        title=_("Invalid JSON")
                    )

    def set_event_summary(self):
        """Auto-generate event summary if not provided"""
        if not self.event_summary:
            user = self.triggered_by or "System"
            if self.triggered_by:
                user = frappe.db.get_value("User", self.triggered_by, "full_name") or self.triggered_by

            self.event_summary = _("{0} {1} {2} ({3})").format(
                user,
                self.event_type.lower() if self.event_type else "modified",
                self.reference_doctype or "document",
                self.reference_docname or "unknown"
            )

    def before_insert(self):
        """Set defaults before insert"""
        if not self.triggered_by:
            self.triggered_by = frappe.session.user

        if not self.session_id:
            self.session_id = frappe.session.sid

        if not self.correlation_id:
            self.correlation_id = frappe.generate_hash(length=16)

    def after_insert(self):
        """Handle post-insert actions"""
        # Trigger webhook delivery if configured
        self.queue_webhook_delivery()

    def queue_webhook_delivery(self):
        """Queue webhook delivery for this event"""
        try:
            # Check if any webhooks are configured for this event type
            webhooks = frappe.get_all(
                "Webhook Configuration",
                filters={
                    "enabled": 1,
                    "doctype_triggers": ["like", f"%{self.reference_doctype}%"]
                },
                pluck="name"
            )

            if webhooks:
                frappe.enqueue(
                    "frappe_pim.pim.doctype.pim_event.pim_event.deliver_event_webhooks",
                    event_name=self.name,
                    queue="short"
                )
        except Exception:
            # Don't fail event creation if webhook queueing fails
            pass

    def mark_as_processed(self):
        """Mark event as processed"""
        self.processed = 1
        self.processed_at = frappe.utils.now_datetime()
        self.save(ignore_permissions=True)

    def mark_webhook_delivered(self, success: bool = True, error: Optional[str] = None):
        """Mark webhook delivery status"""
        self.delivery_attempts = (self.delivery_attempts or 0) + 1
        if success:
            self.webhook_delivered = 1
        elif error:
            self.last_delivery_error = error[:500]  # Truncate error message
        self.save(ignore_permissions=True)


# ============================================
# API Methods
# ============================================

@frappe.whitelist()
def create_pim_event(
    event_type: str,
    event_category: str,
    reference_doctype: str,
    reference_docname: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    changed_fields: Optional[str] = None,
    event_metadata: Optional[str] = None,
    source_system: Optional[str] = None,
    trigger_method: str = "Manual",
    severity: str = "Info",
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    golden_record: Optional[str] = None,
    parent_event: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    sequence_number: int = 0
) -> Dict[str, Any]:
    """Create a new PIM Event record

    Args:
        event_type: Type of event (Created, Updated, Deleted, etc.)
        event_category: Category of event (Product, Attribute, etc.)
        reference_doctype: DocType of the document
        reference_docname: Name of the document
        old_value: Previous value (JSON string)
        new_value: New value (JSON string)
        changed_fields: List of changed fields (JSON array)
        event_metadata: Additional metadata (JSON object)
        source_system: Source System name
        trigger_method: How the event was triggered
        severity: Event severity level
        channel: Channel context
        locale: Locale context
        golden_record: Associated golden record
        parent_event: Parent event for batch operations
        correlation_id: Correlation ID for tracing
        causation_id: ID of causing event
        batch_id: Batch operation ID
        sequence_number: Order within batch

    Returns:
        Dict with event name and status
    """
    try:
        event = frappe.get_doc({
            "doctype": "PIM Event",
            "event_type": event_type,
            "event_category": event_category,
            "reference_doctype": reference_doctype,
            "reference_docname": reference_docname,
            "event_timestamp": frappe.utils.now_datetime(),
            "old_value": old_value,
            "new_value": new_value,
            "changed_fields": changed_fields,
            "event_metadata": event_metadata,
            "source_system": source_system,
            "trigger_method": trigger_method,
            "severity": severity,
            "channel": channel,
            "locale": locale,
            "golden_record": golden_record,
            "parent_event": parent_event,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "batch_id": batch_id,
            "sequence_number": sequence_number,
            "triggered_by": frappe.session.user
        })
        event.insert(ignore_permissions=True)

        return {
            "success": True,
            "event_name": event.name,
            "correlation_id": event.correlation_id
        }
    except Exception as e:
        frappe.log_error(f"Error creating PIM Event: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


@frappe.whitelist()
def get_events(
    reference_doctype: Optional[str] = None,
    reference_docname: Optional[str] = None,
    event_type: Optional[str] = None,
    event_category: Optional[str] = None,
    triggered_by: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Get PIM events with filters

    Args:
        reference_doctype: Filter by DocType
        reference_docname: Filter by document name
        event_type: Filter by event type
        event_category: Filter by category
        triggered_by: Filter by user
        from_date: Start date filter
        to_date: End date filter
        limit: Maximum records to return
        offset: Records to skip

    Returns:
        List of event records
    """
    filters = {}

    if reference_doctype:
        filters["reference_doctype"] = reference_doctype
    if reference_docname:
        filters["reference_docname"] = reference_docname
    if event_type:
        filters["event_type"] = event_type
    if event_category:
        filters["event_category"] = event_category
    if triggered_by:
        filters["triggered_by"] = triggered_by
    if from_date:
        filters["event_timestamp"] = [">=", from_date]
    if to_date:
        if "event_timestamp" in filters:
            filters["event_timestamp"] = ["between", [from_date, to_date]]
        else:
            filters["event_timestamp"] = ["<=", to_date]

    return frappe.get_all(
        "PIM Event",
        filters=filters,
        fields=[
            "name", "event_type", "event_category", "event_timestamp",
            "reference_doctype", "reference_docname", "triggered_by",
            "trigger_method", "severity", "event_summary", "processed",
            "source_system", "channel", "locale", "correlation_id"
        ],
        order_by="event_timestamp desc",
        limit_page_length=min(limit, 500),
        limit_start=offset
    )


@frappe.whitelist()
def get_document_history(
    doctype: str,
    docname: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Get complete event history for a document

    Args:
        doctype: DocType of the document
        docname: Name of the document
        limit: Maximum events to return

    Returns:
        List of events in chronological order
    """
    return frappe.get_all(
        "PIM Event",
        filters={
            "reference_doctype": doctype,
            "reference_docname": docname
        },
        fields=[
            "name", "event_type", "event_category", "event_timestamp",
            "triggered_by", "trigger_method", "severity", "event_summary",
            "old_value", "new_value", "changed_fields", "source_system",
            "channel", "locale", "workflow_state", "correlation_id"
        ],
        order_by="event_timestamp asc",
        limit_page_length=min(limit, 1000)
    )


@frappe.whitelist()
def get_event_chain(correlation_id: str) -> List[Dict[str, Any]]:
    """Get all events in a correlation chain

    Args:
        correlation_id: Correlation ID to search for

    Returns:
        List of correlated events in chronological order
    """
    return frappe.get_all(
        "PIM Event",
        filters={"correlation_id": correlation_id},
        fields=[
            "name", "event_type", "event_category", "event_timestamp",
            "reference_doctype", "reference_docname", "triggered_by",
            "trigger_method", "event_summary", "causation_id",
            "sequence_number", "batch_id"
        ],
        order_by="event_timestamp asc, sequence_number asc"
    )


@frappe.whitelist()
def get_batch_events(batch_id: str) -> List[Dict[str, Any]]:
    """Get all events in a batch operation

    Args:
        batch_id: Batch ID to search for

    Returns:
        List of batch events in sequence order
    """
    return frappe.get_all(
        "PIM Event",
        filters={"batch_id": batch_id},
        fields=[
            "name", "event_type", "event_category", "event_timestamp",
            "reference_doctype", "reference_docname", "event_summary",
            "sequence_number", "processed", "severity"
        ],
        order_by="sequence_number asc"
    )


@frappe.whitelist()
def replay_event(event_name: str, reason: str = "") -> Dict[str, Any]:
    """Replay a PIM event (create new event based on original)

    Args:
        event_name: Name of the original event to replay
        reason: Reason for replaying the event

    Returns:
        Dict with new event name and status
    """
    if not frappe.has_permission("PIM Event", "write"):
        frappe.throw(_("You do not have permission to replay events"))

    original = frappe.get_doc("PIM Event", event_name)

    if not original.is_replayable:
        frappe.throw(_("This event cannot be replayed"))

    new_event = frappe.get_doc({
        "doctype": "PIM Event",
        "event_type": original.event_type,
        "event_category": original.event_category,
        "reference_doctype": original.reference_doctype,
        "reference_docname": original.reference_docname,
        "event_timestamp": frappe.utils.now_datetime(),
        "old_value": original.old_value,
        "new_value": original.new_value,
        "changed_fields": original.changed_fields,
        "event_metadata": original.event_metadata,
        "source_system": original.source_system,
        "trigger_method": "System",
        "severity": original.severity,
        "channel": original.channel,
        "locale": original.locale,
        "replayed": 1,
        "original_event": event_name,
        "replay_reason": reason,
        "correlation_id": original.correlation_id,
        "causation_id": event_name
    })
    new_event.insert(ignore_permissions=True)

    return {
        "success": True,
        "original_event": event_name,
        "new_event": new_event.name
    }


@frappe.whitelist()
def mark_events_processed(event_names: str) -> Dict[str, Any]:
    """Mark multiple events as processed

    Args:
        event_names: JSON array of event names

    Returns:
        Dict with count of processed events
    """
    try:
        names = json.loads(event_names) if isinstance(event_names, str) else event_names
        count = 0

        for name in names:
            frappe.db.set_value(
                "PIM Event", name,
                {
                    "processed": 1,
                    "processed_at": frappe.utils.now_datetime()
                },
                update_modified=False
            )
            count += 1

        frappe.db.commit()
        return {"success": True, "count": count}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_event_statistics(
    reference_doctype: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
) -> Dict[str, Any]:
    """Get event statistics for reporting

    Args:
        reference_doctype: Filter by DocType
        from_date: Start date
        to_date: End date

    Returns:
        Dict with event statistics
    """
    filters = {}
    if reference_doctype:
        filters["reference_doctype"] = reference_doctype
    if from_date:
        filters["event_timestamp"] = [">=", from_date]
    if to_date:
        if "event_timestamp" in filters:
            filters["event_timestamp"] = ["between", [from_date, to_date]]
        else:
            filters["event_timestamp"] = ["<=", to_date]

    # Get counts by event type
    type_counts = frappe.db.sql("""
        SELECT event_type, COUNT(*) as count
        FROM `tabPIM Event`
        WHERE 1=1
        {type_filter}
        {date_filter}
        GROUP BY event_type
        ORDER BY count DESC
    """.format(
        type_filter=f"AND reference_doctype = '{reference_doctype}'" if reference_doctype else "",
        date_filter=f"AND event_timestamp >= '{from_date}'" if from_date else ""
    ), as_dict=True)

    # Get counts by category
    category_counts = frappe.db.sql("""
        SELECT event_category, COUNT(*) as count
        FROM `tabPIM Event`
        WHERE 1=1
        {type_filter}
        {date_filter}
        GROUP BY event_category
        ORDER BY count DESC
    """.format(
        type_filter=f"AND reference_doctype = '{reference_doctype}'" if reference_doctype else "",
        date_filter=f"AND event_timestamp >= '{from_date}'" if from_date else ""
    ), as_dict=True)

    # Get total count
    total_count = frappe.db.count("PIM Event", filters)
    unprocessed_count = frappe.db.count("PIM Event", {**filters, "processed": 0})

    return {
        "total_events": total_count,
        "unprocessed_events": unprocessed_count,
        "by_type": {r.event_type: r.count for r in type_counts},
        "by_category": {r.event_category: r.count for r in category_counts}
    }


@frappe.whitelist()
def purge_old_events(days: int = 365, dry_run: bool = True) -> Dict[str, Any]:
    """Purge old PIM events (System Manager only)

    Args:
        days: Delete events older than this many days
        dry_run: If True, only return count without deleting

    Returns:
        Dict with deletion status and count
    """
    if not frappe.has_permission("PIM Event", "delete"):
        frappe.throw(_("You do not have permission to purge events"))

    if days < 30:
        frappe.throw(_("Cannot purge events less than 30 days old"))

    cutoff_date = frappe.utils.add_days(frappe.utils.now(), -days)

    count = frappe.db.count("PIM Event", {
        "event_timestamp": ["<", cutoff_date],
        "processed": 1,
        "is_replayable": 0
    })

    if dry_run:
        return {
            "dry_run": True,
            "events_to_delete": count,
            "cutoff_date": str(cutoff_date)
        }

    # Actual deletion
    frappe.db.delete("PIM Event", {
        "event_timestamp": ["<", cutoff_date],
        "processed": 1,
        "is_replayable": 0
    })
    frappe.db.commit()

    return {
        "success": True,
        "deleted_count": count,
        "cutoff_date": str(cutoff_date)
    }


def deliver_event_webhooks(event_name: str):
    """Deliver webhooks for an event (called from background job)

    Args:
        event_name: Name of the PIM Event to deliver webhooks for
    """
    try:
        event = frappe.get_doc("PIM Event", event_name)

        # Find matching webhook configurations
        webhooks = frappe.get_all(
            "Webhook Configuration",
            filters={
                "enabled": 1
            },
            fields=["name", "url", "headers", "auth_type"]
        )

        if not webhooks:
            return

        # Prepare payload
        payload = {
            "event_name": event.name,
            "event_type": event.event_type,
            "event_category": event.event_category,
            "event_timestamp": str(event.event_timestamp),
            "reference_doctype": event.reference_doctype,
            "reference_docname": event.reference_docname,
            "old_value": json.loads(event.old_value) if event.old_value else None,
            "new_value": json.loads(event.new_value) if event.new_value else None,
            "triggered_by": event.triggered_by,
            "correlation_id": event.correlation_id
        }

        # Deliver to each webhook (simplified - actual implementation should use webhook_delivery module)
        success = True
        error = None

        for webhook in webhooks:
            try:
                import requests
                response = requests.post(
                    webhook.url,
                    json=payload,
                    timeout=30
                )
                if response.status_code >= 400:
                    error = f"HTTP {response.status_code}"
                    success = False
            except Exception as e:
                error = str(e)
                success = False

        event.mark_webhook_delivered(success, error)

    except Exception as e:
        frappe.log_error(f"Webhook delivery failed for {event_name}: {str(e)}")


# ============================================
# Helper Functions
# ============================================

def create_event_for_doc(
    doc: Document,
    event_type: str,
    old_doc: Optional[Document] = None,
    **kwargs
) -> Optional[str]:
    """Helper function to create a PIM Event for a document change

    Args:
        doc: The document that changed
        event_type: Type of event
        old_doc: Previous version of document (for updates)
        **kwargs: Additional event fields

    Returns:
        Event name if created, None otherwise
    """
    try:
        old_value = None
        new_value = None
        changed_fields = None

        if event_type == "Updated" and old_doc:
            # Calculate changed fields
            changes = []
            old_dict = old_doc.as_dict() if hasattr(old_doc, 'as_dict') else old_doc
            new_dict = doc.as_dict() if hasattr(doc, 'as_dict') else doc

            for key in new_dict:
                if key.startswith('_') or key in ['modified', 'modified_by']:
                    continue
                if old_dict.get(key) != new_dict.get(key):
                    changes.append(key)

            if changes:
                changed_fields = json.dumps(changes)
                old_value = json.dumps({k: old_dict.get(k) for k in changes})
                new_value = json.dumps({k: new_dict.get(k) for k in changes})
        elif event_type == "Created":
            new_dict = doc.as_dict() if hasattr(doc, 'as_dict') else doc
            # Filter out internal fields
            filtered = {k: v for k, v in new_dict.items()
                       if not k.startswith('_') and k not in ['docstatus', 'idx']}
            new_value = json.dumps(filtered, default=str)
        elif event_type == "Deleted":
            old_dict = doc.as_dict() if hasattr(doc, 'as_dict') else doc
            filtered = {k: v for k, v in old_dict.items()
                       if not k.startswith('_') and k not in ['docstatus', 'idx']}
            old_value = json.dumps(filtered, default=str)

        # Determine category based on doctype
        category_map = {
            "Product Master": "Product",
            "Product Variant": "Product",
            "Attribute": "Attribute",
            "Product Attribute Value": "Attribute",
            "Taxonomy Node": "Classification",
            "Product Classification": "Classification",
            "Digital Asset": "Asset",
            "Channel": "Channel",
            "Golden Record": "GoldenRecord",
            "AI Enrichment Job": "AI",
            "AI Approval Queue": "AI"
        }
        event_category = category_map.get(doc.doctype, "System")

        result = create_pim_event(
            event_type=event_type,
            event_category=event_category,
            reference_doctype=doc.doctype,
            reference_docname=doc.name,
            old_value=old_value,
            new_value=new_value,
            changed_fields=changed_fields,
            trigger_method=kwargs.get("trigger_method", "Manual"),
            severity=kwargs.get("severity", "Info"),
            channel=kwargs.get("channel"),
            locale=kwargs.get("locale"),
            source_system=kwargs.get("source_system"),
            golden_record=kwargs.get("golden_record"),
            correlation_id=kwargs.get("correlation_id"),
            batch_id=kwargs.get("batch_id"),
            sequence_number=kwargs.get("sequence_number", 0)
        )

        return result.get("event_name") if result.get("success") else None

    except Exception as e:
        frappe.log_error(f"Error creating PIM Event for {doc.doctype} {doc.name}: {str(e)}")
        return None
