"""
PIM Event Sourcing Utilities
Provides helper functions for creating PIM Events during document lifecycle
"""

import frappe
from frappe import _
from frappe.model.document import Document
from typing import Optional, Dict, Any, List
import json


# ============================================
# Event Type Constants
# ============================================

EVENT_TYPE_CREATED = "Created"
EVENT_TYPE_UPDATED = "Updated"
EVENT_TYPE_DELETED = "Deleted"
EVENT_TYPE_SUBMITTED = "Submitted"
EVENT_TYPE_CANCELLED = "Cancelled"
EVENT_TYPE_PUBLISHED = "Published"
EVENT_TYPE_UNPUBLISHED = "Unpublished"
EVENT_TYPE_MERGED = "Merged"
EVENT_TYPE_ENRICHED = "Enriched"
EVENT_TYPE_VALIDATED = "Validated"


# ============================================
# Event Category Constants
# ============================================

EVENT_CATEGORY_PRODUCT = "Product"
EVENT_CATEGORY_ATTRIBUTE = "Attribute"
EVENT_CATEGORY_CLASSIFICATION = "Classification"
EVENT_CATEGORY_ASSET = "Asset"
EVENT_CATEGORY_CHANNEL = "Channel"
EVENT_CATEGORY_GOLDEN_RECORD = "GoldenRecord"
EVENT_CATEGORY_AI = "AI"
EVENT_CATEGORY_SYSTEM = "System"


# ============================================
# DocType to Event Category Mapping
# ============================================

DOCTYPE_CATEGORY_MAP = {
    "Product Master": EVENT_CATEGORY_PRODUCT,
    "Product Variant": EVENT_CATEGORY_PRODUCT,
    "Product Type": EVENT_CATEGORY_PRODUCT,
    "Product Family": EVENT_CATEGORY_PRODUCT,
    "Attribute": EVENT_CATEGORY_ATTRIBUTE,
    "Attribute Group": EVENT_CATEGORY_ATTRIBUTE,
    "Product Attribute Value": EVENT_CATEGORY_ATTRIBUTE,
    "Taxonomy": EVENT_CATEGORY_CLASSIFICATION,
    "Taxonomy Node": EVENT_CATEGORY_CLASSIFICATION,
    "Product Classification": EVENT_CATEGORY_CLASSIFICATION,
    "Digital Asset": EVENT_CATEGORY_ASSET,
    "Product Asset Link": EVENT_CATEGORY_ASSET,
    "Sales Channel": EVENT_CATEGORY_CHANNEL,
    "Channel Readiness Status": EVENT_CATEGORY_CHANNEL,
    "Golden Record": EVENT_CATEGORY_GOLDEN_RECORD,
    "AI Enrichment Job": EVENT_CATEGORY_AI,
    "AI Approval Queue": EVENT_CATEGORY_AI,
}


def get_event_category(doctype: str) -> str:
    """Get the event category for a given DocType

    Args:
        doctype: The DocType name

    Returns:
        Event category string
    """
    return DOCTYPE_CATEGORY_MAP.get(doctype, EVENT_CATEGORY_SYSTEM)


def create_pim_event(
    event_type: str,
    reference_doctype: str,
    reference_docname: str,
    event_category: Optional[str] = None,
    old_value: Optional[Dict] = None,
    new_value: Optional[Dict] = None,
    changed_fields: Optional[List[str]] = None,
    event_metadata: Optional[Dict] = None,
    source_system: Optional[str] = None,
    trigger_method: str = "System",
    severity: str = "Info",
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    golden_record: Optional[str] = None,
    correlation_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    sequence_number: int = 0
) -> Optional[str]:
    """Create a PIM Event record

    Args:
        event_type: Type of event (Created, Updated, Deleted, etc.)
        reference_doctype: DocType of the referenced document
        reference_docname: Name of the referenced document
        event_category: Category of event (auto-detected if not provided)
        old_value: Previous value as dict
        new_value: New value as dict
        changed_fields: List of field names that changed
        event_metadata: Additional metadata
        source_system: Source system identifier
        trigger_method: How event was triggered (Manual, System, API, etc.)
        severity: Event severity (Info, Warning, Error, Critical)
        channel: Channel context
        locale: Locale context
        golden_record: Associated golden record
        correlation_id: Correlation ID for tracing
        batch_id: Batch operation ID
        sequence_number: Order within batch

    Returns:
        Event name if created successfully, None otherwise
    """
    try:
        # Auto-detect category if not provided
        if not event_category:
            event_category = get_event_category(reference_doctype)
        
        # Map Virtual DocTypes to their underlying real DocTypes for reference validation
        # Product Master is a Virtual DocType that maps to Item
        virtual_to_real_doctype = {
            "Product Master": "Item",
        }
        actual_reference_doctype = virtual_to_real_doctype.get(reference_doctype, reference_doctype)

        # Serialize dict values to JSON strings
        old_value_json = json.dumps(old_value, default=str) if old_value else None
        new_value_json = json.dumps(new_value, default=str) if new_value else None
        changed_fields_json = json.dumps(changed_fields) if changed_fields else None
        metadata_json = json.dumps(event_metadata, default=str) if event_metadata else None

        event = frappe.get_doc({
            "doctype": "PIM Event",
            "event_type": event_type,
            "event_category": event_category,
            "reference_doctype": actual_reference_doctype,
            "reference_docname": reference_docname,
            "event_timestamp": frappe.utils.now_datetime(),
            "old_value": old_value_json,
            "new_value": new_value_json,
            "changed_fields": changed_fields_json,
            "event_metadata": metadata_json,
            "source_system": source_system,
            "trigger_method": trigger_method,
            "severity": severity,
            "channel": channel,
            "locale": locale,
            "golden_record": golden_record,
            "correlation_id": correlation_id or frappe.generate_hash(length=16),
            "batch_id": batch_id,
            "sequence_number": sequence_number,
            "triggered_by": frappe.session.user
        })
        # ignore_links=True allows Virtual DocTypes (like Product Master)
        # which don't have real database tables
        event.insert(ignore_permissions=True, ignore_links=True)

        return event.name

    except Exception as e:
        frappe.log_error(
            message=f"Error creating PIM Event for {reference_doctype}/{reference_docname}: {str(e)}",
            title="PIM Event Creation Error"
        )
        return None


def create_event_from_doc(
    doc: Document,
    event_type: str,
    old_doc: Optional[Document] = None,
    **kwargs
) -> Optional[str]:
    """Create a PIM Event from a Frappe Document

    This is a convenience wrapper that handles extracting values from documents
    and calculating changed fields automatically.

    Args:
        doc: The document that changed
        event_type: Type of event (Created, Updated, Deleted)
        old_doc: Previous version of document (for update events)
        **kwargs: Additional event parameters

    Returns:
        Event name if created, None otherwise
    """
    try:
        old_value = None
        new_value = None
        changed_fields = None

        # Extract relevant fields (exclude internal/system fields)
        exclude_fields = {
            '_comments', '_liked_by', '_user_tags', '_assign',
            'modified', 'modified_by', 'creation', 'owner',
            'idx', 'docstatus', '__last_sync_hash', '__islocal',
            '__unsaved', '__run_link_triggers'
        }

        if event_type == EVENT_TYPE_CREATED:
            # For create events, capture the new document state
            new_dict = doc.as_dict() if hasattr(doc, 'as_dict') else {}
            new_value = {
                k: v for k, v in new_dict.items()
                if not k.startswith('_') and k not in exclude_fields
            }

        elif event_type == EVENT_TYPE_UPDATED and old_doc:
            # For update events, calculate what changed
            old_dict = old_doc.as_dict() if hasattr(old_doc, 'as_dict') else old_doc
            new_dict = doc.as_dict() if hasattr(doc, 'as_dict') else {}

            changes = []
            old_values = {}
            new_values = {}

            for key in new_dict:
                if key.startswith('_') or key in exclude_fields:
                    continue
                old_val = old_dict.get(key)
                new_val = new_dict.get(key)
                if old_val != new_val:
                    changes.append(key)
                    old_values[key] = old_val
                    new_values[key] = new_val

            if changes:
                changed_fields = changes
                old_value = old_values
                new_value = new_values
            else:
                # No actual changes, skip event creation
                return None

        elif event_type == EVENT_TYPE_DELETED:
            # For delete events, capture the document state before deletion
            old_dict = doc.as_dict() if hasattr(doc, 'as_dict') else {}
            old_value = {
                k: v for k, v in old_dict.items()
                if not k.startswith('_') and k not in exclude_fields
            }

        return create_pim_event(
            event_type=event_type,
            reference_doctype=doc.doctype,
            reference_docname=doc.name,
            old_value=old_value,
            new_value=new_value,
            changed_fields=changed_fields,
            **kwargs
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error creating PIM Event from doc {doc.doctype}/{doc.name}: {str(e)}",
            title="PIM Event Creation Error"
        )
        return None


# ============================================
# Product Master Specific Event Functions
# ============================================

def on_product_master_after_insert(doc: Document, method: Optional[str] = None):
    """Handle Product Master after_insert hook

    Creates a 'Created' event for the new Product Master.

    Args:
        doc: The Product Master document
        method: The hook method name (unused)
    """
    create_event_from_doc(
        doc=doc,
        event_type=EVENT_TYPE_CREATED,
        trigger_method="Document Hook",
        event_metadata={
            "hook": "after_insert",
            "sku": getattr(doc, 'sku', None),
            "product_type": getattr(doc, 'product_type', None),
            "product_family": getattr(doc, 'product_family', None)
        }
    )


def on_product_master_on_update(doc: Document, method: Optional[str] = None):
    """Handle Product Master on_update hook

    Creates an 'Updated' event if there are actual changes.

    Args:
        doc: The Product Master document
        method: The hook method name (unused)
    """
    # Get the previous version from database
    if not doc.is_new():
        try:
            old_doc = frappe.get_doc(doc.doctype, doc.name, for_update=False)
            # Use get_doc_before_save if available
            if hasattr(doc, 'get_doc_before_save'):
                old_doc = doc.get_doc_before_save()
        except Exception:
            old_doc = None

        if old_doc:
            create_event_from_doc(
                doc=doc,
                event_type=EVENT_TYPE_UPDATED,
                old_doc=old_doc,
                trigger_method="Document Hook",
                event_metadata={
                    "hook": "on_update",
                    "sku": getattr(doc, 'sku', None)
                }
            )


def on_product_master_on_trash(doc: Document, method: Optional[str] = None):
    """Handle Product Master on_trash hook

    Creates a 'Deleted' event before the document is removed.

    Args:
        doc: The Product Master document
        method: The hook method name (unused)
    """
    create_event_from_doc(
        doc=doc,
        event_type=EVENT_TYPE_DELETED,
        trigger_method="Document Hook",
        event_metadata={
            "hook": "on_trash",
            "sku": getattr(doc, 'sku', None),
            "product_name": getattr(doc, 'product_name', None)
        }
    )


def on_product_master_validate(doc: Document, method: Optional[str] = None):
    """Handle Product Master validate hook

    Stores the document state before changes for later comparison.

    Args:
        doc: The Product Master document
        method: The hook method name (unused)
    """
    # Store the previous state for comparison in on_update
    if not doc.is_new():
        try:
            doc._previous_doc = frappe.get_doc(doc.doctype, doc.name).as_dict()
        except Exception:
            doc._previous_doc = None


# ============================================
# Generic Document Event Functions
# ============================================

def on_document_after_insert(doc: Document, method: Optional[str] = None):
    """Generic after_insert handler for PIM DocTypes

    Args:
        doc: The document
        method: The hook method name (unused)
    """
    # Only create events for PIM-related DocTypes
    if doc.doctype in DOCTYPE_CATEGORY_MAP:
        create_event_from_doc(
            doc=doc,
            event_type=EVENT_TYPE_CREATED,
            trigger_method="Document Hook"
        )


def on_document_on_update(doc: Document, method: Optional[str] = None):
    """Generic on_update handler for PIM DocTypes

    Args:
        doc: The document
        method: The hook method name (unused)
    """
    # Only create events for PIM-related DocTypes
    if doc.doctype in DOCTYPE_CATEGORY_MAP and not doc.is_new():
        # Try to get previous state
        old_doc = getattr(doc, '_previous_doc', None)
        if old_doc:
            create_event_from_doc(
                doc=doc,
                event_type=EVENT_TYPE_UPDATED,
                old_doc=old_doc,
                trigger_method="Document Hook"
            )


def on_document_on_trash(doc: Document, method: Optional[str] = None):
    """Generic on_trash handler for PIM DocTypes

    Args:
        doc: The document
        method: The hook method name (unused)
    """
    # Only create events for PIM-related DocTypes
    if doc.doctype in DOCTYPE_CATEGORY_MAP:
        create_event_from_doc(
            doc=doc,
            event_type=EVENT_TYPE_DELETED,
            trigger_method="Document Hook"
        )


def on_document_validate(doc: Document, method: Optional[str] = None):
    """Generic validate handler for PIM DocTypes

    Stores the document state before changes for later comparison.

    Args:
        doc: The document
        method: The hook method name (unused)
    """
    # Store previous state for PIM DocTypes
    if doc.doctype in DOCTYPE_CATEGORY_MAP and not doc.is_new():
        try:
            doc._previous_doc = frappe.get_doc(doc.doctype, doc.name).as_dict()
        except Exception:
            doc._previous_doc = None


# ============================================
# Batch Event Creation
# ============================================

def create_batch_events(
    documents: List[Dict[str, Any]],
    event_type: str,
    batch_name: Optional[str] = None
) -> Dict[str, Any]:
    """Create multiple PIM Events in a batch

    Args:
        documents: List of dicts with 'doctype' and 'name' keys
        event_type: Event type for all documents
        batch_name: Optional batch identifier

    Returns:
        Dict with created event names and any errors
    """
    batch_id = batch_name or frappe.generate_hash(length=12)
    correlation_id = frappe.generate_hash(length=16)
    created_events = []
    errors = []

    for idx, doc_info in enumerate(documents):
        try:
            event_name = create_pim_event(
                event_type=event_type,
                reference_doctype=doc_info.get('doctype'),
                reference_docname=doc_info.get('name'),
                batch_id=batch_id,
                correlation_id=correlation_id,
                sequence_number=idx + 1,
                trigger_method="Batch Operation",
                event_metadata=doc_info.get('metadata')
            )
            if event_name:
                created_events.append(event_name)
        except Exception as e:
            errors.append({
                'doctype': doc_info.get('doctype'),
                'name': doc_info.get('name'),
                'error': str(e)
            })

    return {
        'batch_id': batch_id,
        'correlation_id': correlation_id,
        'created_events': created_events,
        'event_count': len(created_events),
        'errors': errors
    }
