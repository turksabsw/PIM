"""
Migrate Tenant Config from Single DocType to per-user DocType.

Previously Tenant Config was a Single (one per site), meaning all users
shared the same onboarding config. This patch creates a per-user record
for the administrator using the existing Single data, then removes the
Single entries so they don't conflict with the new table-based approach.
"""

import frappe


def execute():
    # Read existing data from tabSingles before the table is created
    singles_rows = frappe.db.sql(
        "SELECT field, value FROM `tabSingles` WHERE doctype = 'Tenant Config'",
        as_dict=True,
    )
    existing_data = {row.field: row.value for row in singles_rows}

    if not existing_data:
        return  # Nothing to migrate

    # Determine which user performed the original onboarding
    admin_user = existing_data.get("owner") or "Administrator"

    # Skip if a per-user record already exists for this user
    if frappe.db.exists("Tenant Config", admin_user):
        return

    doc = frappe.new_doc("Tenant Config")
    doc.user = admin_user

    # Fields to skip (meta / system fields that don't belong in the new record)
    skip_fields = {
        "doctype", "name", "creation", "modified", "owner",
        "modified_by", "docstatus", "idx",
    }

    for field, value in existing_data.items():
        if field in skip_fields:
            continue
        if hasattr(doc, field) and value is not None:
            doc.set(field, value)

    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    # Clean up old Single data so it doesn't cause confusion
    frappe.db.sql(
        "DELETE FROM `tabSingles` WHERE doctype = 'Tenant Config'"
    )
    frappe.db.commit()
