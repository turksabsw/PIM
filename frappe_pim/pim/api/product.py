"""PIM Product API Endpoints

This module provides whitelisted API endpoints for Product Master CRUD operations.
Product Master is a Virtual DocType backed by ERPNext Item, so all operations
use the Frappe Document API (not raw SQL) to respect Virtual DocType abstraction.

Endpoints:
- get_products: List products with filtering and pagination
- get_product_detail: Get full product details with attributes
- create_product: Create a new product
- update_product: Update an existing product
- delete_product: Delete a product
- bulk_update_products: Bulk update a field across multiple products
- get_product_families: List product families for dropdowns
- get_product_statuses: List available status options
"""

import frappe
from frappe import _
from typing import Dict, List, Optional, Any
import json


@frappe.whitelist()
def get_products(
    product_family=None,
    status=None,
    search=None,
    completeness_min=None,
    completeness_max=None,
    page=1,
    page_size=50,
    order_by="modified",
    order_dir="desc",
    fields=None
):
    """Get list of products with filtering and pagination.

    Args:
        product_family: Filter by Product Family name
        status: Filter by status (Draft, Active, Inactive, Archived)
        search: Search term for product_name, product_code, or short_description
        completeness_min: Minimum completeness score (0-100)
        completeness_max: Maximum completeness score (0-100)
        page: Page number (1-based, default: 1)
        page_size: Number of products per page (default: 50, max: 200)
        order_by: Field to order by (default: modified)
        order_dir: Order direction - asc or desc (default: desc)
        fields: JSON list of fields to return (optional)

    Returns:
        dict: Paginated product list with metadata
            - products: List of product records
            - total: Total count matching filters
            - page: Current page number
            - page_size: Items per page
            - total_pages: Total number of pages

    Example:
        >>> result = get_products(status="Active", page=1, page_size=20)
        >>> print(f"Found {result['total']} products")
    """
    # Permission check
    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted to read products"), frappe.PermissionError)

    # Validate and sanitize parameters
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))

    # Build filters
    filters = {}

    if product_family:
        filters["product_family"] = product_family

    if status:
        filters["status"] = status

    if completeness_min is not None:
        filters["completeness_score"] = [">=", float(completeness_min)]

    if completeness_max is not None:
        if "completeness_score" in filters:
            # Both min and max specified
            filters["completeness_score"] = [
                "between",
                [float(completeness_min or 0), float(completeness_max)]
            ]
        else:
            filters["completeness_score"] = ["<=", float(completeness_max)]

    # Handle search
    or_filters = None
    if search:
        search_term = f"%{search}%"
        or_filters = [
            ["product_name", "like", search_term],
            ["product_code", "like", search_term],
            ["short_description", "like", search_term]
        ]

    # Determine fields to return
    if fields:
        if isinstance(fields, str):
            fields = json.loads(fields)
    else:
        fields = [
            "name", "product_name", "product_code", "status",
            "short_description", "product_family", "completeness_score",
            "image", "creation", "modified"
        ]

    # Validate order_by field
    allowed_order_fields = [
        "name", "product_name", "product_code", "status",
        "completeness_score", "creation", "modified"
    ]
    if order_by not in allowed_order_fields:
        order_by = "modified"

    order_dir = "desc" if order_dir.lower() not in ["asc", "desc"] else order_dir.lower()

    # Get total count - use frappe.get_all with limit_page_length=0
    # because Product Master is a Virtual DocType (no tabProduct Master table)
    count_args = {
        "filters": filters,
        "fields": ["name"],
        "limit_page_length": 0
    }
    if or_filters:
        count_args["or_filters"] = or_filters

    all_names = frappe.get_all("Product Master", **count_args)
    total = len(all_names)

    # Calculate pagination
    start = (page - 1) * page_size
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    # Get paginated products
    list_args = {
        "filters": filters,
        "fields": fields,
        "order_by": f"{order_by} {order_dir}",
        "start": start,
        "page_length": page_size
    }
    if or_filters:
        list_args["or_filters"] = or_filters

    products = frappe.get_all("Product Master", **list_args)

    return {
        "products": products,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@frappe.whitelist()
def get_product_detail(name, include_attributes=True, include_media=True, include_variants=False):
    """Get full product details including attributes and media.

    Args:
        name: Product Master name (document ID)
        include_attributes: Include EAV attribute values (default: True)
        include_media: Include media attachments (default: True)
        include_variants: Include linked Product Variants (default: False)

    Returns:
        dict: Complete product data with optional nested data

    Example:
        >>> product = get_product_detail("PROD-001", include_variants=True)
        >>> print(product["product_name"])
    """
    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        doc = frappe.get_doc("Product Master", name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Product '{0}' not found").format(name), frappe.DoesNotExistError)

    # Build response
    product = {
        "name": doc.name,
        "product_name": doc.product_name,
        "product_code": getattr(doc, "product_code", doc.name),
        "status": getattr(doc, "status", "Draft"),
        "short_description": getattr(doc, "short_description", None),
        "long_description": doc.get("long_description"),
        "product_family": getattr(doc, "product_family", None),
        "product_type": getattr(doc, "product_type", None),
        # category: form uses 'category', backend stores as 'product_category'
        "category": getattr(doc, "product_category", None),
        "brand": getattr(doc, "brand", None),
        "has_variants": getattr(doc, "has_variants", False),
        "completeness_score": getattr(doc, "completeness_score", 0),
        "image": doc.get("image"),
        "creation": doc.creation.isoformat() if doc.creation else None,
        "modified": doc.modified.isoformat() if doc.modified else None,
        "owner": doc.owner,
        "modified_by": doc.modified_by,
    }

    # Convert string booleans from API calls
    include_attributes = _to_bool(include_attributes)
    include_media = _to_bool(include_media)
    include_variants = _to_bool(include_variants)

    # Include EAV attributes
    if include_attributes:
        product["attributes"] = _get_product_attributes(doc)

    # Include media
    if include_media:
        product["media"] = _get_product_media_list(doc)

    # Include variants
    if include_variants:
        product["variants"] = _get_product_variants(name)

    return product


@frappe.whitelist()
def create_product(
    product_name,
    product_code=None,
    product_family=None,
    product_type=None,
    category=None,
    brand=None,
    status="Draft",
    short_description=None,
    long_description=None,
    has_variants=None,
    attributes=None,
    attribute_values=None,
    media=None,
    image=None,
    **kwargs
):
    """Create a new product."""
    if not frappe.has_permission("Product Master", "create"):
        frappe.throw(_("Not permitted to create products"), frappe.PermissionError)

    # Parse attributes if JSON string
    if attributes and isinstance(attributes, str):
        attributes = json.loads(attributes)

    # Prepare document data
    doc_data = {
        "doctype": "Product Master",
        "product_name": product_name,
        "status": status or "Draft",
    }

    if product_code:
        doc_data["product_code"] = product_code
    if product_family and frappe.db.exists("Product Family", product_family):
        doc_data["product_family"] = product_family
    if product_type and frappe.db.exists("PIM Product Type", product_type):
        doc_data["product_type"] = product_type
    # category in form maps to product_category in Product Master
    if category:
        doc_data["product_category"] = category
    if brand:
        doc_data["brand"] = brand
    if short_description:
        doc_data["short_description"] = short_description
    if long_description:
        doc_data["long_description"] = long_description
    if has_variants is not None:
        doc_data["has_variants"] = has_variants
    if image:
        doc_data["image"] = image

    # Create document via Virtual DocType (creates ERPNext Item under the hood)
    try:
        doc = frappe.get_doc(doc_data)
        doc.insert(ignore_permissions=True)

        # Add attribute values if provided
        if attributes:
            _set_product_attributes(doc, attributes)
            doc.save(ignore_permissions=True)

        frappe.db.commit()

        return {
            "success": True,
            "name": doc.name,
            "product_name": doc.product_name,
            "product_code": getattr(doc, "product_code", doc.name),
            "status": getattr(doc, "status", status),
            "product_family": getattr(doc, "product_family", None),
            "product_type": getattr(doc, "product_type", None),
        }

    except frappe.DuplicateEntryError:
        frappe.throw(
            _("A product with this code already exists"),
            title=_("Duplicate Product Code")
        )
    except Exception as e:
        frappe.log_error(
            message=f"Product creation failed: {str(e)}",
            title="PIM Product API Error"
        )
        frappe.throw(
            _("Failed to create product: {0}").format(str(e)),
            title=_("Product Creation Failed")
        )


@frappe.whitelist()
def update_product(
    name,
    product_name=None,
    product_code=None,
    product_family=None,
    product_type=None,
    category=None,
    brand=None,
    status=None,
    short_description=None,
    long_description=None,
    has_variants=None,
    attributes=None,
    attribute_values=None,
    media=None,
    image=None,
    **kwargs
):
    """Update an existing product."""
    if not frappe.has_permission("Product Master", "write"):
        frappe.throw(_("Not permitted to update products"), frappe.PermissionError)

    try:
        doc = frappe.get_doc("Product Master", name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Product '{0}' not found").format(name), frappe.DoesNotExistError)

    # Parse attributes if JSON string
    if attributes and isinstance(attributes, str):
        attributes = json.loads(attributes)

    if product_name is not None:
        doc.product_name = product_name
    if product_code is not None:
        doc.product_code = product_code
    if product_family is not None:
        if not product_family or frappe.db.exists("Product Family", product_family):
            doc.product_family = product_family
    if product_type is not None:
        if not product_type or frappe.db.exists("PIM Product Type", product_type):
            doc.product_type = product_type
    if category is not None:
        doc.product_category = category
    if brand is not None:
        doc.brand = brand
    if status is not None:
        doc.status = status
    if short_description is not None:
        doc.short_description = short_description
    if long_description is not None:
        doc.long_description = long_description
    if has_variants is not None:
        doc.has_variants = has_variants
    if image is not None:
        doc.image = image

    if attributes:
        _set_product_attributes(doc, attributes)

    try:
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "name": doc.name,
            "product_name": doc.product_name,
            "product_code": getattr(doc, "product_code", doc.name),
            "status": getattr(doc, "status", None),
            "product_family": getattr(doc, "product_family", None),
            "product_type": getattr(doc, "product_type", None),
            "modified": doc.modified.isoformat() if doc.modified else None,
        }

    except frappe.DuplicateEntryError:
        frappe.throw(
            _("A product with this code already exists"),
            title=_("Duplicate Product Code")
        )
    except Exception as e:
        frappe.log_error(
            message=f"Product update failed for {name}: {str(e)}",
            title="PIM Product API Error"
        )
        frappe.throw(
            _("Failed to update product: {0}").format(str(e)),
            title=_("Product Update Failed")
        )


@frappe.whitelist()
def delete_product(name, force=False):
    """Delete a product.

    Args:
        name: Product Master name (document ID)
        force: Force delete even if product has variants (default: False)

    Returns:
        dict: Deletion result

    Example:
        >>> result = delete_product("PROD-001")
        >>> print(result["message"])
    """
    if not frappe.has_permission("Product Master", "delete"):
        frappe.throw(_("Not permitted to delete products"), frappe.PermissionError)

    # Verify product exists via Virtual DocType
    try:
        frappe.get_doc("Product Master", name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Product '{0}' not found").format(name), frappe.DoesNotExistError)

    # Convert string boolean from API calls
    force = _to_bool(force)

    # Check for linked variants
    variant_count = frappe.db.count("Product Variant", {"parent_product": name})
    if variant_count > 0 and not force:
        frappe.throw(
            _("Cannot delete product with {0} linked variant(s). Use force=True to delete anyway.").format(variant_count),
            title=_("Product Has Variants")
        )

    try:
        # Delete variants first if force=True
        if variant_count > 0 and force:
            variants = frappe.get_all(
                "Product Variant",
                filters={"parent_product": name},
                pluck="name"
            )
            for variant in variants:
                frappe.delete_doc("Product Variant", variant, ignore_permissions=True)

        # Delete the product (Virtual DocType handles Item deletion)
        frappe.delete_doc("Product Master", name)
        frappe.db.commit()

        return {
            "success": True,
            "message": _("Product '{0}' deleted successfully").format(name),
            "variants_deleted": variant_count if force else 0
        }

    except Exception as e:
        frappe.log_error(
            message=f"Product deletion failed for {name}: {str(e)}",
            title="PIM Product API Error"
        )
        frappe.throw(
            _("Failed to delete product: {0}").format(str(e)),
            title=_("Product Deletion Failed")
        )


@frappe.whitelist()
def bulk_update_products(products, field, value):
    """Bulk update a field across multiple products.

    Args:
        products: JSON list of product names to update
        field: Field name to update
        value: New value to set

    Returns:
        dict: Update result with count of updated products

    Example:
        >>> result = bulk_update_products(
        ...     products=["PROD-001", "PROD-002"],
        ...     field="status",
        ...     value="Active"
        ... )
    """
    if not frappe.has_permission("Product Master", "write"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if isinstance(products, str):
        products = json.loads(products)

    # Validate field is allowed for bulk update
    allowed_fields = ["status", "product_family"]
    if field not in allowed_fields:
        frappe.throw(
            _("Field '{0}' is not allowed for bulk update. Allowed: {1}").format(
                field, ", ".join(allowed_fields)
            ),
            title=_("Invalid Field")
        )

    updated = 0
    errors = []

    for product_name in products:
        try:
            # Use Document API for Virtual DocType compatibility
            doc = frappe.get_doc("Product Master", product_name)
            doc.set(field, value)
            doc.save(ignore_permissions=True)
            updated += 1
        except frappe.DoesNotExistError:
            errors.append(f"{product_name}: not found")
        except Exception as e:
            errors.append(f"{product_name}: {str(e)}")
            frappe.log_error(
                f"Bulk update failed for {product_name}: {e}",
                "PIM Bulk Update"
            )

    frappe.db.commit()

    return {
        "success": len(errors) == 0,
        "updated": updated,
        "total": len(products),
        "errors": errors if errors else None
    }


@frappe.whitelist()
def get_product_families():
    """Get list of Product Families for dropdowns/filters.

    Returns:
        list: Product Family records with name, label, and parent
    """
    if not frappe.has_permission("Product Family", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    return frappe.get_all(
        "Product Family",
        fields=["name", "family_name", "parent_family", "is_group"],
        order_by="lft asc"
    )


@frappe.whitelist(allow_guest=True)
def get_product_statuses():
    """Get available product status options.

    Returns:
        list: Status options with value and label
    """
    return [
        {"value": "Draft", "label": _("Draft")},
        {"value": "Active", "label": _("Active")},
        {"value": "Inactive", "label": _("Inactive")},
        {"value": "Archived", "label": _("Archived")}
    ]


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _to_bool(value):
    """Convert a value to boolean, handling string representations from API calls.

    Args:
        value: Value to convert (bool, int, str)

    Returns:
        bool: Converted boolean value
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _get_product_attributes(doc):
    """Extract attributes from product document as dict.

    Handles all 9 EAV value columns:
    value_text, value_long_text, value_int, value_float, value_boolean,
    value_date, value_datetime, value_link, value_json

    Args:
        doc: Product Master document

    Returns:
        dict: Attribute code -> value mapping with metadata
    """
    attributes = {}

    for attr_row in (doc.get("attribute_values") or []):
        attr_code = attr_row.get("attribute")
        if not attr_code:
            continue

        # Determine value from appropriate column based on priority
        value = None
        value_type = "text"

        # Check each value column in priority order
        if attr_row.get("value_json"):
            value = attr_row.value_json
            value_type = "json"
        elif attr_row.get("value_long_text"):
            value = attr_row.value_long_text
            value_type = "long_text"
        elif attr_row.get("value_text"):
            value = attr_row.value_text
            value_type = "text"
        elif attr_row.get("value_int") is not None:
            value = attr_row.value_int
            value_type = "integer"
        elif attr_row.get("value_float") is not None:
            value = attr_row.value_float
            value_type = "float"
        elif attr_row.get("value_boolean") is not None:
            value = bool(attr_row.value_boolean)
            value_type = "boolean"
        elif attr_row.get("value_datetime"):
            value = str(attr_row.value_datetime)
            value_type = "datetime"
        elif attr_row.get("value_date"):
            value = str(attr_row.value_date)
            value_type = "date"
        elif attr_row.get("value_link"):
            value = attr_row.value_link
            value_type = "link"

        # Get attribute metadata
        attr_meta = {}
        try:
            attr_meta = frappe.get_cached_value(
                "PIM Attribute", attr_code,
                ["attribute_name", "data_type", "attribute_group"],
                as_dict=True
            ) or {}
        except Exception:
            pass

        attributes[attr_code] = {
            "value": value,
            "value_type": value_type,
            "display_value": attr_row.get("display_value") or value,
            "label": attr_meta.get("attribute_name", attr_code),
            "data_type": attr_meta.get("data_type"),
            "group": attr_meta.get("attribute_group"),
            "unit": attr_row.get("unit"),
            "source": attr_row.get("source"),
            "locale": attr_row.get("locale"),
            "is_inherited": attr_row.get("is_inherited", False)
        }

    return attributes


def _get_product_media_list(doc):
    """Extract media items from product document.

    Args:
        doc: Product Master document

    Returns:
        list: Media items with type, URL, and metadata
    """
    media_list = []

    # Primary image
    if doc.get("image"):
        media_list.append({
            "type": "image",
            "url": doc.image,
            "is_primary": True,
            "sort_order": 0
        })

    # Additional media from child table
    for idx, media in enumerate(doc.get("media") or [], start=1):
        media_list.append({
            "type": media.get("media_type", "image"),
            "url": media.get("file_url"),
            "title": media.get("title"),
            "alt_text": media.get("alt_text"),
            "is_primary": False,
            "sort_order": media.get("sort_order", idx)
        })

    return media_list


def _get_product_variants(parent_product):
    """Get variants for a product with their axis values.

    Uses the axis_values child table (Product Variant Axis Value)
    rather than flat variant_attribute fields.

    Args:
        parent_product: Product Master name (Item name)

    Returns:
        list: Variant records with nested axis_values
    """
    variants = frappe.get_all(
        "Product Variant",
        filters={"parent_product": parent_product},
        fields=[
            "name", "variant_name", "variant_code", "status",
            "variant_level", "completeness_score", "image",
            "erp_item", "description"
        ],
        order_by="variant_code asc"
    )

    # Enrich each variant with its axis values
    for variant in variants:
        axis_values = frappe.get_all(
            "Product Variant Axis Value",
            filters={"parent": variant["name"]},
            fields=["attribute", "attribute_value", "display_value", "option"],
            order_by="idx asc"
        )
        variant["axis_values"] = axis_values

    return variants


# EAV data type to value column mapping
# Matches PIM Attribute's DATA_TYPE_TO_VALUE_COLUMN mapping
_DATA_TYPE_TO_COLUMN = {
    "Text": "value_text",
    "Short Text": "value_text",
    "Select": "value_text",
    "Textarea": "value_long_text",
    "HTML": "value_long_text",
    "Rich Text": "value_long_text",
    "Long Text": "value_long_text",
    "Integer": "value_int",
    "Float": "value_float",
    "Currency": "value_float",
    "Percent": "value_float",
    "Boolean": "value_boolean",
    "Date": "value_date",
    "Datetime": "value_datetime",
    "Link": "value_link",
    "JSON": "value_json",
}

# All value columns that need to be cleared before setting a new value
_ALL_VALUE_COLUMNS = [
    "value_text", "value_long_text", "value_int", "value_float",
    "value_boolean", "value_date", "value_datetime", "value_link",
    "value_json"
]


def _set_product_attributes(doc, attributes):
    """Set attribute values on a product document using EAV pattern.

    Handles all 12 data types via the appropriate value column.

    Args:
        doc: Product Master document
        attributes: Dict of attribute_code -> value mappings
    """
    if not attributes:
        return

    # Get existing attribute rows indexed by attribute code
    existing = {}
    for row in (doc.get("attribute_values") or []):
        if row.attribute:
            existing[row.attribute] = row

    for attr_code, value in attributes.items():
        # Validate attribute exists
        if not frappe.db.exists("PIM Attribute", attr_code):
            continue

        # Get attribute data type
        data_type = frappe.db.get_value("PIM Attribute", attr_code, "data_type") or "Text"

        # Update existing or create new row
        if attr_code in existing:
            row = existing[attr_code]
        else:
            row = doc.append("attribute_values", {"attribute": attr_code})

        # Clear all value columns first
        for col in _ALL_VALUE_COLUMNS:
            row.set(col, None)

        # Skip if value is None (attribute cleared)
        if value is None:
            continue

        # Determine target column from data type
        column = _DATA_TYPE_TO_COLUMN.get(data_type, "value_text")

        # Set value with appropriate type coercion
        if column == "value_int":
            row.value_int = int(value)
        elif column == "value_float":
            row.value_float = float(value)
        elif column == "value_boolean":
            row.value_boolean = _to_bool(value)
        elif column == "value_date":
            row.value_date = value
        elif column == "value_datetime":
            row.value_datetime = value
        elif column == "value_json":
            row.value_json = value if isinstance(value, str) else json.dumps(value)
        elif column == "value_link":
            row.value_link = str(value)
        elif column == "value_long_text":
            row.value_long_text = str(value)
        else:
            # Default: value_text
            row.value_text = str(value)
