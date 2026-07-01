"""PIM Sync Queue Processor

This module contains the background task for processing the sync queue
between PIM and ERPNext. It runs on a scheduled basis via Frappe's
scheduler to handle bidirectional sync operations.

Task Schedule:
    - process_sync_queue: Every minute - Processes pending sync entries
    - cleanup_old_sync_entries: Daily - Removes old completed/cancelled entries

The sync queue processor:
    1. Fetches pending sync queue entries ordered by priority
    2. Enqueues individual sync jobs for parallel processing
    3. Handles errors and retries with dead letter tracking

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def process_sync_queue():
    """Process pending sync queue entries.

    This is the main scheduled task that runs every minute. It fetches
    pending sync entries and enqueues them for background processing.
    Each entry is processed individually to allow parallel execution
    and prevent one failed entry from blocking others.

    The task:
        1. Gets pending entries (limited to 50 per run)
        2. Enqueues each entry for individual processing
        3. Uses job_id to prevent duplicate jobs for same entry

    Limits processing to 50 entries per run to avoid overwhelming
    the background workers.
    """
    import frappe

    try:
        frappe.logger("pim_sync").info(
            "Starting process_sync_queue task"
        )

        # Get pending entries using helper from sync queue module
        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            get_pending_entries
        )

        pending = get_pending_entries(limit=50)

        if not pending:
            frappe.logger("pim_sync").debug(
                "No pending sync entries to process"
            )
            return

        enqueued = 0
        skipped = 0

        for entry_name in pending:
            try:
                # Use job_id to prevent duplicate processing
                job_id = f"pim_sync_{entry_name}"

                # Check if job already exists and is running
                from frappe.utils.background_jobs import is_job_enqueued
                if is_job_enqueued(job_id):
                    skipped += 1
                    continue

                frappe.enqueue(
                    "frappe_pim.pim.sync.queue_processor.process_single_entry",
                    queue="default",
                    timeout=300,
                    job_id=job_id,
                    entry_name=entry_name
                )
                enqueued += 1

            except Exception as e:
                frappe.log_error(
                    message=f"Error enqueueing sync entry {entry_name}: {str(e)}",
                    title="PIM Sync Queue Error"
                )

        frappe.logger("pim_sync").info(
            f"process_sync_queue: {enqueued} enqueued, {skipped} skipped (already running)"
        )

    except Exception as e:
        frappe.log_error(
            message=f"process_sync_queue task failed: {str(e)}",
            title="PIM Sync Queue Error"
        )


def process_single_entry(entry_name):
    """Process a single sync queue entry.

    This function is called as a background job for each sync entry.
    It handles the actual sync operation and updates the entry status.

    Args:
        entry_name: Name of the PIM Sync Queue entry to process

    The processing:
        1. Marks entry as Processing
        2. Determines sync direction (PIM to ERP or ERP to PIM)
        3. Executes appropriate sync action (Create, Update, Delete)
        4. Marks as Completed or Failed based on result
        5. Handles conflict detection and resolution
    """
    import frappe
    import traceback

    try:
        frappe.logger("pim_sync").debug(
            f"Processing sync entry: {entry_name}"
        )

        # Get the sync queue entry
        if not frappe.db.exists("PIM Sync Queue", entry_name):
            frappe.logger("pim_sync").warning(
                f"Sync entry not found: {entry_name}"
            )
            return

        entry = frappe.get_doc("PIM Sync Queue", entry_name)

        # Skip if not pending (may have been cancelled or already processed)
        if entry.status != "Pending":
            frappe.logger("pim_sync").debug(
                f"Skipping non-pending entry {entry_name}: {entry.status}"
            )
            return

        # Mark as processing
        entry.db_set({
            "status": "Processing",
            "started_at": frappe.utils.now_datetime(),
            "job_id": f"pim_sync_{entry_name}"
        })
        frappe.db.commit()

        # Process based on sync direction
        if entry.sync_direction == "PIM to ERP":
            result = _sync_pim_to_erp(entry)
        else:
            result = _sync_erp_to_pim(entry)

        # Update entry status based on result
        if result.get("success"):
            entry.reload()
            _mark_entry_completed(entry, result)
        else:
            entry.reload()
            _mark_entry_failed(entry, result.get("error", "Unknown error"))

        frappe.db.commit()

    except Exception as e:
        error_trace = traceback.format_exc()
        frappe.log_error(
            message=f"Error processing sync entry {entry_name}: {str(e)}\n{error_trace}",
            title="PIM Sync Processing Error"
        )

        # Mark entry as failed
        try:
            if frappe.db.exists("PIM Sync Queue", entry_name):
                entry = frappe.get_doc("PIM Sync Queue", entry_name)
                _mark_entry_failed(entry, str(e), error_trace)
                frappe.db.commit()
        except Exception:
            pass


def _sync_pim_to_erp(entry):
    """Sync from PIM to ERPNext.

    Handles sync operations from PIM Product documents to ERPNext Items.

    Args:
        entry: PIM Sync Queue document

    Returns:
        dict: {success: bool, erp_document: str, error: str}
    """
    import frappe

    try:
        doctype_name = entry.doctype_name
        document_name = entry.document_name
        sync_action = entry.sync_action

        # Validate document exists
        if not frappe.db.exists(doctype_name, document_name):
            return {
                "success": False,
                "error": f"Document {doctype_name}/{document_name} not found"
            }

        doc = frappe.get_doc(doctype_name, document_name)

        # Check if ERPNext is available
        if not _is_erpnext_installed():
            return {
                "success": False,
                "error": "ERPNext is not installed"
            }

        # Handle based on sync action
        if sync_action == "Delete":
            return _handle_pim_delete(doc, entry)
        elif sync_action == "Create":
            return _handle_pim_create(doc, entry)
        else:  # Update
            return _handle_pim_update(doc, entry)

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _sync_erp_to_pim(entry):
    """Sync from ERPNext to PIM.

    Handles sync operations from ERPNext Items to PIM Product documents.

    Args:
        entry: PIM Sync Queue document

    Returns:
        dict: {success: bool, pim_document: str, error: str}
    """
    import frappe

    try:
        doctype_name = entry.doctype_name
        document_name = entry.document_name
        sync_action = entry.sync_action

        # Validate document exists (unless delete action)
        if sync_action != "Delete" and not frappe.db.exists(doctype_name, document_name):
            return {
                "success": False,
                "error": f"Document {doctype_name}/{document_name} not found"
            }

        # Handle delete action separately
        if sync_action == "Delete":
            return _handle_erp_delete(entry)

        doc = frappe.get_doc(doctype_name, document_name)

        # Check for conflicts before syncing
        conflict = _check_sync_conflict(entry, doc)
        if conflict:
            return _handle_conflict(entry, conflict, doc)

        # Execute sync based on action
        if sync_action == "Create":
            return _handle_erp_create(doc, entry)
        else:  # Update
            return _handle_erp_update(doc, entry)

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _handle_pim_create(doc, entry):
    """Handle PIM to ERP create operation.

    Creates an ERPNext Item from a PIM Product document.

    Args:
        doc: PIM document (Product Master or Product Variant)
        entry: PIM Sync Queue entry

    Returns:
        dict: Sync result
    """
    import frappe

    try:
        from frappe_pim.pim.utils.erp_sync import create_erp_item

        # Product Variant creates Item directly
        if doc.doctype == "Product Variant":
            item_name = create_erp_item(doc)
            if item_name:
                return {
                    "success": True,
                    "erp_document": item_name,
                    "message": f"Created ERPNext Item: {item_name}"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to create ERPNext Item"
                }

        # Product Master may need to create template item
        elif doc.doctype == "Product Master":
            # Template items are created only if has_variants is set
            if doc.get("has_variants"):
                item_name = _create_template_item(doc)
                if item_name:
                    return {
                        "success": True,
                        "erp_document": item_name,
                        "message": f"Created ERPNext template Item: {item_name}"
                    }
            return {
                "success": True,
                "message": "Product Master synced (no Item created for non-template)"
            }

        return {
            "success": False,
            "error": f"Unsupported DocType for PIM to ERP create: {doc.doctype}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _handle_pim_update(doc, entry):
    """Handle PIM to ERP update operation.

    Updates linked ERPNext Item from PIM document changes.

    Args:
        doc: PIM document
        entry: PIM Sync Queue entry

    Returns:
        dict: Sync result
    """
    import frappe

    try:
        from frappe_pim.pim.utils.erp_sync import sync_to_erp_item

        if doc.doctype == "Product Variant":
            success = sync_to_erp_item(doc)
            if success:
                return {
                    "success": True,
                    "erp_document": doc.get("erp_item"),
                    "message": f"Updated ERPNext Item: {doc.get('erp_item')}"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to sync to ERPNext Item"
                }

        elif doc.doctype == "Product Master":
            # Update template item if exists
            if doc.get("erp_item") and frappe.db.exists("Item", doc.erp_item):
                _update_template_item(doc)
                return {
                    "success": True,
                    "erp_document": doc.erp_item,
                    "message": f"Updated ERPNext template Item: {doc.erp_item}"
                }
            return {
                "success": True,
                "message": "Product Master synced (no linked Item)"
            }

        return {
            "success": False,
            "error": f"Unsupported DocType for PIM to ERP update: {doc.doctype}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _handle_pim_delete(doc, entry):
    """Handle PIM to ERP delete operation.

    Handles deletion of linked ERPNext Item when PIM document is deleted.

    Args:
        doc: PIM document
        entry: PIM Sync Queue entry

    Returns:
        dict: Sync result
    """
    import frappe

    try:
        # Get the linked ERP item
        erp_item = doc.get("erp_item") if doc else entry.get("erp_document")

        if not erp_item:
            return {
                "success": True,
                "message": "No linked ERPNext Item to delete"
            }

        # Check if Item exists
        if not frappe.db.exists("Item", erp_item):
            return {
                "success": True,
                "message": f"ERPNext Item {erp_item} already deleted"
            }

        # Check PIM Settings for delete behavior
        delete_erp_item = frappe.db.get_single_value(
            "PIM Settings", "delete_erp_item_on_variant_delete"
        ) if frappe.db.exists("DocType", "PIM Settings") else False

        if delete_erp_item:
            # Attempt to delete the Item
            try:
                frappe.delete_doc("Item", erp_item, force=True)
                return {
                    "success": True,
                    "message": f"Deleted ERPNext Item: {erp_item}"
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Cannot delete Item {erp_item}: {str(e)}"
                }
        else:
            # Just unlink - clear the erp_item reference
            return {
                "success": True,
                "message": f"ERPNext Item {erp_item} unlinked (not deleted per settings)"
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _handle_erp_create(doc, entry):
    """Handle ERP to PIM create operation.

    Creates a PIM Product Variant from an ERPNext Item.

    Args:
        doc: ERPNext Item document
        entry: PIM Sync Queue entry

    Returns:
        dict: Sync result
    """
    import frappe

    try:
        # Check if Product Variant already exists
        if frappe.db.exists("Product Variant", {"erp_item": doc.name}):
            return {
                "success": True,
                "message": f"Product Variant already exists for Item: {doc.name}"
            }

        # Check auto-create setting
        auto_create = frappe.db.get_single_value(
            "PIM Settings", "auto_create_variant_from_item"
        ) if frappe.db.exists("DocType", "PIM Settings") else False

        if not auto_create:
            return {
                "success": True,
                "message": "Auto-create variant from Item disabled"
            }

        # Create Product Variant
        variant = frappe.new_doc("Product Variant")
        variant.sku = doc.item_code
        variant.variant_name = doc.item_name
        variant.description = doc.description or ""
        variant.uom = doc.stock_uom or "Nos"
        variant.erp_item = doc.name
        variant.status = "Draft"
        variant._from_erpnext_sync = True
        variant.flags.from_erp = True
        variant.insert(ignore_permissions=True)

        return {
            "success": True,
            "pim_document": variant.name,
            "message": f"Created Product Variant: {variant.name}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _handle_erp_update(doc, entry):
    """Handle ERP to PIM update operation.

    Updates linked PIM Product Variant from ERPNext Item changes.

    Args:
        doc: ERPNext Item document
        entry: PIM Sync Queue entry

    Returns:
        dict: Sync result
    """
    import frappe

    try:
        # Find linked Product Variant
        variant_name = frappe.db.get_value(
            "Product Variant",
            {"erp_item": doc.name},
            "name"
        )

        if not variant_name:
            return {
                "success": True,
                "message": f"No Product Variant linked to Item: {doc.name}"
            }

        variant = frappe.get_doc("Product Variant", variant_name)

        # Map Item fields to Variant fields
        field_mapping = {
            "item_name": "variant_name",
            "description": "description",
            "stock_uom": "uom"
        }

        has_changes = False
        for item_field, variant_field in field_mapping.items():
            item_value = doc.get(item_field)
            if item_value and variant.get(variant_field) != item_value:
                variant.set(variant_field, item_value)
                has_changes = True

        if has_changes:
            variant._from_erpnext_sync = True
            variant.flags.from_erp = True
            variant.flags.ignore_version = True
            variant.save(ignore_permissions=True)

        return {
            "success": True,
            "pim_document": variant_name,
            "message": f"Updated Product Variant: {variant_name}" if has_changes else "No changes needed"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _handle_erp_delete(entry):
    """Handle ERP to PIM delete operation.

    Unlinks PIM Product Variant when ERPNext Item is deleted.

    Args:
        entry: PIM Sync Queue entry

    Returns:
        dict: Sync result
    """
    import frappe

    try:
        document_name = entry.document_name

        # Find and unlink Product Variant
        variant_name = frappe.db.get_value(
            "Product Variant",
            {"erp_item": document_name},
            "name"
        )

        if variant_name:
            frappe.db.set_value(
                "Product Variant",
                variant_name,
                "erp_item",
                None,
                update_modified=False
            )

        return {
            "success": True,
            "pim_document": variant_name,
            "message": f"Unlinked Product Variant {variant_name}" if variant_name else "No linked variant found"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def _check_sync_conflict(entry, doc):
    """Check for sync conflicts.

    Detects if both PIM and ERP have been modified since last sync.

    Args:
        entry: PIM Sync Queue entry
        doc: Source document

    Returns:
        dict or None: Conflict details if conflict exists
    """
    import frappe
    from frappe.utils import get_datetime

    # Only check for ERP to PIM sync
    if entry.sync_direction != "ERP to PIM":
        return None

    if entry.doctype_name != "Item":
        return None

    # Find linked Product Variant
    variant_name = frappe.db.get_value(
        "Product Variant",
        {"erp_item": doc.name},
        "name"
    )

    if not variant_name:
        return None

    # Get last sync time from variant
    variant = frappe.get_doc("Product Variant", variant_name)
    last_sync = variant.get("last_sync_at")

    if not last_sync:
        return None

    last_sync_dt = get_datetime(last_sync)

    # Check if both were modified after last sync
    item_modified = get_datetime(doc.modified)
    variant_modified = get_datetime(variant.modified)

    if item_modified > last_sync_dt and variant_modified > last_sync_dt:
        return {
            "type": "concurrent_modification",
            "pim_document": variant_name,
            "pim_modified": str(variant_modified),
            "erp_document": doc.name,
            "erp_modified": str(item_modified),
            "last_sync": str(last_sync)
        }

    return None


def _handle_conflict(entry, conflict, doc):
    """Handle detected sync conflict.

    Applies conflict resolution rules from PIM Sync Conflict Rule.

    Args:
        entry: PIM Sync Queue entry
        conflict: Conflict details dict
        doc: Source document

    Returns:
        dict: Resolution result
    """
    import frappe
    import json

    try:
        # Record conflict in entry
        entry.db_set({
            "has_conflict": 1,
            "conflict_details": json.dumps(conflict)
        })

        # Find applicable conflict rule
        rule = _get_conflict_rule(entry.doctype_name, doc)

        if not rule:
            # Default: ERP wins (overwrite PIM)
            resolution = "erp_wins"
        else:
            resolution = rule.resolution_strategy or "erp_wins"

        entry.db_set("conflict_resolution", resolution)

        # Apply resolution
        if resolution == "pim_wins":
            # Keep PIM data, skip this sync
            return {
                "success": True,
                "message": "Conflict resolved: PIM wins (skipped ERP update)"
            }
        elif resolution == "erp_wins":
            # Continue with ERP to PIM sync
            return _handle_erp_update(doc, entry)
        elif resolution == "manual":
            # Mark for manual review
            return {
                "success": False,
                "error": "Conflict requires manual resolution"
            }
        else:
            # Unknown resolution, default to ERP wins
            return _handle_erp_update(doc, entry)

    except Exception as e:
        return {
            "success": False,
            "error": f"Conflict resolution failed: {str(e)}"
        }


def _get_conflict_rule(doctype_name, doc):
    """Get applicable conflict resolution rule.

    Args:
        doctype_name: DocType being synced
        doc: Document being synced

    Returns:
        PIM Sync Conflict Rule document or None
    """
    import frappe

    if not frappe.db.exists("DocType", "PIM Sync Conflict Rule"):
        return None

    # Find rule for this doctype
    rules = frappe.get_all(
        "PIM Sync Conflict Rule",
        filters={
            "source_doctype": doctype_name,
            "enabled": 1
        },
        fields=["name", "resolution_strategy"],
        order_by="priority desc",
        limit=1
    )

    if rules:
        return frappe.get_doc("PIM Sync Conflict Rule", rules[0].name)

    return None


def _create_template_item(product_master):
    """Create ERPNext template Item from Product Master.

    Args:
        product_master: Product Master document

    Returns:
        str: Created Item name or None
    """
    import frappe

    try:
        # Check if Item already exists
        if product_master.get("erp_item"):
            return product_master.erp_item

        item_code = product_master.get("sku") or product_master.name

        if frappe.db.exists("Item", item_code):
            product_master.db_set("erp_item", item_code, update_modified=False)
            return item_code

        # Get item group
        item_group = _get_item_group_for_product(product_master)

        # Create template Item
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": item_code,
            "item_name": product_master.product_name or item_code,
            "item_group": item_group,
            "description": product_master.get("description") or "",
            "has_variants": 1 if product_master.get("has_variants") else 0,
            "is_stock_item": 1
        })

        item.flags._from_pim_sync = True
        item.insert(ignore_permissions=True)

        # Link back to Product Master
        product_master.db_set("erp_item", item.name, update_modified=False)

        return item.name

    except Exception as e:
        frappe.log_error(
            message=f"Error creating template Item for {product_master.name}: {str(e)}",
            title="PIM Sync Error"
        )
        return None


def _update_template_item(product_master):
    """Update linked ERPNext template Item from Product Master.

    Args:
        product_master: Product Master document
    """
    import frappe

    try:
        if not product_master.get("erp_item"):
            return

        item = frappe.get_doc("Item", product_master.erp_item)

        # Update fields
        updates = {}
        if product_master.get("product_name") and item.item_name != product_master.product_name:
            updates["item_name"] = product_master.product_name

        if product_master.get("description") and item.description != product_master.description:
            updates["description"] = product_master.description

        if updates:
            item.update(updates)
            item.flags._from_pim_sync = True
            item.save(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(
            message=f"Error updating template Item for {product_master.name}: {str(e)}",
            title="PIM Sync Error"
        )


def _get_item_group_for_product(product):
    """Get appropriate Item Group for a product.

    Args:
        product: Product document

    Returns:
        str: Item Group name
    """
    import frappe

    default_group = "Products"

    try:
        if not frappe.db.exists("Item Group", default_group):
            groups = frappe.get_all("Item Group", limit=1, pluck="name")
            if groups:
                default_group = groups[0]
            else:
                default_group = "All Item Groups"

        # Try to get from product family
        family = product.get("product_family")
        if family:
            # Check for mapped item group
            mapped = frappe.db.get_value("Product Family", family, "item_group")
            if mapped and frappe.db.exists("Item Group", mapped):
                return mapped

            # Check if family name matches item group
            if frappe.db.exists("Item Group", family):
                return family

        return default_group

    except Exception:
        return default_group


def _mark_entry_completed(entry, result):
    """Mark sync queue entry as completed.

    Args:
        entry: PIM Sync Queue document
        result: Sync result dict
    """
    from frappe.utils import now_datetime, time_diff_in_seconds

    now = now_datetime()
    updates = {
        "status": "Completed",
        "completed_at": now,
        "result_message": result.get("message", "Sync completed successfully")
    }

    if result.get("erp_document"):
        updates["erp_document"] = result["erp_document"]

    if entry.started_at:
        diff_seconds = time_diff_in_seconds(now, entry.started_at)
        updates["processing_time_ms"] = int(diff_seconds * 1000)

    entry.db_set(updates)


def _mark_entry_failed(entry, error_message, error_traceback=None):
    """Mark sync queue entry as failed.

    Args:
        entry: PIM Sync Queue document
        error_message: Error description
        error_traceback: Full traceback string
    """
    import frappe
    from frappe.utils import now_datetime, time_diff_in_seconds

    now = now_datetime()
    new_retry_count = (entry.retry_count or 0) + 1

    updates = {
        "status": "Failed",
        "completed_at": now,
        "error_message": error_message,
        "retry_count": new_retry_count
    }

    if error_traceback:
        updates["error_traceback"] = error_traceback

    if entry.started_at:
        diff_seconds = time_diff_in_seconds(now, entry.started_at)
        updates["processing_time_ms"] = int(diff_seconds * 1000)

    entry.db_set(updates)

    # Check if should notify about dead letter
    if new_retry_count >= (entry.max_retries or 3):
        frappe.publish_realtime(
            event="pim_sync_dead_letter",
            message={
                "sync_queue": entry.name,
                "doctype_name": entry.doctype_name,
                "document_name": entry.document_name,
                "error": error_message
            },
            user=entry.created_by_user
        )


def _is_erpnext_installed():
    """Check if ERPNext is installed.

    Returns:
        bool: True if ERPNext is available
    """
    import frappe

    try:
        return frappe.db.exists("DocType", "Item")
    except Exception:
        return False


def cleanup_old_sync_entries():
    """Clean up old completed and cancelled sync entries.

    This daily task removes sync queue entries that are older than
    30 days and have been completed or cancelled. This keeps the
    sync queue table manageable.

    Can also be called manually to free up space:
        frappe.enqueue("frappe_pim.pim.sync.queue_processor.cleanup_old_sync_entries")
    """
    import frappe

    try:
        frappe.logger("pim_sync").info(
            "Starting cleanup_old_sync_entries task"
        )

        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            cleanup_old_entries
        )

        deleted = cleanup_old_entries(days=30)

        frappe.logger("pim_sync").info(
            f"cleanup_old_sync_entries completed: {deleted} entries deleted"
        )

    except Exception as e:
        frappe.log_error(
            message=f"cleanup_old_sync_entries task failed: {str(e)}",
            title="PIM Sync Cleanup Error"
        )


def retry_all_failed():
    """Retry all failed sync entries that haven't exceeded max retries.

    This utility function can be called manually to retry failed entries:
        frappe.enqueue("frappe_pim.pim.sync.queue_processor.retry_all_failed")

    Returns:
        int: Number of entries reset for retry
    """
    import frappe

    try:
        frappe.logger("pim_sync").info(
            "Starting retry_all_failed task"
        )

        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            retry_failed_entries
        )

        retried = retry_failed_entries(max_entries=100)

        frappe.logger("pim_sync").info(
            f"retry_all_failed completed: {len(retried)} entries reset for retry"
        )

        return len(retried)

    except Exception as e:
        frappe.log_error(
            message=f"retry_all_failed task failed: {str(e)}",
            title="PIM Sync Retry Error"
        )
        return 0


def get_sync_queue_status():
    """Get current sync queue status summary.

    Returns stats about the sync queue for monitoring and dashboards.

    Returns:
        dict: Queue statistics
    """
    import frappe

    try:
        from frappe_pim.pim.doctype.pim_sync_queue.pim_sync_queue import (
            get_sync_stats
        )

        return get_sync_stats()

    except Exception as e:
        frappe.log_error(
            message=f"get_sync_queue_status failed: {str(e)}",
            title="PIM Sync Status Error"
        )
        return {
            "error": str(e)
        }
