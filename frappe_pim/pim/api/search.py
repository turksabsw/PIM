"""
Custom search functions for PIM DocTypes
"""

import frappe
from frappe import _
from frappe.desk.search import search_link as original_search_link


@frappe.whitelist()
def custom_search_link(doctype, txt, **kwargs):
    """Custom search_link that handles virtual DocTypes like Product Master
    
    Args:
        doctype: DocType to search
        txt: Search text
        **kwargs: Additional parameters
        
    Returns:
        Search results in standard format
    """
    # Handle Product Master and Product Variant (Virtual DocTypes)
    if doctype == "Product Master":
        # Search in Item table
        results = frappe.db.sql("""
            SELECT 
                item_code as value,
                item_name as description
            FROM `tabItem`
            WHERE 
                item_code LIKE %(txt)s 
                OR item_name LIKE %(txt)s
            ORDER BY modified DESC
            LIMIT 20
        """, {"txt": f"%{txt}%"}, as_dict=True)
        
        return {"results": results}
    
    elif doctype == "Product Variant":
        # Search in Item table for variants only
        results = frappe.db.sql("""
            SELECT 
                item_code as value,
                item_name as description
            FROM `tabItem`
            WHERE 
                has_variants = 0
                AND (item_code LIKE %(txt)s OR item_name LIKE %(txt)s)
            ORDER BY modified DESC
            LIMIT 20
        """, {"txt": f"%{txt}%"}, as_dict=True)
        
        return {"results": results}
    
    # For all other DocTypes, use original search_link
    return original_search_link(doctype, txt, **kwargs)


@frappe.whitelist()
def search_product_master(doctype, txt, searchfield, start, page_len, filters):
    """Custom search for Product Master (Virtual DocType)
    
    Since Product Master is a virtual DocType mapping to Item,
    we search Item table and return results in the format expected by Frappe.
    
    Args:
        doctype: DocType name (should be "Product Master")
        txt: Search text
        searchfield: Field to search in
        start: Start index for pagination
        page_len: Number of results per page
        filters: Additional filters
        
    Returns:
        List of tuples: [(item_code, item_name), ...]
    """
    # Search in Item table
    conditions = []
    values = []
    
    if txt:
        conditions.append("(item_code LIKE %(txt)s OR item_name LIKE %(txt)s)")
        values = {"txt": f"%{txt}%"}
    
    # Build WHERE clause
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Execute query
    results = frappe.db.sql(f"""
        SELECT 
            item_code as name,
            item_name
        FROM `tabItem`
        WHERE {where_clause}
        ORDER BY 
            CASE 
                WHEN item_code LIKE %(txt)s THEN 0
                WHEN item_name LIKE %(txt)s THEN 1
                ELSE 2
            END,
            modified DESC
        LIMIT %(start)s, %(page_len)s
    """, {
        "txt": f"%{txt}%" if txt else "%",
        "start": start or 0,
        "page_len": page_len or 20
    })
    
    return results


@frappe.whitelist()
def search_product_variant(doctype, txt, searchfield, start, page_len, filters):
    """Custom search for Product Variant (Virtual DocType)
    
    Args:
        doctype: DocType name (should be "Product Variant")
        txt: Search text
        searchfield: Field to search in
        start: Start index for pagination
        page_len: Number of results per page
        filters: Additional filters
        
    Returns:
        List of tuples: [(item_code, item_name), ...]
    """
    # Search in Item table for variants
    conditions = ["has_variants = 0"]  # Only variants, not templates
    values = {"txt": f"%{txt}%"}
    
    if txt:
        conditions.append("(item_code LIKE %(txt)s OR item_name LIKE %(txt)s)")
    
    # Build WHERE clause
    where_clause = " AND ".join(conditions)
    
    # Execute query
    results = frappe.db.sql(f"""
        SELECT 
            item_code as name,
            item_name
        FROM `tabItem`
        WHERE {where_clause}
        ORDER BY modified DESC
        LIMIT %(start)s, %(page_len)s
    """, {
        "txt": f"%{txt}%" if txt else "%",
        "start": start or 0,
        "page_len": page_len or 20
    })
    
    return results

