"""
PIM Sync Queue Controller
Queue-based sync operations for bidirectional ERPNext integration
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, time_diff_in_seconds


class PIMSyncQueue(Document):

    def validate(self):
        self.validate_document_exists()
        self.set_defaults()

    def validate_document_exists(self):
        """Ensure the referenced document exists"""
        if self.doctype_name and self.document_name:
            if not frappe.db.exists(self.doctype_name, self.document_name):
                frappe.throw(
                    _("Document {0} of type {1} does not exist").format(
                        self.document_name, self.doctype_name
                    ),
                    title=_("Document Not Found")
                )

    def set_defaults(self):
        """Set default values"""
        if not self.created_by_user:
            self.created_by_user = frappe.session.user

        if self.max_retries is None:
            self.max_retries = 3

        if self.priority is None:
            self.priority = 0

    def before_insert(self):
        """Before insert - check for duplicate pending entries"""
        self.check_duplicate_pending()

    def check_duplicate_pending(self):
        """Check for existing pending entry for same document"""
        existing = frappe.db.exists(
            "PIM Sync Queue",
            {
                "doctype_name": self.doctype_name,
                "document_name": self.document_name,
                "sync_direction": self.sync_direction,
                "status": ["in", ["Pending", "Processing"]],
                "name": ["!=", self.name or ""]
            }
        )

        if existing:
            # Update priority if new entry has higher priority
            existing_priority = frappe.db.get_value(
                "PIM Sync Queue", existing, "priority"
            )
            if self.priority > (existing_priority or 0):
                frappe.db.set_value(
                    "PIM Sync Queue", existing, "priority", self.priority
                )
                frappe.msgprint(
                    _("Updated priority of existing sync entry {0}").format(existing),
                    indicator="blue"
                )

            # Merge payload if this has new data
            if self.payload:
                existing_payload = frappe.db.get_value(
                    "PIM Sync Queue", existing, "payload"
                )
                try:
                    existing_data = json.loads(existing_payload) if existing_payload else {}
                    new_data = json.loads(self.payload) if isinstance(self.payload, str) else self.payload
                    merged = {**existing_data, **new_data}
                    frappe.db.set_value(
                        "PIM Sync Queue", existing, "payload", json.dumps(merged)
                    )
                except (json.JSONDecodeError, TypeError):
                    pass

            frappe.throw(
                _("Pending sync entry already exists: {0}").format(existing),
                title=_("Duplicate Entry")
            )

    def on_update(self):
        """After update - handle status changes"""
        if self.has_value_changed("status"):
            self.handle_status_change()

    def handle_status_change(self):
        """Handle actions based on status transitions"""
        if self.status == "Processing":
            if not self.started_at:
                self.db_set("started_at", now_datetime())

        elif self.status == "Completed":
            now = now_datetime()
            self.db_set("completed_at", now)
            if self.started_at:
                diff_seconds = time_diff_in_seconds(now, self.started_at)
                self.db_set("processing_time_ms", int(diff_seconds * 1000))

        elif self.status == "Failed":
            now = now_datetime()
            self.db_set("completed_at", now)
            if self.started_at:
                diff_seconds = time_diff_in_seconds(now, self.started_at)
                self.db_set("processing_time_ms", int(diff_seconds * 1000))

    def mark_processing(self, job_id=None):
        """Mark this entry as processing

        Args:
            job_id: Background job ID for tracking
        """
        self.db_set({
            "status": "Processing",
            "started_at": now_datetime(),
            "job_id": job_id
        })

    def mark_completed(self, result_message=None, erp_document=None):
        """Mark this entry as completed

        Args:
            result_message: Success message
            erp_document: Linked ERP document name
        """
        now = now_datetime()
        updates = {
            "status": "Completed",
            "completed_at": now,
            "result_message": result_message
        }

        if erp_document:
            updates["erp_document"] = erp_document

        if self.started_at:
            diff_seconds = time_diff_in_seconds(now, self.started_at)
            updates["processing_time_ms"] = int(diff_seconds * 1000)

        self.db_set(updates)

    def mark_failed(self, error_message, error_traceback=None):
        """Mark this entry as failed

        Args:
            error_message: Error description
            error_traceback: Full traceback string
        """
        now = now_datetime()
        new_retry_count = (self.retry_count or 0) + 1

        updates = {
            "status": "Failed",
            "completed_at": now,
            "error_message": error_message,
            "error_traceback": error_traceback,
            "retry_count": new_retry_count
        }

        if self.started_at:
            diff_seconds = time_diff_in_seconds(now, self.started_at)
            updates["processing_time_ms"] = int(diff_seconds * 1000)

        self.db_set(updates)

        # Check if should be moved to dead letter
        if new_retry_count >= (self.max_retries or 3):
            frappe.publish_realtime(
                event="pim_sync_dead_letter",
                message={
                    "sync_queue": self.name,
                    "doctype_name": self.doctype_name,
                    "document_name": self.document_name,
                    "error": error_message
                },
                user=self.created_by_user
            )

    def retry(self):
        """Reset entry for retry processing"""
        if self.status != "Failed":
            frappe.throw(
                _("Only failed entries can be retried"),
                title=_("Invalid Action")
            )

        if (self.retry_count or 0) >= (self.max_retries or 3):
            frappe.throw(
                _("Maximum retry count ({0}) exceeded").format(self.max_retries),
                title=_("Max Retries Exceeded")
            )

        self.db_set({
            "status": "Pending",
            "started_at": None,
            "completed_at": None,
            "processing_time_ms": None,
            "error_message": None,
            "error_traceback": None,
            "job_id": None
        })

        return True

    def cancel_sync(self, reason=None):
        """Cancel this sync entry

        Args:
            reason: Reason for cancellation
        """
        if self.status not in ["Pending", "Failed"]:
            frappe.throw(
                _("Only pending or failed entries can be cancelled"),
                title=_("Invalid Action")
            )

        self.db_set({
            "status": "Cancelled",
            "result_message": reason or "Manually cancelled"
        })

    def can_process(self):
        """Check if this entry can be processed

        Returns:
            bool: True if entry can be processed
        """
        if self.status != "Pending":
            return False

        # Check scheduled time
        if self.scheduled_at:
            from frappe.utils import get_datetime
            if get_datetime(self.scheduled_at) > now_datetime():
                return False

        # Check retry count
        if (self.retry_count or 0) >= (self.max_retries or 3):
            return False

        return True

    def set_conflict(self, conflict_details, resolution=None):
        """Record a conflict during sync

        Args:
            conflict_details: Dict with conflict information
            resolution: How the conflict was resolved
        """
        self.db_set({
            "has_conflict": 1,
            "conflict_details": json.dumps(conflict_details) if isinstance(conflict_details, dict) else conflict_details,
            "conflict_resolution": resolution
        })


# Module-level helper functions

def queue_sync_entry(doctype_name, document_name, sync_direction="PIM to ERP",
                     sync_action="Update", priority=0, payload=None, changed_fields=None):
    """Create a new sync queue entry

    Args:
        doctype_name: DocType being synced
        document_name: Document name being synced
        sync_direction: "PIM to ERP" or "ERP to PIM"
        sync_action: "Create", "Update", or "Delete"
        priority: Higher = more urgent (default 0)
        payload: Optional JSON payload with sync data
        changed_fields: Optional list of changed field names

    Returns:
        PIM Sync Queue document or None if duplicate exists
    """
    # Check for existing pending entry
    existing = frappe.db.exists(
        "PIM Sync Queue",
        {
            "doctype_name": doctype_name,
            "document_name": document_name,
            "sync_direction": sync_direction,
            "status": ["in", ["Pending", "Processing"]]
        }
    )

    if existing:
        # Update existing entry if higher priority
        existing_priority = frappe.db.get_value(
            "PIM Sync Queue", existing, "priority"
        )
        if priority > (existing_priority or 0):
            frappe.db.set_value("PIM Sync Queue", existing, "priority", priority)

        # Merge changed fields
        if changed_fields:
            existing_fields = frappe.db.get_value(
                "PIM Sync Queue", existing, "changed_fields"
            ) or ""
            all_fields = set(existing_fields.split(",")) if existing_fields else set()
            all_fields.update(changed_fields if isinstance(changed_fields, list) else [changed_fields])
            frappe.db.set_value(
                "PIM Sync Queue", existing, "changed_fields",
                ",".join(filter(None, all_fields))
            )

        return frappe.get_doc("PIM Sync Queue", existing)

    # Create new entry
    doc = frappe.new_doc("PIM Sync Queue")
    doc.doctype_name = doctype_name
    doc.document_name = document_name
    doc.sync_direction = sync_direction
    doc.sync_action = sync_action
    doc.priority = priority
    doc.created_by_user = frappe.session.user

    if payload:
        doc.payload = json.dumps(payload) if isinstance(payload, dict) else payload

    if changed_fields:
        doc.changed_fields = ",".join(changed_fields) if isinstance(changed_fields, list) else changed_fields

    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return doc


def get_pending_entries(limit=50, sync_direction=None, doctype_name=None):
    """Get pending sync entries for processing

    Args:
        limit: Maximum entries to return (default 50)
        sync_direction: Optional filter by direction
        doctype_name: Optional filter by DocType

    Returns:
        List of PIM Sync Queue names
    """
    filters = {
        "status": "Pending"
    }

    if sync_direction:
        filters["sync_direction"] = sync_direction

    if doctype_name:
        filters["doctype_name"] = doctype_name

    # Build query to handle scheduled_at
    entries = frappe.get_all(
        "PIM Sync Queue",
        filters=filters,
        fields=["name", "scheduled_at", "retry_count", "max_retries"],
        order_by="priority desc, creation asc",
        limit=limit * 2  # Get extra to filter out scheduled ones
    )

    now = now_datetime()
    result = []

    for entry in entries:
        if len(result) >= limit:
            break

        # Skip if scheduled for later
        if entry.scheduled_at and entry.scheduled_at > now:
            continue

        # Skip if max retries exceeded
        if (entry.retry_count or 0) >= (entry.max_retries or 3):
            continue

        result.append(entry.name)

    return result


def get_sync_stats():
    """Get sync queue statistics

    Returns:
        dict with counts by status
    """
    stats = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "total_today": 0,
        "avg_processing_time_ms": 0
    }

    # Count by status
    for status in ["Pending", "Processing", "Completed", "Failed", "Cancelled"]:
        count = frappe.db.count("PIM Sync Queue", {"status": status})
        stats[status.lower()] = count

    # Count today's entries
    from frappe.utils import today
    stats["total_today"] = frappe.db.count(
        "PIM Sync Queue",
        {"creation": [">=", today()]}
    )

    # Average processing time for completed entries today
    avg_time = frappe.db.sql("""
        SELECT AVG(processing_time_ms)
        FROM `tabPIM Sync Queue`
        WHERE status = 'Completed'
        AND DATE(creation) = CURDATE()
        AND processing_time_ms > 0
    """)

    if avg_time and avg_time[0][0]:
        stats["avg_processing_time_ms"] = int(avg_time[0][0])

    return stats


def retry_failed_entries(doctype_name=None, document_name=None, max_entries=10):
    """Retry failed sync entries

    Args:
        doctype_name: Optional filter by DocType
        document_name: Optional filter by document
        max_entries: Maximum entries to retry

    Returns:
        List of retried entry names
    """
    filters = {
        "status": "Failed"
    }

    if doctype_name:
        filters["doctype_name"] = doctype_name

    if document_name:
        filters["document_name"] = document_name

    failed_entries = frappe.get_all(
        "PIM Sync Queue",
        filters=filters,
        fields=["name", "retry_count", "max_retries"],
        order_by="creation desc",
        limit=max_entries
    )

    retried = []
    for entry in failed_entries:
        if (entry.retry_count or 0) < (entry.max_retries or 3):
            frappe.db.set_value(
                "PIM Sync Queue", entry.name,
                {
                    "status": "Pending",
                    "started_at": None,
                    "completed_at": None,
                    "processing_time_ms": None,
                    "error_message": None,
                    "error_traceback": None,
                    "job_id": None
                }
            )
            retried.append(entry.name)

    if retried:
        frappe.db.commit()

    return retried


def cleanup_old_entries(days=30, status=None):
    """Clean up old sync queue entries

    Args:
        days: Delete entries older than this many days
        status: Only delete entries with this status (default: Completed, Cancelled)

    Returns:
        Number of deleted entries
    """
    from frappe.utils import add_days, today

    cutoff_date = add_days(today(), -days)

    if status:
        statuses = [status]
    else:
        statuses = ["Completed", "Cancelled"]

    deleted = 0
    for st in statuses:
        entries = frappe.get_all(
            "PIM Sync Queue",
            filters={
                "status": st,
                "creation": ["<", cutoff_date]
            },
            pluck="name"
        )

        for name in entries:
            frappe.delete_doc("PIM Sync Queue", name, force=True)
            deleted += 1

    if deleted:
        frappe.db.commit()

    return deleted


def get_entry_for_document(doctype_name, document_name, status=None):
    """Get sync entry for a specific document

    Args:
        doctype_name: DocType name
        document_name: Document name
        status: Optional status filter

    Returns:
        Latest PIM Sync Queue entry or None
    """
    filters = {
        "doctype_name": doctype_name,
        "document_name": document_name
    }

    if status:
        filters["status"] = status

    entry = frappe.get_all(
        "PIM Sync Queue",
        filters=filters,
        fields=["name"],
        order_by="creation desc",
        limit=1
    )

    if entry:
        return frappe.get_doc("PIM Sync Queue", entry[0].name)

    return None
