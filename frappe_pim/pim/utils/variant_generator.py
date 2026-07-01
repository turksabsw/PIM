"""
PIM Variant Generator Utility
Generates product variants from template using axis attributes with SKU pattern support

This module provides functions for:
- Generating all variant combinations from axis attributes
- Creating SKUs using customizable patterns (MASTER-{color}-{size})
- Validating variant combinations for uniqueness
- Batch creation of variants with progress tracking

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import re
import itertools
from typing import List, Dict, Optional, Tuple, Any


# SKU pattern placeholders
SKU_PLACEHOLDER_REGEX = re.compile(r'\{(\w+)\}')

# Reserved placeholders
RESERVED_PLACEHOLDERS = {
    'master': 'master_code',      # Product Master code
    'master_name': 'master_name', # Product Master name
    'idx': 'idx',                 # Sequential index
    'uuid': 'uuid'                # Unique identifier
}


def generate_variants(
    product_master: str,
    axis_attributes: List[Dict[str, Any]],
    sku_pattern: Optional[str] = None,
    create_immediately: bool = True,
    status: str = "Draft",
    inherit_attributes: bool = True,
    skip_existing: bool = True
) -> Dict[str, Any]:
    """Generate product variants from a Product Master using axis attributes.

    Creates all possible combinations of the specified axis attribute values
    as Product Variant documents.

    Args:
        product_master: Name of the Product Master document
        axis_attributes: List of dicts with attribute configuration:
            [
                {
                    "attribute": "color",     # PIM Attribute name
                    "values": ["Red", "Blue"] # Values to generate variants for
                },
                {
                    "attribute": "size",
                    "values": ["S", "M", "L"]
                }
            ]
        sku_pattern: SKU pattern with placeholders, e.g. "{master}-{color}-{size}"
                     If not provided, auto-generates as MASTER-VAL1-VAL2
        create_immediately: If True, creates variants in database immediately
                           If False, returns preview data without creating
        status: Initial status for created variants (default: "Draft")
        inherit_attributes: Whether to inherit attributes from master
        skip_existing: Skip creation of variants that already exist

    Returns:
        dict with generation results:
        {
            "success": bool,
            "product_master": str,
            "total_combinations": int,
            "created": int,
            "skipped": int,  # Already existing
            "errors": int,
            "variants": list,  # Created/preview variant data
            "messages": list
        }

    Example:
        >>> result = generate_variants(
        ...     "PROD-001",
        ...     [
        ...         {"attribute": "color", "values": ["Red", "Blue"]},
        ...         {"attribute": "size", "values": ["S", "M", "L"]}
        ...     ],
        ...     sku_pattern="{master}-{color}-{size}"
        ... )
        >>> print(f"Created {result['created']} variants")
    """
    import frappe
    from frappe import _

    # Initialize result
    result = {
        "success": False,
        "product_master": product_master,
        "total_combinations": 0,
        "created": 0,
        "skipped": 0,
        "errors": 0,
        "variants": [],
        "messages": []
    }

    try:
        # Validate product master exists
        if not frappe.db.exists("Product Master", product_master):
            result["messages"].append(f"Product Master '{product_master}' not found")
            return result

        # Get master info
        master = frappe.db.get_value(
            "Product Master",
            product_master,
            ["name", "product_code", "product_name", "product_family"],
            as_dict=True
        )

        # Validate axis attributes
        validation_result = _validate_axis_attributes(axis_attributes)
        if not validation_result["valid"]:
            result["messages"].extend(validation_result["errors"])
            return result

        # Generate all combinations
        combinations = _generate_combinations(axis_attributes)
        result["total_combinations"] = len(combinations)

        if not combinations:
            result["messages"].append("No combinations to generate")
            return result

        # Determine SKU pattern
        if not sku_pattern:
            sku_pattern = _get_default_sku_pattern(axis_attributes, master)

        # Validate SKU pattern
        pattern_validation = validate_sku_pattern(sku_pattern, axis_attributes)
        if not pattern_validation["valid"]:
            result["messages"].extend(pattern_validation["errors"])
            return result

        # Generate variants
        for idx, combo in enumerate(combinations, start=1):
            try:
                # Generate SKU
                sku = generate_sku(
                    pattern=sku_pattern,
                    attribute_values=combo,
                    master_code=master.product_code,
                    master_name=master.product_name,
                    idx=idx
                )

                # Check if variant already exists
                if skip_existing and _variant_exists(product_master, sku, combo):
                    result["skipped"] += 1
                    result["variants"].append({
                        "sku": sku,
                        "combination": combo,
                        "status": "skipped",
                        "reason": "Already exists"
                    })
                    continue

                # Prepare variant data
                variant_data = _prepare_variant_data(
                    product_master=product_master,
                    sku=sku,
                    combination=combo,
                    master=master,
                    status=status
                )

                if create_immediately:
                    # Create variant in database
                    variant = _create_variant_document(
                        variant_data,
                        inherit_attributes=inherit_attributes
                    )
                    result["created"] += 1
                    result["variants"].append({
                        "name": variant.name,
                        "sku": sku,
                        "combination": combo,
                        "status": "created"
                    })
                else:
                    # Preview mode - just return data
                    result["created"] += 1
                    result["variants"].append({
                        "sku": sku,
                        "combination": combo,
                        "status": "preview",
                        "data": variant_data
                    })

            except Exception as e:
                result["errors"] += 1
                result["variants"].append({
                    "sku": sku if 'sku' in dir() else None,
                    "combination": combo,
                    "status": "error",
                    "error": str(e)
                })
                frappe.log_error(
                    message=f"Error creating variant: {str(e)}",
                    title="PIM Variant Generator Error"
                )

        if create_immediately:
            frappe.db.commit()

        result["success"] = result["errors"] == 0

    except Exception as e:
        result["messages"].append(f"Variant generation failed: {str(e)}")
        frappe.log_error(
            message=f"Variant generation failed for {product_master}: {str(e)}",
            title="PIM Variant Generator Error"
        )

    return result


def generate_sku(
    pattern: str,
    attribute_values: Dict[str, str],
    master_code: Optional[str] = None,
    master_name: Optional[str] = None,
    idx: Optional[int] = None
) -> str:
    """Generate a SKU from a pattern and attribute values.

    Replaces placeholders in the pattern with actual values.

    Args:
        pattern: SKU pattern with placeholders, e.g. "{master}-{color}-{size}"
        attribute_values: Dict mapping attribute names to values
        master_code: Product Master code (for {master} placeholder)
        master_name: Product Master name (for {master_name} placeholder)
        idx: Sequential index (for {idx} placeholder)

    Returns:
        Generated SKU string

    Example:
        >>> sku = generate_sku(
        ...     "{master}-{color}-{size}",
        ...     {"color": "Red", "size": "Large"},
        ...     master_code="SHIRT"
        ... )
        >>> print(sku)  # "SHIRT-RED-LRG" (normalized)
    """
    import frappe

    sku = pattern

    # Replace reserved placeholders
    if master_code:
        sku = sku.replace("{master}", _normalize_sku_segment(master_code))

    if master_name:
        sku = sku.replace("{master_name}", _normalize_sku_segment(master_name))

    if idx is not None:
        sku = sku.replace("{idx}", str(idx).zfill(3))

    if "{uuid}" in sku:
        sku = sku.replace("{uuid}", frappe.generate_hash("", 6).upper())

    # Replace attribute placeholders
    for attr, value in attribute_values.items():
        placeholder = "{" + attr + "}"
        if placeholder in sku:
            sku = sku.replace(placeholder, _normalize_sku_segment(str(value)))

        # Also try lowercase attribute name
        placeholder_lower = "{" + attr.lower() + "}"
        if placeholder_lower in sku:
            sku = sku.replace(placeholder_lower, _normalize_sku_segment(str(value)))

    # Clean up any unreplaced placeholders
    sku = re.sub(r'\{[^}]+\}', '', sku)

    # Clean up multiple consecutive separators
    sku = re.sub(r'-+', '-', sku)
    sku = sku.strip('-')

    return sku.upper()


def validate_variant_combination(
    product_master: str,
    combination: Dict[str, str],
    exclude_variant: Optional[str] = None
) -> Dict[str, Any]:
    """Validate that a variant combination is unique for the product master.

    Checks if a variant with the same attribute combination already exists.

    Args:
        product_master: Name of the Product Master
        combination: Dict mapping attribute names to values
        exclude_variant: Variant name to exclude from check (for updates)

    Returns:
        dict with validation result:
        {
            "valid": bool,
            "existing_variant": str or None,
            "message": str
        }

    Example:
        >>> result = validate_variant_combination(
        ...     "PROD-001",
        ...     {"color": "Red", "size": "Large"}
        ... )
        >>> if not result["valid"]:
        ...     print(f"Duplicate: {result['existing_variant']}")
    """
    import frappe
    from frappe import _

    result = {
        "valid": True,
        "existing_variant": None,
        "message": ""
    }

    try:
        # Get all existing variants for this master
        existing_variants = frappe.get_all(
            "Product Variant",
            filters={"product_master": product_master},
            fields=[
                "name",
                "option_1_attribute", "option_1_value",
                "option_2_attribute", "option_2_value",
                "option_3_attribute", "option_3_value",
                "option_4_attribute", "option_4_value"
            ]
        )

        for variant in existing_variants:
            # Skip the variant being updated
            if exclude_variant and variant.name == exclude_variant:
                continue

            # Build combination for existing variant
            existing_combo = {}
            for i in range(1, 5):
                attr = variant.get(f"option_{i}_attribute")
                val = variant.get(f"option_{i}_value")
                if attr and val:
                    existing_combo[attr] = val

            # Compare combinations
            if _combinations_match(combination, existing_combo):
                result["valid"] = False
                result["existing_variant"] = variant.name
                result["message"] = _(
                    "A variant with this combination already exists: {0}"
                ).format(variant.name)
                return result

        result["message"] = _("Combination is unique")

    except Exception as e:
        result["valid"] = False
        result["message"] = _("Error validating combination: {0}").format(str(e))

    return result


def preview_variant_combinations(
    product_master: str,
    axis_attributes: List[Dict[str, Any]],
    sku_pattern: Optional[str] = None
) -> Dict[str, Any]:
    """Preview variant combinations without creating them.

    Useful for showing users what variants will be generated before
    actually creating them.

    Args:
        product_master: Name of the Product Master
        axis_attributes: List of axis attribute configurations
        sku_pattern: Optional SKU pattern

    Returns:
        dict with preview data:
        {
            "total_combinations": int,
            "existing_count": int,
            "new_count": int,
            "combinations": list of dicts with sku and attribute values
        }
    """
    return generate_variants(
        product_master=product_master,
        axis_attributes=axis_attributes,
        sku_pattern=sku_pattern,
        create_immediately=False
    )


def validate_sku_pattern(
    pattern: str,
    axis_attributes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Validate a SKU pattern against axis attributes.

    Checks that the pattern contains valid placeholders.

    Args:
        pattern: SKU pattern to validate
        axis_attributes: List of axis attribute configurations

    Returns:
        dict with validation result:
        {
            "valid": bool,
            "errors": list of error messages,
            "placeholders": list of found placeholders,
            "missing_attributes": list of attribute names not in pattern
        }
    """
    result = {
        "valid": True,
        "errors": [],
        "placeholders": [],
        "missing_attributes": []
    }

    # Find all placeholders in pattern
    placeholders = SKU_PLACEHOLDER_REGEX.findall(pattern)
    result["placeholders"] = placeholders

    # Get attribute names
    attr_names = {attr["attribute"].lower() for attr in axis_attributes}

    # Check each placeholder
    for placeholder in placeholders:
        placeholder_lower = placeholder.lower()

        # Check if it's a reserved placeholder
        if placeholder_lower in RESERVED_PLACEHOLDERS:
            continue

        # Check if it matches an axis attribute
        if placeholder_lower not in attr_names:
            result["valid"] = False
            result["errors"].append(
                f"Unknown placeholder '{{{placeholder}}}' - not a reserved name or axis attribute"
            )

    # Check for missing attributes in pattern
    pattern_lower = pattern.lower()
    for attr in axis_attributes:
        attr_name = attr["attribute"].lower()
        if "{" + attr_name + "}" not in pattern_lower:
            result["missing_attributes"].append(attr["attribute"])

    # Warn if no axis attributes are in the pattern
    if result["missing_attributes"] and len(result["missing_attributes"]) == len(axis_attributes):
        result["errors"].append(
            "SKU pattern doesn't include any axis attribute placeholders - "
            "generated SKUs may not be unique"
        )
        result["valid"] = False

    return result


def get_axis_attribute_options(
    product_master: str = None,
    product_family: str = None
) -> List[Dict[str, Any]]:
    """Get available axis attributes and their possible values.

    Retrieves attributes that are marked as variant axis attributes
    for the product family, along with their allowed values (options).

    Args:
        product_master: Product Master name (will look up family)
        product_family: Product Family name (direct)

    Returns:
        list of dicts with axis attribute info:
        [
            {
                "attribute": "color",
                "attribute_name": "Color",
                "values": ["Red", "Blue", "Green"],
                "data_type": "Select"
            }
        ]
    """
    import frappe

    if product_master and not product_family:
        product_family = frappe.db.get_value(
            "Product Master", product_master, "product_family"
        )

    if not product_family:
        return []

    axis_attributes = []

    try:
        # Get family attribute templates marked as variant axis
        templates = frappe.get_all(
            "Family Attribute Template",
            filters={
                "parent": product_family,
                "is_variant_attribute": 1
            },
            fields=["attribute"],
            order_by="idx"
        )

        for template in templates:
            attr_name = template.attribute

            # Get attribute details
            attr = frappe.db.get_value(
                "PIM Attribute",
                attr_name,
                ["name", "attribute_name", "data_type"],
                as_dict=True
            )

            if not attr:
                continue

            # Get attribute options/values
            values = _get_attribute_values(attr_name, attr.data_type)

            axis_attributes.append({
                "attribute": attr.name,
                "attribute_name": attr.attribute_name,
                "values": values,
                "data_type": attr.data_type
            })

    except Exception as e:
        # Handle case where DocType doesn't exist yet
        import frappe
        frappe.log_error(
            message=f"Error getting axis attributes: {str(e)}",
            title="PIM Variant Generator"
        )

    return axis_attributes


def bulk_generate_variants(
    product_masters: List[str],
    use_family_attributes: bool = True,
    custom_attributes: Optional[List[Dict[str, Any]]] = None,
    sku_pattern: Optional[str] = None,
    status: str = "Draft"
) -> Dict[str, Any]:
    """Generate variants for multiple product masters.

    Useful for batch variant generation across multiple products.

    Args:
        product_masters: List of Product Master names
        use_family_attributes: Use axis attributes from product family
        custom_attributes: Override with custom axis attributes
        sku_pattern: SKU pattern to use
        status: Initial status for variants

    Returns:
        dict with batch generation results:
        {
            "total_masters": int,
            "successful": int,
            "failed": int,
            "results": dict mapping master name to generation result
        }
    """
    import frappe

    result = {
        "total_masters": len(product_masters),
        "successful": 0,
        "failed": 0,
        "results": {}
    }

    for master in product_masters:
        try:
            if use_family_attributes:
                axis_attrs = get_axis_attribute_options(product_master=master)
            else:
                axis_attrs = custom_attributes or []

            if not axis_attrs:
                result["results"][master] = {
                    "success": False,
                    "message": "No axis attributes found"
                }
                result["failed"] += 1
                continue

            gen_result = generate_variants(
                product_master=master,
                axis_attributes=axis_attrs,
                sku_pattern=sku_pattern,
                create_immediately=True,
                status=status
            )

            result["results"][master] = gen_result

            if gen_result["success"]:
                result["successful"] += 1
            else:
                result["failed"] += 1

        except Exception as e:
            result["results"][master] = {
                "success": False,
                "message": str(e)
            }
            result["failed"] += 1

    return result


def delete_variants_for_master(
    product_master: str,
    force: bool = False
) -> Dict[str, Any]:
    """Delete all variants for a product master.

    Args:
        product_master: Product Master name
        force: Force delete even if variants are published

    Returns:
        dict with deletion result
    """
    import frappe
    from frappe import _

    result = {
        "success": False,
        "deleted": 0,
        "skipped": 0,
        "messages": []
    }

    try:
        variants = frappe.get_all(
            "Product Variant",
            filters={"product_master": product_master},
            fields=["name", "published_channels"]
        )

        for variant in variants:
            try:
                # Check if published (if not forcing)
                if not force:
                    published = frappe.db.count(
                        "Product Channel",
                        {"parent": variant.name}
                    )
                    if published > 0:
                        result["skipped"] += 1
                        result["messages"].append(
                            f"Skipped {variant.name}: published to channels"
                        )
                        continue

                frappe.delete_doc(
                    "Product Variant",
                    variant.name,
                    ignore_permissions=True
                )
                result["deleted"] += 1

            except Exception as e:
                result["messages"].append(f"Error deleting {variant.name}: {str(e)}")

        frappe.db.commit()
        result["success"] = True

    except Exception as e:
        result["messages"].append(f"Deletion failed: {str(e)}")

    return result


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _validate_axis_attributes(axis_attributes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate axis attributes configuration.

    Args:
        axis_attributes: List of axis attribute configurations

    Returns:
        dict with validation result
    """
    import frappe

    result = {
        "valid": True,
        "errors": []
    }

    if not axis_attributes:
        result["valid"] = False
        result["errors"].append("No axis attributes provided")
        return result

    if len(axis_attributes) > 4:
        result["valid"] = False
        result["errors"].append("Maximum 4 axis attributes supported")
        return result

    for attr in axis_attributes:
        # Check required fields
        if "attribute" not in attr:
            result["valid"] = False
            result["errors"].append("Axis attribute missing 'attribute' field")
            continue

        if "values" not in attr or not attr["values"]:
            result["valid"] = False
            result["errors"].append(
                f"Axis attribute '{attr['attribute']}' has no values"
            )
            continue

        # Validate attribute exists
        if not frappe.db.exists("PIM Attribute", attr["attribute"]):
            result["valid"] = False
            result["errors"].append(
                f"PIM Attribute '{attr['attribute']}' does not exist"
            )

    return result


def _generate_combinations(
    axis_attributes: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """Generate all combinations of axis attribute values.

    Args:
        axis_attributes: List of axis attribute configurations

    Returns:
        List of dicts with attribute value combinations
    """
    if not axis_attributes:
        return []

    # Extract attribute names and values
    attrs = [(attr["attribute"], attr["values"]) for attr in axis_attributes]

    # Generate cartesian product
    combinations = []
    value_lists = [values for _, values in attrs]

    for combo in itertools.product(*value_lists):
        combo_dict = {}
        for (attr_name, _), value in zip(attrs, combo):
            combo_dict[attr_name] = value
        combinations.append(combo_dict)

    return combinations


def _get_default_sku_pattern(
    axis_attributes: List[Dict[str, Any]],
    master: Dict[str, Any]
) -> str:
    """Generate default SKU pattern from axis attributes.

    Args:
        axis_attributes: List of axis attribute configurations
        master: Product Master info dict

    Returns:
        Default SKU pattern string
    """
    parts = ["{master}"]

    for attr in axis_attributes:
        attr_name = attr["attribute"].lower().replace(" ", "_")
        parts.append("{" + attr_name + "}")

    return "-".join(parts)


def _normalize_sku_segment(value: str) -> str:
    """Normalize a value for use in SKU.

    Removes special characters and limits length.

    Args:
        value: Value to normalize

    Returns:
        Normalized string suitable for SKU
    """
    if not value:
        return ""

    # Remove special characters, keep alphanumeric and hyphens
    normalized = re.sub(r'[^A-Za-z0-9-]', '', str(value))

    # Limit length (max 10 chars per segment)
    if len(normalized) > 10:
        normalized = normalized[:10]

    return normalized.upper()


def _variant_exists(
    product_master: str,
    sku: str,
    combination: Dict[str, str]
) -> bool:
    """Check if a variant already exists.

    Args:
        product_master: Product Master name
        sku: Generated SKU to check
        combination: Attribute combination dict

    Returns:
        True if variant exists, False otherwise
    """
    import frappe

    # Check by SKU first (faster)
    if frappe.db.exists("Product Variant", sku):
        return True

    # Check by combination
    validation = validate_variant_combination(product_master, combination)
    return not validation["valid"]


def _combinations_match(
    combo1: Dict[str, str],
    combo2: Dict[str, str]
) -> bool:
    """Check if two attribute combinations match.

    Args:
        combo1: First combination dict
        combo2: Second combination dict

    Returns:
        True if combinations are equivalent
    """
    # Normalize keys to lowercase for comparison
    norm1 = {k.lower(): v.lower() if isinstance(v, str) else v
             for k, v in combo1.items()}
    norm2 = {k.lower(): v.lower() if isinstance(v, str) else v
             for k, v in combo2.items()}

    return norm1 == norm2


def _prepare_variant_data(
    product_master: str,
    sku: str,
    combination: Dict[str, str],
    master: Dict[str, Any],
    status: str
) -> Dict[str, Any]:
    """Prepare variant document data.

    Args:
        product_master: Product Master name
        sku: Generated SKU
        combination: Attribute combination dict
        master: Product Master info dict
        status: Initial status

    Returns:
        Dict with variant document data
    """
    # Generate variant name from combination
    combo_parts = [f"{v}" for v in combination.values()]
    variant_name = f"{master.get('product_name', '')} - {' / '.join(combo_parts)}"

    variant_data = {
        "doctype": "Product Variant",
        "variant_code": sku,
        "variant_name": variant_name[:140],  # Limit length
        "product_master": product_master,
        "status": status
    }

    # Map combination to option fields (max 4)
    attrs = list(combination.items())
    for i, (attr, value) in enumerate(attrs[:4], start=1):
        variant_data[f"option_{i}_attribute"] = attr
        variant_data[f"option_{i}_value"] = value

    return variant_data


def _create_variant_document(
    variant_data: Dict[str, Any],
    inherit_attributes: bool = True
) -> Any:
    """Create a Product Variant document.

    Args:
        variant_data: Variant document data
        inherit_attributes: Whether to inherit from master

    Returns:
        Created Product Variant document
    """
    import frappe

    variant = frappe.get_doc(variant_data)
    variant.insert(ignore_permissions=True)

    return variant


def _get_attribute_values(attr_name: str, data_type: str) -> List[str]:
    """Get possible values for an attribute.

    Args:
        attr_name: PIM Attribute name
        data_type: Attribute data type

    Returns:
        List of possible values
    """
    import frappe

    values = []

    # For Select/Multi Select, get from PIM Attribute Option
    if data_type in ("Select", "Multi Select"):
        try:
            options = frappe.get_all(
                "PIM Attribute Option",
                filters={"attribute": attr_name, "is_active": 1},
                fields=["option_value", "option_label"],
                order_by="sort_order, option_label"
            )
            values = [opt.option_value for opt in options]
        except Exception:
            pass

    return values
