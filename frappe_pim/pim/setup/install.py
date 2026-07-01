"""PIM Application Installation and Migration Hooks

This module contains lifecycle hooks for the Frappe PIM application:
- after_install: Called after app installation
- after_migrate: Called after database migrations
- before_uninstall: Called before app removal

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def after_install():
    """Run after app installation.

    Creates default roles and attribute groups for PIM functionality.
    """
    import frappe

    create_default_roles()
    create_default_attribute_groups()
    frappe.db.commit()


def after_migrate():
    """Run after bench migrate.

    Ensures required database indexes exist for optimal performance.
    """
    update_indexes()


def before_uninstall():
    """Cleanup before app removal.

    Perform any necessary cleanup when uninstalling the PIM app.
    Currently a placeholder for future cleanup logic.
    """
    pass


def create_default_roles():
    """Create PIM-specific roles if they don't exist.

    Roles:
    - PIM Manager: Full access to all PIM features
    - PIM User: Basic access to view and edit products
    """
    import frappe

    roles = ["PIM Manager", "PIM User"]
    for role in roles:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({
                "doctype": "Role",
                "role_name": role,
                "desk_access": 1,
                "is_custom": 1
            }).insert(ignore_permissions=True)


def create_default_attribute_groups():
    """Create standard attribute groups for organizing attributes.

    Groups:
    - General: Basic product information
    - Dimensions: Size, weight, volume
    - SEO: Search engine optimization fields
    - Technical: Technical specifications
    """
    import frappe

    groups = ["General", "Dimensions", "SEO", "Technical"]

    # Check if PIM Attribute Group DocType exists before creating records
    if not frappe.db.exists("DocType", "PIM Attribute Group"):
        return

    for group in groups:
        if not frappe.db.exists("PIM Attribute Group", group):
            try:
                frappe.get_doc({
                    "doctype": "PIM Attribute Group",
                    "group_name": group,
                    "is_standard": 1
                }).insert(ignore_permissions=True)
            except Exception:
                # DocType may not be installed yet during first migration
                pass


def update_indexes():
    """Ensure required database indexes exist for optimal performance.

    Creates composite indexes on frequently queried columns in EAV tables.
    """
    import frappe

    # EAV composite index for faster attribute value lookups
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_pav_parent_attr
            ON `tabProduct Attribute Value` (parent, attribute)
        """)
    except Exception:
        # Index might already exist or table not yet created
        pass

    # Product family index for faster family-based queries
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_pm_family
            ON `tabProduct Master` (product_family)
        """)
    except Exception:
        pass

    # Completeness score index for filtering incomplete products
    try:
        frappe.db.sql("""
            CREATE INDEX IF NOT EXISTS idx_pm_completeness
            ON `tabProduct Master` (completeness_score)
        """)
    except Exception:
        pass
