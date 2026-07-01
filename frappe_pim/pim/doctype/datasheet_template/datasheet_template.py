"""
Datasheet Template Controller
Manages product datasheet templates with customizable layouts for PDF/HTML generation

This module provides comprehensive datasheet template configuration including:
- Page layout (size, orientation, margins)
- Header/footer configuration
- Section visibility and styling
- Attribute selection
- Visual styling options
- Output format settings
"""

import frappe
from frappe import _
from frappe.model.document import Document
import re
from datetime import datetime


# Page size definitions in millimeters (width x height)
PAGE_SIZES = {
    "A4": (210, 297),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "A3": (297, 420),
    "A5": (148, 210),
}


class DatasheetTemplate(Document):
    """Controller for Datasheet Template DocType"""

    def validate(self):
        """Validate template configuration"""
        self.validate_template_code()
        self.validate_margins()
        self.validate_custom_page_size()
        self.validate_fonts()
        self.validate_colors()
        self.validate_watermark()
        self.validate_default_template()

    def validate_template_code(self):
        """Ensure template_code is URL-safe slug"""
        if not self.template_code:
            # Auto-generate from name
            self.template_code = frappe.scrub(self.template_name)

        # Must be lowercase, no spaces, alphanumeric with underscores/hyphens
        if not re.match(r'^[a-z][a-z0-9_-]*$', self.template_code):
            frappe.throw(
                _("Template Code must start with a letter and contain only lowercase letters, numbers, underscores, and hyphens"),
                title=_("Invalid Template Code")
            )

    def validate_margins(self):
        """Validate margin values are within reasonable bounds"""
        margin_fields = [
            'margin_top_mm', 'margin_bottom_mm',
            'margin_left_mm', 'margin_right_mm'
        ]

        for field in margin_fields:
            value = getattr(self, field, 0) or 0
            if value < 0:
                frappe.throw(
                    _("{0} cannot be negative").format(field.replace('_', ' ').title()),
                    title=_("Invalid Margin")
                )
            if value > 100:
                frappe.throw(
                    _("{0} cannot exceed 100mm").format(field.replace('_', ' ').title()),
                    title=_("Invalid Margin")
                )

    def validate_custom_page_size(self):
        """Validate custom page dimensions if custom size is selected"""
        if self.page_size == "Custom":
            if not self.custom_width_mm or self.custom_width_mm <= 0:
                frappe.throw(
                    _("Custom Width is required when Page Size is Custom"),
                    title=_("Invalid Custom Size")
                )
            if not self.custom_height_mm or self.custom_height_mm <= 0:
                frappe.throw(
                    _("Custom Height is required when Page Size is Custom"),
                    title=_("Invalid Custom Size")
                )

            # Reasonable bounds for page sizes
            if self.custom_width_mm < 50 or self.custom_width_mm > 1000:
                frappe.throw(
                    _("Custom Width must be between 50mm and 1000mm"),
                    title=_("Invalid Custom Size")
                )
            if self.custom_height_mm < 50 or self.custom_height_mm > 1000:
                frappe.throw(
                    _("Custom Height must be between 50mm and 1000mm"),
                    title=_("Invalid Custom Size")
                )

    def validate_fonts(self):
        """Validate font settings"""
        valid_fonts = ['Helvetica', 'Arial', 'Times New Roman', 'Georgia', 'Open Sans', 'Roboto']

        if self.heading_font and self.heading_font not in valid_fonts:
            frappe.throw(
                _("Invalid heading font: {0}").format(self.heading_font),
                title=_("Invalid Font")
            )

        if self.body_font and self.body_font not in valid_fonts:
            frappe.throw(
                _("Invalid body font: {0}").format(self.body_font),
                title=_("Invalid Font")
            )

        # Validate font size
        if self.base_font_size and (self.base_font_size < 6 or self.base_font_size > 24):
            frappe.throw(
                _("Base font size must be between 6 and 24 points"),
                title=_("Invalid Font Size")
            )

    def validate_colors(self):
        """Validate color values are valid hex codes"""
        color_fields = ['primary_color', 'secondary_color']

        for field in color_fields:
            value = getattr(self, field, None)
            if value:
                # Accept both #RRGGBB and #RGB formats
                if not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', value):
                    frappe.throw(
                        _("{0} must be a valid hex color code (e.g., #1F272E)").format(
                            field.replace('_', ' ').title()
                        ),
                        title=_("Invalid Color")
                    )

    def validate_watermark(self):
        """Validate watermark settings"""
        if self.include_watermark:
            if self.watermark_opacity is not None:
                if self.watermark_opacity < 0 or self.watermark_opacity > 100:
                    frappe.throw(
                        _("Watermark opacity must be between 0 and 100"),
                        title=_("Invalid Watermark Settings")
                    )

    def validate_default_template(self):
        """Ensure only one template is marked as default"""
        if self.is_default and self.enabled:
            # Unset default on other templates
            other_defaults = frappe.get_all(
                "Datasheet Template",
                filters={
                    "is_default": 1,
                    "name": ["!=", self.name or ""]
                },
                pluck="name"
            )

            for template_name in other_defaults:
                frappe.db.set_value(
                    "Datasheet Template",
                    template_name,
                    "is_default",
                    0,
                    update_modified=False
                )

    def before_save(self):
        """Prepare data before saving"""
        # Ensure sort_order is set
        if self.sort_order is None:
            self.sort_order = self.get_next_sort_order()

        # Set default filename pattern if not provided
        if not self.filename_pattern:
            self.filename_pattern = "{product_code}_datasheet_{date}"

    def get_next_sort_order(self):
        """Get next available sort order"""
        max_order = frappe.db.sql("""
            SELECT MAX(sort_order) FROM `tabDatasheet Template`
        """)
        if max_order and max_order[0][0] is not None:
            return max_order[0][0] + 10
        return 10

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        # Check if this is the default template
        if self.is_default:
            frappe.throw(
                _("Cannot delete the default template. Set another template as default first."),
                title=_("Cannot Delete Default")
            )

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:datasheet_template:{self.name}")
            frappe.cache().delete_key("pim:all_datasheet_templates")
            frappe.cache().delete_key("pim:default_datasheet_template")
        except Exception:
            pass

    def get_page_dimensions(self):
        """Get page dimensions in millimeters

        Returns:
            tuple: (width, height) in millimeters
        """
        if self.page_size == "Custom":
            return (self.custom_width_mm, self.custom_height_mm)

        dimensions = PAGE_SIZES.get(self.page_size, PAGE_SIZES["A4"])

        # Swap for landscape orientation
        if self.page_orientation == "Landscape":
            return (dimensions[1], dimensions[0])

        return dimensions

    def get_content_area(self):
        """Get content area dimensions after margins

        Returns:
            dict: Content area dimensions and position
        """
        page_width, page_height = self.get_page_dimensions()

        margin_top = self.margin_top_mm or 15
        margin_bottom = self.margin_bottom_mm or 15
        margin_left = self.margin_left_mm or 15
        margin_right = self.margin_right_mm or 15

        # Account for header/footer
        header_height = self.header_height_mm if self.show_header else 0
        footer_height = self.footer_height_mm if self.show_footer else 0

        content_width = page_width - margin_left - margin_right
        content_height = page_height - margin_top - margin_bottom - header_height - footer_height

        return {
            "x": margin_left,
            "y": margin_top + header_height,
            "width": content_width,
            "height": content_height,
            "column_width": content_width / int(self.columns or 1)
        }

    def get_selected_attributes(self):
        """Parse and return list of selected attributes

        Returns:
            list: List of attribute codes
        """
        if not self.selected_attributes:
            return []

        return [
            attr.strip()
            for attr in self.selected_attributes.split(',')
            if attr.strip()
        ]

    def get_selected_attribute_groups(self):
        """Parse and return list of selected attribute groups

        Returns:
            list: List of attribute group codes
        """
        if not self.selected_attribute_groups:
            return []

        return [
            group.strip()
            for group in self.selected_attribute_groups.split(',')
            if group.strip()
        ]

    def get_product_families(self):
        """Parse and return list of applicable product families

        Returns:
            list: List of product family codes
        """
        if self.apply_to_all_products or not self.product_families:
            return []

        return [
            family.strip()
            for family in self.product_families.split(',')
            if family.strip()
        ]

    def get_channels(self):
        """Parse and return list of applicable channels

        Returns:
            list: List of channel codes
        """
        if self.apply_to_all_products or not self.channels:
            return []

        return [
            channel.strip()
            for channel in self.channels.split(',')
            if channel.strip()
        ]

    def get_brands(self):
        """Parse and return list of applicable brands

        Returns:
            list: List of brand codes
        """
        if self.apply_to_all_products or not self.brands:
            return []

        return [
            brand.strip()
            for brand in self.brands.split(',')
            if brand.strip()
        ]

    def is_applicable_to_product(self, product):
        """Check if this template is applicable to a given product

        Args:
            product: Product Master document or dict

        Returns:
            bool: True if template can be used for this product
        """
        if self.apply_to_all_products:
            return True

        # Check product family
        families = self.get_product_families()
        if families:
            product_family = product.get('product_family') if isinstance(product, dict) else product.product_family
            if product_family and product_family not in families:
                return False

        # Check brand
        brands = self.get_brands()
        if brands:
            product_brand = product.get('brand') if isinstance(product, dict) else product.brand
            if product_brand and product_brand not in brands:
                return False

        return True

    def generate_filename(self, product):
        """Generate output filename for a product

        Args:
            product: Product Master document or dict

        Returns:
            str: Generated filename (without extension)
        """
        pattern = self.filename_pattern or "{product_code}_datasheet_{date}"

        # Get product values
        if isinstance(product, dict):
            product_code = product.get('product_code', product.get('name', 'unknown'))
            product_name = product.get('product_name', 'Product')
        else:
            product_code = product.product_code or product.name
            product_name = product.product_name or 'Product'

        # Replace placeholders
        filename = pattern.format(
            product_code=frappe.scrub(product_code),
            product_name=frappe.scrub(product_name[:30]),  # Limit name length
            date=datetime.now().strftime('%Y%m%d'),
            datetime=datetime.now().strftime('%Y%m%d_%H%M%S')
        )

        # Sanitize filename
        filename = re.sub(r'[^\w\-]', '_', filename)
        return filename

    def get_style_config(self):
        """Get styling configuration as a dictionary

        Returns:
            dict: Style configuration for rendering
        """
        return {
            "primary_color": self.primary_color or "#1F272E",
            "secondary_color": self.secondary_color or "#5E64FF",
            "heading_font": self.heading_font or "Helvetica",
            "body_font": self.body_font or "Helvetica",
            "base_font_size": self.base_font_size or 10,
            "custom_css": self.custom_css,
            "custom_html_header": self.custom_html_header,
            "custom_html_footer": self.custom_html_footer
        }

    def get_sections_config(self):
        """Get section visibility and configuration

        Returns:
            dict: Section configuration for rendering
        """
        return {
            "product_header": {
                "enabled": self.show_product_header,
                "style": self.product_header_style,
                "show_code": self.show_product_code,
                "show_status": self.show_product_status,
                "show_barcode": self.show_barcode,
                "barcode_type": self.barcode_type
            },
            "images": {
                "enabled": self.show_images,
                "layout": self.image_layout,
                "max_images": self.max_images,
                "main_width_percent": self.main_image_width_percent,
                "show_border": self.image_border,
                "show_caption": self.image_caption
            },
            "description": {
                "enabled": self.show_description,
                "heading": self.description_heading,
                "truncate": self.truncate_description,
                "max_chars": self.max_description_chars
            },
            "attributes": {
                "enabled": self.show_attributes,
                "heading": self.attributes_heading,
                "layout": self.attributes_layout,
                "selection": self.attribute_selection,
                "selected": self.get_selected_attributes(),
                "groups": self.get_selected_attribute_groups(),
                "hide_empty": self.hide_empty_attributes
            },
            "dimensions": {
                "enabled": self.show_dimensions,
                "heading": self.dimensions_heading,
                "show_packaging": self.show_packaging_dimensions,
                "dimension_units": self.dimension_units,
                "weight_units": self.weight_units
            },
            "pricing": {
                "enabled": self.show_pricing,
                "heading": self.pricing_heading,
                "price_list": self.price_list,
                "show_currency": self.show_currency_symbol
            },
            "gs1": {
                "show_gs1": self.show_gs1_info,
                "show_certifications": self.show_certifications,
                "show_country_of_origin": self.show_country_of_origin,
                "show_manufacturer": self.show_manufacturer
            },
            "nutrition": {
                "enabled": self.show_nutrition,
                "style": self.nutrition_style,
                "show_allergens": self.show_allergens,
                "show_ingredients": self.show_ingredients
            }
        }

    def get_header_config(self):
        """Get header configuration

        Returns:
            dict: Header configuration for rendering
        """
        return {
            "enabled": self.show_header,
            "logo": self.header_logo,
            "logo_position": self.header_logo_position,
            "logo_width_mm": self.header_logo_width_mm,
            "text": self.header_text,
            "height_mm": self.header_height_mm
        }

    def get_footer_config(self):
        """Get footer configuration

        Returns:
            dict: Footer configuration for rendering
        """
        return {
            "enabled": self.show_footer,
            "show_page_numbers": self.show_page_numbers,
            "page_number_format": self.page_number_format,
            "text": self.footer_text,
            "show_date": self.show_generation_date,
            "height_mm": self.footer_height_mm
        }

    def get_watermark_config(self):
        """Get watermark configuration

        Returns:
            dict: Watermark configuration for rendering
        """
        return {
            "enabled": self.include_watermark,
            "text": self.watermark_text,
            "opacity": self.watermark_opacity or 15
        }

    def to_render_config(self):
        """Export complete configuration for datasheet renderer

        Returns:
            dict: Complete template configuration
        """
        return {
            "name": self.name,
            "template_code": self.template_code,
            "page": {
                "size": self.page_size,
                "orientation": self.page_orientation,
                "dimensions": self.get_page_dimensions(),
                "columns": int(self.columns or 1),
                "margins": {
                    "top": self.margin_top_mm or 15,
                    "bottom": self.margin_bottom_mm or 15,
                    "left": self.margin_left_mm or 15,
                    "right": self.margin_right_mm or 15
                }
            },
            "content_area": self.get_content_area(),
            "header": self.get_header_config(),
            "footer": self.get_footer_config(),
            "sections": self.get_sections_config(),
            "style": self.get_style_config(),
            "watermark": self.get_watermark_config(),
            "output": {
                "format": self.output_format,
                "filename_pattern": self.filename_pattern
            }
        }

    @frappe.whitelist()
    def preview(self):
        """Generate a preview of the datasheet

        Returns:
            dict: Preview result with URL or error
        """
        if not self.preview_product:
            frappe.throw(_("Please select a Preview Product first"))

        # Update last preview timestamp
        self.db_set("last_preview", datetime.now())

        # Generate preview (delegate to content ops API)
        try:
            from frappe_pim.pim.api.content_ops import generate_datasheet_preview
            return generate_datasheet_preview(
                product=self.preview_product,
                template=self.name
            )
        except ImportError:
            # Content ops API not yet implemented
            return {
                "status": "info",
                "message": _("Datasheet preview requires the Content Ops module")
            }

    @frappe.whitelist()
    def duplicate(self):
        """Create a duplicate of this template

        Returns:
            str: Name of the new template
        """
        new_doc = frappe.copy_doc(self)
        new_doc.template_name = f"{self.template_name} (Copy)"
        new_doc.template_code = f"{self.template_code}_copy"
        new_doc.is_default = 0
        new_doc.insert()

        return new_doc.name


# ============================================================================
# Module-level Functions
# ============================================================================

def get_default_template():
    """Get the default datasheet template

    Returns:
        Document: Default Datasheet Template or None
    """
    template_name = frappe.db.get_value(
        "Datasheet Template",
        {"is_default": 1, "enabled": 1},
        "name"
    )

    if template_name:
        return frappe.get_doc("Datasheet Template", template_name)

    # Fallback to first enabled template
    template_name = frappe.db.get_value(
        "Datasheet Template",
        {"enabled": 1},
        "name",
        order_by="sort_order asc"
    )

    if template_name:
        return frappe.get_doc("Datasheet Template", template_name)

    return None


def get_template_for_product(product):
    """Get the most appropriate template for a product

    Args:
        product: Product Master document or name

    Returns:
        Document: Best matching Datasheet Template or None
    """
    if isinstance(product, str):
        product = frappe.get_doc("Product Master", product)

    # First try to find a specific template for this product's family/brand
    templates = frappe.get_all(
        "Datasheet Template",
        filters={"enabled": 1},
        fields=["name", "apply_to_all_products", "product_families", "brands"],
        order_by="sort_order asc"
    )

    for template_data in templates:
        template = frappe.get_doc("Datasheet Template", template_data.name)
        if template.is_applicable_to_product(product):
            return template

    # Fallback to default
    return get_default_template()


@frappe.whitelist()
def get_datasheet_templates(enabled_only=True):
    """Get all datasheet templates

    Args:
        enabled_only: If True, return only enabled templates

    Returns:
        list: List of template dicts
    """
    filters = {}
    if enabled_only:
        filters["enabled"] = 1

    return frappe.get_all(
        "Datasheet Template",
        filters=filters,
        fields=[
            "name", "template_name", "template_code", "enabled",
            "is_default", "page_size", "page_orientation",
            "output_format", "sort_order"
        ],
        order_by="sort_order asc"
    )


@frappe.whitelist()
def get_templates_for_product(product_name):
    """Get applicable templates for a specific product

    Args:
        product_name: Name of the Product Master

    Returns:
        list: List of applicable template dicts
    """
    try:
        product = frappe.get_doc("Product Master", product_name)
    except frappe.DoesNotExistError:
        return []

    templates = get_datasheet_templates(enabled_only=True)
    applicable = []

    for template_data in templates:
        template = frappe.get_doc("Datasheet Template", template_data.name)
        if template.is_applicable_to_product(product):
            applicable.append(template_data)

    return applicable


@frappe.whitelist()
def duplicate_template(template_name):
    """Duplicate a datasheet template

    Args:
        template_name: Name of the template to duplicate

    Returns:
        str: Name of the new template
    """
    doc = frappe.get_doc("Datasheet Template", template_name)
    return doc.duplicate()


@frappe.whitelist()
def set_default_template(template_name):
    """Set a template as the default

    Args:
        template_name: Name of the template to set as default
    """
    # Unset all other defaults
    frappe.db.sql("""
        UPDATE `tabDatasheet Template`
        SET is_default = 0
        WHERE is_default = 1
    """)

    # Set the new default
    frappe.db.set_value(
        "Datasheet Template",
        template_name,
        "is_default",
        1,
        update_modified=True
    )

    frappe.db.commit()
    return {"success": True, "message": _("Default template updated")}


@frappe.whitelist()
def preview_template(template_name, product_name=None):
    """Generate a preview of a datasheet template

    Args:
        template_name: Name of the template
        product_name: Optional product to use for preview

    Returns:
        dict: Preview result
    """
    doc = frappe.get_doc("Datasheet Template", template_name)

    if product_name:
        doc.db_set("preview_product", product_name)

    return doc.preview()


@frappe.whitelist()
def get_page_sizes():
    """Get available page sizes with dimensions

    Returns:
        list: List of page size options
    """
    sizes = []
    for name, (width, height) in PAGE_SIZES.items():
        sizes.append({
            "value": name,
            "label": f"{name} ({width}mm x {height}mm)"
        })
    sizes.append({
        "value": "Custom",
        "label": _("Custom Size")
    })
    return sizes


@frappe.whitelist()
def get_available_fonts():
    """Get list of available fonts

    Returns:
        list: List of font options
    """
    return [
        {"value": "Helvetica", "label": "Helvetica"},
        {"value": "Arial", "label": "Arial"},
        {"value": "Times New Roman", "label": "Times New Roman"},
        {"value": "Georgia", "label": "Georgia"},
        {"value": "Open Sans", "label": "Open Sans"},
        {"value": "Roboto", "label": "Roboto"}
    ]


@frappe.whitelist()
def get_barcode_types():
    """Get available barcode types

    Returns:
        list: List of barcode type options
    """
    return [
        {"value": "EAN-13", "label": "EAN-13 (International)"},
        {"value": "UPC-A", "label": "UPC-A (North America)"},
        {"value": "Code 128", "label": "Code 128 (Alphanumeric)"},
        {"value": "QR Code", "label": "QR Code (2D)"}
    ]


@frappe.whitelist()
def get_template_render_config(template_name):
    """Get complete render configuration for a template

    Args:
        template_name: Name of the template

    Returns:
        dict: Complete template configuration for rendering
    """
    doc = frappe.get_doc("Datasheet Template", template_name)
    return doc.to_render_config()
