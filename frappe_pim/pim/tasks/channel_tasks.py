"""PIM Channel Tasks

This module contains scheduled tasks for channel operations.
"""


def sync_channel_statuses():
    """Sync channel statuses."""
    import frappe
    frappe.logger("pim_scheduler").info("sync_channel_statuses task executed")

