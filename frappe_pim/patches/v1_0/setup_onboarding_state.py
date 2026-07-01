"""Patch: Setup PIM Onboarding State and initial configuration data.

Creates initial onboarding state records for existing PIM users and ensures
standard attribute types, attribute groups, and conflict resolution rules
are installed. All operations are idempotent — safe to run multiple times.

This patch runs during `bench migrate` for v1.0 installations.
"""

import frappe
from frappe import _


def execute():
    """Main patch entry point.

    Performs the following setup steps:
    1. Install standard PIM Attribute Types (12 types)
    2. Install standard PIM Attribute Groups (5+ groups)
    3. Install default sync conflict resolution rules
    4. Create PIM Onboarding State for existing PIM Manager users
    5. Ensure required database indexes exist
    """
    _install_standard_attribute_types()
    _install_standard_attribute_groups()
    _install_default_conflict_rules()
    _create_onboarding_states()
    _ensure_indexes()


def _install_standard_attribute_types():
    """Install the 12 standard attribute types if they don't exist.

    Delegates to the install function in PIM Attribute Type controller.
    Silently skips if the DocType doesn't exist yet (first install).
    """
    if not frappe.db.exists("DocType", "PIM Attribute Type"):
        return

    try:
        from frappe_pim.pim.doctype.pim_attribute_type.pim_attribute_type import (
            install_standard_types,
        )
        install_standard_types()
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="PIM Patch: Failed to install standard attribute types",
            message=frappe.get_traceback(),
        )


def _install_standard_attribute_groups():
    """Install the standard attribute groups if they don't exist.

    Delegates to the install function in PIM Attribute Group controller.
    Silently skips if the DocType doesn't exist yet (first install).
    """
    if not frappe.db.exists("DocType", "PIM Attribute Group"):
        return

    try:
        from frappe_pim.pim.doctype.pim_attribute_group.pim_attribute_group import (
            install_standard_groups,
        )
        install_standard_groups()
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="PIM Patch: Failed to install standard attribute groups",
            message=frappe.get_traceback(),
        )


def _install_default_conflict_rules():
    """Install default sync conflict resolution rules if they don't exist.

    Silently skips if the DocType doesn't exist yet (first install).
    """
    if not frappe.db.exists("DocType", "PIM Sync Conflict Rule"):
        return

    try:
        from frappe_pim.pim.doctype.pim_sync_conflict_rule.pim_sync_conflict_rule import (
            create_default_rules,
        )
        create_default_rules()
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="PIM Patch: Failed to install default conflict rules",
            message=frappe.get_traceback(),
        )


def _create_onboarding_states():
    """Create PIM Onboarding State records for existing PIM users.

    For each user with the PIM Manager role who doesn't already have an
    onboarding state, creates one in 'pending' status. This handles the
    upgrade scenario where PIM is installed on an existing site.
    """
    if not frappe.db.exists("DocType", "PIM Onboarding State"):
        return

    try:
        # Get users with PIM Manager role who don't have an onboarding state
        pim_managers = frappe.get_all(
            "Has Role",
            filters={
                "role": "PIM Manager",
                "parenttype": "User",
            },
            fields=["parent"],
            distinct=True,
        )

        if not pim_managers:
            # If no PIM Managers yet, create for Administrator
            pim_managers = [{"parent": "Administrator"}]

        for user_entry in pim_managers:
            user = user_entry.get("parent")

            if not user:
                continue

            # Skip disabled users
            if user != "Administrator" and not frappe.db.get_value(
                "User", user, "enabled"
            ):
                continue

            # Check if onboarding state already exists for this user
            existing = frappe.db.exists(
                "PIM Onboarding State", {"user": user}
            )

            if existing:
                continue

            doc = frappe.new_doc("PIM Onboarding State")
            doc.user = user
            doc.current_step = "pending"
            doc.progress_percent = 0
            doc.is_completed = 0
            doc.is_skipped = 0
            doc.insert(ignore_permissions=True)

        frappe.db.commit()

    except Exception:
        frappe.log_error(
            title="PIM Patch: Failed to create onboarding states",
            message=frappe.get_traceback(),
        )


def _ensure_indexes():
    """Create database indexes for optimal PIM query performance.

    All indexes use IF NOT EXISTS so they are safe to run repeatedly.
    """
    indexes = [
        # EAV composite index for faster attribute value lookups
        (
            "tabProduct Attribute Value",
            "idx_pav_parent_attr",
            "(parent, attribute)",
        ),
        # Sync queue indexes for efficient queue processing
        (
            "tabPIM Sync Queue Entry",
            "idx_sq_status_created",
            "(sync_status, creation)",
        ),
        # Onboarding state lookup by user
        (
            "tabPIM Onboarding State",
            "idx_pos_user",
            "(user)",
        ),
    ]

    for table, index_name, columns in indexes:
        try:
            frappe.db.sql(
                "CREATE INDEX IF NOT EXISTS `{index}` ON `{table}` {cols}".format(
                    index=index_name,
                    table=table,
                    cols=columns,
                )
            )
        except Exception:
            # Table may not exist yet during first migration
            pass
