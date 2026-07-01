# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt

"""
AI Approval Queue DocType Controller

Handles the approval workflow for AI-generated content suggestions.
Implements auto-approval based on confidence thresholds and sends
notifications to reviewers when manual approval is required.

Key Features:
- Auto-approval based on confidence score threshold
- Notification system for pending approvals
- Apply approved content to products
- Track review history and metrics
- Expire stale suggestions

Event Handlers:
- on_queue_insert: Called after a new queue entry is created
- on_queue_update: Called after a queue entry is updated

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from typing import Dict, List, Optional
import json
from datetime import datetime


# =============================================================================
# Default Configuration
# =============================================================================

# Default confidence threshold for auto-approval (0-100)
DEFAULT_AUTO_APPROVAL_THRESHOLD = 85.0

# Enrichment types that can be auto-approved
AUTO_APPROVABLE_TYPES = [
    "description",
    "title",
    "keywords",
    "meta_description",
    "bullet_points",
]

# Field mapping from enrichment type to Item field
ENRICHMENT_FIELD_MAPPING = {
    "description": "pim_description",
    "title": "pim_title",
    "keywords": "pim_keywords",
    "meta_description": "pim_meta_description",
    "bullet_points": "pim_bullet_points",
}

# Notification email template
NOTIFICATION_TEMPLATE = """
<h3>AI Enrichment Pending Approval</h3>

<p>A new AI-generated content suggestion requires your review:</p>

<table style="border-collapse: collapse; width: 100%;">
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Product:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{product_name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Enrichment Type:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{enrichment_type}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Confidence Score:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{confidence_score}%</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>AI Model:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{model_used}</td>
    </tr>
</table>

<h4>Original Content:</h4>
<div style="background: #f5f5f5; padding: 10px; border-radius: 4px;">
{original_content}
</div>

<h4>Suggested Content:</h4>
<div style="background: #e8f5e9; padding: 10px; border-radius: 4px;">
{suggested_content}
</div>

<p>
    <a href="{doc_url}" style="background: #5e64ff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">
        Review Now
    </a>
</p>
"""


# =============================================================================
# Document Class
# =============================================================================

class AIApprovalQueue:
    """
    Controller for AI Approval Queue DocType.

    Note: This is implemented as a regular class rather than inheriting from
    frappe.model.document.Document to allow importing without Frappe.
    The actual Document subclass is created at module load time when
    Frappe is available.
    """

    pass  # Methods are added dynamically when Frappe is available


# =============================================================================
# Document Event Handlers
# =============================================================================

def on_queue_insert(doc, method=None):
    """
    Event handler called after a new AI Approval Queue entry is created.

    This function:
    1. Checks if auto-approval is enabled and applicable
    2. Auto-approves if confidence score meets threshold
    3. Sends notification if manual review is required

    Args:
        doc: The AI Approval Queue document
        method: Event method name (unused, for Frappe compatibility)

    Usage in hooks.py:
        doc_events = {
            "AI Approval Queue": {
                "after_insert": "frappe_pim.pim.doctype.ai_approval_queue.ai_approval_queue.on_queue_insert"
            }
        }
    """
    import frappe

    # Skip if already processed
    if doc.status != "Pending":
        return

    # Check for auto-approval
    if _should_auto_approve(doc):
        _auto_approve(doc)
        return

    # Send notification for manual review
    _send_approval_notification(doc)


def on_queue_update(doc, method=None):
    """
    Event handler called after an AI Approval Queue entry is updated.

    This function:
    1. Handles status changes (Approved -> Apply content)
    2. Tracks review metrics
    3. Updates product with approved content

    Args:
        doc: The AI Approval Queue document
        method: Event method name (unused, for Frappe compatibility)

    Usage in hooks.py:
        doc_events = {
            "AI Approval Queue": {
                "on_update": "frappe_pim.pim.doctype.ai_approval_queue.ai_approval_queue.on_queue_update"
            }
        }
    """
    import frappe

    # Check if status changed to Approved
    if doc.has_value_changed("status"):
        old_status = doc.get_doc_before_save().status if doc.get_doc_before_save() else None

        if doc.status in ["Approved", "Auto Approved"] and old_status == "Pending":
            # Apply the approved content to the product
            _apply_approved_content(doc)

            # Set reviewer info for manual approval
            if doc.status == "Approved" and not doc.reviewed_by:
                doc.reviewed_by = frappe.session.user
                doc.reviewed_on = frappe.utils.now_datetime()
                doc.db_update()

        elif doc.status == "Rejected" and old_status == "Pending":
            # Track rejection
            if not doc.reviewed_by:
                doc.reviewed_by = frappe.session.user
                doc.reviewed_on = frappe.utils.now_datetime()
                doc.db_update()

            # Log rejection for analytics
            _log_rejection(doc)


def validate_queue_entry(doc, method=None):
    """
    Validation handler for AI Approval Queue entries.

    Args:
        doc: The AI Approval Queue document
        method: Event method name (unused)
    """
    import frappe

    # Validate product exists
    if doc.product and not frappe.db.exists("Item", doc.product):
        frappe.throw(f"Product {doc.product} does not exist")

    # Validate enrichment type
    valid_types = ["description", "title", "keywords", "translation",
                   "attributes", "meta_description", "bullet_points"]
    if doc.enrichment_type and doc.enrichment_type not in valid_types:
        frappe.throw(f"Invalid enrichment type: {doc.enrichment_type}")

    # Validate confidence score range
    if doc.confidence_score is not None:
        if doc.confidence_score < 0 or doc.confidence_score > 100:
            frappe.throw("Confidence score must be between 0 and 100")


# =============================================================================
# Auto-Approval Logic
# =============================================================================

def _should_auto_approve(doc) -> bool:
    """
    Check if the queue entry should be auto-approved.

    Auto-approval criteria:
    1. Enrichment type is in the allowed list
    2. Confidence score meets the threshold
    3. Auto-approval is enabled in settings

    Args:
        doc: The AI Approval Queue document

    Returns:
        True if should auto-approve, False otherwise
    """
    import frappe

    # Check if enrichment type allows auto-approval
    if doc.enrichment_type not in AUTO_APPROVABLE_TYPES:
        return False

    # Get auto-approval threshold
    threshold = _get_auto_approval_threshold(doc.enrichment_type)

    # Check confidence score
    confidence = doc.confidence_score or 0
    if confidence < threshold:
        return False

    # Check if auto-approval is enabled in settings
    if not _is_auto_approval_enabled():
        return False

    return True


def _get_auto_approval_threshold(enrichment_type: str) -> float:
    """
    Get the auto-approval threshold for an enrichment type.

    Args:
        enrichment_type: Type of enrichment

    Returns:
        Threshold percentage (0-100)
    """
    try:
        import frappe

        # Try to get from PIM Settings
        if frappe.db.exists("DocType", "PIM Settings"):
            settings = frappe.get_single("PIM Settings")

            # Type-specific threshold
            field_name = f"auto_approval_threshold_{enrichment_type}"
            if hasattr(settings, field_name) and getattr(settings, field_name):
                return float(getattr(settings, field_name))

            # General threshold
            if hasattr(settings, "ai_auto_approval_threshold"):
                return float(settings.ai_auto_approval_threshold or DEFAULT_AUTO_APPROVAL_THRESHOLD)

    except Exception:
        pass

    return DEFAULT_AUTO_APPROVAL_THRESHOLD


def _is_auto_approval_enabled() -> bool:
    """
    Check if auto-approval is enabled in settings.

    Returns:
        True if enabled, False otherwise
    """
    try:
        import frappe

        # Check PIM Settings
        if frappe.db.exists("DocType", "PIM Settings"):
            settings = frappe.get_single("PIM Settings")
            if hasattr(settings, "enable_ai_auto_approval"):
                return bool(settings.enable_ai_auto_approval)

        # Default to enabled if settings don't exist
        return True

    except Exception:
        return True


def _auto_approve(doc):
    """
    Auto-approve the queue entry and apply content.

    Args:
        doc: The AI Approval Queue document
    """
    import frappe

    # Update status
    doc.status = "Auto Approved"
    doc.auto_approved = 1
    doc.auto_approval_rule = f"Confidence >= {_get_auto_approval_threshold(doc.enrichment_type)}%"
    doc.reviewed_on = frappe.utils.now_datetime()
    doc.db_update()

    # Apply content to product
    _apply_approved_content(doc)

    # Log auto-approval
    frappe.logger().info(
        f"AI Approval Queue {doc.name} auto-approved for product {doc.product} "
        f"(confidence: {doc.confidence_score}%)"
    )


# =============================================================================
# Content Application
# =============================================================================

def _apply_approved_content(doc):
    """
    Apply approved AI content to the product.

    Args:
        doc: The AI Approval Queue document
    """
    import frappe

    if not doc.product or not doc.suggested_content:
        return

    try:
        # Get the target field
        target_field = ENRICHMENT_FIELD_MAPPING.get(doc.enrichment_type)
        if not target_field:
            frappe.logger().warning(
                f"No field mapping for enrichment type: {doc.enrichment_type}"
            )
            return

        # Check if Item has the field
        item = frappe.get_doc("Item", doc.product)

        # Handle different content types
        content = doc.suggested_content
        if doc.enrichment_type in ["keywords", "bullet_points"]:
            # These might be JSON arrays
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    content = ", ".join(str(x) for x in parsed)
            except (json.JSONDecodeError, TypeError):
                pass

        # Apply content if field exists
        if hasattr(item, target_field):
            item.set(target_field, content)
            item.flags.from_ai_approval = True
            item.save(ignore_permissions=True)

            # Update last enrichment date if field exists
            if hasattr(item, "pim_last_enrichment_date"):
                item.pim_last_enrichment_date = frappe.utils.today()
                item.db_update()

            frappe.logger().info(
                f"Applied AI enrichment ({doc.enrichment_type}) to product {doc.product}"
            )
        else:
            frappe.logger().warning(
                f"Field {target_field} not found on Item DocType"
            )

    except Exception as e:
        frappe.logger().error(
            f"Error applying AI content to product {doc.product}: {str(e)}"
        )


# =============================================================================
# Notification System
# =============================================================================

def _send_approval_notification(doc):
    """
    Send notification to reviewers that approval is required.

    Args:
        doc: The AI Approval Queue document
    """
    import frappe

    try:
        # Get recipients
        recipients = _get_notification_recipients()

        if not recipients:
            return

        # Build notification content
        doc_url = frappe.utils.get_url_to_form("AI Approval Queue", doc.name)

        message = NOTIFICATION_TEMPLATE.format(
            product_name=doc.product_name or doc.product,
            enrichment_type=doc.enrichment_type.title().replace("_", " "),
            confidence_score=round(doc.confidence_score or 0, 1),
            model_used=doc.model_used or "Unknown",
            original_content=doc.original_content or "(No original content)",
            suggested_content=doc.suggested_content or "",
            doc_url=doc_url,
        )

        subject = f"AI Enrichment Pending Review: {doc.product_name or doc.product}"

        # Send email notification
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message,
            delayed=True,
            reference_doctype="AI Approval Queue",
            reference_name=doc.name,
        )

        # Update notification status
        doc.notification_sent = 1
        doc.notification_date = frappe.utils.now_datetime()
        doc.db_update()

    except Exception as e:
        frappe.logger().error(
            f"Error sending AI approval notification: {str(e)}"
        )


def _get_notification_recipients() -> List[str]:
    """
    Get list of users who should receive approval notifications.

    Returns:
        List of email addresses
    """
    import frappe

    recipients = []

    try:
        # Get from PIM Settings
        if frappe.db.exists("DocType", "PIM Settings"):
            settings = frappe.get_single("PIM Settings")
            if hasattr(settings, "ai_approval_notification_recipients"):
                custom_recipients = settings.ai_approval_notification_recipients
                if custom_recipients:
                    recipients.extend([r.strip() for r in custom_recipients.split(",") if r.strip()])

        # If no custom recipients, get users with PIM Manager role
        if not recipients:
            managers = frappe.get_all(
                "Has Role",
                filters={"role": "PIM Manager", "parenttype": "User"},
                fields=["parent"]
            )

            for manager in managers:
                user = frappe.get_doc("User", manager.parent)
                if user.enabled and user.email:
                    recipients.append(user.email)

        # Fallback to System Manager if no PIM Managers
        if not recipients:
            admins = frappe.get_all(
                "Has Role",
                filters={"role": "System Manager", "parenttype": "User"},
                fields=["parent"],
                limit=3
            )

            for admin in admins:
                user = frappe.get_doc("User", admin.parent)
                if user.enabled and user.email:
                    recipients.append(user.email)

    except Exception:
        pass

    return list(set(recipients))  # Remove duplicates


# =============================================================================
# Analytics and Logging
# =============================================================================

def _log_rejection(doc):
    """
    Log rejection for analytics.

    Args:
        doc: The AI Approval Queue document
    """
    import frappe

    try:
        # Log to error log for now (could be a separate analytics table)
        frappe.logger().info(
            f"AI Enrichment rejected: product={doc.product}, "
            f"type={doc.enrichment_type}, "
            f"confidence={doc.confidence_score}, "
            f"reason={doc.rejection_reason or 'Not specified'}"
        )

    except Exception:
        pass


# =============================================================================
# Utility Functions
# =============================================================================

def get_pending_approvals(product: str = None, enrichment_type: str = None) -> List[Dict]:
    """
    Get list of pending approval queue entries.

    Args:
        product: Optional product filter
        enrichment_type: Optional enrichment type filter

    Returns:
        List of queue entry dictionaries
    """
    import frappe

    filters = {"status": "Pending"}

    if product:
        filters["product"] = product

    if enrichment_type:
        filters["enrichment_type"] = enrichment_type

    return frappe.get_all(
        "AI Approval Queue",
        filters=filters,
        fields=[
            "name", "product", "product_name", "enrichment_type",
            "confidence_score", "model_used", "creation"
        ],
        order_by="creation desc"
    )


def approve_queue_entry(name: str, notes: str = None) -> bool:
    """
    Approve a queue entry programmatically.

    Args:
        name: Queue entry name
        notes: Optional approval notes

    Returns:
        True if successful, False otherwise
    """
    import frappe

    try:
        doc = frappe.get_doc("AI Approval Queue", name)

        if doc.status != "Pending":
            frappe.throw(f"Cannot approve entry with status: {doc.status}")

        doc.status = "Approved"
        doc.notes = notes
        doc.reviewed_by = frappe.session.user
        doc.reviewed_on = frappe.utils.now_datetime()
        doc.save(ignore_permissions=True)

        return True

    except Exception as e:
        frappe.logger().error(f"Error approving queue entry {name}: {str(e)}")
        return False


def reject_queue_entry(name: str, reason: str = None) -> bool:
    """
    Reject a queue entry programmatically.

    Args:
        name: Queue entry name
        reason: Optional rejection reason

    Returns:
        True if successful, False otherwise
    """
    import frappe

    try:
        doc = frappe.get_doc("AI Approval Queue", name)

        if doc.status != "Pending":
            frappe.throw(f"Cannot reject entry with status: {doc.status}")

        doc.status = "Rejected"
        doc.rejection_reason = reason
        doc.reviewed_by = frappe.session.user
        doc.reviewed_on = frappe.utils.now_datetime()
        doc.save(ignore_permissions=True)

        return True

    except Exception as e:
        frappe.logger().error(f"Error rejecting queue entry {name}: {str(e)}")
        return False


def expire_stale_entries(days: int = 30):
    """
    Mark old pending entries as expired.

    Args:
        days: Number of days after which entries are considered stale
    """
    import frappe
    from frappe.utils import add_days, now_datetime

    cutoff_date = add_days(now_datetime(), -days)

    stale_entries = frappe.get_all(
        "AI Approval Queue",
        filters={
            "status": "Pending",
            "creation": ["<", cutoff_date]
        },
        pluck="name"
    )

    for entry_name in stale_entries:
        try:
            doc = frappe.get_doc("AI Approval Queue", entry_name)
            doc.status = "Expired"
            doc.notes = f"Auto-expired after {days} days"
            doc.save(ignore_permissions=True)
        except Exception as e:
            frappe.logger().error(f"Error expiring queue entry {entry_name}: {str(e)}")


def get_approval_stats(days: int = 30) -> Dict:
    """
    Get approval statistics for the specified period.

    Args:
        days: Number of days to include

    Returns:
        Dictionary with statistics
    """
    import frappe
    from frappe.utils import add_days, now_datetime

    cutoff_date = add_days(now_datetime(), -days)

    # Count by status
    status_counts = {}
    for status in ["Pending", "Approved", "Auto Approved", "Rejected", "Expired"]:
        count = frappe.db.count(
            "AI Approval Queue",
            filters={
                "status": status,
                "creation": [">=", cutoff_date]
            }
        )
        status_counts[status.lower().replace(" ", "_")] = count

    # Calculate averages
    total = sum(status_counts.values())
    approved = status_counts.get("approved", 0) + status_counts.get("auto_approved", 0)

    return {
        "period_days": days,
        "total_entries": total,
        "status_breakdown": status_counts,
        "approval_rate": round((approved / total * 100) if total > 0 else 0, 1),
        "auto_approval_rate": round(
            (status_counts.get("auto_approved", 0) / total * 100) if total > 0 else 0, 1
        ),
    }


# =============================================================================
# Frappe Document Class (created when Frappe is available)
# =============================================================================

try:
    import frappe
    from frappe.model.document import Document

    class AIApprovalQueue(Document):
        """AI Approval Queue Document"""

        def validate(self):
            """Validate the document before saving"""
            validate_queue_entry(self)

        def after_insert(self):
            """Handle after insert event"""
            on_queue_insert(self)

        def on_update(self):
            """Handle update event"""
            on_queue_update(self)

        def approve(self, notes: str = None):
            """Approve this queue entry"""
            return approve_queue_entry(self.name, notes)

        def reject(self, reason: str = None):
            """Reject this queue entry"""
            return reject_queue_entry(self.name, reason)

except ImportError:
    # Frappe not available, use stub class
    pass


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Document class
    "AIApprovalQueue",
    # Event handlers
    "on_queue_insert",
    "on_queue_update",
    "validate_queue_entry",
    # Utility functions
    "get_pending_approvals",
    "approve_queue_entry",
    "reject_queue_entry",
    "expire_stale_entries",
    "get_approval_stats",
    # Constants
    "DEFAULT_AUTO_APPROVAL_THRESHOLD",
    "AUTO_APPROVABLE_TYPES",
    "ENRICHMENT_FIELD_MAPPING",
]
