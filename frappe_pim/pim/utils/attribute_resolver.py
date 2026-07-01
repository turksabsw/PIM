"""3D Attribute Value Resolution with Fallback Cascade

This module provides comprehensive attribute value resolution for the PIM system
with support for 3D scoping (locale x channel x time dimensions).

The resolution follows a fallback cascade:
    1. Exact match (locale + channel + time)
    2. Locale + channel (no time constraint)
    3. Locale only
    4. Channel only
    5. Unscoped (base value)

Additionally, locale fallback chains are supported, allowing values to cascade
through parent locales (e.g., en_US -> en -> default).

These functions integrate with:
    - Product Attribute Value (EAV storage)
    - PIM Locale (fallback chains)
    - Channel (scope restrictions)
    - Attribute (metadata and validation)

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from typing import Optional, Any, Dict, List, Union, Tuple
from datetime import date, datetime


# ============================================================================
# Core Resolution Functions
# ============================================================================

def get_scoped_attribute_value(
    product: str,
    attribute: str,
    locale: Optional[str] = None,
    channel: Optional[str] = None,
    as_of_date: Optional[Union[str, date]] = None,
    include_locale_fallback: bool = True,
    include_metadata: bool = False
) -> Any:
    """Get attribute value with 3D scope resolution.

    Resolves the best matching value using the fallback cascade:
    specific scope -> default scope -> None

    Resolution order:
    1. Exact match (locale + channel + time)
    2. Locale + channel (no time)
    3. Locale only
    4. Channel only
    5. Unscoped (base value)

    If include_locale_fallback is True, the resolution also tries
    parent locales in the fallback chain.

    Args:
        product: Product Master name or SKU
        attribute: Attribute name (code)
        locale: Locale for scoped value (e.g., en_US, fr_FR)
        channel: Channel for scoped value (e.g., ecommerce, retail)
        as_of_date: Date for time-based validity (default: today)
        include_locale_fallback: Include locale fallback chain resolution
        include_metadata: Return dict with value and metadata instead of just value

    Returns:
        The resolved attribute value, or dict with metadata if include_metadata=True.
        Returns None if no value found.

    Example:
        >>> get_scoped_attribute_value("PROD-001", "description", locale="en_US", channel="web")
        "Premium wireless headphones with active noise cancellation"

        >>> get_scoped_attribute_value("PROD-001", "price", channel="retail", include_metadata=True)
        {"value": 199.99, "locale": None, "channel": "retail", "scope_match": "channel_only"}
    """
    import frappe

    try:
        # Resolve product name if SKU provided
        product_name = _resolve_product_name(product)
        if not product_name:
            return _build_result(None, include_metadata)

        # Get attribute values for this product and attribute
        attribute_values = _get_attribute_values(product_name, attribute)
        if not attribute_values:
            return _build_result(None, include_metadata)

        # Build locale fallback chain
        locale_chain = _get_locale_chain(locale, include_locale_fallback)

        # Normalize as_of_date
        effective_date = _normalize_date(as_of_date)

        # Try each scope level in order
        resolved = _resolve_with_fallback(
            attribute_values=attribute_values,
            locale_chain=locale_chain,
            channel=channel,
            effective_date=effective_date
        )

        if resolved:
            value = _extract_value(resolved["row"])
            if include_metadata:
                return {
                    "value": value,
                    "locale": resolved["row"].get("locale"),
                    "channel": resolved["row"].get("channel"),
                    "valid_from": resolved["row"].get("valid_from"),
                    "valid_to": resolved["row"].get("valid_to"),
                    "source_system": resolved["row"].get("source_system"),
                    "scope_match": resolved["scope_match"],
                    "is_inherited": resolved["row"].get("is_inherited", False)
                }
            return value

        return _build_result(None, include_metadata)

    except Exception as e:
        frappe.log_error(
            message=f"Error resolving attribute '{attribute}' for product '{product}': {str(e)}",
            title="PIM Attribute Resolution Error"
        )
        return _build_result(None, include_metadata)


def get_all_scoped_attributes(
    product: str,
    locale: Optional[str] = None,
    channel: Optional[str] = None,
    as_of_date: Optional[Union[str, date]] = None,
    attribute_group: Optional[str] = None,
    include_locale_fallback: bool = True,
    include_inherited: bool = True,
    include_empty: bool = False
) -> List[Dict[str, Any]]:
    """Get all attribute values for a product with scope resolution.

    Resolves the best matching value for each attribute using the
    fallback cascade. Optionally includes inherited attributes from
    parent products.

    Args:
        product: Product Master name or SKU
        locale: Locale for scoped values
        channel: Channel for scoped values
        as_of_date: Date for time-based validity
        attribute_group: Filter by attribute group
        include_locale_fallback: Include locale fallback chain resolution
        include_inherited: Include attributes inherited from parent product
        include_empty: Include attributes that have no value (as None)

    Returns:
        List of attribute value dictionaries with metadata

    Example:
        >>> get_all_scoped_attributes("PROD-001", locale="en_US", channel="web")
        [
            {
                "attribute": "description",
                "attribute_name": "Product Description",
                "attribute_type": "Text",
                "attribute_group": "Marketing",
                "value": "Premium headphones...",
                "locale": "en_US",
                "channel": "web",
                "scope_match": "exact",
                "is_inherited": False
            },
            ...
        ]
    """
    import frappe

    try:
        product_name = _resolve_product_name(product)
        if not product_name:
            return []

        # Get all attribute values for this product
        all_values = _get_all_attribute_values(product_name)

        # Group by attribute
        attr_values_map = {}
        for av in all_values:
            attr = av.get("attribute")
            if attr not in attr_values_map:
                attr_values_map[attr] = []
            attr_values_map[attr].append(av)

        # Build locale fallback chain
        locale_chain = _get_locale_chain(locale, include_locale_fallback)
        effective_date = _normalize_date(as_of_date)

        # Get attribute metadata for filtering
        attribute_meta = _get_attribute_metadata()

        # Resolve each attribute
        results = []
        seen_attributes = set()

        for attr, values in attr_values_map.items():
            # Filter by attribute group if specified
            meta = attribute_meta.get(attr, {})
            if attribute_group and meta.get("attribute_group") != attribute_group:
                continue

            # Resolve value with fallback
            resolved = _resolve_with_fallback(
                attribute_values=values,
                locale_chain=locale_chain,
                channel=channel,
                effective_date=effective_date
            )

            if resolved:
                results.append(_build_attribute_result(
                    attribute=attr,
                    row=resolved["row"],
                    scope_match=resolved["scope_match"],
                    meta=meta,
                    is_inherited=False
                ))
                seen_attributes.add(attr)
            elif include_empty:
                results.append({
                    "attribute": attr,
                    "attribute_name": meta.get("attribute_name", attr),
                    "attribute_type": meta.get("attribute_type"),
                    "attribute_group": meta.get("attribute_group"),
                    "unit_of_measure": meta.get("unit_of_measure"),
                    "value": None,
                    "locale": locale,
                    "channel": channel,
                    "scope_match": None,
                    "is_inherited": False
                })
                seen_attributes.add(attr)

        # Include inherited attributes from parent product
        if include_inherited:
            parent_product = frappe.db.get_value("Product Master", product_name, "parent_product")
            if parent_product:
                inherited = get_all_scoped_attributes(
                    product=parent_product,
                    locale=locale,
                    channel=channel,
                    as_of_date=as_of_date,
                    attribute_group=attribute_group,
                    include_locale_fallback=include_locale_fallback,
                    include_inherited=True,
                    include_empty=False
                )

                for attr_result in inherited:
                    if attr_result["attribute"] not in seen_attributes:
                        attr_result["is_inherited"] = True
                        attr_result["inherited_from"] = parent_product
                        results.append(attr_result)
                        seen_attributes.add(attr_result["attribute"])

        return results

    except Exception as e:
        frappe.log_error(
            message=f"Error getting all scoped attributes for product '{product}': {str(e)}",
            title="PIM Attribute Resolution Error"
        )
        return []


def resolve_attribute_for_channel(
    product: str,
    attribute: str,
    channel: str,
    preferred_locale: Optional[str] = None
) -> Dict[str, Any]:
    """Resolve attribute value optimized for channel output.

    This is a convenience function that resolves an attribute value
    for a specific channel, considering the channel's default locale
    and locale restrictions.

    Args:
        product: Product Master name or SKU
        attribute: Attribute name
        channel: Channel name (required)
        preferred_locale: Preferred locale (falls back to channel default)

    Returns:
        Dict with resolved value and metadata
    """
    import frappe

    # Get channel configuration
    channel_config = _get_channel_config(channel)
    if not channel_config:
        return {"value": None, "error": f"Channel '{channel}' not found"}

    # Determine locale to use
    locale = preferred_locale
    if locale:
        # Check if locale is supported by channel
        supported_locales = channel_config.get("supported_locales", [])
        if supported_locales and locale not in supported_locales:
            locale = channel_config.get("default_locale")
    else:
        locale = channel_config.get("default_locale")

    # Resolve attribute
    result = get_scoped_attribute_value(
        product=product,
        attribute=attribute,
        locale=locale,
        channel=channel,
        include_locale_fallback=True,
        include_metadata=True
    )

    if result:
        result["channel_name"] = channel_config.get("channel_name")
        result["effective_locale"] = locale

    return result


# ============================================================================
# Bulk Resolution Functions
# ============================================================================

def resolve_attributes_bulk(
    products: List[str],
    attributes: List[str],
    locale: Optional[str] = None,
    channel: Optional[str] = None,
    as_of_date: Optional[Union[str, date]] = None
) -> Dict[str, Dict[str, Any]]:
    """Resolve multiple attributes for multiple products efficiently.

    Optimized for bulk operations like exports or API responses.

    Args:
        products: List of product names or SKUs
        attributes: List of attribute names
        locale: Locale for scoped values
        channel: Channel for scoped values
        as_of_date: Date for time-based validity

    Returns:
        Nested dict: {product_name: {attribute: value, ...}, ...}

    Example:
        >>> resolve_attributes_bulk(
        ...     products=["PROD-001", "PROD-002"],
        ...     attributes=["description", "price", "color"]
        ... )
        {
            "PROD-001": {"description": "...", "price": 199.99, "color": "Black"},
            "PROD-002": {"description": "...", "price": 149.99, "color": "White"}
        }
    """
    import frappe

    try:
        results = {}

        # Resolve product names
        product_names = []
        for p in products:
            name = _resolve_product_name(p)
            if name:
                product_names.append(name)
                results[name] = {}

        if not product_names:
            return results

        # Build locale chain once
        locale_chain = _get_locale_chain(locale, include_fallback=True)
        effective_date = _normalize_date(as_of_date)

        # Get all attribute values for all products in one query
        all_values = frappe.get_all(
            "Product Attribute Value",
            filters={
                "parent": ["in", product_names],
                "attribute": ["in", attributes]
            },
            fields=[
                "parent", "attribute", "locale", "channel",
                "valid_from", "valid_to", "source_system",
                "value_text", "value_long_text", "value_int",
                "value_float", "value_boolean", "value_date",
                "value_datetime", "value_link", "is_inherited"
            ]
        )

        # Group by product and attribute
        product_attr_map = {}
        for av in all_values:
            product_name = av.get("parent")
            attr = av.get("attribute")
            if product_name not in product_attr_map:
                product_attr_map[product_name] = {}
            if attr not in product_attr_map[product_name]:
                product_attr_map[product_name][attr] = []
            product_attr_map[product_name][attr].append(av)

        # Resolve for each product and attribute
        for product_name in product_names:
            for attr in attributes:
                values = product_attr_map.get(product_name, {}).get(attr, [])
                if values:
                    resolved = _resolve_with_fallback(
                        attribute_values=values,
                        locale_chain=locale_chain,
                        channel=channel,
                        effective_date=effective_date
                    )
                    if resolved:
                        results[product_name][attr] = _extract_value(resolved["row"])
                    else:
                        results[product_name][attr] = None
                else:
                    results[product_name][attr] = None

        return results

    except Exception as e:
        frappe.log_error(
            message=f"Error in bulk attribute resolution: {str(e)}",
            title="PIM Bulk Resolution Error"
        )
        return {}


# ============================================================================
# Time-Based Resolution
# ============================================================================

def get_attribute_value_at_time(
    product: str,
    attribute: str,
    at_datetime: Union[str, datetime],
    locale: Optional[str] = None,
    channel: Optional[str] = None
) -> Any:
    """Get the attribute value that was valid at a specific point in time.

    This is useful for historical reporting and audit purposes.

    Args:
        product: Product Master name or SKU
        attribute: Attribute name
        at_datetime: The point in time to query
        locale: Locale for scoped value
        channel: Channel for scoped value

    Returns:
        The attribute value that was valid at the specified time
    """
    import frappe
    from frappe.utils import get_datetime

    try:
        at_dt = get_datetime(at_datetime) if isinstance(at_datetime, str) else at_datetime

        return get_scoped_attribute_value(
            product=product,
            attribute=attribute,
            locale=locale,
            channel=channel,
            as_of_date=at_dt.date() if hasattr(at_dt, 'date') else at_dt,
            include_locale_fallback=True
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error getting attribute at time: {str(e)}",
            title="PIM Time Resolution Error"
        )
        return None


def get_attribute_validity_periods(
    product: str,
    attribute: str,
    locale: Optional[str] = None,
    channel: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all validity periods for an attribute value.

    Returns all time-scoped values with their validity periods.

    Args:
        product: Product Master name or SKU
        attribute: Attribute name
        locale: Filter by locale
        channel: Filter by channel

    Returns:
        List of values with their valid_from and valid_to dates

    Example:
        >>> get_attribute_validity_periods("PROD-001", "price", channel="retail")
        [
            {"value": 199.99, "valid_from": "2024-01-01", "valid_to": "2024-06-30"},
            {"value": 179.99, "valid_from": "2024-07-01", "valid_to": None}
        ]
    """
    import frappe

    try:
        product_name = _resolve_product_name(product)
        if not product_name:
            return []

        filters = {
            "parent": product_name,
            "attribute": attribute
        }

        if locale:
            filters["locale"] = locale
        if channel:
            filters["channel"] = channel

        values = frappe.get_all(
            "Product Attribute Value",
            filters=filters,
            fields=[
                "valid_from", "valid_to", "locale", "channel",
                "value_text", "value_long_text", "value_int",
                "value_float", "value_boolean", "value_date",
                "value_datetime", "value_link"
            ],
            order_by="valid_from asc"
        )

        return [
            {
                "value": _extract_value(v),
                "valid_from": v.get("valid_from"),
                "valid_to": v.get("valid_to"),
                "locale": v.get("locale"),
                "channel": v.get("channel")
            }
            for v in values
        ]

    except Exception as e:
        frappe.log_error(
            message=f"Error getting validity periods: {str(e)}",
            title="PIM Validity Resolution Error"
        )
        return []


# ============================================================================
# Scope Analysis Functions
# ============================================================================

def analyze_attribute_coverage(
    product: str,
    locales: Optional[List[str]] = None,
    channels: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Analyze attribute coverage across locales and channels.

    Returns a matrix showing which attributes have values for which
    locale/channel combinations.

    Args:
        product: Product Master name or SKU
        locales: List of locales to check (default: all enabled locales)
        channels: List of channels to check (default: all enabled channels)

    Returns:
        Coverage analysis with gaps and recommendations
    """
    import frappe

    try:
        product_name = _resolve_product_name(product)
        if not product_name:
            return {"error": "Product not found"}

        # Get locales and channels if not provided
        if not locales:
            locales = frappe.get_all(
                "PIM Locale",
                filters={"enabled": 1},
                pluck="name"
            )
        if not channels:
            channels = frappe.get_all(
                "Channel",
                filters={"enabled": 1},
                pluck="name"
            )

        # Get all attribute values
        all_values = _get_all_attribute_values(product_name)

        # Build coverage matrix
        coverage = {}
        all_attributes = set()

        for av in all_values:
            attr = av.get("attribute")
            loc = av.get("locale") or "_default"
            chan = av.get("channel") or "_default"
            all_attributes.add(attr)

            if attr not in coverage:
                coverage[attr] = {}
            if loc not in coverage[attr]:
                coverage[attr][loc] = {}

            coverage[attr][loc][chan] = _extract_value(av) is not None

        # Analyze gaps
        gaps = []
        for attr in all_attributes:
            for loc in locales + ["_default"]:
                for chan in channels + ["_default"]:
                    has_value = coverage.get(attr, {}).get(loc, {}).get(chan, False)
                    if not has_value and loc != "_default" and chan != "_default":
                        gaps.append({
                            "attribute": attr,
                            "locale": loc if loc != "_default" else None,
                            "channel": chan if chan != "_default" else None
                        })

        return {
            "product": product_name,
            "locales": locales,
            "channels": channels,
            "attributes": list(all_attributes),
            "coverage": coverage,
            "gaps": gaps,
            "gap_count": len(gaps),
            "total_possible": len(all_attributes) * len(locales) * len(channels),
            "coverage_percentage": round(
                (1 - len(gaps) / max(1, len(all_attributes) * len(locales) * len(channels))) * 100,
                2
            )
        }

    except Exception as e:
        frappe.log_error(
            message=f"Error analyzing coverage: {str(e)}",
            title="PIM Coverage Analysis Error"
        )
        return {"error": str(e)}


# ============================================================================
# Cache Support Functions
# ============================================================================

def get_cached_attribute_value(
    product: str,
    attribute: str,
    locale: Optional[str] = None,
    channel: Optional[str] = None,
    cache_ttl: int = 300
) -> Any:
    """Get attribute value with caching support.

    Caches resolved values for performance. Cache is automatically
    invalidated when the product or attribute is modified.

    Args:
        product: Product Master name or SKU
        attribute: Attribute name
        locale: Locale for scoped value
        channel: Channel for scoped value
        cache_ttl: Cache time-to-live in seconds (default: 5 minutes)

    Returns:
        Resolved attribute value
    """
    import frappe

    # Build cache key
    cache_key = f"pim:attr:{product}:{attribute}:{locale or 'none'}:{channel or 'none'}"

    # Try to get from cache
    cached = frappe.cache().get_value(cache_key)
    if cached is not None:
        return cached

    # Resolve value
    value = get_scoped_attribute_value(
        product=product,
        attribute=attribute,
        locale=locale,
        channel=channel
    )

    # Cache the result
    frappe.cache().set_value(cache_key, value, expires_in_sec=cache_ttl)

    return value


def invalidate_attribute_cache(
    product: str,
    attribute: Optional[str] = None
) -> None:
    """Invalidate cached attribute values for a product.

    Call this when attribute values are modified.

    Args:
        product: Product Master name
        attribute: Specific attribute to invalidate (optional, all if not provided)
    """
    import frappe

    # Build pattern for cache key deletion
    if attribute:
        pattern = f"pim:attr:{product}:{attribute}:*"
    else:
        pattern = f"pim:attr:{product}:*"

    try:
        frappe.cache().delete_keys(pattern)
    except Exception:
        # Fallback: clear all PIM attribute caches for this product
        frappe.cache().delete_key(f"pim:attr:{product}")


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _resolve_product_name(product: str) -> Optional[str]:
    """Resolve product name from name or SKU"""
    import frappe

    # Check if it's a valid name
    if frappe.db.exists("Product Master", product):
        return product

    # Try to find by SKU
    name = frappe.db.get_value("Product Master", {"sku": product}, "name")
    return name


def _get_attribute_values(product_name: str, attribute: str) -> List[Dict]:
    """Get all attribute value rows for a product and attribute"""
    import frappe

    return frappe.get_all(
        "Product Attribute Value",
        filters={
            "parent": product_name,
            "attribute": attribute
        },
        fields=[
            "name", "locale", "channel", "valid_from", "valid_to",
            "source_system", "is_inherited", "inherited_from",
            "value_text", "value_long_text", "value_int",
            "value_float", "value_boolean", "value_date",
            "value_datetime", "value_link"
        ]
    )


def _get_all_attribute_values(product_name: str) -> List[Dict]:
    """Get all attribute values for a product"""
    import frappe

    return frappe.get_all(
        "Product Attribute Value",
        filters={"parent": product_name},
        fields=[
            "attribute", "locale", "channel", "valid_from", "valid_to",
            "source_system", "is_inherited", "inherited_from",
            "value_text", "value_long_text", "value_int",
            "value_float", "value_boolean", "value_date",
            "value_datetime", "value_link"
        ]
    )


def _get_locale_chain(
    locale: Optional[str],
    include_fallback: bool = True
) -> List[Optional[str]]:
    """Get locale resolution chain including fallbacks"""
    import frappe

    chain = []

    if locale:
        chain.append(locale)

        if include_fallback:
            # Get fallback chain from PIM Locale
            try:
                current = locale
                visited = {locale}
                while current:
                    fallback = frappe.db.get_value("PIM Locale", current, "fallback_locale")
                    if fallback and fallback not in visited:
                        chain.append(fallback)
                        visited.add(fallback)
                        current = fallback
                    else:
                        break
            except Exception:
                pass

    # Always include unscoped (None) as final fallback
    chain.append(None)

    return chain


def _normalize_date(as_of_date: Optional[Union[str, date]]) -> Optional[date]:
    """Normalize date input to date object"""
    import frappe
    from frappe.utils import getdate, today

    if as_of_date is None:
        return getdate(today())

    if isinstance(as_of_date, str):
        return getdate(as_of_date)

    return as_of_date


def _resolve_with_fallback(
    attribute_values: List[Dict],
    locale_chain: List[Optional[str]],
    channel: Optional[str],
    effective_date: Optional[date]
) -> Optional[Dict]:
    """Resolve best value using fallback cascade

    Resolution order:
    1. locale + channel + time (exact match)
    2. locale + channel (ignore time)
    3. locale only
    4. channel only
    5. unscoped
    """
    from frappe.utils import getdate

    # Filter by time validity first
    time_valid = []
    time_ignored = []

    for av in attribute_values:
        valid_from = av.get("valid_from")
        valid_to = av.get("valid_to")

        is_time_valid = True
        if effective_date:
            if valid_from and getdate(valid_from) > effective_date:
                is_time_valid = False
            if valid_to and getdate(valid_to) < effective_date:
                is_time_valid = False

        if is_time_valid:
            time_valid.append(av)
        time_ignored.append(av)  # Keep all for fallback without time

    # Try resolution with time validity
    result = _try_scope_resolution(time_valid, locale_chain, channel, with_time=True)
    if result:
        return result

    # Fallback to resolution without time constraint
    result = _try_scope_resolution(time_ignored, locale_chain, channel, with_time=False)
    return result


def _try_scope_resolution(
    values: List[Dict],
    locale_chain: List[Optional[str]],
    channel: Optional[str],
    with_time: bool
) -> Optional[Dict]:
    """Try to resolve value with scope matching"""

    # Resolution levels with priorities
    # Priority 1: locale + channel (for each locale in chain)
    for loc in locale_chain:
        if channel:
            matches = [
                v for v in values
                if v.get("locale") == loc and v.get("channel") == channel
            ]
            if matches:
                return {
                    "row": matches[0],
                    "scope_match": "exact" if with_time else "locale_channel"
                }

    # Priority 2: locale only (for each locale in chain)
    for loc in locale_chain:
        if loc:  # Skip None locale at this stage
            matches = [
                v for v in values
                if v.get("locale") == loc and not v.get("channel")
            ]
            if matches:
                return {
                    "row": matches[0],
                    "scope_match": "locale_only"
                }

    # Priority 3: channel only
    if channel:
        matches = [
            v for v in values
            if not v.get("locale") and v.get("channel") == channel
        ]
        if matches:
            return {
                "row": matches[0],
                "scope_match": "channel_only"
            }

    # Priority 4: unscoped (no locale, no channel)
    matches = [
        v for v in values
        if not v.get("locale") and not v.get("channel")
    ]
    if matches:
        return {
            "row": matches[0],
            "scope_match": "unscoped"
        }

    return None


def _extract_value(row: Dict) -> Any:
    """Extract the actual value from an EAV row"""
    # Check value fields in priority order
    value_fields = [
        "value_text",
        "value_long_text",
        "value_int",
        "value_float",
        "value_boolean",
        "value_date",
        "value_datetime",
        "value_link"
    ]

    for field in value_fields:
        value = row.get(field)
        if value is not None:
            # Handle empty strings
            if isinstance(value, str) and len(value.strip()) == 0:
                continue
            return value

    return None


def _build_result(value: Any, include_metadata: bool) -> Any:
    """Build return result based on include_metadata flag"""
    if include_metadata:
        return {
            "value": value,
            "locale": None,
            "channel": None,
            "scope_match": None
        }
    return value


def _get_attribute_metadata() -> Dict[str, Dict]:
    """Get metadata for all attributes"""
    import frappe

    try:
        # Try PIM Attribute first
        attributes = frappe.get_all(
            "PIM Attribute",
            fields=[
                "name", "attribute_name", "attribute_type",
                "attribute_group", "unit_of_measure"
            ]
        )
        return {a["name"]: a for a in attributes}
    except Exception:
        try:
            # Fallback to Attribute
            attributes = frappe.get_all(
                "Attribute",
                fields=[
                    "name", "attribute_name", "attribute_type",
                    "attribute_group", "unit_of_measure"
                ]
            )
            return {a["name"]: a for a in attributes}
        except Exception:
            return {}


def _build_attribute_result(
    attribute: str,
    row: Dict,
    scope_match: str,
    meta: Dict,
    is_inherited: bool
) -> Dict[str, Any]:
    """Build attribute result dictionary"""
    return {
        "attribute": attribute,
        "attribute_name": meta.get("attribute_name", attribute),
        "attribute_type": meta.get("attribute_type"),
        "attribute_group": meta.get("attribute_group"),
        "unit_of_measure": meta.get("unit_of_measure"),
        "value": _extract_value(row),
        "locale": row.get("locale"),
        "channel": row.get("channel"),
        "valid_from": row.get("valid_from"),
        "valid_to": row.get("valid_to"),
        "source_system": row.get("source_system"),
        "scope_match": scope_match,
        "is_inherited": is_inherited
    }


def _get_channel_config(channel: str) -> Optional[Dict]:
    """Get channel configuration"""
    import frappe

    try:
        config = frappe.db.get_value(
            "Channel",
            channel,
            ["name", "channel_name", "channel_code", "default_locale", "enabled"],
            as_dict=True
        )

        if config:
            # Get supported locales from child table
            try:
                locales = frappe.get_all(
                    "Channel Locale",
                    filters={"parent": channel},
                    pluck="locale"
                )
                config["supported_locales"] = locales
            except Exception:
                config["supported_locales"] = []

        return config
    except Exception:
        return None


# ============================================================================
# Whitelisted API Functions
# ============================================================================

def whitelist_get_attribute_value():
    """Wrapper for get_scoped_attribute_value for API access"""
    import frappe

    @frappe.whitelist()
    def get_attribute_value(
        product: str,
        attribute: str,
        locale: Optional[str] = None,
        channel: Optional[str] = None,
        as_of_date: Optional[str] = None,
        include_metadata: bool = False
    ):
        return get_scoped_attribute_value(
            product=product,
            attribute=attribute,
            locale=locale,
            channel=channel,
            as_of_date=as_of_date,
            include_metadata=include_metadata == "true" or include_metadata is True
        )

    return get_attribute_value


def whitelist_get_all_attributes():
    """Wrapper for get_all_scoped_attributes for API access"""
    import frappe

    @frappe.whitelist()
    def get_all_attributes(
        product: str,
        locale: Optional[str] = None,
        channel: Optional[str] = None,
        attribute_group: Optional[str] = None,
        include_inherited: bool = True
    ):
        return get_all_scoped_attributes(
            product=product,
            locale=locale,
            channel=channel,
            attribute_group=attribute_group,
            include_inherited=include_inherited == "true" or include_inherited is True
        )

    return get_all_attributes
