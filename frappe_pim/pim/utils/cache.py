"""PIM Cache Management Utilities

This module provides cache invalidation and caching helper functions
for the PIM application. It uses Frappe's built-in Redis cache interface.

Cache keys follow the naming convention:
    pim:{entity_type}:{identifier}

For example:
    - pim:product:PROD-001
    - pim:family:Electronics
    - pim:attribute:color
    - pim:grid_data:Electronics

These functions are called as doc_events hooks when PIM documents
are updated to ensure cache coherency.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def invalidate_product_cache(doc, method=None):
    """Clear product-related caches when a Product Master is updated.

    Invalidates caches for:
        - The specific product
        - Family products list (products in the same family)
        - Grid data for the product's family

    Args:
        doc: The Product Master document being updated
        method: The hook method name (unused, for Frappe hook signature)

    Example:
        When product PROD-001 in family "Electronics" is updated,
        these cache keys are invalidated:
            - pim:product:PROD-001
            - pim:family_products:Electronics
            - pim:grid_data:Electronics
    """
    import frappe

    try:
        cache = frappe.cache()
        product_name = doc.name if hasattr(doc, "name") else str(doc)

        # Product-specific cache
        cache.delete_key(f"pim:product:{product_name}")

        # Family-related caches (if product has a family)
        family = doc.get("product_family") if hasattr(doc, "get") else None
        if family:
            cache.delete_key(f"pim:family_products:{family}")
            cache.delete_key(f"pim:grid_data:{family}")

        # Invalidate product list cache
        cache.delete_key("pim:all_products")

        # Invalidate completeness report caches
        cache.delete_key(f"pim:completeness:{product_name}")

    except Exception as e:
        # Log error but don't fail the operation
        frappe.log_error(
            message=f"Error invalidating product cache for {doc.name}: {str(e)}",
            title="PIM Cache Invalidation Error"
        )


def invalidate_attribute_cache(doc, method=None):
    """Clear attribute-related caches when a PIM Attribute is updated.

    Invalidates caches for:
        - The specific attribute
        - All attributes list
        - Attribute options (for select-type attributes)

    Args:
        doc: The PIM Attribute document being updated
        method: The hook method name (unused, for Frappe hook signature)

    Example:
        When attribute "color" is updated, these cache keys are invalidated:
            - pim:attribute:color
            - pim:all_attributes
            - pim:attribute_options:color
    """
    import frappe

    try:
        cache = frappe.cache()
        attr_name = doc.name if hasattr(doc, "name") else str(doc)

        # Attribute-specific cache
        cache.delete_key(f"pim:attribute:{attr_name}")

        # Global attribute list cache
        cache.delete_key("pim:all_attributes")

        # Attribute options cache (for select-type attributes)
        cache.delete_key(f"pim:attribute_options:{attr_name}")

        # Attribute groups cache
        if hasattr(doc, "get"):
            group = doc.get("attribute_group")
            if group:
                cache.delete_key(f"pim:attribute_group:{group}")

    except Exception as e:
        frappe.log_error(
            message=f"Error invalidating attribute cache for {doc.name}: {str(e)}",
            title="PIM Cache Invalidation Error"
        )


def invalidate_family_cache(doc, method=None):
    """Clear family-related caches when a Product Family is updated.

    Invalidates caches for:
        - The specific family
        - Family attribute templates
        - Family tree structure
        - Child family caches

    Args:
        doc: The Product Family document being updated
        method: The hook method name (unused, for Frappe hook signature)

    Example:
        When family "Electronics" is updated, these cache keys are invalidated:
            - pim:family:Electronics
            - pim:family_attrs:Electronics
            - pim:family_tree
    """
    import frappe

    try:
        cache = frappe.cache()
        family_name = doc.name if hasattr(doc, "name") else str(doc)

        # Family-specific cache
        cache.delete_key(f"pim:family:{family_name}")

        # Family attribute templates cache
        cache.delete_key(f"pim:family_attrs:{family_name}")

        # Family products cache
        cache.delete_key(f"pim:family_products:{family_name}")

        # Grid data for this family
        cache.delete_key(f"pim:grid_data:{family_name}")

        # Global family tree cache
        cache.delete_key("pim:family_tree")
        cache.delete_key("pim:all_families")

        # If family has parent, invalidate parent's children cache
        if hasattr(doc, "get"):
            parent = doc.get("parent_product_family")
            if parent:
                cache.delete_key(f"pim:family_children:{parent}")

    except Exception as e:
        frappe.log_error(
            message=f"Error invalidating family cache for {doc.name}: {str(e)}",
            title="PIM Cache Invalidation Error"
        )


def invalidate_variant_cache(doc, method=None):
    """Clear variant-related caches when a Product Variant is updated.

    Invalidates caches for:
        - The specific variant
        - Parent product's variants list
        - Grid data for the parent's family

    Args:
        doc: The Product Variant document being updated
        method: The hook method name (unused, for Frappe hook signature)
    """
    import frappe

    try:
        cache = frappe.cache()
        variant_name = doc.name if hasattr(doc, "name") else str(doc)

        # Variant-specific cache
        cache.delete_key(f"pim:variant:{variant_name}")

        # Parent product's variants list
        if hasattr(doc, "get"):
            parent = doc.get("parent_product")
            if parent:
                cache.delete_key(f"pim:product_variants:{parent}")
                cache.delete_key(f"pim:product:{parent}")

    except Exception as e:
        frappe.log_error(
            message=f"Error invalidating variant cache for {doc.name}: {str(e)}",
            title="PIM Cache Invalidation Error"
        )


def get_cached(key, getter, ttl=3600):
    """Get a value from cache or compute and store it.

    This is a cache-aside pattern helper that:
        1. Tries to get the value from Redis cache
        2. If not found, calls the getter function
        3. Stores the result in cache with the specified TTL
        4. Returns the value

    Args:
        key: The cache key (will be prefixed with 'pim:')
        getter: A callable that returns the value if not cached
        ttl: Time-to-live in seconds (default: 3600 = 1 hour)

    Returns:
        The cached or computed value

    Example:
        def get_expensive_data():
            return frappe.db.sql(...)

        data = get_cached("my_data", get_expensive_data, ttl=1800)
    """
    import frappe

    try:
        cache = frappe.cache()
        cache_key = f"pim:{key}" if not key.startswith("pim:") else key

        # Try to get from cache
        result = cache.get_value(cache_key)

        if result is None:
            # Compute the value
            result = getter()

            # Store in cache with TTL
            if result is not None:
                cache.set_value(cache_key, result, expires_in_sec=ttl)

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Error in get_cached for key {key}: {str(e)}",
            title="PIM Cache Error"
        )
        # Fall back to computing without caching
        try:
            return getter()
        except Exception:
            return None


def clear_all_pim_cache():
    """Clear all PIM-related caches.

    This is useful for maintenance operations or when bulk data
    changes are made that would invalidate multiple cache entries.

    Warning: This should be used sparingly as it will cause
    temporary performance degradation while caches are rebuilt.
    """
    import frappe

    try:
        cache = frappe.cache()

        # Get all keys matching pim:* pattern and delete them
        # Note: Frappe's cache.delete_keys() handles pattern matching
        cache.delete_keys("pim:*")

        frappe.log_error(
            message="All PIM caches cleared",
            title="PIM Cache Maintenance"
        )

    except Exception as e:
        frappe.log_error(
            message=f"Error clearing all PIM caches: {str(e)}",
            title="PIM Cache Error"
        )


def warm_cache_for_family(family_name):
    """Pre-populate caches for a product family.

    Loads commonly accessed data for a family into cache to
    improve performance for subsequent requests.

    Args:
        family_name: Name of the Product Family to warm cache for
    """
    import frappe

    try:
        cache = frappe.cache()

        # Cache family document
        family = frappe.get_doc("Product Family", family_name)
        cache.set_value(f"pim:family:{family_name}", family.as_dict(), expires_in_sec=3600)

        # Cache family attribute templates
        templates = frappe.get_all(
            "Family Attribute Template",
            filters={"parent": family_name},
            fields=["attribute", "is_required", "is_variant_attribute", "default_value"]
        )
        cache.set_value(f"pim:family_attrs:{family_name}", templates, expires_in_sec=3600)

        # Cache product count for family
        product_count = frappe.db.count("Product Master", {"product_family": family_name})
        cache.set_value(f"pim:family_product_count:{family_name}", product_count, expires_in_sec=1800)

    except Exception as e:
        frappe.log_error(
            message=f"Error warming cache for family {family_name}: {str(e)}",
            title="PIM Cache Error"
        )
