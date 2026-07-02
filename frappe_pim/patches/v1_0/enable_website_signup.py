import frappe


def execute():
    """Enable public website signup so the SPA register tab works."""
    ws = frappe.get_single("Website Settings")
    if ws.disable_signup:
        ws.disable_signup = 0
        ws.save(ignore_permissions=True)
        frappe.db.commit()
