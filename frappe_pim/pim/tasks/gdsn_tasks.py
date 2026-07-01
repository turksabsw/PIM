"""PIM GDSN Tasks

This module contains scheduled tasks for GDSN synchronization.
"""


def sync_pending_products():
    """Sync products to GDSN data pools."""
    import frappe
    frappe.logger("pim_scheduler").info("sync_pending_products task executed")

