"""PIM AI Tasks

This module contains scheduled tasks for AI-related operations.
"""


def process_pending_enrichments():
    """Process pending AI enrichment queue items."""
    import frappe
    frappe.logger("pim_scheduler").info("process_pending_enrichments task executed")


def expire_old_approvals():
    """Process AI approval queue - expire old items."""
    import frappe
    frappe.logger("pim_scheduler").info("expire_old_approvals task executed")


def refresh_translation_memory():
    """Refresh translation memory statistics."""
    import frappe
    frappe.logger("pim_scheduler").info("refresh_translation_memory task executed")

