"""PIM Notification Configuration

This module defines notification configurations for PIM events.
Notifications are sent to users when specific PIM events occur,
such as product approval requests, quality issues, or channel sync failures.
"""


def get_notification_config():
    """Get notification configuration for PIM events.
    
    Returns a dictionary mapping event types to notification settings.
    Each event type can have:
        - enabled: Whether notifications are enabled for this event
        - recipients: List of roles or users who should receive notifications
        - template: Email template name to use
        - subject: Email subject template
        - message: Email message template
    
    Returns:
        dict: Notification configuration dictionary
    
    Example:
        {
            "product_approved": {
                "enabled": True,
                "recipients": ["PIM Manager"],
                "template": "Product Approved",
            },
            "quality_issue": {
                "enabled": True,
                "recipients": ["Data Steward"],
                "template": "Quality Issue",
            },
        }
    """
    import frappe
    
    try:
        # Default notification configuration
        config = {
            "product_approved": {
                "enabled": True,
                "recipients": ["PIM Manager"],
                "template": None,
                "subject": "Product Approved: {product_name}",
                "message": "Product {product_name} has been approved.",
            },
            "product_rejected": {
                "enabled": True,
                "recipients": ["PIM Manager", "PIM User"],
                "template": None,
                "subject": "Product Rejected: {product_name}",
                "message": "Product {product_name} has been rejected. Reason: {reason}",
            },
            "quality_issue": {
                "enabled": True,
                "recipients": ["Data Steward", "PIM Manager"],
                "template": None,
                "subject": "Quality Issue Detected: {product_name}",
                "message": "Quality issue detected for product {product_name}: {issue}",
            },
            "channel_sync_failed": {
                "enabled": True,
                "recipients": ["PIM Manager"],
                "template": None,
                "subject": "Channel Sync Failed: {channel_name}",
                "message": "Failed to sync products to channel {channel_name}. Error: {error}",
            },
            "ai_enrichment_complete": {
                "enabled": True,
                "recipients": ["PIM User"],
                "template": None,
                "subject": "AI Enrichment Complete: {product_name}",
                "message": "AI enrichment has been completed for product {product_name}.",
            },
            "partner_submission": {
                "enabled": True,
                "recipients": ["PIM Manager"],
                "template": None,
                "subject": "New Partner Submission: {product_name}",
                "message": "New partner submission received for product {product_name}.",
            },
        }
        
        # Try to load custom configuration from PIM Settings if it exists
        if frappe.db.exists("DocType", "PIM Settings"):
            try:
                pim_settings = frappe.get_cached_doc("PIM Settings")
                # If PIM Settings has notification config, merge it
                if hasattr(pim_settings, "notification_config"):
                    custom_config = frappe.parse_json(getattr(pim_settings, "notification_config", "{}"))
                    if custom_config:
                        config.update(custom_config)
            except Exception:
                # If PIM Settings doesn't exist or can't be loaded, use defaults
                pass
        
        return config
    
    except Exception as e:
        frappe.log_error(
            message=f"Error in get_notification_config: {str(e)}",
            title="PIM Notification Config Error"
        )
        # Return minimal default config on error
        return {
            "product_approved": {
                "enabled": True,
                "recipients": ["PIM Manager"],
                "template": None,
                "subject": "Product Approved: {product_name}",
                "message": "Product {product_name} has been approved.",
            },
        }

