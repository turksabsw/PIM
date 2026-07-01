"""PIM Jinja Template Helper Functions

This module provides Jinja template helper functions for the PIM application.
These functions are registered in hooks.py under the `jinja` configuration
and can be used directly in Frappe's Jinja templates.

Usage in templates:
    {{ get_product_attributes("PROD-001") }}
    {{ get_completeness_badge(75.5) }}
    {{ get_completeness_badge(product.completeness_score) }}

The functions are designed to be safe for template use with proper
error handling and fallback values.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""


def get_product_attributes(product_name, include_empty=False, group_by=None):
    """Get formatted product attributes for display in templates.

    Retrieves all attribute values for a product and formats them
    for display in Jinja templates. Supports optional grouping by
    attribute group and filtering of empty values.

    Args:
        product_name: Name of the Product Master document
        include_empty: If True, include attributes with no value set
                       (default: False)
        group_by: If "group", return attributes grouped by attribute group
                  (default: None for flat list)

    Returns:
        list or dict: List of attribute dicts with name, value, and type,
                      or dict grouped by attribute group name

    Example:
        In Jinja template:
        {% set attrs = get_product_attributes("PROD-001") %}
        {% for attr in attrs %}
            <div>{{ attr.label }}: {{ attr.display_value }}</div>
        {% endfor %}

        With grouping:
        {% set attrs = get_product_attributes("PROD-001", group_by="group") %}
        {% for group_name, group_attrs in attrs.items() %}
            <h3>{{ group_name }}</h3>
            {% for attr in group_attrs %}
                <div>{{ attr.label }}: {{ attr.display_value }}</div>
            {% endfor %}
        {% endfor %}
    """
    import frappe

    try:
        # Get product document
        if not frappe.db.exists("Product Master", product_name):
            return [] if group_by is None else {}

        doc = frappe.get_doc("Product Master", product_name)
        attribute_values = doc.get("attribute_values") or []

        if not attribute_values:
            return [] if group_by is None else {}

        # Build attribute list with display information
        result = []
        for row in attribute_values:
            attr_code = row.get("attribute")
            if not attr_code:
                continue

            # Get raw value from EAV columns
            raw_value = _get_raw_value(row)

            # Skip empty values unless requested
            if not include_empty and not raw_value:
                continue

            # Get attribute metadata
            attr_meta = _get_attribute_metadata(attr_code)

            # Format display value with prefix and suffix
            data_type = attr_meta.get("data_type", "Text")
            display_value = format_attribute_value(
                raw_value,
                data_type,
                unit=attr_meta.get("unit", ""),
                attribute=attr_code
            ) if raw_value else ""

            result.append({
                "code": attr_code,
                "label": attr_meta.get("label", attr_code),
                "value": raw_value,
                "display_value": display_value or "",
                "data_type": data_type,
                "group": attr_meta.get("group", "General"),
                "unit": attr_meta.get("unit", ""),
                "is_required": row.get("is_required", 0),
            })

        # Sort by attribute label
        result.sort(key=lambda x: x["label"])

        # Group by attribute group if requested
        if group_by == "group":
            grouped = {}
            for attr in result:
                group_name = attr.get("group", "General")
                if group_name not in grouped:
                    grouped[group_name] = []
                grouped[group_name].append(attr)
            return grouped

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Error getting product attributes for {product_name}: {str(e)}",
            title="PIM Jinja Helper Error"
        )
        return [] if group_by is None else {}


def get_completeness_badge(score, size="md"):
    """Generate an HTML badge for completeness score display.

    Creates a color-coded badge HTML element based on the completeness
    score. The badge color indicates the data quality level:
        - Green (>= 80%): Good data quality
        - Yellow (>= 50%): Moderate data quality
        - Red (< 50%): Poor data quality

    Args:
        score: Completeness score (0-100) or None
        size: Badge size - "sm", "md", or "lg" (default: "md")

    Returns:
        str: HTML string for the completeness badge

    Example:
        In Jinja template:
        {{ get_completeness_badge(product.completeness_score) }}
        {{ get_completeness_badge(75.5, size="lg") }}

    Output examples:
        <span class="badge badge-success badge-md">85%</span>
        <span class="badge badge-warning badge-md">65%</span>
        <span class="badge badge-danger badge-md">30%</span>
    """
    try:
        # Handle None or invalid scores
        if score is None:
            score = 0.0

        # Ensure score is a number
        try:
            score = float(score)
        except (ValueError, TypeError):
            score = 0.0

        # Clamp score to valid range
        score = max(0.0, min(100.0, score))

        # Determine badge color based on score
        if score >= 80:
            badge_class = "success"
            icon = "check"
        elif score >= 50:
            badge_class = "warning"
            icon = "alert-circle"
        else:
            badge_class = "danger"
            icon = "x"

        # Validate size parameter
        valid_sizes = ["sm", "md", "lg"]
        if size not in valid_sizes:
            size = "md"

        # Size-based styling
        size_classes = {
            "sm": "font-size: 10px; padding: 2px 6px;",
            "md": "font-size: 12px; padding: 4px 8px;",
            "lg": "font-size: 14px; padding: 6px 12px;",
        }

        # Format score for display
        display_score = f"{score:.0f}%" if score == int(score) else f"{score:.1f}%"

        # Build badge HTML with inline styles for maximum compatibility
        color_styles = {
            "success": "background-color: #28a745; color: white;",
            "warning": "background-color: #ffc107; color: #212529;",
            "danger": "background-color: #dc3545; color: white;",
        }

        badge_html = (
            f'<span class="pim-completeness-badge pim-badge-{badge_class} pim-badge-{size}" '
            f'style="{color_styles[badge_class]} {size_classes[size]} '
            f'border-radius: 4px; display: inline-block; font-weight: 500;" '
            f'title="Data completeness: {display_score}">'
            f'{display_score}'
            f'</span>'
        )

        return badge_html

    except Exception:
        # Return a safe fallback on any error
        return '<span class="pim-completeness-badge" style="color: #6c757d;">--</span>'


def get_completeness_progress_bar(score, show_label=True, height="8px"):
    """Generate an HTML progress bar for completeness score display.

    Creates a visual progress bar with color coding based on the
    completeness score.

    Args:
        score: Completeness score (0-100) or None
        show_label: If True, show percentage text (default: True)
        height: CSS height value for the bar (default: "8px")

    Returns:
        str: HTML string for the completeness progress bar

    Example:
        In Jinja template:
        {{ get_completeness_progress_bar(product.completeness_score) }}
        {{ get_completeness_progress_bar(75.5, show_label=False, height="4px") }}
    """
    try:
        # Handle None or invalid scores
        if score is None:
            score = 0.0

        try:
            score = float(score)
        except (ValueError, TypeError):
            score = 0.0

        # Clamp score to valid range
        score = max(0.0, min(100.0, score))

        # Determine color based on score
        if score >= 80:
            bar_color = "#28a745"  # Green
        elif score >= 50:
            bar_color = "#ffc107"  # Yellow
        else:
            bar_color = "#dc3545"  # Red

        # Format score for display
        display_score = f"{score:.0f}%" if score == int(score) else f"{score:.1f}%"

        # Build progress bar HTML
        label_html = f'<span style="margin-left: 8px; font-size: 12px;">{display_score}</span>' if show_label else ''

        progress_html = (
            f'<div class="pim-completeness-progress" style="display: flex; align-items: center;">'
            f'<div style="flex: 1; background-color: #e9ecef; border-radius: 4px; height: {height}; overflow: hidden;">'
            f'<div style="width: {score}%; height: 100%; background-color: {bar_color}; '
            f'transition: width 0.3s ease;"></div>'
            f'</div>'
            f'{label_html}'
            f'</div>'
        )

        return progress_html

    except Exception:
        # Return a safe fallback on any error
        return '<div class="pim-completeness-progress">--</div>'


def get_product_status_badge(status):
    """Generate an HTML badge for product status display.

    Creates a color-coded badge for product workflow status.

    Args:
        status: Product status string (e.g., "Draft", "Active", "Archived")

    Returns:
        str: HTML string for the status badge

    Example:
        {{ get_product_status_badge(product.status) }}
    """
    try:
        if not status:
            status = "Unknown"

        # Normalize status
        status = str(status).strip()

        # Status color mapping
        status_colors = {
            "Draft": {"bg": "#6c757d", "text": "white"},
            "Pending Review": {"bg": "#17a2b8", "text": "white"},
            "Active": {"bg": "#28a745", "text": "white"},
            "Published": {"bg": "#28a745", "text": "white"},
            "Inactive": {"bg": "#ffc107", "text": "#212529"},
            "Archived": {"bg": "#343a40", "text": "white"},
            "Discontinued": {"bg": "#dc3545", "text": "white"},
        }

        colors = status_colors.get(status, {"bg": "#6c757d", "text": "white"})

        badge_html = (
            f'<span class="pim-status-badge" '
            f'style="background-color: {colors["bg"]}; color: {colors["text"]}; '
            f'padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500;">'
            f'{status}'
            f'</span>'
        )

        return badge_html

    except Exception:
        return '<span class="pim-status-badge" style="color: #6c757d;">Unknown</span>'


def format_attribute_value(value, data_type, unit=None, attribute=None):
    """Format an attribute value for display based on its data type.

    Formats raw attribute values into human-readable display strings
    based on the attribute's data type, including prefix and suffix if defined.

    Args:
        value: The raw attribute value
        data_type: Attribute data type (Text, Integer, Float, Boolean, Date, etc.)
        unit: Optional unit of measurement (e.g., "kg", "cm") - deprecated, use attribute instead
        attribute: Optional attribute name or code to get prefix/suffix from PIM Attribute

    Returns:
        str: Formatted display value with prefix and suffix if applicable

    Example:
        {{ format_attribute_value(attr.value, attr.data_type, attribute=attr.attribute) }}
    """
    import frappe

    try:
        if value is None:
            return ""

        formatted = str(value)

        if data_type == "Boolean":
            formatted = "Yes" if value else "No"

        elif data_type == "Integer":
            try:
                formatted = f"{int(value):,}"
            except (ValueError, TypeError):
                formatted = str(value)

        elif data_type in ("Float", "Decimal", "Currency"):
            try:
                float_val = float(value)
                formatted = f"{float_val:,.2f}"
            except (ValueError, TypeError):
                formatted = str(value)

        elif data_type == "Date":
            try:
                from frappe.utils import formatdate
                formatted = formatdate(value)
            except Exception:
                formatted = str(value)

        elif data_type == "Datetime":
            try:
                from frappe.utils import format_datetime
                formatted = format_datetime(value)
            except Exception:
                formatted = str(value)

        elif data_type == "Percent":
            try:
                formatted = f"{float(value):.1f}%"
            except (ValueError, TypeError):
                formatted = str(value)

        # Get prefix and suffix from PIM Attribute if attribute is provided
        prefix = ""
        suffix = ""
        
        if attribute:
            try:
                # Try to get attribute doc by name
                attr_doc = frappe.get_doc("PIM Attribute", attribute)
                if attr_doc:
                    prefix = attr_doc.value_prefix or ""
                    suffix = attr_doc.value_suffix or ""
            except Exception:
                # If attribute not found by name, try to search by code
                try:
                    attr_name = frappe.db.get_value("PIM Attribute", {"attribute_code": attribute}, "name")
                    if attr_name:
                        attr_doc = frappe.get_doc("PIM Attribute", attr_name)
                        prefix = attr_doc.value_prefix or ""
                        suffix = attr_doc.value_suffix or ""
                except Exception:
                    pass
        
        # Use unit as fallback if no suffix from attribute (backward compatibility)
        if not suffix and unit:
            suffix = unit

        # Apply prefix and suffix
        if prefix and formatted:
            formatted = f"{prefix}{formatted}"
        if suffix and formatted:
            formatted = f"{formatted}{suffix}"

        return formatted

    except Exception:
        return str(value) if value is not None else ""


# --- Helper Functions ---


def _get_display_value(row):
    """Extract the display value from an EAV row.

    Checks all value columns in the Product Attribute Value row
    and returns the first non-empty value found.

    Args:
        row: Product Attribute Value row (dict-like)

    Returns:
        str or None: The display value or None if empty
    """
    # Priority order for value columns
    value_fields = [
        ("value_text", str),
        ("value_data", str),
        ("value_link", str),
        ("value_int", lambda x: str(int(x))),
        ("value_float", lambda x: f"{float(x):.2f}"),
        ("value_boolean", lambda x: "Yes" if x else "No"),
        ("value_date", str),
        ("value_datetime", str),
    ]

    for field, formatter in value_fields:
        value = row.get(field)
        if value is not None:
            if isinstance(value, str) and not value.strip():
                continue
            try:
                return formatter(value)
            except (ValueError, TypeError):
                return str(value)

    return None


def _get_raw_value(row):
    """Extract the raw value from an EAV row.

    Returns the first non-empty value from the EAV row without formatting.

    Args:
        row: Product Attribute Value row (dict-like)

    Returns:
        The raw value or None if empty
    """
    value_fields = [
        "value_text",
        "value_data",
        "value_link",
        "value_int",
        "value_float",
        "value_boolean",
        "value_date",
        "value_datetime",
    ]

    for field in value_fields:
        value = row.get(field)
        if value is not None:
            if isinstance(value, str) and not value.strip():
                continue
            return value

    return None


def _get_attribute_metadata(attr_code):
    """Get metadata for an attribute including label and group.

    Retrieves the PIM Attribute document to get display name,
    data type, and group information.

    Args:
        attr_code: The attribute code/name

    Returns:
        dict: Attribute metadata with label, data_type, group, unit
    """
    import frappe

    try:
        # Check cache first
        cache_key = f"pim:attr_meta:{attr_code}"
        cached = frappe.cache().get_value(cache_key)
        if cached:
            return cached

        # Get from database
        if frappe.db.exists("PIM Attribute", attr_code):
            attr_doc = frappe.get_cached_doc("PIM Attribute", attr_code)
            metadata = {
                "label": attr_doc.get("attribute_name") or attr_code,
                "data_type": attr_doc.get("data_type") or "Text",
                "group": attr_doc.get("attribute_group") or "General",
                "unit": attr_doc.get("unit") or "",
            }
        else:
            # Fallback for unknown attributes
            metadata = {
                "label": attr_code,
                "data_type": "Text",
                "group": "General",
                "unit": "",
            }

        # Cache for 30 minutes
        frappe.cache().set_value(cache_key, metadata, expires_in_sec=1800)
        return metadata

    except Exception:
        return {
            "label": attr_code,
            "data_type": "Text",
            "group": "General",
            "unit": "",
        }


# =============================================================================
# GS1/Barcode Helpers
# =============================================================================


def format_gtin(gtin, with_dashes=True):
    """Format GTIN (Global Trade Item Number) for display.
    
    Formats a GTIN code with optional dashes for better readability.
    Supports GTIN-8, GTIN-12 (UPC), GTIN-13 (EAN), and GTIN-14 formats.
    
    Args:
        gtin: GTIN code as string or number
        with_dashes: If True, add dashes for readability (default: True)
    
    Returns:
        str: Formatted GTIN string
    
    Example:
        {{ format_gtin("1234567890123") }}
        {{ format_gtin("1234567890123", with_dashes=False) }}
    """
    try:
        if not gtin:
            return ""
        
        gtin_str = str(gtin).strip().replace("-", "").replace(" ", "")
        
        if not gtin_str or not gtin_str.isdigit():
            return str(gtin)
        
        if with_dashes:
            # Format based on length
            if len(gtin_str) == 8:
                return f"{gtin_str[0]}-{gtin_str[1:4]}-{gtin_str[4:7]}-{gtin_str[7]}"
            elif len(gtin_str) == 12:
                return f"{gtin_str[0]}-{gtin_str[1:6]}-{gtin_str[6:11]}-{gtin_str[11]}"
            elif len(gtin_str) == 13:
                return f"{gtin_str[0]}-{gtin_str[1:7]}-{gtin_str[7:12]}-{gtin_str[12]}"
            elif len(gtin_str) == 14:
                return f"{gtin_str[0]}-{gtin_str[1:3]}-{gtin_str[3:8]}-{gtin_str[8:13]}-{gtin_str[13]}"
        
        return gtin_str
    
    except Exception:
        return str(gtin) if gtin else ""


def get_barcode_image(gtin, format_type="code128", width=2, height=100):
    """Generate barcode image as base64 data URL.
    
    Creates a barcode image from GTIN and returns it as a base64-encoded
    data URL that can be used directly in HTML img tags.
    
    Args:
        gtin: GTIN code to encode
        format_type: Barcode format - "code128", "ean13", "ean8", "upc" (default: "code128")
        width: Bar width in pixels (default: 2)
        height: Bar height in pixels (default: 100)
    
    Returns:
        str: Base64 data URL for the barcode image, or empty string on error
    
    Example:
        <img src="{{ get_barcode_image(product.gtin) }}" alt="Barcode">
    """
    try:
        if not gtin:
            return ""
        
        # Try to import barcode library
        try:
            import barcode
            from barcode.writer import ImageWriter
            from io import BytesIO
            import base64
        except ImportError:
            # Fallback: return placeholder
            return f"data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48dGV4dCB4PSI1MCUiIHk9IjUwJSIgZm9udC1zaXplPSIxNCIgZmlsbD0iIzY2NiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPkJhcmNvZGUgTGlicmFyeSBOb3QgSW5zdGFsbGVkPC90ZXh0Pjwvc3ZnPg=="
        
        # Map format types
        format_map = {
            "code128": barcode.get_barcode_class("code128"),
            "ean13": barcode.get_barcode_class("ean13"),
            "ean8": barcode.get_barcode_class("ean8"),
            "upc": barcode.get_barcode_class("upc"),
        }
        
        barcode_class = format_map.get(format_type.lower(), format_map["code128"])
        
        # Create barcode
        code = barcode_class(str(gtin), writer=ImageWriter())
        
        # Generate image
        buffer = BytesIO()
        code.write(buffer, options={"module_width": width, "module_height": height})
        buffer.seek(0)
        
        # Convert to base64
        img_data = base64.b64encode(buffer.read()).decode()
        
        return f"data:image/png;base64,{img_data}"
    
    except Exception:
        return ""


def get_packaging_hierarchy(product_name, as_html=True):
    """Get GS1 packaging hierarchy as formatted HTML or dict.
    
    Retrieves the GS1 packaging hierarchy for a product and formats
    it for display in templates.
    
    Args:
        product_name: Name of the Product Master document
        as_html: If True, return formatted HTML; if False, return dict (default: True)
    
    Returns:
        str or dict: Formatted HTML string or dictionary with hierarchy data
    
    Example:
        {{ get_packaging_hierarchy("PROD-001") }}
    """
    import frappe
    
    try:
        if not frappe.db.exists("Product Master", product_name):
            return "" if as_html else {}
        
        # Get GS1 packaging hierarchy if exists
        hierarchies = frappe.get_all(
            "GS1 Packaging Hierarchy",
            filters={"product": product_name},
            fields=["name", "gtin", "packaging_level", "quantity", "description"],
            order_by="packaging_level"
        )
        
        if not hierarchies:
            return "" if as_html else {}
        
        if as_html:
            html = '<div class="pim-packaging-hierarchy">'
            for h in hierarchies:
                level = h.get("packaging_level", "Unknown")
                qty = h.get("quantity", 1)
                gtin = h.get("gtin", "")
                desc = h.get("description", "")
                
                html += (
                    f'<div class="packaging-level" style="margin: 8px 0; padding: 8px; '
                    f'border-left: 3px solid #007bff;">'
                    f'<strong>Level {level}</strong>: {qty} unit(s)'
                )
                if gtin:
                    html += f' | GTIN: {format_gtin(gtin)}'
                if desc:
                    html += f' | {desc}'
                html += '</div>'
            html += '</div>'
            return html
        else:
            return {"hierarchies": hierarchies}
    
    except Exception:
        return "" if as_html else {}


# =============================================================================
# Nutrition/Allergen Helpers
# =============================================================================


def get_nutrition_table(product_name, show_per_100g=True):
    """Format nutrition facts as HTML table.
    
    Retrieves nutrition facts for a product and formats them as
    an HTML table suitable for product labels.
    
    Args:
        product_name: Name of the Product Master document
        show_per_100g: If True, show values per 100g; if False, show per serving (default: True)
    
    Returns:
        str: HTML table string with nutrition facts
    
    Example:
        {{ get_nutrition_table("PROD-001") }}
    """
    import frappe
    
    try:
        if not frappe.db.exists("Product Master", product_name):
            return ""
        
        # Get nutrition facts
        nutrition = frappe.get_all(
            "Nutrition Facts",
            filters={"product": product_name},
            fields=["*"],
            limit=1
        )
        
        if not nutrition:
            return ""
        
        nutrition = nutrition[0]
        
        # Build HTML table
        html = '<table class="pim-nutrition-table" style="width: 100%; border-collapse: collapse; margin: 16px 0;">'
        html += '<thead><tr style="border-bottom: 2px solid #333;"><th colspan="2" style="text-align: left; padding: 8px;">Nutrition Facts</th></tr></thead>'
        html += '<tbody>'
        
        # Energy
        if nutrition.get("energy_kcal"):
            html += f'<tr><td style="padding: 4px 8px;">Energy</td><td style="padding: 4px 8px; text-align: right;">{nutrition.get("energy_kcal")} kcal</td></tr>'
        
        # Macronutrients
        nutrients = [
            ("protein", "Protein", "g"),
            ("carbohydrates", "Carbohydrates", "g"),
            ("fat", "Fat", "g"),
            ("fiber", "Fiber", "g"),
            ("sugar", "Sugar", "g"),
            ("sodium", "Sodium", "mg"),
        ]
        
        for field, label, unit in nutrients:
            value = nutrition.get(field)
            if value:
                html += f'<tr><td style="padding: 4px 8px;">{label}</td><td style="padding: 4px 8px; text-align: right;">{value} {unit}</td></tr>'
        
        html += '</tbody></table>'
        return html
    
    except Exception:
        return ""


def get_allergen_badges(product_name):
    """Generate allergen warning badges.
    
    Retrieves allergen information for a product and creates
    warning badges for each allergen.
    
    Args:
        product_name: Name of the Product Master document
    
    Returns:
        str: HTML string with allergen badges
    
    Example:
        {{ get_allergen_badges("PROD-001") }}
    """
    import frappe
    
    try:
        if not frappe.db.exists("Product Master", product_name):
            return ""
        
        # Get allergen items
        allergens = frappe.get_all(
            "Allergen Item",
            filters={"parent": product_name, "parenttype": "Product Master"},
            fields=["allergen", "severity"],
            order_by="severity desc"
        )
        
        if not allergens:
            return ""
        
        html = '<div class="pim-allergen-badges" style="margin: 8px 0;">'
        for allergen in allergens:
            allergen_name = allergen.get("allergen", "Unknown")
            severity = allergen.get("severity", "Moderate")
            
            # Color based on severity
            colors = {
                "High": {"bg": "#dc3545", "text": "white"},
                "Moderate": {"bg": "#ffc107", "text": "#212529"},
                "Low": {"bg": "#17a2b8", "text": "white"},
            }
            color = colors.get(severity, {"bg": "#6c757d", "text": "white"})
            
            html += (
                f'<span class="allergen-badge" style="display: inline-block; '
                f'margin: 2px 4px; padding: 4px 8px; background-color: {color["bg"]}; '
                f'color: {color["text"]}; border-radius: 4px; font-size: 11px; font-weight: 500;">'
                f'⚠ {allergen_name}'
                f'</span>'
            )
        html += '</div>'
        return html
    
    except Exception:
        return ""


# =============================================================================
# Media Helpers
# =============================================================================


def get_product_image(product_name, variant_name=None, index=0, width=None, height=None):
    """Get product image URL with optional transformation.
    
    Retrieves a product image URL, optionally for a specific variant,
    with optional size transformations.
    
    Args:
        product_name: Name of the Product Master document
        variant_name: Optional variant name for variant-specific images
        index: Image index (0 for first image, default: 0)
        width: Optional width in pixels
        height: Optional height in pixels
    
    Returns:
        str: Image URL or empty string
    
    Example:
        <img src="{{ get_product_image('PROD-001', width=300, height=300) }}" alt="Product">
    """
    import frappe
    
    try:
        filters = {"parent": product_name, "parenttype": "Product Master"}
        if variant_name:
            filters["variant"] = variant_name
        
        images = frappe.get_all(
            "Product Media",
            filters=filters,
            fields=["image", "is_primary"],
            order_by="is_primary desc, idx",
            limit=index + 1
        )
        
        if not images or len(images) <= index:
            return ""
        
        image_url = images[index].get("image")
        if not image_url:
            return ""
        
        # Add size parameters if specified
        if width or height:
            params = []
            if width:
                params.append(f"w={width}")
            if height:
                params.append(f"h={height}")
            if params:
                separator = "&" if "?" in image_url else "?"
                image_url = f"{image_url}{separator}{'&'.join(params)}"
        
        return image_url
    
    except Exception:
        return ""


def get_media_gallery(product_name, variant_name=None, max_images=10):
    """Get product media gallery as HTML.
    
    Creates an HTML gallery of product images.
    
    Args:
        product_name: Name of the Product Master document
        variant_name: Optional variant name for variant-specific images
        max_images: Maximum number of images to show (default: 10)
    
    Returns:
        str: HTML string with image gallery
    
    Example:
        {{ get_media_gallery("PROD-001") }}
    """
    import frappe
    
    try:
        filters = {"parent": product_name, "parenttype": "Product Master"}
        if variant_name:
            filters["variant"] = variant_name
        
        images = frappe.get_all(
            "Product Media",
            filters=filters,
            fields=["image", "is_primary", "alt_text"],
            order_by="is_primary desc, idx",
            limit=max_images
        )
        
        if not images:
            return ""
        
        html = '<div class="pim-media-gallery" style="display: flex; flex-wrap: wrap; gap: 8px;">'
        for img in images:
            img_url = img.get("image", "")
            alt = img.get("alt_text", "Product image")
            if img_url:
                html += (
                    f'<img src="{img_url}" alt="{alt}" '
                    f'style="max-width: 150px; max-height: 150px; object-fit: cover; border-radius: 4px; cursor: pointer;" '
                    f'onclick="window.open(this.src, \'_blank\')">'
                )
        html += '</div>'
        return html
    
    except Exception:
        return ""


# =============================================================================
# Channel/Quality Helpers
# =============================================================================


def get_channel_readiness(product_name, channel_name):
    """Get channel readiness indicator.
    
    Checks if a product is ready for a specific channel and returns
    a status indicator.
    
    Args:
        product_name: Name of the Product Master document
        channel_name: Name of the Channel document
    
    Returns:
        str: HTML string with readiness status
    
    Example:
        {{ get_channel_readiness("PROD-001", "Amazon") }}
    """
    import frappe
    
    try:
        if not frappe.db.exists("Product Master", product_name) or not frappe.db.exists("Channel", channel_name):
            return '<span style="color: #6c757d;">Unknown</span>'
        
        # Check product-channel relationship
        product_channel = frappe.get_all(
            "Product Channel",
            filters={"product": product_name, "channel": channel_name},
            fields=["is_active", "readiness_score"],
            limit=1
        )
        
        if not product_channel:
            return '<span style="color: #6c757d;">Not Configured</span>'
        
        pc = product_channel[0]
        is_active = pc.get("is_active", 0)
        score = pc.get("readiness_score", 0)
        
        if is_active and score >= 80:
            return '<span style="color: #28a745; font-weight: 500;">✓ Ready</span>'
        elif is_active and score >= 50:
            return '<span style="color: #ffc107; font-weight: 500;">⚠ Partial</span>'
        elif is_active:
            return '<span style="color: #dc3545; font-weight: 500;">✗ Not Ready</span>'
        else:
            return '<span style="color: #6c757d;">Inactive</span>'
    
    except Exception:
        return '<span style="color: #6c757d;">Error</span>'


def get_quality_badge(score):
    """Get quality score badge.
    
    Creates a badge for data quality score similar to completeness badge.
    
    Args:
        score: Quality score (0-100) or None
    
    Returns:
        str: HTML string for quality badge
    
    Example:
        {{ get_quality_badge(product.quality_score) }}
    """
    return get_completeness_badge(score)


def get_quality_issues_summary(product_name):
    """Get data quality issues summary.
    
    Retrieves and formats data quality issues for a product.
    
    Args:
        product_name: Name of the Product Master document
    
    Returns:
        str: HTML string with quality issues summary
    
    Example:
        {{ get_quality_issues_summary("PROD-001") }}
    """
    import frappe
    
    try:
        if not frappe.db.exists("Product Master", product_name):
            return ""
        
        # This would typically query data quality rules and violations
        # For now, return a placeholder
        return ""
    
    except Exception:
        return ""


# =============================================================================
# Datasheet/Print Helpers
# =============================================================================


def get_spec_table(product_name, group_by=None):
    """Generate product specification table.
    
    Creates an HTML table with product specifications/attributes.
    
    Args:
        product_name: Name of the Product Master document
        group_by: Optional grouping - "group" to group by attribute group (default: None)
    
    Returns:
        str: HTML table string
    
    Example:
        {{ get_spec_table("PROD-001") }}
    """
    import frappe
    
    try:
        attrs = get_product_attributes(product_name, include_empty=False, group_by=group_by)
        
        if not attrs:
            return ""
        
        html = '<table class="pim-spec-table" style="width: 100%; border-collapse: collapse; margin: 16px 0;">'
        html += '<thead><tr style="border-bottom: 2px solid #333;"><th style="text-align: left; padding: 8px;">Specification</th><th style="text-align: left; padding: 8px;">Value</th></tr></thead>'
        html += '<tbody>'
        
        if isinstance(attrs, dict):
            # Grouped attributes
            for group_name, group_attrs in attrs.items():
                html += f'<tr><td colspan="2" style="padding: 8px; font-weight: bold; background-color: #f8f9fa;">{group_name}</td></tr>'
                for attr in group_attrs:
                    html += (
                        f'<tr style="border-bottom: 1px solid #dee2e6;">'
                        f'<td style="padding: 8px; font-weight: 500;">{attr.get("label", "")}</td>'
                        f'<td style="padding: 8px;">{attr.get("display_value", "")}</td>'
                        f'</tr>'
                    )
        else:
            # Flat list
            for attr in attrs:
                html += (
                    f'<tr style="border-bottom: 1px solid #dee2e6;">'
                    f'<td style="padding: 8px; font-weight: 500;">{attr.get("label", "")}</td>'
                    f'<td style="padding: 8px;">{attr.get("display_value", "")}</td>'
                    f'</tr>'
                )
        
        html += '</tbody></table>'
        return html
    
    except Exception:
        return ""


def format_dimensions(length, width, height, unit="cm"):
    """Format dimensions for display.
    
    Formats product dimensions (length x width x height) for display.
    
    Args:
        length: Length value
        width: Width value
        height: Height value
        unit: Unit of measurement (default: "cm")
    
    Returns:
        str: Formatted dimensions string
    
    Example:
        {{ format_dimensions(product.length, product.width, product.height) }}
    """
    try:
        parts = []
        if length:
            parts.append(str(length))
        if width:
            parts.append(str(width))
        if height:
            parts.append(str(height))
        
        if not parts:
            return ""
        
        dim_str = " × ".join(parts)
        if unit:
            dim_str += f" {unit}"
        
        return dim_str
    
    except Exception:
        return ""
