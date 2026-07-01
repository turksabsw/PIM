# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt

"""
Partner Submission DocType Controller

Handles product submissions from brand portal partners. Manages the
approval workflow from draft to approved/rejected, and creates Items
in ERPNext upon approval.

Key Features:
- Submission validation and quality scoring
- Approval workflow management
- Automatic Item creation on approval
- GTIN/barcode validation
- Notification system for status changes
- Portal user submission tracking

Event Handlers:
- validate_submission: Validation before save
- on_submission_insert: Called after new submission is created
- on_submission_update: Called after submission is updated
- on_submission_submit: Called when submission is submitted (workflow)

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from typing import Dict, List, Optional
from datetime import datetime
import json
import re


# =============================================================================
# Constants
# =============================================================================

# Status workflow transitions
VALID_STATUS_TRANSITIONS = {
    "Draft": ["Submitted"],
    "Submitted": ["Under Review", "Approved", "Rejected", "Needs Revision"],
    "Under Review": ["Approved", "Rejected", "Needs Revision"],
    "Needs Revision": ["Submitted"],
    "Approved": [],  # Terminal state
    "Rejected": ["Draft"],  # Can be revised and resubmitted
}

# Required fields for submission
REQUIRED_FIELDS = [
    "product_name",
    "product_code",
]

# Optional but recommended fields (affect quality score)
RECOMMENDED_FIELDS = [
    "short_description",
    "full_description",
    "barcode",
    "primary_image",
    "standard_price",
    "weight",
]

# Quality score weights
QUALITY_WEIGHTS = {
    "product_name": 10,
    "product_code": 10,
    "short_description": 15,
    "full_description": 15,
    "barcode": 10,
    "primary_image": 15,
    "additional_images": 5,
    "standard_price": 10,
    "weight": 5,
    "product_type": 5,
}

# Notification templates
SUBMISSION_RECEIVED_TEMPLATE = """
<h3>Product Submission Received</h3>

<p>Dear {partner_name},</p>

<p>Your product submission has been received and is pending review:</p>

<table style="border-collapse: collapse; width: 100%;">
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Submission ID:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{submission_id}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Product Name:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{product_name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Product Code:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{product_code}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Status:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{status}</td>
    </tr>
</table>

<p>We will notify you once your submission has been reviewed.</p>
"""

SUBMISSION_APPROVED_TEMPLATE = """
<h3>Product Submission Approved</h3>

<p>Dear {partner_name},</p>

<p>Your product submission has been <strong style="color: green;">approved</strong>!</p>

<table style="border-collapse: collapse; width: 100%;">
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Submission ID:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{submission_id}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Product Name:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{product_name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Product Code:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{product_code}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Created Item:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{created_item}</td>
    </tr>
</table>

<p>Your product is now available in our catalog.</p>
"""

SUBMISSION_REJECTED_TEMPLATE = """
<h3>Product Submission Requires Attention</h3>

<p>Dear {partner_name},</p>

<p>Your product submission has been <strong style="color: red;">rejected</strong>.</p>

<table style="border-collapse: collapse; width: 100%;">
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Submission ID:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{submission_id}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Product Name:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{product_name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Rejection Reason:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{rejection_reason}</td>
    </tr>
</table>

<p>Please review the feedback and resubmit if applicable.</p>
"""


# =============================================================================
# Document Class
# =============================================================================

class PartnerSubmission:
    """
    Controller for Partner Submission DocType.

    Note: This is implemented as a regular class rather than inheriting from
    frappe.model.document.Document to allow importing without Frappe.
    The actual Document subclass is created at module load time when
    Frappe is available.
    """

    pass  # Methods are added dynamically when Frappe is available


# =============================================================================
# Document Event Handlers
# =============================================================================

def validate_submission(doc, method=None):
    """
    Validation handler for Partner Submission.

    This function validates:
    1. Portal user exists and is active
    2. Required fields are present
    3. Product code uniqueness
    4. Barcode/GTIN format if provided
    5. Status transitions are valid
    6. Calculates quality score

    Args:
        doc: The Partner Submission document
        method: Event method name (unused, for Frappe compatibility)

    Usage in hooks.py:
        doc_events = {
            "Partner Submission": {
                "validate": "frappe_pim.pim.doctype.partner_submission.partner_submission.validate_submission"
            }
        }
    """
    import frappe

    # Validate portal user
    if doc.portal_user:
        portal_user = frappe.get_doc("Brand Portal User", doc.portal_user)

        if portal_user.status != "Active":
            frappe.throw(
                f"Portal user {doc.portal_user} is not active.",
                title="Invalid Portal User"
            )

        # Check submission limits
        if not portal_user.can_submit_products:
            frappe.throw(
                "You do not have permission to submit products.",
                title="Permission Denied"
            )

        # Check monthly limit
        if portal_user.max_submissions_per_month > 0:
            current = portal_user.current_month_submissions or 0
            if current >= portal_user.max_submissions_per_month:
                frappe.throw(
                    f"Monthly submission limit ({portal_user.max_submissions_per_month}) reached.",
                    title="Limit Exceeded"
                )

    # Validate required fields
    for field in REQUIRED_FIELDS:
        if not doc.get(field):
            frappe.throw(
                f"{frappe.unscrub(field)} is required.",
                title="Missing Required Field"
            )

    # Validate product code uniqueness (across submissions and items)
    if doc.product_code:
        # Check in other submissions
        existing_submission = frappe.db.exists(
            "Partner Submission",
            {"product_code": doc.product_code, "name": ["!=", doc.name]}
        )
        if existing_submission:
            frappe.throw(
                f"Product code {doc.product_code} already exists in another submission.",
                title="Duplicate Product Code"
            )

        # Check in Items
        existing_item = frappe.db.exists("Item", doc.product_code)
        if existing_item:
            frappe.throw(
                f"Product code {doc.product_code} already exists as an Item.",
                title="Duplicate Product Code"
            )

    # Validate barcode if provided
    if doc.barcode:
        if not _validate_gtin(doc.barcode):
            frappe.throw(
                f"Invalid barcode/GTIN: {doc.barcode}. Please check the format and check digit.",
                title="Invalid Barcode"
            )

    # Validate status transition
    if not doc.is_new() and doc.has_value_changed("submission_status"):
        old_doc = doc.get_doc_before_save()
        if old_doc:
            old_status = old_doc.submission_status
            new_status = doc.submission_status

            valid_transitions = VALID_STATUS_TRANSITIONS.get(old_status, [])
            if new_status not in valid_transitions:
                frappe.throw(
                    f"Cannot change status from '{old_status}' to '{new_status}'. "
                    f"Valid transitions: {', '.join(valid_transitions) or 'None'}",
                    title="Invalid Status Transition"
                )

    # Calculate quality score
    doc.quality_score = _calculate_quality_score(doc)


def on_submission_insert(doc, method=None):
    """
    Event handler called after a new Partner Submission is created.

    This function:
    1. Updates portal user submission count
    2. Sends confirmation notification to partner
    3. Notifies reviewers if submitted

    Args:
        doc: The Partner Submission document
        method: Event method name (unused, for Frappe compatibility)

    Usage in hooks.py:
        doc_events = {
            "Partner Submission": {
                "after_insert": "frappe_pim.pim.doctype.partner_submission.partner_submission.on_submission_insert"
            }
        }
    """
    import frappe

    # Update portal user stats
    if doc.portal_user:
        try:
            from frappe_pim.pim.doctype.brand_portal_user.brand_portal_user import (
                update_submission_stats
            )
            update_submission_stats(doc.portal_user, "submitted")
        except ImportError:
            pass

    # Log the new submission
    frappe.logger().info(
        f"New partner submission created: {doc.name} for product {doc.product_name}"
    )


def on_submission_update(doc, method=None):
    """
    Event handler called after a Partner Submission is updated.

    This function:
    1. Handles status changes
    2. Creates Item on approval
    3. Sends notifications
    4. Updates portal user stats

    Args:
        doc: The Partner Submission document
        method: Event method name (unused, for Frappe compatibility)

    Usage in hooks.py:
        doc_events = {
            "Partner Submission": {
                "on_update": "frappe_pim.pim.doctype.partner_submission.partner_submission.on_submission_update"
            }
        }
    """
    import frappe

    # Handle status changes
    if doc.has_value_changed("submission_status"):
        old_doc = doc.get_doc_before_save()
        old_status = old_doc.submission_status if old_doc else None

        if doc.submission_status == "Submitted" and old_status == "Draft":
            # Mark submission date
            doc.submission_date = frappe.utils.now_datetime()
            doc.db_update()

            # Notify reviewers
            _notify_reviewers(doc)

            # Send confirmation to partner
            _send_partner_notification(doc, "received")

        elif doc.submission_status == "Approved":
            # Set reviewer info
            if not doc.reviewer:
                doc.reviewer = frappe.session.user
                doc.reviewed_on = frappe.utils.now_datetime()

            # Create Item from submission
            item = create_item_from_submission(doc.name)
            if item:
                doc.created_item = item
                doc.item_created_on = frappe.utils.now_datetime()

            doc.db_update()

            # Update portal user stats
            _update_portal_user_stats(doc, "approved")

            # Send notification to partner
            _send_partner_notification(doc, "approved")

        elif doc.submission_status == "Rejected":
            # Set reviewer info
            if not doc.reviewer:
                doc.reviewer = frappe.session.user
                doc.reviewed_on = frappe.utils.now_datetime()
                doc.db_update()

            # Update portal user stats
            _update_portal_user_stats(doc, "rejected")

            # Send notification to partner
            _send_partner_notification(doc, "rejected")

        elif doc.submission_status == "Needs Revision":
            # Set reviewer info
            if not doc.reviewer:
                doc.reviewer = frappe.session.user
                doc.reviewed_on = frappe.utils.now_datetime()
                doc.db_update()

            # Send notification to partner
            _send_partner_notification(doc, "revision")


def on_submission_submit(doc, method=None):
    """
    Event handler called when a Partner Submission is submitted (Frappe submit).

    This is triggered by the Frappe submit action (docstatus = 1),
    not to be confused with the submission_status field.

    Args:
        doc: The Partner Submission document
        method: Event method name (unused, for Frappe compatibility)
    """
    import frappe

    # If being submitted via Frappe workflow, change status to Submitted
    if doc.submission_status == "Draft":
        doc.submission_status = "Submitted"
        doc.submission_date = frappe.utils.now_datetime()
        doc.db_update()

        # Notify reviewers
        _notify_reviewers(doc)


# =============================================================================
# GTIN Validation
# =============================================================================

def _validate_gtin(gtin: str) -> bool:
    """
    Validate GTIN/barcode format and check digit.

    Supports GTIN-8, GTIN-12 (UPC), GTIN-13 (EAN), GTIN-14.

    Args:
        gtin: Barcode string

    Returns:
        True if valid, False otherwise
    """
    if not gtin:
        return False

    # Remove spaces and hyphens
    gtin = re.sub(r'[\s-]', '', str(gtin))

    # Check if numeric
    if not gtin.isdigit():
        return False

    # Check valid length
    if len(gtin) not in [8, 12, 13, 14]:
        return False

    # Verify check digit
    return _verify_check_digit(gtin)


def _verify_check_digit(gtin: str) -> bool:
    """
    Verify GTIN check digit using modulo 10 algorithm.

    Args:
        gtin: GTIN string

    Returns:
        True if check digit is valid
    """
    digits = [int(d) for d in gtin]
    check_digit = digits[-1]
    data_digits = digits[:-1]

    # Pad to 17 digits for consistent calculation
    while len(data_digits) < 17:
        data_digits.insert(0, 0)

    # Calculate check digit
    odd_sum = sum(data_digits[i] for i in range(0, 17, 2))
    even_sum = sum(data_digits[i] for i in range(1, 17, 2))

    total = odd_sum + (even_sum * 3)
    calculated_check = (10 - (total % 10)) % 10

    return calculated_check == check_digit


# =============================================================================
# Quality Score Calculation
# =============================================================================

def _calculate_quality_score(doc) -> float:
    """
    Calculate quality score based on completeness.

    Args:
        doc: The Partner Submission document

    Returns:
        Quality score as percentage (0-100)
    """
    total_weight = sum(QUALITY_WEIGHTS.values())
    earned_weight = 0

    for field, weight in QUALITY_WEIGHTS.items():
        value = doc.get(field)

        if field == "additional_images":
            # Check for multiple images
            if value and len(str(value).split(",")) > 1:
                earned_weight += weight
        elif value:
            earned_weight += weight

    return round((earned_weight / total_weight) * 100, 1)


# =============================================================================
# Item Creation
# =============================================================================

def create_item_from_submission(submission_name: str) -> Optional[str]:
    """
    Create an ERPNext Item from a Partner Submission.

    Args:
        submission_name: Partner Submission name

    Returns:
        Created Item name or None
    """
    import frappe

    try:
        doc = frappe.get_doc("Partner Submission", submission_name)

        if doc.created_item:
            # Item already created
            return doc.created_item

        # Create new Item
        item = frappe.new_doc("Item")

        # Basic fields
        item.item_code = doc.product_code
        item.item_name = doc.product_name
        item.item_group = doc.item_group or "Products"
        item.stock_uom = "Nos"
        item.is_stock_item = 1

        # PIM custom fields on Item (custom_field.json fixture uses custom_pim_* prefix)
        item.description = doc.full_description or doc.short_description or ""

        if hasattr(item, "custom_pim_status"):
            item.custom_pim_status = "Draft"

        # Brand (native Item field)
        if doc.brand:
            item.brand = doc.brand

        # Barcode
        if doc.barcode:
            item.append("barcodes", {
                "barcode": doc.barcode,
                "barcode_type": _get_barcode_type(doc.barcode)
            })

        # Description
        item.description = doc.short_description or doc.product_name

        # Weight
        if doc.weight:
            item.weight_per_unit = doc.weight
            item.weight_uom = doc.weight_uom or "Kg"

        # Image
        if doc.primary_image:
            item.image = doc.primary_image

        # Flag to prevent sync loops
        item.flags.from_partner_submission = True
        item.flags.ignore_permissions = True

        # Insert the item
        item.insert(ignore_permissions=True)

        frappe.logger().info(
            f"Created Item {item.name} from Partner Submission {submission_name}"
        )

        return item.name

    except Exception as e:
        frappe.logger().error(
            f"Error creating Item from submission {submission_name}: {str(e)}"
        )
        return None


def _get_barcode_type(barcode: str) -> str:
    """
    Determine barcode type based on length.

    Args:
        barcode: Barcode string

    Returns:
        Barcode type name
    """
    barcode = re.sub(r'[\s-]', '', str(barcode))

    length = len(barcode)
    if length == 8:
        return "EAN-8"
    elif length == 12:
        return "UPC-A"
    elif length == 13:
        return "EAN-13"
    elif length == 14:
        return "GTIN-14"
    else:
        return "EAN"


# =============================================================================
# Notification Functions
# =============================================================================

def _notify_reviewers(doc):
    """
    Send notification to PIM reviewers about new submission.

    Args:
        doc: The Partner Submission document
    """
    import frappe

    try:
        recipients = _get_reviewers()

        if not recipients:
            return

        doc_url = frappe.utils.get_url_to_form("Partner Submission", doc.name)

        message = f"""
<h3>New Product Submission for Review</h3>

<p>A new product submission requires review:</p>

<table style="border-collapse: collapse; width: 100%;">
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Submission ID:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{doc.name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Product Name:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{doc.product_name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Brand:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{doc.brand or 'N/A'}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Quality Score:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{doc.quality_score or 0}%</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Priority:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{doc.priority or 'Medium'}</td>
    </tr>
</table>

<p>
    <a href="{doc_url}" style="background: #5e64ff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">
        Review Submission
    </a>
</p>
"""

        frappe.sendmail(
            recipients=recipients,
            subject=f"New Product Submission: {doc.product_name}",
            message=message,
            delayed=True,
            reference_doctype="Partner Submission",
            reference_name=doc.name,
        )

    except Exception as e:
        frappe.logger().error(f"Error notifying reviewers: {str(e)}")


def _send_partner_notification(doc, notification_type: str):
    """
    Send notification to the partner about submission status.

    Args:
        doc: The Partner Submission document
        notification_type: Type of notification (received, approved, rejected, revision)
    """
    import frappe

    try:
        # Get partner email
        if not doc.portal_user:
            return

        portal_user = frappe.get_doc("Brand Portal User", doc.portal_user)
        if not portal_user.email:
            return

        partner_name = portal_user.full_name or portal_user.user

        if notification_type == "received":
            subject = f"Submission Received: {doc.product_name}"
            message = SUBMISSION_RECEIVED_TEMPLATE.format(
                partner_name=partner_name,
                submission_id=doc.name,
                product_name=doc.product_name,
                product_code=doc.product_code,
                status=doc.submission_status,
            )

        elif notification_type == "approved":
            subject = f"Submission Approved: {doc.product_name}"
            message = SUBMISSION_APPROVED_TEMPLATE.format(
                partner_name=partner_name,
                submission_id=doc.name,
                product_name=doc.product_name,
                product_code=doc.product_code,
                created_item=doc.created_item or "Pending",
            )

        elif notification_type == "rejected":
            subject = f"Submission Rejected: {doc.product_name}"
            message = SUBMISSION_REJECTED_TEMPLATE.format(
                partner_name=partner_name,
                submission_id=doc.name,
                product_name=doc.product_name,
                rejection_reason=doc.rejection_reason or "No reason provided",
            )

        elif notification_type == "revision":
            subject = f"Revision Requested: {doc.product_name}"
            message = f"""
<h3>Revision Requested for Your Submission</h3>

<p>Dear {partner_name},</p>

<p>Your product submission requires revisions:</p>

<p><strong>Requested Changes:</strong></p>
<p>{doc.revision_requested or 'Please review the submission details.'}</p>

<p>Please make the necessary changes and resubmit.</p>
"""
        else:
            return

        frappe.sendmail(
            recipients=[portal_user.email],
            subject=subject,
            message=message,
            delayed=True,
            reference_doctype="Partner Submission",
            reference_name=doc.name,
        )

    except Exception as e:
        frappe.logger().error(f"Error sending partner notification: {str(e)}")


def _get_reviewers() -> List[str]:
    """
    Get list of PIM reviewer email addresses.

    Returns:
        List of email addresses
    """
    import frappe

    recipients = []

    try:
        # Get PIM Managers
        managers = frappe.get_all(
            "Has Role",
            filters={"role": "PIM Manager", "parenttype": "User"},
            fields=["parent"]
        )

        for manager in managers:
            user = frappe.get_doc("User", manager.parent)
            if user.enabled and user.email:
                recipients.append(user.email)

    except Exception:
        pass

    return list(set(recipients))


def _update_portal_user_stats(doc, status_change: str):
    """
    Update portal user submission statistics.

    Args:
        doc: The Partner Submission document
        status_change: Status change type ('approved' or 'rejected')
    """
    try:
        from frappe_pim.pim.doctype.brand_portal_user.brand_portal_user import (
            update_submission_stats
        )

        if doc.portal_user:
            update_submission_stats(doc.portal_user, status_change)

    except ImportError:
        pass


# =============================================================================
# Utility Functions
# =============================================================================

def get_pending_submissions(brand: str = None, priority: str = None) -> List[Dict]:
    """
    Get list of pending submissions for review.

    Args:
        brand: Optional brand filter
        priority: Optional priority filter

    Returns:
        List of submission dicts
    """
    import frappe

    filters = {"submission_status": ["in", ["Submitted", "Under Review"]]}

    if brand:
        filters["brand"] = brand

    if priority:
        filters["priority"] = priority

    return frappe.get_all(
        "Partner Submission",
        filters=filters,
        fields=[
            "name", "product_name", "product_code", "brand",
            "submission_status", "priority", "quality_score",
            "portal_user", "submission_date"
        ],
        order_by="priority desc, submission_date asc"
    )


def get_partner_submissions(portal_user: str, status: str = None) -> List[Dict]:
    """
    Get submissions for a specific portal user.

    Args:
        portal_user: Portal user name
        status: Optional status filter

    Returns:
        List of submission dicts
    """
    import frappe

    filters = {"portal_user": portal_user}

    if status:
        filters["submission_status"] = status

    return frappe.get_all(
        "Partner Submission",
        filters=filters,
        fields=[
            "name", "product_name", "product_code",
            "submission_status", "quality_score",
            "submission_date", "created_item"
        ],
        order_by="creation desc"
    )


def approve_submission(name: str, notes: str = None) -> bool:
    """
    Approve a submission programmatically.

    Args:
        name: Submission name
        notes: Optional review notes

    Returns:
        True if successful
    """
    import frappe

    try:
        doc = frappe.get_doc("Partner Submission", name)

        if doc.submission_status not in ["Submitted", "Under Review"]:
            frappe.throw(f"Cannot approve submission with status: {doc.submission_status}")

        doc.submission_status = "Approved"
        if notes:
            doc.review_notes = notes
        doc.save(ignore_permissions=True)

        return True

    except Exception as e:
        frappe.logger().error(f"Error approving submission {name}: {str(e)}")
        return False


def reject_submission(name: str, reason: str = None) -> bool:
    """
    Reject a submission programmatically.

    Args:
        name: Submission name
        reason: Rejection reason

    Returns:
        True if successful
    """
    import frappe

    try:
        doc = frappe.get_doc("Partner Submission", name)

        if doc.submission_status not in ["Submitted", "Under Review"]:
            frappe.throw(f"Cannot reject submission with status: {doc.submission_status}")

        doc.submission_status = "Rejected"
        if reason:
            doc.rejection_reason = reason
        doc.save(ignore_permissions=True)

        return True

    except Exception as e:
        frappe.logger().error(f"Error rejecting submission {name}: {str(e)}")
        return False


# =============================================================================
# Frappe Document Class (created when Frappe is available)
# =============================================================================

try:
    import frappe
    from frappe.model.document import Document

    class PartnerSubmission(Document):
        """Partner Submission Document"""

        def validate(self):
            """Validate the document before saving"""
            validate_submission(self)

        def after_insert(self):
            """Handle after insert event"""
            on_submission_insert(self)

        def on_update(self):
            """Handle update event"""
            on_submission_update(self)

        def on_submit(self):
            """Handle Frappe submit event"""
            on_submission_submit(self)

        def approve(self, notes: str = None):
            """Approve this submission"""
            return approve_submission(self.name, notes)

        def reject(self, reason: str = None):
            """Reject this submission"""
            return reject_submission(self.name, reason)

        def get_quality_score(self) -> float:
            """Get/recalculate quality score"""
            return _calculate_quality_score(self)

except ImportError:
    # Frappe not available, use stub class
    pass


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Document class
    "PartnerSubmission",
    # Event handlers
    "validate_submission",
    "on_submission_insert",
    "on_submission_update",
    "on_submission_submit",
    # Utility functions
    "get_pending_submissions",
    "get_partner_submissions",
    "approve_submission",
    "reject_submission",
    "create_item_from_submission",
    # Constants
    "VALID_STATUS_TRANSITIONS",
    "REQUIRED_FIELDS",
    "QUALITY_WEIGHTS",
]
