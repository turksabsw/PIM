"""
Product REST API
Provides REST API endpoints for product operations (get, search, completeness)
"""

import frappe
from frappe import _
from typing import Optional, List, Dict, Any, Union
import json


# ============================================================================
# Product Retrieval APIs
# ============================================================================

@frappe.whitelist()
def get_product(
    sku: Optional[str] = None,
    name: Optional[str] = None,
    include_attributes: bool = True,
    include_variants: bool = False,
    include_classifications: bool = False,
    include_assets: bool = False,
    locale: Optional[str] = None,
    channel: Optional[str] = None
) -> Dict[str, Any]:
    """Get a single product by SKU or document name

    Args:
        sku: Product SKU
        name: Product Master document name
        include_attributes: Include product attribute values
        include_variants: Include variant products
        include_classifications: Include taxonomy classifications
        include_assets: Include linked digital assets
        locale: Locale for scoped attributes (e.g., en_US)
        channel: Channel for scoped attributes (e.g., ecommerce)

    Returns:
        Product data dictionary

    Raises:
        frappe.DoesNotExistError: If product not found
    """
    # Convert string booleans to actual booleans
    include_attributes = _to_bool(include_attributes)
    include_variants = _to_bool(include_variants)
    include_classifications = _to_bool(include_classifications)
    include_assets = _to_bool(include_assets)

    # Validate input
    if not sku and not name:
        frappe.throw(
            _("Either 'sku' or 'name' parameter is required"),
            title=_("Missing Parameter")
        )

    # Find product
    product_name = name
    if not product_name and sku:
        product_name = frappe.db.get_value("Product Master", {"sku": sku}, "name")
        if not product_name:
            frappe.throw(
                _("Product with SKU '{0}' not found").format(sku),
                exc=frappe.DoesNotExistError
            )

    # Check permissions
    if not frappe.has_permission("Product Master", "read", product_name):
        frappe.throw(
            _("You do not have permission to access this product"),
            exc=frappe.PermissionError
        )

    # Get product document
    try:
        product = frappe.get_doc("Product Master", product_name)
    except frappe.DoesNotExistError:
        frappe.throw(
            _("Product '{0}' not found").format(product_name),
            exc=frappe.DoesNotExistError
        )

    # Build response
    result = _serialize_product(product)

    # Add optional data
    if include_attributes:
        result["attributes"] = get_product_attributes(
            product_name=product_name,
            locale=locale,
            channel=channel
        )

    if include_variants:
        result["variants"] = _get_product_variants(product_name)

    if include_classifications:
        result["classifications"] = _get_product_classifications(product_name)

    if include_assets:
        result["assets"] = _get_product_assets(product_name)

    return result


@frappe.whitelist()
def get_products(
    skus: Optional[str] = None,
    names: Optional[str] = None,
    include_attributes: bool = False,
    locale: Optional[str] = None,
    channel: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get multiple products by SKUs or names

    Args:
        skus: Comma-separated list of SKUs or JSON array
        names: Comma-separated list of document names or JSON array
        include_attributes: Include product attribute values
        locale: Locale for scoped attributes
        channel: Channel for scoped attributes

    Returns:
        List of product data dictionaries
    """
    include_attributes = _to_bool(include_attributes)

    # Parse input lists
    sku_list = _parse_list_param(skus)
    name_list = _parse_list_param(names)

    if not sku_list and not name_list:
        frappe.throw(
            _("Either 'skus' or 'names' parameter is required"),
            title=_("Missing Parameter")
        )

    # Resolve SKUs to names
    product_names = list(name_list) if name_list else []
    if sku_list:
        sku_to_name = frappe.get_all(
            "Product Master",
            filters={"sku": ["in", sku_list]},
            fields=["name", "sku"],
            as_list=False
        )
        product_names.extend([p["name"] for p in sku_to_name])

    # Remove duplicates while preserving order
    seen = set()
    unique_names = []
    for n in product_names:
        if n not in seen:
            seen.add(n)
            unique_names.append(n)

    # Get products
    results = []
    for product_name in unique_names:
        try:
            if not frappe.has_permission("Product Master", "read", product_name):
                continue

            product = frappe.get_doc("Product Master", product_name)
            data = _serialize_product(product)

            if include_attributes:
                data["attributes"] = get_product_attributes(
                    product_name=product_name,
                    locale=locale,
                    channel=channel
                )

            results.append(data)
        except frappe.DoesNotExistError:
            continue

    return results


# ============================================================================
# Product Search APIs
# ============================================================================

@frappe.whitelist()
def search_products(
    query: Optional[str] = None,
    product_type: Optional[str] = None,
    product_family: Optional[str] = None,
    product_category: Optional[str] = None,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    taxonomy: Optional[str] = None,
    taxonomy_node: Optional[str] = None,
    brand: Optional[str] = None,
    manufacturer: Optional[str] = None,
    min_completeness: Optional[int] = None,
    has_variants: Optional[bool] = None,
    is_variant: Optional[bool] = None,
    parent_product: Optional[str] = None,
    created_after: Optional[str] = None,
    modified_after: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    order_by: str = "modified desc",
    include_count: bool = True
) -> Dict[str, Any]:
    """Search products with filters

    Args:
        query: Full-text search query (searches SKU, name, short_description)
        product_type: Filter by product type
        product_family: Filter by product family
        product_category: Filter by product category
        status: Filter by status (Draft, Pending Review, Approved, Published, Archived)
        channel: Filter by published channel
        taxonomy: Filter by taxonomy classification
        taxonomy_node: Filter by specific taxonomy node
        brand: Filter by brand
        manufacturer: Filter by manufacturer
        min_completeness: Minimum completeness score (0-100)
        has_variants: Filter products with/without variants
        is_variant: Filter variant products only
        parent_product: Filter variants of a specific parent
        created_after: Filter by creation date (ISO format)
        modified_after: Filter by modification date (ISO format)
        limit: Maximum results to return (default 20, max 100)
        offset: Skip first N results for pagination
        order_by: Sort order (e.g., "modified desc", "sku asc")
        include_count: Include total count in response

    Returns:
        Dictionary with 'data' (list of products) and optionally 'total' count
    """
    # Convert string params
    limit = min(int(limit), 100)
    offset = int(offset)
    include_count = _to_bool(include_count)

    # Build filters
    filters = {}
    or_filters = []

    if product_type:
        filters["product_type"] = product_type
    if product_family:
        filters["product_family"] = product_family
    if product_category:
        filters["product_category"] = product_category
    if status:
        filters["status"] = status
    if brand:
        filters["brand"] = brand
    if manufacturer:
        filters["manufacturer"] = manufacturer
    if parent_product:
        filters["parent_product"] = parent_product

    if has_variants is not None:
        has_variants = _to_bool(has_variants)
        filters["has_variants"] = 1 if has_variants else 0

    if is_variant is not None:
        is_variant = _to_bool(is_variant)
        filters["is_variant"] = 1 if is_variant else 0

    if min_completeness is not None:
        filters["completeness_score"] = [">=", int(min_completeness)]

    if created_after:
        filters["creation"] = [">=", created_after]

    if modified_after:
        filters["modified"] = [">=", modified_after]

    # Full-text search
    if query and len(query) >= 2:
        search_pattern = f"%{query}%"
        or_filters = [
            ["sku", "like", search_pattern],
            ["product_name", "like", search_pattern],
            ["short_description", "like", search_pattern]
        ]

    # Validate order_by to prevent SQL injection
    allowed_order_fields = [
        "name", "sku", "product_name", "modified", "creation",
        "completeness_score", "status", "product_type", "product_family"
    ]
    order_parts = order_by.split()
    if len(order_parts) >= 1:
        order_field = order_parts[0]
        order_dir = order_parts[1].lower() if len(order_parts) > 1 else "desc"
        if order_field not in allowed_order_fields:
            order_field = "modified"
        if order_dir not in ["asc", "desc"]:
            order_dir = "desc"
        order_by = f"{order_field} {order_dir}"

    # Get products with channel and taxonomy filters
    if channel or taxonomy or taxonomy_node:
        product_names = _get_filtered_product_names(
            channel=channel,
            taxonomy=taxonomy,
            taxonomy_node=taxonomy_node
        )
        if product_names:
            filters["name"] = ["in", product_names]
        else:
            # No matching products
            return {"data": [], "total": 0} if include_count else {"data": []}

    # Build query
    products = frappe.get_all(
        "Product Master",
        filters=filters,
        or_filters=or_filters if or_filters else None,
        fields=[
            "name", "sku", "product_name", "short_description",
            "product_type", "product_family", "product_category",
            "status", "completeness_score", "brand", "manufacturer",
            "is_variant", "has_variants", "parent_product",
            "creation", "modified"
        ],
        order_by=order_by,
        limit_start=offset,
        limit_page_length=limit
    )

    result = {"data": products}

    if include_count:
        total = frappe.db.count(
            "Product Master",
            filters=filters,
            or_filters=or_filters if or_filters else None
        )
        result["total"] = total
        result["limit"] = limit
        result["offset"] = offset

    return result


@frappe.whitelist()
def autocomplete_products(
    query: str,
    limit: int = 10
) -> List[Dict[str, str]]:
    """Autocomplete product search for UI dropdowns

    Args:
        query: Search query (minimum 2 characters)
        limit: Maximum results (default 10, max 50)

    Returns:
        List of products with name, sku, and display label
    """
    if not query or len(query) < 2:
        return []

    limit = min(int(limit), 50)
    search_pattern = f"%{query}%"

    products = frappe.db.sql(
        """
        SELECT name, sku, product_name, status
        FROM `tabProduct Master`
        WHERE (
            sku LIKE %(search)s
            OR product_name LIKE %(search)s
        )
        ORDER BY
            CASE
                WHEN sku = %(exact)s THEN 0
                WHEN sku LIKE %(prefix)s THEN 1
                WHEN product_name = %(exact)s THEN 2
                WHEN product_name LIKE %(prefix)s THEN 3
                ELSE 4
            END,
            product_name ASC
        LIMIT %(limit)s
        """,
        {
            "search": search_pattern,
            "exact": query,
            "prefix": f"{query}%",
            "limit": limit
        },
        as_dict=True
    )

    return [
        {
            "name": p["name"],
            "sku": p["sku"],
            "label": f"{p['sku']} - {p['product_name']}",
            "status": p["status"]
        }
        for p in products
    ]


# ============================================================================
# Product Completeness APIs
# ============================================================================

@frappe.whitelist()
def get_product_completeness(
    sku: Optional[str] = None,
    product_name: Optional[str] = None,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    detailed: bool = False
) -> Dict[str, Any]:
    """Get completeness score for a product

    Args:
        sku: Product SKU
        product_name: Product Master document name
        channel: Calculate completeness for specific channel
        locale: Calculate completeness for specific locale
        detailed: Include detailed breakdown of missing/filled attributes

    Returns:
        Completeness information with score and optional details
    """
    detailed = _to_bool(detailed)

    # Find product
    if not product_name and sku:
        product_name = frappe.db.get_value("Product Master", {"sku": sku}, "name")

    if not product_name:
        frappe.throw(
            _("Product not found"),
            exc=frappe.DoesNotExistError
        )

    # Check permissions
    if not frappe.has_permission("Product Master", "read", product_name):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    # Get product
    product = frappe.get_doc("Product Master", product_name)

    # Calculate completeness
    result = _calculate_completeness(
        product=product,
        channel=channel,
        locale=locale,
        detailed=detailed
    )

    return result


@frappe.whitelist()
def get_channel_readiness(
    sku: Optional[str] = None,
    product_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get readiness status for all channels for a product

    Args:
        sku: Product SKU
        product_name: Product Master document name

    Returns:
        List of channel readiness statuses
    """
    # Find product
    if not product_name and sku:
        product_name = frappe.db.get_value("Product Master", {"sku": sku}, "name")

    if not product_name:
        frappe.throw(
            _("Product not found"),
            exc=frappe.DoesNotExistError
        )

    # Get all enabled channels
    channels = frappe.get_all(
        "Channel",
        filters={"enabled": 1},
        fields=["name", "channel_name", "channel_code"]
    )

    # Calculate readiness for each channel
    results = []
    for channel in channels:
        completeness = _calculate_completeness(
            product=frappe.get_doc("Product Master", product_name),
            channel=channel["name"],
            detailed=True
        )

        results.append({
            "channel": channel["name"],
            "channel_name": channel["channel_name"],
            "channel_code": channel.get("channel_code"),
            "completeness_score": completeness["score"],
            "is_ready": completeness["score"] >= completeness.get("threshold", 100),
            "missing_required": completeness.get("missing_required", []),
            "missing_optional": completeness.get("missing_optional", [])
        })

    return results


# ============================================================================
# Product Attributes APIs
# ============================================================================

@frappe.whitelist()
def get_product_attributes(
    sku: Optional[str] = None,
    product_name: Optional[str] = None,
    locale: Optional[str] = None,
    channel: Optional[str] = None,
    attribute_group: Optional[str] = None,
    include_inherited: bool = True
) -> List[Dict[str, Any]]:
    """Get product attributes with optional scoping

    Args:
        sku: Product SKU
        product_name: Product Master document name
        locale: Locale for scoped values (falls back if not found)
        channel: Channel for scoped values (falls back if not found)
        attribute_group: Filter by attribute group
        include_inherited: Include attributes inherited from parent product

    Returns:
        List of attribute values with metadata
    """
    include_inherited = _to_bool(include_inherited)

    # Find product
    if not product_name and sku:
        product_name = frappe.db.get_value("Product Master", {"sku": sku}, "name")

    if not product_name:
        frappe.throw(
            _("Product not found"),
            exc=frappe.DoesNotExistError
        )

    # Check permissions
    if not frappe.has_permission("Product Master", "read", product_name):
        frappe.throw(_("Permission denied"), exc=frappe.PermissionError)

    # Get attribute values using 3D scoped resolution
    return _get_scoped_attributes(
        product_name=product_name,
        locale=locale,
        channel=channel,
        attribute_group=attribute_group,
        include_inherited=include_inherited
    )


# ============================================================================
# Helper Functions
# ============================================================================

def _to_bool(value: Any) -> bool:
    """Convert various inputs to boolean"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)


def _parse_list_param(value: Optional[str]) -> List[str]:
    """Parse comma-separated or JSON array parameter"""
    if not value:
        return []

    # Try JSON array first
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

    # Comma-separated
    return [item.strip() for item in value.split(",") if item.strip()]


def _serialize_product(product) -> Dict[str, Any]:
    """Serialize product document to dictionary"""
    return {
        "name": product.name,
        "sku": product.sku,
        "product_name": product.product_name,
        "short_description": product.short_description,
        "long_description": product.long_description,
        "product_type": product.product_type,
        "product_family": product.product_family,
        "product_category": product.product_category,
        "brand": product.brand,
        "manufacturer": product.manufacturer,
        "status": product.status,
        "completeness_score": product.completeness_score,
        "is_variant": product.is_variant,
        "has_variants": product.has_variants,
        "parent_product": product.parent_product,
        "item": getattr(product, "item", None),
        "creation": str(product.creation),
        "modified": str(product.modified),
        "owner": product.owner,
        "modified_by": product.modified_by
    }


def _get_product_variants(product_name: str) -> List[Dict[str, Any]]:
    """Get variants of a product"""
    variants = frappe.get_all(
        "Product Master",
        filters={"parent_product": product_name},
        fields=[
            "name", "sku", "product_name", "status",
            "completeness_score", "variant_level"
        ],
        order_by="variant_level, sku"
    )
    return variants


def _get_product_classifications(product_name: str) -> List[Dict[str, Any]]:
    """Get taxonomy classifications for a product"""
    try:
        classifications = frappe.get_all(
            "Product Classification",
            filters={"parent": product_name},
            fields=[
                "taxonomy", "taxonomy_node", "is_primary",
                "classification_date", "confidence_score"
            ]
        )

        # Enrich with taxonomy node details
        for cls in classifications:
            if cls.get("taxonomy_node"):
                node = frappe.db.get_value(
                    "Taxonomy Node",
                    cls["taxonomy_node"],
                    ["node_name", "node_code", "full_path"],
                    as_dict=True
                )
                if node:
                    cls["node_name"] = node["node_name"]
                    cls["node_code"] = node["node_code"]
                    cls["full_path"] = node["full_path"]

        return classifications
    except Exception:
        return []


def _get_product_assets(product_name: str) -> List[Dict[str, Any]]:
    """Get digital assets linked to a product"""
    try:
        assets = frappe.get_all(
            "Product Asset Link",
            filters={"parent": product_name},
            fields=["asset", "asset_role", "sort_order", "is_primary"]
        )

        # Enrich with asset details
        for asset_link in assets:
            if asset_link.get("asset"):
                asset = frappe.db.get_value(
                    "Digital Asset",
                    asset_link["asset"],
                    ["asset_name", "file_url", "file_type", "mime_type"],
                    as_dict=True
                )
                if asset:
                    asset_link.update(asset)

        return sorted(assets, key=lambda x: x.get("sort_order", 0))
    except Exception:
        return []


def _get_filtered_product_names(
    channel: Optional[str] = None,
    taxonomy: Optional[str] = None,
    taxonomy_node: Optional[str] = None
) -> List[str]:
    """Get product names filtered by channel or taxonomy"""
    product_names = set()

    # Filter by channel
    if channel:
        try:
            channel_products = frappe.get_all(
                "Product Channel",
                filters={"parent": ["is", "set"], "channel": channel},
                pluck="parent"
            )
            if not channel_products:
                return []
            product_names = set(channel_products)
        except Exception:
            pass

    # Filter by taxonomy
    if taxonomy or taxonomy_node:
        try:
            tax_filters = {"parent": ["is", "set"]}
            if taxonomy:
                tax_filters["taxonomy"] = taxonomy
            if taxonomy_node:
                tax_filters["taxonomy_node"] = taxonomy_node

            tax_products = frappe.get_all(
                "Product Classification",
                filters=tax_filters,
                pluck="parent"
            )

            if product_names:
                product_names = product_names.intersection(set(tax_products))
            else:
                product_names = set(tax_products)
        except Exception:
            pass

    return list(product_names)


def _calculate_completeness(
    product,
    channel: Optional[str] = None,
    locale: Optional[str] = None,
    detailed: bool = False
) -> Dict[str, Any]:
    """Calculate completeness score for a product

    Uses a point-based system:
    - Required fields: higher weight
    - Optional fields: lower weight
    - Channel-specific requirements if channel provided
    """
    filled_required = []
    missing_required = []
    filled_optional = []
    missing_optional = []

    # Core required fields
    core_required_fields = [
        ("sku", "SKU"),
        ("product_name", "Product Name"),
        ("product_type", "Product Type"),
        ("product_family", "Product Family")
    ]

    # Extended required fields
    extended_required_fields = [
        ("short_description", "Short Description"),
        ("status", "Status")
    ]

    # Optional fields
    optional_fields = [
        ("long_description", "Long Description"),
        ("brand", "Brand"),
        ("manufacturer", "Manufacturer"),
        ("product_category", "Product Category")
    ]

    # Check core required fields
    for field, label in core_required_fields:
        value = getattr(product, field, None)
        if value:
            filled_required.append({"field": field, "label": label})
        else:
            missing_required.append({"field": field, "label": label})

    # Check extended required fields
    for field, label in extended_required_fields:
        value = getattr(product, field, None)
        if value:
            filled_required.append({"field": field, "label": label})
        else:
            missing_required.append({"field": field, "label": label})

    # Check optional fields
    for field, label in optional_fields:
        value = getattr(product, field, None)
        if value:
            filled_optional.append({"field": field, "label": label})
        else:
            missing_optional.append({"field": field, "label": label})

    # Get channel-specific requirements
    threshold = 100
    if channel:
        try:
            channel_requirements = frappe.get_all(
                "Channel Attribute Requirement",
                filters={"parent": channel, "is_required": 1},
                pluck="attribute"
            )

            # Check attribute values
            for attr in channel_requirements:
                has_value = frappe.db.exists(
                    "Product Attribute Value",
                    {
                        "parent": product.name,
                        "attribute": attr,
                        "value": ["is", "set"]
                    }
                )
                attr_label = frappe.db.get_value("Attribute", attr, "attribute_name") or attr

                if has_value:
                    filled_required.append({"field": attr, "label": attr_label, "type": "attribute"})
                else:
                    missing_required.append({"field": attr, "label": attr_label, "type": "attribute"})

            # Get channel threshold
            threshold = frappe.db.get_value(
                "Channel", channel, "minimum_completeness"
            ) or 100
        except Exception:
            pass

    # Calculate score
    total_required = len(filled_required) + len(missing_required)
    total_optional = len(filled_optional) + len(missing_optional)

    # Weighted scoring: required fields count more
    required_weight = 0.8
    optional_weight = 0.2

    required_score = (len(filled_required) / total_required * 100) if total_required > 0 else 100
    optional_score = (len(filled_optional) / total_optional * 100) if total_optional > 0 else 100

    final_score = round(
        (required_score * required_weight) + (optional_score * optional_weight)
    )

    result = {
        "product": product.name,
        "sku": product.sku,
        "score": final_score,
        "threshold": threshold,
        "is_complete": len(missing_required) == 0,
        "meets_threshold": final_score >= threshold,
        "channel": channel,
        "locale": locale
    }

    if detailed:
        result["filled_required"] = filled_required
        result["missing_required"] = missing_required
        result["filled_optional"] = filled_optional
        result["missing_optional"] = missing_optional
        result["breakdown"] = {
            "required_filled": len(filled_required),
            "required_total": total_required,
            "optional_filled": len(filled_optional),
            "optional_total": total_optional
        }

    return result


def _get_scoped_attributes(
    product_name: str,
    locale: Optional[str] = None,
    channel: Optional[str] = None,
    attribute_group: Optional[str] = None,
    include_inherited: bool = True
) -> List[Dict[str, Any]]:
    """Get product attributes with 3D scope resolution

    Resolution order (fallback cascade):
    1. Exact match (locale + channel)
    2. Locale only
    3. Channel only
    4. Unscoped (base value)
    """
    results = []
    seen_attributes = set()

    # Get product's attribute values
    filters = {"parent": product_name}

    attribute_values = frappe.get_all(
        "Product Attribute Value",
        filters=filters,
        fields=[
            "name", "attribute", "value", "locale", "channel",
            "valid_from", "valid_to", "source_system"
        ],
        order_by="attribute, locale, channel"
    )

    # Group by attribute
    attr_values_map = {}
    for av in attribute_values:
        attr = av["attribute"]
        if attr not in attr_values_map:
            attr_values_map[attr] = []
        attr_values_map[attr].append(av)

    # Resolve best value for each attribute
    for attr, values in attr_values_map.items():
        # Filter by attribute group if specified
        if attribute_group:
            attr_group = frappe.db.get_value("Attribute", attr, "attribute_group")
            if attr_group != attribute_group:
                continue

        resolved_value = _resolve_scoped_value(values, locale, channel)

        if resolved_value:
            # Get attribute metadata
            attr_meta = frappe.db.get_value(
                "Attribute",
                attr,
                ["attribute_name", "attribute_type", "attribute_group", "unit_of_measure"],
                as_dict=True
            )

            results.append({
                "attribute": attr,
                "attribute_name": attr_meta.get("attribute_name") if attr_meta else attr,
                "attribute_type": attr_meta.get("attribute_type") if attr_meta else None,
                "attribute_group": attr_meta.get("attribute_group") if attr_meta else None,
                "unit_of_measure": attr_meta.get("unit_of_measure") if attr_meta else None,
                "value": resolved_value["value"],
                "locale": resolved_value.get("locale"),
                "channel": resolved_value.get("channel"),
                "source_system": resolved_value.get("source_system"),
                "is_inherited": False
            })
            seen_attributes.add(attr)

    # Include inherited attributes from parent product
    if include_inherited:
        parent_product = frappe.db.get_value("Product Master", product_name, "parent_product")
        if parent_product:
            inherited = _get_scoped_attributes(
                product_name=parent_product,
                locale=locale,
                channel=channel,
                attribute_group=attribute_group,
                include_inherited=True
            )

            for attr in inherited:
                if attr["attribute"] not in seen_attributes:
                    attr["is_inherited"] = True
                    attr["inherited_from"] = parent_product
                    results.append(attr)
                    seen_attributes.add(attr["attribute"])

    return results


def _resolve_scoped_value(
    values: List[Dict],
    locale: Optional[str] = None,
    channel: Optional[str] = None
) -> Optional[Dict]:
    """Resolve the best value from a list using 3D scope fallback

    Resolution order:
    1. locale + channel (exact match)
    2. locale only
    3. channel only
    4. unscoped
    """
    # Score each value based on scope match
    scored = []
    for v in values:
        score = 0
        v_locale = v.get("locale")
        v_channel = v.get("channel")

        # Exact match gets highest score
        if v_locale == locale and v_channel == channel:
            score = 4
        elif v_locale == locale and not v_channel:
            score = 3
        elif v_channel == channel and not v_locale:
            score = 2
        elif not v_locale and not v_channel:
            score = 1
        else:
            # Non-matching scoped value
            continue

        scored.append((score, v))

    if not scored:
        return None

    # Return highest scoring value
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]
