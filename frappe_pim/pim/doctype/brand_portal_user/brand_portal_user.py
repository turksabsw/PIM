# Copyright (c) 2024, Frappe PIM and contributors
# For license information, please see license.txt

"""
Brand Portal User DocType Controller

Manages brand portal users who can submit and manage product data
for their associated brands. Provides access control, permission
management, and activity tracking.

Key Features:
- User validation and permission management
- Activity tracking (submissions, logins)
- Status management (Active, Inactive, Suspended)
- Monthly submission limits
- Role-based permissions (Brand User, Manager, Admin)

Event Handlers:
- validate_portal_user: Validation before save
- on_portal_user_insert: Called after new user is created
- on_portal_user_update: Called after user is updated

Note: frappe imports are deferred to function/method level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from typing import Dict, List, Optional
from datetime import datetime


# =============================================================================
# Constants
# =============================================================================

# Portal roles with their default permissions
PORTAL_ROLE_PERMISSIONS = {
    "Brand User": {
        "can_submit_products": True,
        "can_edit_products": True,
        "can_view_analytics": False,
        "can_manage_media": True,
        "can_approve_submissions": False,
        "can_manage_users": False,
    },
    "Brand Manager": {
        "can_submit_products": True,
        "can_edit_products": True,
        "can_view_analytics": True,
        "can_manage_media": True,
        "can_approve_submissions": True,
        "can_manage_users": False,
    },
    "Brand Admin": {
        "can_submit_products": True,
        "can_edit_products": True,
        "can_view_analytics": True,
        "can_manage_media": True,
        "can_approve_submissions": True,
        "can_manage_users": True,
    },
}

# Status transitions
VALID_STATUS_TRANSITIONS = {
    "Pending Approval": ["Active", "Inactive", "Suspended"],
    "Active": ["Inactive", "Suspended"],
    "Inactive": ["Active", "Suspended"],
    "Suspended": ["Active", "Inactive"],
}

# Notification template for new portal user
NEW_USER_NOTIFICATION_TEMPLATE = """
<h3>New Brand Portal User Registration</h3>

<p>A new brand portal user has registered and requires approval:</p>

<table style="border-collapse: collapse; width: 100%;">
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>User:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{full_name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Email:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{email}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Brand:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{brand_name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Company:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{company_name}</td>
    </tr>
    <tr>
        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Requested Role:</strong></td>
        <td style="padding: 8px; border: 1px solid #ddd;">{portal_role}</td>
    </tr>
</table>

<p>
    <a href="{doc_url}" style="background: #5e64ff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">
        Review Now
    </a>
</p>
"""


# =============================================================================
# Document Class
# =============================================================================

class BrandPortalUser:
    """
    Controller for Brand Portal User DocType.

    Note: This is implemented as a regular class rather than inheriting from
    frappe.model.document.Document to allow importing without Frappe.
    The actual Document subclass is created at module load time when
    Frappe is available.
    """

    pass  # Methods are added dynamically when Frappe is available


# =============================================================================
# Document Event Handlers
# =============================================================================

def validate_portal_user(doc, method=None):
    """
    Validation handler for Brand Portal User.

    This function validates:
    1. User exists and is enabled
    2. Brand exists and is enabled
    3. User is not already a portal user for another brand
    4. Status transitions are valid
    5. Permission combinations are valid for the role

    Args:
        doc: The Brand Portal User document
        method: Event method name (unused, for Frappe compatibility)

    Usage in hooks.py:
        doc_events = {
            "Brand Portal User": {
                "validate": "frappe_pim.pim.doctype.brand_portal_user.brand_portal_user.validate_portal_user"
            }
        }
    """
    import frappe

    # Validate user exists and is enabled
    if doc.user:
        user = frappe.get_doc("User", doc.user)
        if not user.enabled:
            frappe.throw(
                f"User {doc.user} is disabled. Please enable the user first.",
                title="Invalid User"
            )

    # Validate brand exists and is enabled
    if doc.brand:
        if not frappe.db.exists("Brand", doc.brand):
            frappe.throw(
                f"Brand {doc.brand} does not exist.",
                title="Invalid Brand"
            )

        brand = frappe.get_doc("Brand", doc.brand)
        if hasattr(brand, "enabled") and not brand.enabled:
            frappe.throw(
                f"Brand {doc.brand} is disabled.",
                title="Invalid Brand"
            )

    # Check for duplicate portal user
    if doc.user and doc.is_new():
        existing = frappe.db.exists(
            "Brand Portal User",
            {"user": doc.user, "name": ["!=", doc.name]}
        )
        if existing:
            frappe.throw(
                f"User {doc.user} is already registered as a portal user.",
                title="Duplicate User"
            )

    # Validate status transition
    if not doc.is_new() and doc.has_value_changed("status"):
        old_doc = doc.get_doc_before_save()
        if old_doc:
            old_status = old_doc.status
            new_status = doc.status

            valid_transitions = VALID_STATUS_TRANSITIONS.get(old_status, [])
            if new_status not in valid_transitions:
                frappe.throw(
                    f"Cannot change status from '{old_status}' to '{new_status}'. "
                    f"Valid transitions: {', '.join(valid_transitions)}",
                    title="Invalid Status Transition"
                )

    # Apply role-based permission defaults for new users
    if doc.is_new() and doc.portal_role:
        _apply_role_permissions(doc)

    # Validate monthly submission limit
    if doc.max_submissions_per_month < 0:
        frappe.throw(
            "Max submissions per month cannot be negative.",
            title="Invalid Limit"
        )


def on_portal_user_insert(doc, method=None):
    """
    Event handler called after a new Brand Portal User is created.

    This function:
    1. Assigns Brand Portal role to the user
    2. Sends notification to PIM Managers for approval
    3. Logs the new registration

    Args:
        doc: The Brand Portal User document
        method: Event method name (unused, for Frappe compatibility)

    Usage in hooks.py:
        doc_events = {
            "Brand Portal User": {
                "after_insert": "frappe_pim.pim.doctype.brand_portal_user.brand_portal_user.on_portal_user_insert"
            }
        }
    """
    import frappe

    # Assign Brand Portal User role if not already assigned
    if doc.user:
        _assign_portal_role(doc.user)

    # Send notification for approval if status is Pending
    if doc.status == "Pending Approval":
        _send_approval_notification(doc)

    # Log the new registration
    frappe.logger().info(
        f"New brand portal user registered: {doc.user} for brand {doc.brand}"
    )


def on_portal_user_update(doc, method=None):
    """
    Event handler called after a Brand Portal User is updated.

    This function:
    1. Handles status changes (activation, suspension)
    2. Updates user permissions based on role changes
    3. Tracks activity changes

    Args:
        doc: The Brand Portal User document
        method: Event method name (unused, for Frappe compatibility)

    Usage in hooks.py:
        doc_events = {
            "Brand Portal User": {
                "on_update": "frappe_pim.pim.doctype.brand_portal_user.brand_portal_user.on_portal_user_update"
            }
        }
    """
    import frappe

    # Handle status changes
    if doc.has_value_changed("status"):
        old_doc = doc.get_doc_before_save()
        old_status = old_doc.status if old_doc else None

        if doc.status == "Active" and old_status == "Pending Approval":
            # User approved
            doc.approved_on = frappe.utils.now_datetime()
            doc.approved_by = frappe.session.user
            doc.db_update()

            # Enable user access
            _enable_user_access(doc)

            # Send welcome notification
            _send_welcome_notification(doc)

        elif doc.status == "Suspended":
            # User suspended
            doc.suspended_on = frappe.utils.now_datetime()
            doc.suspended_by = frappe.session.user
            doc.db_update()

            # Disable user access
            _disable_user_access(doc)

            # Send suspension notification
            _send_suspension_notification(doc)

        elif doc.status == "Inactive":
            # User deactivated
            _disable_user_access(doc)

        elif doc.status == "Active" and old_status in ["Inactive", "Suspended"]:
            # User reactivated
            _enable_user_access(doc)

    # Handle role changes
    if doc.has_value_changed("portal_role"):
        _apply_role_permissions(doc)
        doc.db_update()


# =============================================================================
# Role and Permission Management
# =============================================================================

def _apply_role_permissions(doc):
    """
    Apply default permissions based on portal role.

    Args:
        doc: The Brand Portal User document
    """
    role_permissions = PORTAL_ROLE_PERMISSIONS.get(doc.portal_role, {})

    for field, value in role_permissions.items():
        if hasattr(doc, field):
            setattr(doc, field, 1 if value else 0)


def _assign_portal_role(user_name: str):
    """
    Assign Brand Portal User role to the Frappe user.

    Args:
        user_name: The user's name/email
    """
    import frappe

    try:
        user = frappe.get_doc("User", user_name)

        # Check if role already exists
        has_role = any(r.role == "Brand Portal User" for r in user.roles)

        if not has_role:
            user.append("roles", {"role": "Brand Portal User"})
            user.save(ignore_permissions=True)

    except Exception as e:
        frappe.logger().error(f"Error assigning portal role to {user_name}: {str(e)}")


def _enable_user_access(doc):
    """
    Enable portal access for the user.

    Args:
        doc: The Brand Portal User document
    """
    import frappe

    try:
        if doc.user:
            user = frappe.get_doc("User", doc.user)

            # Ensure user is enabled
            if not user.enabled:
                user.enabled = 1
                user.save(ignore_permissions=True)

            # Ensure portal role is assigned
            _assign_portal_role(doc.user)

    except Exception as e:
        frappe.logger().error(f"Error enabling user access for {doc.user}: {str(e)}")


def _disable_user_access(doc):
    """
    Disable portal access for the user.

    Args:
        doc: The Brand Portal User document
    """
    import frappe

    try:
        if doc.user:
            user = frappe.get_doc("User", doc.user)

            # Remove Brand Portal User role
            user.roles = [r for r in user.roles if r.role != "Brand Portal User"]
            user.save(ignore_permissions=True)

    except Exception as e:
        frappe.logger().error(f"Error disabling user access for {doc.user}: {str(e)}")


# =============================================================================
# Notification Functions
# =============================================================================

def _send_approval_notification(doc):
    """
    Send notification to PIM Managers about new user requiring approval.

    Args:
        doc: The Brand Portal User document
    """
    import frappe

    try:
        recipients = _get_pim_managers()

        if not recipients:
            return

        doc_url = frappe.utils.get_url_to_form("Brand Portal User", doc.name)

        message = NEW_USER_NOTIFICATION_TEMPLATE.format(
            full_name=doc.full_name or doc.user,
            email=doc.email or "",
            brand_name=doc.brand_name or doc.brand,
            company_name=doc.company_name or "(Not specified)",
            portal_role=doc.portal_role,
            doc_url=doc_url,
        )

        subject = f"New Brand Portal User: {doc.full_name or doc.user}"

        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message,
            delayed=True,
            reference_doctype="Brand Portal User",
            reference_name=doc.name,
        )

    except Exception as e:
        frappe.logger().error(f"Error sending approval notification: {str(e)}")


def _send_welcome_notification(doc):
    """
    Send welcome notification to the approved user.

    Args:
        doc: The Brand Portal User document
    """
    import frappe

    try:
        if not doc.email:
            return

        portal_url = frappe.utils.get_url("/brand-portal")

        message = f"""
<h3>Welcome to the Brand Portal!</h3>

<p>Dear {doc.full_name or doc.user},</p>

<p>Your Brand Portal account has been approved. You can now access the portal to manage product data for <strong>{doc.brand_name or doc.brand}</strong>.</p>

<p>Your account details:</p>
<ul>
    <li><strong>Role:</strong> {doc.portal_role}</li>
    <li><strong>Max Submissions/Month:</strong> {doc.max_submissions_per_month or 'Unlimited'}</li>
</ul>

<p>
    <a href="{portal_url}" style="background: #5e64ff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">
        Access Brand Portal
    </a>
</p>

<p>If you have any questions, please contact our support team.</p>
"""

        frappe.sendmail(
            recipients=[doc.email],
            subject=f"Welcome to Brand Portal - {doc.brand_name or doc.brand}",
            message=message,
            delayed=True,
            reference_doctype="Brand Portal User",
            reference_name=doc.name,
        )

    except Exception as e:
        frappe.logger().error(f"Error sending welcome notification: {str(e)}")


def _send_suspension_notification(doc):
    """
    Send suspension notification to the user.

    Args:
        doc: The Brand Portal User document
    """
    import frappe

    try:
        if not doc.email:
            return

        message = f"""
<h3>Brand Portal Account Suspended</h3>

<p>Dear {doc.full_name or doc.user},</p>

<p>Your Brand Portal account for <strong>{doc.brand_name or doc.brand}</strong> has been suspended.</p>

{f'<p><strong>Reason:</strong> {doc.suspension_reason}</p>' if doc.suspension_reason else ''}

<p>If you believe this is an error, please contact our support team for assistance.</p>
"""

        frappe.sendmail(
            recipients=[doc.email],
            subject=f"Brand Portal Account Suspended - {doc.brand_name or doc.brand}",
            message=message,
            delayed=True,
            reference_doctype="Brand Portal User",
            reference_name=doc.name,
        )

    except Exception as e:
        frappe.logger().error(f"Error sending suspension notification: {str(e)}")


def _get_pim_managers() -> List[str]:
    """
    Get list of PIM Manager email addresses.

    Returns:
        List of email addresses
    """
    import frappe

    recipients = []

    try:
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


# =============================================================================
# Utility Functions
# =============================================================================

def get_portal_user_for_brand(brand: str, user: str = None) -> Optional[Dict]:
    """
    Get portal user for a specific brand.

    Args:
        brand: Brand name
        user: Optional user filter (defaults to current user)

    Returns:
        Portal user dict or None
    """
    import frappe

    if not user:
        user = frappe.session.user

    portal_user = frappe.get_all(
        "Brand Portal User",
        filters={"brand": brand, "user": user, "status": "Active"},
        fields=["*"],
        limit=1
    )

    return portal_user[0] if portal_user else None


def get_active_portal_users(brand: str = None) -> List[Dict]:
    """
    Get list of active portal users.

    Args:
        brand: Optional brand filter

    Returns:
        List of portal user dicts
    """
    import frappe

    filters = {"status": "Active"}

    if brand:
        filters["brand"] = brand

    return frappe.get_all(
        "Brand Portal User",
        filters=filters,
        fields=[
            "name", "user", "full_name", "email", "brand",
            "brand_name", "portal_role", "total_submissions"
        ],
        order_by="full_name asc"
    )


def activate_portal_user(name: str, notes: str = None) -> bool:
    """
    Activate a portal user.

    Args:
        name: Portal user name
        notes: Optional approval notes

    Returns:
        True if successful
    """
    import frappe

    try:
        doc = frappe.get_doc("Brand Portal User", name)

        if doc.status not in ["Pending Approval", "Inactive", "Suspended"]:
            frappe.throw(f"Cannot activate user with status: {doc.status}")

        doc.status = "Active"
        if notes:
            doc.approval_notes = notes
        doc.save(ignore_permissions=True)

        return True

    except Exception as e:
        frappe.logger().error(f"Error activating portal user {name}: {str(e)}")
        return False


def deactivate_portal_user(name: str, notes: str = None) -> bool:
    """
    Deactivate a portal user.

    Args:
        name: Portal user name
        notes: Optional notes

    Returns:
        True if successful
    """
    import frappe

    try:
        doc = frappe.get_doc("Brand Portal User", name)

        if doc.status != "Active":
            frappe.throw(f"Cannot deactivate user with status: {doc.status}")

        doc.status = "Inactive"
        if notes:
            doc.notes = notes
        doc.save(ignore_permissions=True)

        return True

    except Exception as e:
        frappe.logger().error(f"Error deactivating portal user {name}: {str(e)}")
        return False


def suspend_portal_user(name: str, reason: str = None) -> bool:
    """
    Suspend a portal user.

    Args:
        name: Portal user name
        reason: Suspension reason

    Returns:
        True if successful
    """
    import frappe

    try:
        doc = frappe.get_doc("Brand Portal User", name)

        if doc.status == "Suspended":
            frappe.throw("User is already suspended")

        doc.status = "Suspended"
        if reason:
            doc.suspension_reason = reason
        doc.save(ignore_permissions=True)

        return True

    except Exception as e:
        frappe.logger().error(f"Error suspending portal user {name}: {str(e)}")
        return False


def reset_monthly_submissions():
    """
    Reset monthly submission counters for all portal users.
    Called by scheduler at the start of each month.
    """
    import frappe

    try:
        frappe.db.sql("""
            UPDATE `tabBrand Portal User`
            SET current_month_submissions = 0
            WHERE current_month_submissions > 0
        """)
        frappe.db.commit()

        frappe.logger().info("Reset monthly submission counters for all portal users")

    except Exception as e:
        frappe.logger().error(f"Error resetting monthly submissions: {str(e)}")


def update_submission_stats(portal_user_name: str, status_change: str = None):
    """
    Update submission statistics for a portal user.

    Args:
        portal_user_name: Portal user name
        status_change: New submission status ('submitted', 'approved', 'rejected')
    """
    import frappe

    try:
        doc = frappe.get_doc("Brand Portal User", portal_user_name)

        if status_change == "submitted":
            doc.total_submissions = (doc.total_submissions or 0) + 1
            doc.current_month_submissions = (doc.current_month_submissions or 0) + 1
            doc.pending_submissions = (doc.pending_submissions or 0) + 1
            doc.last_submission = frappe.utils.now_datetime()

        elif status_change == "approved":
            doc.approved_submissions = (doc.approved_submissions or 0) + 1
            doc.pending_submissions = max((doc.pending_submissions or 0) - 1, 0)

        elif status_change == "rejected":
            doc.rejected_submissions = (doc.rejected_submissions or 0) + 1
            doc.pending_submissions = max((doc.pending_submissions or 0) - 1, 0)

        doc.db_update()

    except Exception as e:
        frappe.logger().error(
            f"Error updating submission stats for {portal_user_name}: {str(e)}"
        )


def record_portal_login(user: str):
    """
    Record portal login timestamp for a user.

    Args:
        user: User name/email
    """
    import frappe

    try:
        portal_user = frappe.get_all(
            "Brand Portal User",
            filters={"user": user, "status": "Active"},
            pluck="name",
            limit=1
        )

        if portal_user:
            frappe.db.set_value(
                "Brand Portal User",
                portal_user[0],
                "last_login",
                frappe.utils.now_datetime(),
                update_modified=False
            )

    except Exception as e:
        frappe.logger().error(f"Error recording portal login for {user}: {str(e)}")


# =============================================================================
# Frappe Document Class (created when Frappe is available)
# =============================================================================

try:
    import frappe
    from frappe.model.document import Document

    class BrandPortalUser(Document):
        """Brand Portal User Document"""

        def validate(self):
            """Validate the document before saving"""
            validate_portal_user(self)

        def after_insert(self):
            """Handle after insert event"""
            on_portal_user_insert(self)

        def on_update(self):
            """Handle update event"""
            on_portal_user_update(self)

        def activate(self, notes: str = None):
            """Activate this portal user"""
            return activate_portal_user(self.name, notes)

        def deactivate(self, notes: str = None):
            """Deactivate this portal user"""
            return deactivate_portal_user(self.name, notes)

        def suspend(self, reason: str = None):
            """Suspend this portal user"""
            return suspend_portal_user(self.name, reason)

        def can_submit(self) -> bool:
            """Check if user can submit products"""
            if self.status != "Active":
                return False
            if not self.can_submit_products:
                return False
            if self.max_submissions_per_month > 0:
                if (self.current_month_submissions or 0) >= self.max_submissions_per_month:
                    return False
            return True

except ImportError:
    # Frappe not available, use stub class
    pass


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Document class
    "BrandPortalUser",
    # Event handlers
    "validate_portal_user",
    "on_portal_user_insert",
    "on_portal_user_update",
    # Utility functions
    "get_portal_user_for_brand",
    "get_active_portal_users",
    "activate_portal_user",
    "deactivate_portal_user",
    "suspend_portal_user",
    "reset_monthly_submissions",
    "update_submission_stats",
    "record_portal_login",
    # Constants
    "PORTAL_ROLE_PERMISSIONS",
    "VALID_STATUS_TRANSITIONS",
]
