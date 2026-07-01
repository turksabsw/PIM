"""PIM Sync API Endpoints

This module provides API endpoints for managing ERPNext synchronization
status, manual sync triggers, and queue management.

Endpoints:
- get_sync_status: Get sync status for a specific document
- trigger_sync: Manually trigger sync for a document
- get_sync_queue_stats: Get sync queue statistics
- retry_failed_sync: Retry failed sync entries
- cancel_sync_entry: Cancel a pending sync entry
- get_sync_history: Get sync history for a document
- get_pending_syncs: Get list of pending sync entries
- force_sync: Force immediate synchronous sync (bypasses queue)

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def get_sync_status(doctype_name, document_name):
    """Get the sync status for a specific document.

    Retrieves the latest sync queue entry for the specified document
    and returns its current status along with sync metadata.

    Args:
        doctype_name: DocType name (e.g., "Product Variant", "Product Master")
        document_name: Document name/ID

    Returns:
        dict: Sync status information
            - has_sync_entry: Whether a sync entry exists
            - status: Current sync status (Pending, Processing, Completed, Failed, Cancelled)
            - sync_direction: "PIM to ERP" or "ERP to PIM"
            - sync_action: Create, Update, or Delete
            - created_at: When sync was queued
            - started_at: When processing started
            - completed_at: When processing completed
            - error_message: Error details if failed
            - erp_document: Linked ERPNext document name
            - retry_count: Number of retry attempts
            - can_retry: Whether entry can be retried

    Example:
        >>> status = get_sync_status("Product Variant", "VAR-001")
        >>> if status["status"] == "Failed":
        ...     print(f"Sync failed: {status['error_message']}")
    """
    import frappe
    from frappe import _

    # Permission check
    if not frappe.has_permission(doctype_name, "read"):
        frappe.throw(_("Not permitted to read {0}").format(doctype_name), frappe.PermissionError)

    # Check if document exists
    if not frappe.db.exists(doctype_name, document_name):
        frappe.throw(
            _("Document {0}/{1} not found").format(doctype_name, document_name),
            frappe.DoesNotExistError
        )

    # Get latest sync queue entry
    from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
        get_entry_for_document
    )

    entry = get_entry_for_document(doctype_name, document_name)

    if not entry:
        # No sync entry - check if document has ERP link
        erp_item = None
        last_sync = None

        if doctype_name == "Product Variant":
            erp_item = frappe.db.get_value(doctype_name, document_name, "erp_item")
            last_sync = frappe.db.get_value(doctype_name, document_name, "last_sync_at")
        elif doctype_name == "Product Master":
            erp_item = frappe.db.get_value(doctype_name, document_name, "erp_item")

        return {
            "has_sync_entry": False,
            "status": "Not Synced" if not erp_item else "Synced",
            "erp_document": erp_item,
            "last_sync_at": str(last_sync) if last_sync else None,
            "message": _("No pending sync operations") if erp_item else _("Document not yet synced to ERPNext")
        }

    # Build response from sync entry
    max_retries = entry.max_retries or 3
    retry_count = entry.retry_count or 0

    return {
        "has_sync_entry": True,
        "sync_entry_name": entry.name,
        "status": entry.status,
        "sync_direction": entry.sync_direction,
        "sync_action": entry.sync_action,
        "priority": entry.priority,
        "created_at": str(entry.creation) if entry.creation else None,
        "scheduled_at": str(entry.scheduled_at) if entry.scheduled_at else None,
        "started_at": str(entry.started_at) if entry.started_at else None,
        "completed_at": str(entry.completed_at) if entry.completed_at else None,
        "processing_time_ms": entry.processing_time_ms,
        "error_message": entry.error_message,
        "result_message": entry.result_message,
        "erp_document": entry.erp_document,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "can_retry": entry.status == "Failed" and retry_count < max_retries,
        "has_conflict": entry.has_conflict,
        "conflict_resolution": entry.conflict_resolution
    }


def trigger_sync(doctype_name, document_name, sync_direction="PIM to ERP", priority=5, force=False):
    """Manually trigger a sync operation for a document.

    Creates a sync queue entry for the specified document if one
    doesn't already exist. Use force=True to create a new entry
    even if one is already pending.

    Args:
        doctype_name: DocType name (e.g., "Product Variant", "Product Master")
        document_name: Document name/ID
        sync_direction: "PIM to ERP" (default) or "ERP to PIM"
        priority: Priority level (0-10, higher = more urgent, default: 5)
        force: Force sync even if pending entry exists

    Returns:
        dict: Result of the sync trigger
            - success: Whether sync was queued successfully
            - sync_entry: Name of the sync queue entry
            - message: Status message

    Example:
        >>> result = trigger_sync("Product Variant", "VAR-001")
        >>> if result["success"]:
        ...     print(f"Sync queued: {result['sync_entry']}")
    """
    import frappe
    from frappe import _

    # Permission check - need write permission to trigger sync
    if not frappe.has_permission(doctype_name, "write"):
        frappe.throw(_("Not permitted to sync {0}").format(doctype_name), frappe.PermissionError)

    # Validate sync direction
    valid_directions = ["PIM to ERP", "ERP to PIM"]
    if sync_direction not in valid_directions:
        frappe.throw(
            _("Invalid sync direction. Must be one of: {0}").format(", ".join(valid_directions)),
            title=_("Invalid Parameter")
        )

    # Validate priority
    priority = max(0, min(10, int(priority)))

    # Check if document exists
    if not frappe.db.exists(doctype_name, document_name):
        frappe.throw(
            _("Document {0}/{1} not found").format(doctype_name, document_name),
            frappe.DoesNotExistError
        )

    # Check for existing pending entry
    if not force:
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
            return {
                "success": False,
                "sync_entry": existing,
                "message": _("Sync already pending or in progress: {0}").format(existing)
            }

    # Create sync queue entry
    from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
        queue_sync_entry
    )

    entry = queue_sync_entry(
        doctype_name=doctype_name,
        document_name=document_name,
        sync_direction=sync_direction,
        sync_action="Update",
        priority=priority
    )

    if entry:
        return {
            "success": True,
            "sync_entry": entry.name,
            "message": _("Sync queued successfully")
        }
    else:
        return {
            "success": False,
            "message": _("Failed to queue sync operation")
        }


def get_sync_queue_stats():
    """Get sync queue statistics for monitoring.

    Returns aggregate statistics about the sync queue including
    counts by status, today's activity, and average processing times.

    Returns:
        dict: Sync queue statistics
            - pending: Count of pending entries
            - processing: Count of entries being processed
            - completed: Count of completed entries
            - failed: Count of failed entries
            - cancelled: Count of cancelled entries
            - total_today: Total entries created today
            - avg_processing_time_ms: Average processing time in milliseconds
            - oldest_pending: Age of oldest pending entry in minutes
            - dead_letter_count: Count of entries exceeding max retries

    Example:
        >>> stats = get_sync_queue_stats()
        >>> print(f"Pending: {stats['pending']}, Failed: {stats['failed']}")
    """
    import frappe
    from frappe import _

    # Permission check - need read permission on sync queue
    if not frappe.has_permission("PIM Sync Queue", "read"):
        frappe.throw(_("Not permitted to view sync queue"), frappe.PermissionError)

    from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
        get_sync_stats
    )

    stats = get_sync_stats()

    # Add additional stats
    try:
        # Oldest pending entry
        oldest_pending = frappe.db.sql("""
            SELECT TIMESTAMPDIFF(MINUTE, creation, NOW()) as age_minutes
            FROM `tabPIM Sync Queue`
            WHERE status = 'Pending'
            ORDER BY creation ASC
            LIMIT 1
        """)
        stats["oldest_pending_minutes"] = oldest_pending[0][0] if oldest_pending and oldest_pending[0][0] else 0

        # Dead letter count (failed entries at max retries)
        dead_letter = frappe.db.sql("""
            SELECT COUNT(*)
            FROM `tabPIM Sync Queue`
            WHERE status = 'Failed'
            AND retry_count >= COALESCE(max_retries, 3)
        """)
        stats["dead_letter_count"] = dead_letter[0][0] if dead_letter else 0

        # Entries by direction
        by_direction = frappe.db.sql("""
            SELECT sync_direction, status, COUNT(*) as count
            FROM `tabPIM Sync Queue`
            WHERE status IN ('Pending', 'Processing', 'Failed')
            GROUP BY sync_direction, status
        """, as_dict=True)

        stats["by_direction"] = {}
        for row in by_direction:
            direction = row.sync_direction
            if direction not in stats["by_direction"]:
                stats["by_direction"][direction] = {}
            stats["by_direction"][direction][row.status.lower()] = row.count

    except Exception as e:
        frappe.log_error(
            message=f"Error getting extended sync stats: {str(e)}",
            title="PIM Sync Stats Error"
        )

    return stats


def retry_failed_sync(sync_entry=None, doctype_name=None, document_name=None, retry_all=False, max_entries=10):
    """Retry failed sync entries.

    Resets failed sync entries to pending status for reprocessing.
    Can retry a specific entry, entries for a specific document,
    or all failed entries.

    Args:
        sync_entry: Specific sync queue entry name to retry
        doctype_name: Filter by DocType name
        document_name: Filter by document name
        retry_all: Retry all failed entries (up to max_entries)
        max_entries: Maximum entries to retry when retry_all=True (default: 10)

    Returns:
        dict: Retry result
            - success: Whether retry operation succeeded
            - retried: List of entry names that were retried
            - skipped: List of entries that couldn't be retried
            - message: Status message

    Example:
        >>> result = retry_failed_sync(sync_entry="SYNC-001")
        >>> if result["success"]:
        ...     print(f"Retried {len(result['retried'])} entries")
    """
    import frappe
    from frappe import _

    # Permission check - need write permission on sync queue
    if not frappe.has_permission("PIM Sync Queue", "write"):
        frappe.throw(_("Not permitted to modify sync queue"), frappe.PermissionError)

    retried = []
    skipped = []

    # Retry specific entry
    if sync_entry:
        if not frappe.db.exists("PIM Sync Queue", sync_entry):
            frappe.throw(
                _("Sync entry {0} not found").format(sync_entry),
                frappe.DoesNotExistError
            )

        entry = frappe.get_doc("PIM Sync Queue", sync_entry)

        if entry.status != "Failed":
            return {
                "success": False,
                "retried": [],
                "skipped": [sync_entry],
                "message": _("Entry is not in Failed status: {0}").format(entry.status)
            }

        if (entry.retry_count or 0) >= (entry.max_retries or 3):
            return {
                "success": False,
                "retried": [],
                "skipped": [sync_entry],
                "message": _("Entry has exceeded maximum retry count")
            }

        # Reset entry for retry
        entry.db_set({
            "status": "Pending",
            "started_at": None,
            "completed_at": None,
            "processing_time_ms": None,
            "error_message": None,
            "error_traceback": None,
            "job_id": None
        })
        retried.append(sync_entry)

    # Retry by document
    elif doctype_name and document_name:
        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            retry_failed_entries
        )
        retried = retry_failed_entries(
            doctype_name=doctype_name,
            document_name=document_name,
            max_entries=max_entries
        )

    # Retry all
    elif retry_all:
        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            retry_failed_entries
        )
        retried = retry_failed_entries(max_entries=max_entries)

    else:
        return {
            "success": False,
            "retried": [],
            "skipped": [],
            "message": _("Please specify sync_entry, document, or retry_all=True")
        }

    frappe.db.commit()

    return {
        "success": len(retried) > 0,
        "retried": retried,
        "skipped": skipped,
        "message": _("Retried {0} entries").format(len(retried)) if retried else _("No entries to retry")
    }


def cancel_sync_entry(sync_entry, reason=None):
    """Cancel a pending or failed sync entry.

    Cancels the specified sync queue entry. Only pending or failed
    entries can be cancelled.

    Args:
        sync_entry: Sync queue entry name to cancel
        reason: Optional reason for cancellation

    Returns:
        dict: Cancellation result
            - success: Whether cancellation succeeded
            - message: Status message

    Example:
        >>> result = cancel_sync_entry("SYNC-001", reason="Duplicate entry")
        >>> print(result["message"])
    """
    import frappe
    from frappe import _

    # Permission check
    if not frappe.has_permission("PIM Sync Queue", "write"):
        frappe.throw(_("Not permitted to modify sync queue"), frappe.PermissionError)

    if not frappe.db.exists("PIM Sync Queue", sync_entry):
        frappe.throw(
            _("Sync entry {0} not found").format(sync_entry),
            frappe.DoesNotExistError
        )

    entry = frappe.get_doc("PIM Sync Queue", sync_entry)

    if entry.status not in ["Pending", "Failed"]:
        return {
            "success": False,
            "message": _("Cannot cancel entry with status: {0}").format(entry.status)
        }

    entry.db_set({
        "status": "Cancelled",
        "result_message": reason or _("Manually cancelled")
    })
    frappe.db.commit()

    return {
        "success": True,
        "message": _("Sync entry cancelled successfully")
    }


def get_sync_history(doctype_name, document_name, limit=10):
    """Get sync history for a specific document.

    Retrieves the sync queue history for a document showing
    all past sync operations and their results.

    Args:
        doctype_name: DocType name
        document_name: Document name/ID
        limit: Maximum number of history entries (default: 10)

    Returns:
        dict: Sync history
            - document: Document identifier
            - entries: List of sync history entries
            - total: Total count of sync entries for this document

    Example:
        >>> history = get_sync_history("Product Variant", "VAR-001", limit=5)
        >>> for entry in history["entries"]:
        ...     print(f"{entry['status']}: {entry['completed_at']}")
    """
    import frappe
    from frappe import _

    # Permission check
    if not frappe.has_permission(doctype_name, "read"):
        frappe.throw(_("Not permitted to read {0}").format(doctype_name), frappe.PermissionError)

    limit = min(100, max(1, int(limit)))

    # Get total count
    total = frappe.db.count(
        "PIM Sync Queue",
        {
            "doctype_name": doctype_name,
            "document_name": document_name
        }
    )

    # Get history entries
    entries = frappe.get_all(
        "PIM Sync Queue",
        filters={
            "doctype_name": doctype_name,
            "document_name": document_name
        },
        fields=[
            "name", "status", "sync_direction", "sync_action",
            "creation", "started_at", "completed_at", "processing_time_ms",
            "error_message", "result_message", "erp_document",
            "retry_count", "has_conflict", "conflict_resolution"
        ],
        order_by="creation desc",
        limit=limit
    )

    # Format dates
    for entry in entries:
        entry["creation"] = str(entry["creation"]) if entry.get("creation") else None
        entry["started_at"] = str(entry["started_at"]) if entry.get("started_at") else None
        entry["completed_at"] = str(entry["completed_at"]) if entry.get("completed_at") else None

    return {
        "document": f"{doctype_name}/{document_name}",
        "entries": entries,
        "total": total
    }


def get_pending_syncs(limit=50, sync_direction=None, doctype_name=None):
    """Get list of pending sync entries.

    Retrieves pending sync queue entries for monitoring or
    dashboard display.

    Args:
        limit: Maximum entries to return (default: 50, max: 200)
        sync_direction: Filter by "PIM to ERP" or "ERP to PIM"
        doctype_name: Filter by DocType name

    Returns:
        dict: Pending sync entries
            - entries: List of pending sync entries
            - total: Total count of pending entries
            - oldest_age_minutes: Age of oldest entry in minutes

    Example:
        >>> pending = get_pending_syncs(limit=20, sync_direction="PIM to ERP")
        >>> print(f"Found {pending['total']} pending syncs")
    """
    import frappe
    from frappe import _

    # Permission check
    if not frappe.has_permission("PIM Sync Queue", "read"):
        frappe.throw(_("Not permitted to view sync queue"), frappe.PermissionError)

    limit = min(200, max(1, int(limit)))

    filters = {"status": "Pending"}

    if sync_direction:
        filters["sync_direction"] = sync_direction

    if doctype_name:
        filters["doctype_name"] = doctype_name

    # Get total count
    total = frappe.db.count("PIM Sync Queue", filters)

    # Get entries
    entries = frappe.get_all(
        "PIM Sync Queue",
        filters=filters,
        fields=[
            "name", "doctype_name", "document_name", "sync_direction",
            "sync_action", "priority", "creation", "scheduled_at",
            "retry_count", "max_retries"
        ],
        order_by="priority desc, creation asc",
        limit=limit
    )

    # Calculate age for each entry
    from frappe.utils import now_datetime, time_diff_in_seconds
    now = now_datetime()

    oldest_age = 0
    for entry in entries:
        if entry.get("creation"):
            age_seconds = time_diff_in_seconds(now, entry["creation"])
            entry["age_minutes"] = int(age_seconds / 60)
            oldest_age = max(oldest_age, entry["age_minutes"])
            entry["creation"] = str(entry["creation"])
        if entry.get("scheduled_at"):
            entry["scheduled_at"] = str(entry["scheduled_at"])

    return {
        "entries": entries,
        "total": total,
        "oldest_age_minutes": oldest_age
    }


def force_sync(doctype_name, document_name, sync_direction="PIM to ERP"):
    """Force immediate synchronous sync (bypasses queue).

    Executes a sync operation immediately without going through
    the queue. Use with caution as this blocks until completion.

    Args:
        doctype_name: DocType name
        document_name: Document name/ID
        sync_direction: "PIM to ERP" or "ERP to PIM"

    Returns:
        dict: Sync result
            - success: Whether sync succeeded
            - erp_document: Linked ERPNext document (if applicable)
            - message: Status message
            - error: Error message if failed

    Example:
        >>> result = force_sync("Product Variant", "VAR-001")
        >>> if result["success"]:
        ...     print(f"Synced to: {result['erp_document']}")
    """
    import frappe
    from frappe import _

    # Permission check - need write permission
    if not frappe.has_permission(doctype_name, "write"):
        frappe.throw(_("Not permitted to sync {0}").format(doctype_name), frappe.PermissionError)

    # Validate sync direction
    if sync_direction not in ["PIM to ERP", "ERP to PIM"]:
        frappe.throw(
            _("Invalid sync direction"),
            title=_("Invalid Parameter")
        )

    # Check if document exists
    if not frappe.db.exists(doctype_name, document_name):
        frappe.throw(
            _("Document {0}/{1} not found").format(doctype_name, document_name),
            frappe.DoesNotExistError
        )

    try:
        doc = frappe.get_doc(doctype_name, document_name)

        if sync_direction == "PIM to ERP":
            # Import sync utility
            from frappe_pim.pim.utils.erp_sync import sync_to_erp_item

            if doctype_name == "Product Variant":
                success = sync_to_erp_item(doc)
                if success:
                    return {
                        "success": True,
                        "erp_document": doc.get("erp_item"),
                        "message": _("Synced to ERPNext Item: {0}").format(doc.get("erp_item"))
                    }
                else:
                    return {
                        "success": False,
                        "error": _("Sync to ERPNext failed")
                    }
            else:
                return {
                    "success": False,
                    "error": _("Force sync only supported for Product Variant")
                }

        else:  # ERP to PIM
            return {
                "success": False,
                "error": _("ERP to PIM force sync not yet implemented")
            }

    except Exception as e:
        frappe.log_error(
            message=f"Force sync failed for {doctype_name}/{document_name}: {str(e)}",
            title="PIM Force Sync Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def cleanup_sync_queue(days=30, status=None):
    """Clean up old sync queue entries.

    Removes old completed or cancelled sync entries to keep
    the queue table manageable.

    Args:
        days: Delete entries older than this many days (default: 30)
        status: Only delete entries with this status (default: Completed, Cancelled)

    Returns:
        dict: Cleanup result
            - deleted: Number of entries deleted
            - message: Status message

    Example:
        >>> result = cleanup_sync_queue(days=7)
        >>> print(f"Deleted {result['deleted']} old entries")
    """
    import frappe
    from frappe import _

    # Permission check - need delete permission
    if not frappe.has_permission("PIM Sync Queue", "delete"):
        frappe.throw(_("Not permitted to delete sync queue entries"), frappe.PermissionError)

    days = max(1, int(days))

    from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
        cleanup_old_entries
    )

    deleted = cleanup_old_entries(days=days, status=status)

    return {
        "deleted": deleted,
        "message": _("Deleted {0} sync queue entries older than {1} days").format(deleted, days)
    }


# ============================================================================
# Whitelist Wrapper
# ============================================================================

def _wrap_for_whitelist():
    """Add @frappe.whitelist() decorators at runtime."""
    import frappe

    global get_sync_status, trigger_sync, get_sync_queue_stats, retry_failed_sync
    global cancel_sync_entry, get_sync_history, get_pending_syncs, force_sync
    global cleanup_sync_queue

    get_sync_status = frappe.whitelist()(get_sync_status)
    trigger_sync = frappe.whitelist()(trigger_sync)
    get_sync_queue_stats = frappe.whitelist()(get_sync_queue_stats)
    retry_failed_sync = frappe.whitelist()(retry_failed_sync)
    cancel_sync_entry = frappe.whitelist()(cancel_sync_entry)
    get_sync_history = frappe.whitelist()(get_sync_history)
    get_pending_syncs = frappe.whitelist()(get_pending_syncs)
    force_sync = frappe.whitelist()(force_sync)
    cleanup_sync_queue = frappe.whitelist()(cleanup_sync_queue)


# Apply whitelist decorators if frappe is available
try:
    _wrap_for_whitelist()
except ImportError:
    pass  # Decorators will be added when module is used in Frappe context
