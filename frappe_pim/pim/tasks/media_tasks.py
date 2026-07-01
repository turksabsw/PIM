"""PIM Media Tasks

This module contains scheduled tasks for media operations.
"""


def generate_pending_variants():
    """Generate channel-specific image variants for new media."""
    import frappe
    frappe.logger("pim_scheduler").info("generate_pending_variants task executed")

