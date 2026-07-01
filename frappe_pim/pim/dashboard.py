"""PIM Dashboard Extensions

This module provides dashboard data extensions for Frappe DocTypes.
Currently extends the ERPNext Item dashboard with PIM-related links
and information.
"""


def get_item_dashboard_data(data):
    """Add PIM links to ERPNext Item dashboard.
    
    This function is called by Frappe when rendering the Item dashboard
    to add PIM-specific links and information.
    
    Args:
        data: Dictionary containing dashboard data for the Item DocType.
              This function modifies it in-place to add PIM-related items.
    
    The data dictionary typically contains:
        - fieldname: Field name being displayed
        - items: List of dashboard items (links, buttons, etc.)
        - transactions: List of related transactions
        - charts: List of dashboard charts
    
    This function adds:
        - Link to related Product Master (if exists)
        - Link to Product Variant (if exists)
        - Quick actions for PIM operations
    """
    import frappe
    
    try:
        # Get the current Item document name
        item_name = data.get("name") or frappe.form_dict.get("name")
        
        if not item_name:
            return data
        
        # Check if Item has related Product Variant
        product_variant = frappe.db.get_value(
            "Product Variant",
            {"erpnext_item": item_name},
            "name"
        )
        
        # Check if Product Variant has related Product Master
        product_master = None
        if product_variant:
            product_master = frappe.db.get_value(
                "Product Variant",
                product_variant,
                "product"
            )
        
        # Add PIM section to dashboard items if not already present
        if "items" not in data:
            data["items"] = []
        
        # Add PIM links if Product Master exists
        if product_master:
            pim_items = [
                {
                    "type": "link",
                    "label": "Product Master",
                    "name": product_master,
                    "link": f"/app/product-master/{product_master}",
                    "description": "View Product Master in PIM",
                }
            ]
            
            if product_variant:
                pim_items.append({
                    "type": "link",
                    "label": "Product Variant",
                    "name": product_variant,
                    "link": f"/app/product-variant/{product_variant}",
                    "description": "View Product Variant in PIM",
                })
            
            # Add PIM items to dashboard
            data["items"].extend(pim_items)
        
        # Add PIM quick actions if user has permission
        user = frappe.session.user
        if user and user != "Guest":
            has_pim_access = frappe.has_permission("Product Master", "read", user=user)
            
            if has_pim_access and not product_master:
                # Add action to create Product Master from Item
                data["items"].append({
                    "type": "action",
                    "label": "Create Product Master",
                    "action": f"frappe_pim.pim.api.product.create_from_item",
                    "description": "Create Product Master from this Item",
                })
    
    except Exception as e:
        # Log error but don't break dashboard
        frappe.log_error(
            message=f"Error in PIM get_item_dashboard_data: {str(e)}",
            title="PIM Dashboard Error"
        )
    
    return data

