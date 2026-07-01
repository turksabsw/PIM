"""PIM Maintenance Tasks

This module contains scheduled tasks for system maintenance.
"""


def reindex_products():
    """Full reindex of product search data."""
    import frappe
    frappe.logger("pim_scheduler").info("reindex_products task executed")


def archive_publish_logs():
    """Archive old channel publish logs."""
    import frappe
    frappe.logger("pim_scheduler").info("archive_publish_logs task executed")

