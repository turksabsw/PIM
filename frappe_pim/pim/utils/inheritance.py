"""Product Attribute Inheritance Utilities

This module provides functions for inheriting attributes from Product Families
and Master Products to their children/variants.

Inheritance flow:
    1. Product Family defines attribute templates via Family Attribute Template
    2. When a Product Master is created, it inherits those attribute templates
    3. When a Product Variant is created, it can inherit attributes from its
       parent Product Master

These functions are called as doc_events hooks when products are created or updated.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def copy_family_attributes(doc, method=None):
    """Copy attribute templates from Product Family to Product Master.

    When a new Product Master is created with a Product Family assigned,
    this function copies all attribute templates defined in the family
    as empty attribute value rows in the product.

    This ensures the product has placeholders for all family-defined
    attributes, making it easier for users to fill in the data and
    enabling accurate completeness scoring.

    Args:
        doc: The Product Master document being inserted
        method: The hook method name (unused, for Frappe hook signature)

    Returns:
        bool: True if attributes were copied, False otherwise

    Example:
        If "Electronics" family has attributes [Brand, Model, Voltage],
        a new product in that family will get three empty attribute
        value rows for Brand, Model, and Voltage.
    """
    import frappe

    try:
        # Skip if no family assigned
        if not doc.get("product_family"):
            return False

        # Skip if product already has attribute values (not a new product)
        existing_values = doc.get("attribute_values") or []
        if existing_values:
            # Only add missing attributes, don't overwrite existing
            return _add_missing_family_attributes(doc, existing_values)

        # Get family attribute templates
        templates = _get_family_attribute_templates(doc.product_family)

        if not templates:
            return False

        # Initialize attribute_values if not present
        if not doc.get("attribute_values"):
            doc.attribute_values = []

        # Create attribute value rows for each template
        for template in templates:
            attribute_row = _create_attribute_value_row(template)
            if attribute_row:
                doc.append("attribute_values", attribute_row)

        return True

    except Exception as e:
        frappe.log_error(
            message=f"Error copying family attributes to {doc.name}: {str(e)}",
            title="PIM Inheritance Error"
        )
        return False


def inherit_from_master(doc, method=None):
    """Inherit attributes from parent Product Master to Product Variant.

    When a Product Variant is created or updated, this function copies
    inheritable attribute values from its parent Product Master.

    Only attributes marked as "inheritable" in the family template are
    copied. Variant-specific attributes (like size, color) are not
    inherited and must be set directly on the variant.

    Args:
        doc: The Product Variant document being inserted/saved
        method: The hook method name (unused, for Frappe hook signature)

    Returns:
        bool: True if attributes were inherited, False otherwise

    Example:
        If parent product has Brand="Apple" and Brand is marked as
        inheritable, the variant will get Brand="Apple" automatically.
    """
    import frappe

    try:
        # Skip if no parent product
        if not doc.get("parent_product"):
            return False

        # Get parent product
        parent = frappe.get_doc("Product Master", doc.parent_product)
        if not parent:
            return False

        # Get family to determine which attributes are inheritable
        family = parent.get("product_family")
        if not family:
            # No family means no inheritance rules, skip
            return False

        # Get inheritable attribute codes
        inheritable_attrs = _get_inheritable_attributes(family)

        if not inheritable_attrs:
            return False

        # Get parent's attribute values
        parent_values = {
            row.attribute: row
            for row in (parent.get("attribute_values") or [])
        }

        # Initialize attribute_values if not present
        if not doc.get("attribute_values"):
            doc.attribute_values = []

        # Get existing variant attribute codes
        existing_attrs = {
            row.attribute for row in doc.get("attribute_values") or []
        }

        inherited_count = 0
        for attr_code in inheritable_attrs:
            # Skip if variant already has this attribute set
            if attr_code in existing_attrs:
                continue

            # Get parent's value for this attribute
            parent_row = parent_values.get(attr_code)
            if parent_row and _has_eav_value(parent_row):
                # Copy the value to variant
                new_row = _copy_attribute_value_row(parent_row)
                if new_row:
                    doc.append("attribute_values", new_row)
                    inherited_count += 1

        return inherited_count > 0

    except Exception as e:
        frappe.log_error(
            message=f"Error inheriting attributes for variant {doc.name}: {str(e)}",
            title="PIM Inheritance Error"
        )
        return False


def copy_attributes_to_variant(master_doc, variant_doc):
    """Explicitly copy attributes from master to variant.

    This is a utility function that can be called directly (not as a hook)
    to copy all inheritable attributes from a Product Master to a
    Product Variant.

    Args:
        master_doc: Source Product Master document
        variant_doc: Target Product Variant document

    Returns:
        int: Number of attributes copied
    """
    import frappe

    try:
        # Get family for inheritance rules
        family = master_doc.get("product_family")
        if not family:
            return 0

        # Get inheritable attributes
        inheritable_attrs = _get_inheritable_attributes(family)

        if not inheritable_attrs:
            return 0

        # Get master's attribute values
        master_values = {
            row.attribute: row
            for row in (master_doc.get("attribute_values") or [])
        }

        # Initialize if needed
        if not variant_doc.get("attribute_values"):
            variant_doc.attribute_values = []

        # Get existing variant attributes
        existing_attrs = {
            row.attribute for row in variant_doc.get("attribute_values") or []
        }

        copied_count = 0
        for attr_code in inheritable_attrs:
            if attr_code in existing_attrs:
                continue

            master_row = master_values.get(attr_code)
            if master_row and _has_eav_value(master_row):
                new_row = _copy_attribute_value_row(master_row)
                if new_row:
                    variant_doc.append("attribute_values", new_row)
                    copied_count += 1

        return copied_count

    except Exception as e:
        frappe.log_error(
            message=f"Error copying attributes to variant: {str(e)}",
            title="PIM Inheritance Error"
        )
        return 0


def refresh_family_attributes(product_name):
    """Refresh a product's attributes from its family template.

    Adds any missing attributes from the family template to the product.
    Does not overwrite existing attribute values.

    Args:
        product_name: Name of the Product Master to refresh

    Returns:
        int: Number of attributes added
    """
    import frappe

    try:
        doc = frappe.get_doc("Product Master", product_name)
        existing_values = doc.get("attribute_values") or []

        added = _add_missing_family_attributes(doc, existing_values)
        if added:
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            return added

        return 0

    except Exception as e:
        frappe.log_error(
            message=f"Error refreshing family attributes for {product_name}: {str(e)}",
            title="PIM Inheritance Error"
        )
        return 0


def _get_family_attribute_templates(family):
    """Get attribute templates for a product family.

    Retrieves all Family Attribute Template rows for the given family,
    ordered by their display sequence.

    Args:
        family: Name of the Product Family

    Returns:
        list: List of template dicts with attribute info
    """
    import frappe

    try:
        templates = frappe.get_all(
            "Family Attribute Template",
            filters={"parent": family},
            fields=[
                "attribute",
                "is_required",
                "is_variant_attribute",
                "default_value",
                "idx"
            ],
            order_by="idx"
        )
        return templates or []
    except Exception:
        # Family Attribute Template DocType may not exist yet
        return []


def _get_inheritable_attributes(family):
    """Get list of inheritable attribute codes for a family.

    Returns attributes that should be inherited from master to variant.
    Excludes variant-specific attributes (like size, color).

    Args:
        family: Name of the Product Family

    Returns:
        list: List of attribute codes that are inheritable
    """
    import frappe

    try:
        # Attributes that are NOT variant-specific are inheritable
        # Variant-specific attributes (is_variant_attribute=1) should be
        # set directly on the variant
        inheritable = frappe.get_all(
            "Family Attribute Template",
            filters={
                "parent": family,
                "is_variant_attribute": 0  # NOT variant-specific
            },
            pluck="attribute"
        )
        return inheritable or []
    except Exception:
        # Fall back to empty list if DocType doesn't exist
        return []


def _add_missing_family_attributes(doc, existing_values):
    """Add missing family attributes to a product.

    Compares family templates with existing attribute values and adds
    any missing attributes as empty rows.

    Args:
        doc: Product Master document
        existing_values: List of existing attribute value rows

    Returns:
        int: Number of attributes added
    """
    import frappe

    try:
        if not doc.get("product_family"):
            return 0

        # Get existing attribute codes
        existing_attrs = {row.get("attribute") for row in existing_values}

        # Get family templates
        templates = _get_family_attribute_templates(doc.product_family)

        added_count = 0
        for template in templates:
            attr_code = template.get("attribute")
            if attr_code and attr_code not in existing_attrs:
                attribute_row = _create_attribute_value_row(template)
                if attribute_row:
                    doc.append("attribute_values", attribute_row)
                    added_count += 1

        return added_count

    except Exception as e:
        frappe.log_error(
            message=f"Error adding missing attributes: {str(e)}",
            title="PIM Inheritance Error"
        )
        return 0


def _create_attribute_value_row(template):
    """Create a new attribute value row from a template.

    Initializes an attribute value row with the attribute code and
    optional default value from the template.

    Args:
        template: Family Attribute Template row dict

    Returns:
        dict: Attribute value row data, or None if invalid
    """
    import frappe

    try:
        attr_code = template.get("attribute")
        if not attr_code:
            return None

        # Get attribute details for data type
        attr_doc = frappe.get_cached_value(
            "PIM Attribute",
            attr_code,
            ["data_type", "attribute_name"],
            as_dict=True
        )

        row = {
            "attribute": attr_code,
            "attribute_name": attr_doc.get("attribute_name") if attr_doc else attr_code,
        }

        # Set default value if provided
        default_value = template.get("default_value")
        if default_value and attr_doc:
            value_field = _get_value_field_for_type(attr_doc.get("data_type"))
            if value_field:
                row[value_field] = _convert_default_value(
                    default_value,
                    attr_doc.get("data_type")
                )

        return row

    except Exception:
        # Return basic row if attribute lookup fails
        return {
            "attribute": template.get("attribute"),
            "attribute_name": template.get("attribute")
        }


def _copy_attribute_value_row(source_row):
    """Create a copy of an attribute value row.

    Copies all value fields from the source row to a new row dict.

    Args:
        source_row: Source Product Attribute Value row

    Returns:
        dict: New attribute value row data
    """
    value_fields = [
        "value_text",
        "value_int",
        "value_float",
        "value_boolean",
        "value_date",
        "value_datetime",
        "value_link",
        "value_data",
    ]

    new_row = {
        "attribute": source_row.get("attribute"),
        "attribute_name": source_row.get("attribute_name"),
    }

    # Copy all value fields
    for field in value_fields:
        value = source_row.get(field)
        if value is not None:
            new_row[field] = value

    return new_row


def _get_value_field_for_type(data_type):
    """Get the appropriate value field for an attribute data type.

    Maps PIM Attribute data types to the correct EAV value column.

    Args:
        data_type: Attribute data type (e.g., "Text", "Integer", "Float")

    Returns:
        str: Name of the value field to use
    """
    type_mapping = {
        "Text": "value_text",
        "Long Text": "value_text",
        "Integer": "value_int",
        "Float": "value_float",
        "Decimal": "value_float",
        "Boolean": "value_boolean",
        "Date": "value_date",
        "Datetime": "value_datetime",
        "Link": "value_link",
        "Select": "value_text",
        "Multi Select": "value_text",
        "Data": "value_data",
    }
    return type_mapping.get(data_type, "value_text")


def _convert_default_value(value, data_type):
    """Convert a default value string to the appropriate type.

    Parses the default value string and converts it to the correct
    Python type for the attribute data type.

    Args:
        value: Default value as string
        data_type: Attribute data type

    Returns:
        Converted value in appropriate type
    """
    if value is None:
        return None

    try:
        if data_type in ("Integer",):
            return int(value)
        elif data_type in ("Float", "Decimal"):
            return float(value)
        elif data_type in ("Boolean",):
            return value.lower() in ("true", "1", "yes")
        else:
            return str(value)
    except (ValueError, AttributeError):
        return str(value)


def _has_eav_value(row):
    """Check if an EAV row has any value set.

    Checks all value columns in the Product Attribute Value row
    to determine if any value is present.

    Args:
        row: Product Attribute Value row (dict-like)

    Returns:
        bool: True if any value column has a value, False otherwise
    """
    value_fields = [
        "value_text",
        "value_int",
        "value_float",
        "value_boolean",
        "value_date",
        "value_datetime",
        "value_link",
        "value_data",
    ]

    for field in value_fields:
        value = row.get(field)
        if value is not None:
            if isinstance(value, str):
                if len(value.strip()) > 0:
                    return True
            elif isinstance(value, bool):
                return True
            elif isinstance(value, (int, float)):
                return True
            else:
                return True

    return False
