"""PIM Reporting Tasks

This module contains scheduled tasks for reporting.
"""


def generate_compliance_report():
    """Generate monthly compliance report."""
    import frappe
    frappe.logger("pim_scheduler").info("generate_compliance_report task executed")

