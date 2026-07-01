"""
Display Template Controller
Manages sales presentation templates for different customer types and channels
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today, cstr
import json


class DisplayTemplate(Document):
    def validate(self):
        self.validate_template_code()
        self.validate_dates()
        self.validate_default_template()
        self.validate_custom_labels()

    def validate_template_code(self):
        """Validate template_code format"""
        if self.template_code:
            # Ensure template code is lowercase and slug-friendly
            import re
            if not re.match(r'^[a-z0-9][a-z0-9\-_]*$', self.template_code):
                frappe.throw(
                    _("Template Code must start with a letter or number and contain only lowercase letters, numbers, hyphens, and underscores"),
                    title=_("Invalid Template Code")
                )

    def validate_dates(self):
        """Validate date field consistency"""
        if self.valid_from and self.valid_to:
            if getdate(self.valid_from) > getdate(self.valid_to):
                frappe.throw(
                    _("Valid From date cannot be after Valid To date"),
                    title=_("Invalid Date Range")
                )

    def validate_default_template(self):
        """Ensure only one default template per type"""
        if self.is_default and self.enabled:
            existing_default = frappe.db.exists(
                "Display Template",
                {
                    "template_type": self.template_type,
                    "is_default": 1,
                    "enabled": 1,
                    "name": ["!=", self.name]
                }
            )
            if existing_default:
                frappe.msgprint(
                    _("Another template '{0}' is already set as default for {1}. It will be unset.").format(
                        existing_default, self.template_type
                    ),
                    indicator="orange",
                    title=_("Default Template Changed")
                )
                # Unset the previous default
                frappe.db.set_value("Display Template", existing_default, "is_default", 0)

    def validate_custom_labels(self):
        """Validate custom_field_labels JSON format"""
        if self.custom_field_labels:
            try:
                labels = json.loads(self.custom_field_labels)
                if not isinstance(labels, dict):
                    frappe.throw(
                        _("Custom Field Labels must be a JSON object mapping field names to labels"),
                        title=_("Invalid JSON Format")
                    )
            except json.JSONDecodeError as e:
                frappe.throw(
                    _("Invalid JSON in Custom Field Labels: {0}").format(str(e)),
                    title=_("JSON Parse Error")
                )

    def before_save(self):
        """Prepare data before saving"""
        self.normalize_template_code()

    def normalize_template_code(self):
        """Normalize template code to lowercase"""
        if self.template_code:
            self.template_code = self.template_code.lower().strip()

    def on_update(self):
        """Handle post-update actions"""
        self.invalidate_cache()

    def on_trash(self):
        """Cleanup before deletion"""
        self.invalidate_cache()

    def invalidate_cache(self):
        """Clear relevant caches"""
        try:
            frappe.cache().delete_key(f"pim:display_template:{self.name}")
            frappe.cache().delete_key(f"pim:display_templates_by_type:{self.template_type}")
            frappe.cache().delete_key("pim:display_templates_list")
        except Exception:
            pass

    @frappe.whitelist()
    def increment_usage(self):
        """Increment usage count and update last used date"""
        self.usage_count = (self.usage_count or 0) + 1
        self.last_used_date = today()
        self.save(ignore_permissions=True)

        return {
            "status": "success",
            "usage_count": self.usage_count
        }

    @frappe.whitelist()
    def generate_preview(self, product=None):
        """Generate preview of template with a product

        Args:
            product: Product Master name to use for preview
        """
        product_name = product or self.preview_product
        if not product_name:
            frappe.throw(_("Please specify a product for preview"))

        if not frappe.db.exists("Product Master", product_name):
            frappe.throw(_("Product '{0}' not found").format(product_name))

        product_doc = frappe.get_doc("Product Master", product_name)

        try:
            rendered = render_template(self, product_doc)
            return {
                "status": "success",
                "html": rendered
            }
        except Exception as e:
            frappe.log_error(
                message=f"Error generating preview for template {self.name}: {str(e)}",
                title="Display Template Preview Error"
            )
            return {
                "status": "error",
                "message": str(e)
            }

    @frappe.whitelist()
    def duplicate_template(self, new_name=None, new_code=None):
        """Create a copy of this template

        Args:
            new_name: Name for the new template
            new_code: Code for the new template
        """
        if not new_code:
            new_code = f"{self.template_code}-copy"

        if frappe.db.exists("Display Template", new_code):
            frappe.throw(_("Template with code '{0}' already exists").format(new_code))

        new_doc = frappe.copy_doc(self)
        new_doc.template_name = new_name or f"{self.template_name} (Copy)"
        new_doc.template_code = new_code
        new_doc.is_default = 0
        new_doc.usage_count = 0
        new_doc.last_used_date = None
        new_doc.insert()

        return {
            "status": "success",
            "template": new_doc.name,
            "message": _("Template duplicated successfully")
        }


def render_template(template_doc, product_doc):
    """Render a display template with product data

    Args:
        template_doc: Display Template document
        product_doc: Product Master document

    Returns:
        Rendered HTML string
    """
    from frappe.utils.jinja import get_jinja_env

    # Prepare context
    context = {
        "product": product_doc,
        "template": template_doc,
        "today": today(),
        "company": frappe.defaults.get_defaults().get("company"),
    }

    # Get custom field labels if any
    custom_labels = {}
    if template_doc.custom_field_labels:
        try:
            custom_labels = json.loads(template_doc.custom_field_labels)
        except Exception:
            pass
    context["field_labels"] = custom_labels

    # Render each section
    parts = []

    if template_doc.header_html:
        try:
            env = get_jinja_env()
            header = env.from_string(template_doc.header_html).render(context)
            parts.append(header)
        except Exception as e:
            parts.append(f"<!-- Header render error: {str(e)} -->")

    if template_doc.body_template:
        try:
            env = get_jinja_env()
            body = env.from_string(template_doc.body_template).render(context)
            parts.append(body)
        except Exception as e:
            parts.append(f"<!-- Body render error: {str(e)} -->")

    if template_doc.footer_html:
        try:
            env = get_jinja_env()
            footer = env.from_string(template_doc.footer_html).render(context)
            parts.append(footer)
        except Exception as e:
            parts.append(f"<!-- Footer render error: {str(e)} -->")

    # Wrap in style if custom CSS provided
    html = "\n".join(parts)
    if template_doc.custom_css:
        html = f"<style>{template_doc.custom_css}</style>\n{html}"

    return html


@frappe.whitelist()
def get_display_templates(
    template_type=None,
    customer_type=None,
    channel=None,
    output_format=None,
    enabled_only=True,
    limit=50,
    offset=0
):
    """Get display templates with optional filtering

    Args:
        template_type: Filter by template type
        customer_type: Filter by customer type
        channel: Filter by channel
        output_format: Filter by output format
        enabled_only: Only return enabled templates (default True)
        limit: Maximum results to return
        offset: Results offset for pagination
    """
    filters = {}

    if enabled_only:
        filters["enabled"] = 1
    if template_type:
        filters["template_type"] = template_type
    if customer_type:
        filters["customer_type"] = customer_type
    if channel:
        filters["channel"] = channel
    if output_format:
        filters["output_format"] = output_format

    # Check validity dates
    today_date = today()
    or_filters = [
        ["valid_from", "is", "not set"],
        ["valid_from", "<=", today_date]
    ]

    return frappe.get_all(
        "Display Template",
        filters=filters,
        fields=[
            "name", "template_name", "template_code", "template_type",
            "customer_type", "channel", "output_format", "enabled",
            "is_default", "sort_order", "version", "usage_count",
            "creation", "modified"
        ],
        order_by="sort_order asc, template_name asc",
        limit_start=offset,
        limit_page_length=limit
    )


@frappe.whitelist()
def get_default_template(template_type, customer_type=None, channel=None):
    """Get the default template for a given type and context

    Args:
        template_type: Type of template to find
        customer_type: Optional customer type filter
        channel: Optional channel filter

    Returns:
        Template name or None
    """
    today_date = today()

    filters = {
        "template_type": template_type,
        "enabled": 1
    }

    # Add optional filters
    if customer_type:
        filters["customer_type"] = ["in", [customer_type, "All", ""]]
    if channel:
        filters["channel"] = channel

    # First try to find default template
    default_template = frappe.db.get_value(
        "Display Template",
        {
            **filters,
            "is_default": 1
        },
        "name"
    )

    if default_template:
        return default_template

    # Fall back to first matching template by sort order
    templates = frappe.get_all(
        "Display Template",
        filters=filters,
        fields=["name"],
        order_by="sort_order asc",
        limit_page_length=1
    )

    return templates[0].name if templates else None


@frappe.whitelist()
def get_templates_for_product(product):
    """Get applicable templates for a specific product

    Args:
        product: Product Master name

    Returns:
        List of applicable templates
    """
    if not product:
        frappe.throw(_("Product is required"))

    if not frappe.db.exists("Product Master", product):
        frappe.throw(_("Product '{0}' not found").format(product))

    # Get product details for filtering
    product_data = frappe.db.get_value(
        "Product Master",
        product,
        ["product_family", "brand"],
        as_dict=True
    )

    # Build filter conditions for matching templates
    templates = frappe.db.sql("""
        SELECT
            name, template_name, template_code, template_type,
            customer_type, output_format, is_default, sort_order
        FROM `tabDisplay Template`
        WHERE enabled = 1
        AND (valid_from IS NULL OR valid_from <= %(today)s)
        AND (valid_to IS NULL OR valid_to >= %(today)s)
        AND (
            (linked_product_family IS NULL OR linked_product_family = '')
            OR linked_product_family = %(family)s
        )
        AND (
            (linked_brand IS NULL OR linked_brand = '')
            OR linked_brand = %(brand)s
        )
        ORDER BY
            CASE WHEN linked_product_family = %(family)s THEN 0 ELSE 1 END,
            CASE WHEN linked_brand = %(brand)s THEN 0 ELSE 1 END,
            sort_order ASC,
            template_name ASC
    """, {
        "today": today(),
        "family": product_data.get("product_family") or "",
        "brand": product_data.get("brand") or ""
    }, as_dict=True)

    return templates


@frappe.whitelist()
def render_product_with_template(product, template):
    """Render a product using a specific template

    Args:
        product: Product Master name
        template: Display Template name

    Returns:
        Dict with rendered HTML and metadata
    """
    if not product:
        frappe.throw(_("Product is required"))
    if not template:
        frappe.throw(_("Template is required"))

    if not frappe.db.exists("Product Master", product):
        frappe.throw(_("Product '{0}' not found").format(product))
    if not frappe.db.exists("Display Template", template):
        frappe.throw(_("Template '{0}' not found").format(template))

    template_doc = frappe.get_doc("Display Template", template)
    product_doc = frappe.get_doc("Product Master", product)

    # Check if template is enabled and valid
    if not template_doc.enabled:
        frappe.throw(_("Template '{0}' is not enabled").format(template))

    today_date = getdate(today())
    if template_doc.valid_from and getdate(template_doc.valid_from) > today_date:
        frappe.throw(_("Template '{0}' is not yet valid").format(template))
    if template_doc.valid_to and getdate(template_doc.valid_to) < today_date:
        frappe.throw(_("Template '{0}' has expired").format(template))

    try:
        rendered_html = render_template(template_doc, product_doc)

        # Increment usage count
        template_doc.increment_usage()

        return {
            "status": "success",
            "html": rendered_html,
            "template": {
                "name": template_doc.name,
                "template_name": template_doc.template_name,
                "template_type": template_doc.template_type,
                "output_format": template_doc.output_format
            },
            "product": {
                "name": product_doc.name,
                "product_name": product_doc.product_name
            }
        }
    except Exception as e:
        frappe.log_error(
            message=f"Error rendering product {product} with template {template}: {str(e)}",
            title="Display Template Render Error"
        )
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist()
def get_template_statistics():
    """Get usage statistics for display templates

    Returns:
        Dict with statistics by type
    """
    stats = frappe.db.sql("""
        SELECT
            template_type,
            COUNT(*) as total_templates,
            SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) as enabled_count,
            SUM(CASE WHEN is_default = 1 THEN 1 ELSE 0 END) as default_count,
            SUM(usage_count) as total_usage,
            AVG(usage_count) as avg_usage
        FROM `tabDisplay Template`
        GROUP BY template_type
        ORDER BY total_usage DESC
    """, as_dict=True)

    return {
        "by_type": stats,
        "total_templates": sum(s.get("total_templates", 0) for s in stats),
        "total_enabled": sum(s.get("enabled_count", 0) for s in stats),
        "total_usage": sum(s.get("total_usage", 0) for s in stats)
    }


@frappe.whitelist()
def bulk_enable_disable(template_list, enabled=True):
    """Enable or disable multiple templates

    Args:
        template_list: JSON string of list of template names
        enabled: Whether to enable (True) or disable (False)
    """
    if isinstance(template_list, str):
        template_list = json.loads(template_list)

    updated = []
    for template_name in template_list:
        try:
            frappe.db.set_value("Display Template", template_name, "enabled", 1 if enabled else 0)
            updated.append(template_name)
        except Exception as e:
            frappe.log_error(
                message=f"Error updating template {template_name}: {str(e)}",
                title="Bulk Template Update Error"
            )

    frappe.cache().delete_key("pim:display_templates_list")

    return {
        "status": "success",
        "updated_count": len(updated),
        "updated": updated
    }
