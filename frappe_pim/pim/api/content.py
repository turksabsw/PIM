"""PIM Content Operations API Endpoints

This module provides API endpoints for generating print catalogs and
product datasheets. Content Operations features include:

- Datasheet Generation: Single-product spec sheets in PDF/HTML
- Print Catalog Generation: Multi-product catalogs with custom layouts
- Batch Generation: Generate datasheets for multiple products at once
- Template Management: Use configurable templates for consistent branding
- Async Processing: Background job support for large catalog generation

All API functions are decorated with @frappe.whitelist() for security
and require appropriate permissions.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from datetime import datetime
from typing import Optional, List, Dict, Any


# Supported output formats
OUTPUT_FORMATS = {
    "pdf": {
        "name": "PDF",
        "extension": "pdf",
        "content_type": "application/pdf",
        "description": "Portable Document Format - best for print"
    },
    "html": {
        "name": "HTML",
        "extension": "html",
        "content_type": "text/html",
        "description": "Web page format - best for online viewing"
    }
}

# Catalog layout types
CATALOG_LAYOUTS = {
    "grid": {
        "name": "Grid Layout",
        "description": "Products arranged in a grid format",
        "products_per_page": 6
    },
    "list": {
        "name": "List Layout",
        "description": "Products in a vertical list with details",
        "products_per_page": 4
    },
    "detailed": {
        "name": "Detailed Layout",
        "description": "One product per page with full details",
        "products_per_page": 1
    },
    "compact": {
        "name": "Compact Layout",
        "description": "Maximized product density for quick reference",
        "products_per_page": 12
    }
}


def generate_datasheet(
    product,
    template=None,
    output_format="pdf",
    language=None,
    include_qr_code=True,
    include_barcode=True,
    async_generation=False
):
    """Generate a product datasheet.

    Creates a single-product specification sheet using the specified
    template or the default template for the product family.

    Args:
        product: Product Master name or JSON list of product names
        template: Datasheet Template name (uses default if not specified)
        output_format: Output format - 'pdf' or 'html' (default: pdf)
        language: Language code for localized content (optional)
        include_qr_code: Include QR code linking to product page (default: True)
        include_barcode: Include product barcode/GTIN (default: True)
        async_generation: Run as background job (default: False)

    Returns:
        dict: Generation result with status, file_url, or job_id

    Example:
        >>> # Generate PDF datasheet
        >>> result = generate_datasheet(product="PROD-001")
        >>> print(result["file_url"])

        >>> # With specific template
        >>> result = generate_datasheet(
        ...     product="PROD-001",
        ...     template="technical_spec",
        ...     output_format="html"
        ... )
    """
    import frappe
    from frappe import _
    import json

    # Check permissions
    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted to generate datasheets"), frappe.PermissionError)

    try:
        # Parse products if JSON string
        if isinstance(product, str):
            try:
                products = json.loads(product)
                if isinstance(products, list):
                    # Batch generation for multiple products
                    return generate_datasheets_batch(
                        products=products,
                        template=template,
                        output_format=output_format,
                        language=language,
                        include_qr_code=include_qr_code,
                        include_barcode=include_barcode,
                        async_generation=async_generation
                    )
            except json.JSONDecodeError:
                pass  # Not JSON, treat as single product name
            products = [product]
        else:
            products = [product]

        # Validate output format
        output_format = output_format.lower()
        if output_format not in OUTPUT_FORMATS:
            frappe.throw(
                _("Unsupported output format: {0}. Supported: {1}").format(
                    output_format,
                    ", ".join(OUTPUT_FORMATS.keys())
                )
            )

        # Async generation via background job
        if async_generation:
            return _enqueue_datasheet_generation(
                product=products[0],
                template=template,
                output_format=output_format,
                language=language,
                include_qr_code=include_qr_code,
                include_barcode=include_barcode
            )

        # Get or determine template
        template_doc = _get_datasheet_template(products[0], template)
        if not template_doc:
            frappe.throw(_("No suitable datasheet template found"))

        # Get product data
        product_data = _get_product_data_for_datasheet(products[0], template_doc)

        # Generate the datasheet
        if output_format == "pdf":
            file_url = _generate_pdf_datasheet(product_data, template_doc, language)
        else:
            file_url = _generate_html_datasheet(product_data, template_doc, language)

        # Log generation
        _log_content_generation(
            content_type="Datasheet",
            product=products[0],
            template=template_doc.name,
            output_format=output_format,
            file_url=file_url
        )

        return {
            "success": True,
            "content_type": "datasheet",
            "format": OUTPUT_FORMATS[output_format]["name"],
            "file_url": file_url,
            "product": products[0],
            "template": template_doc.name,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"Datasheet generation failed: {str(e)}",
            title="PIM Content Generation Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def generate_datasheets_batch(
    products,
    template=None,
    output_format="pdf",
    language=None,
    include_qr_code=True,
    include_barcode=True,
    combine_into_single=False,
    async_generation=True
):
    """Generate datasheets for multiple products.

    Creates datasheets for a batch of products, either as individual
    files or combined into a single document.

    Args:
        products: JSON list of Product Master names
        template: Datasheet Template name (uses default if not specified)
        output_format: Output format - 'pdf' or 'html' (default: pdf)
        language: Language code for localized content (optional)
        include_qr_code: Include QR codes (default: True)
        include_barcode: Include barcodes (default: True)
        combine_into_single: Combine all datasheets into one file (default: False)
        async_generation: Run as background job (default: True for batch)

    Returns:
        dict: Generation result with status and file URLs or job_id
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted to generate datasheets"), frappe.PermissionError)

    try:
        # Parse products list
        if isinstance(products, str):
            products = json.loads(products)

        if not products:
            return {"success": False, "error": "No products specified"}

        # For batch operations, async is recommended
        if async_generation or len(products) > 5:
            return _enqueue_batch_datasheet_generation(
                products=products,
                template=template,
                output_format=output_format,
                language=language,
                include_qr_code=include_qr_code,
                include_barcode=include_barcode,
                combine_into_single=combine_into_single
            )

        # Synchronous batch generation
        results = []
        errors = []

        for product_name in products:
            try:
                result = generate_datasheet(
                    product=product_name,
                    template=template,
                    output_format=output_format,
                    language=language,
                    include_qr_code=include_qr_code,
                    include_barcode=include_barcode,
                    async_generation=False
                )
                if result.get("success"):
                    results.append({
                        "product": product_name,
                        "file_url": result.get("file_url")
                    })
                else:
                    errors.append({
                        "product": product_name,
                        "error": result.get("error")
                    })
            except Exception as e:
                errors.append({
                    "product": product_name,
                    "error": str(e)
                })

        return {
            "success": len(errors) == 0,
            "content_type": "datasheet_batch",
            "format": OUTPUT_FORMATS.get(output_format, {}).get("name", output_format),
            "total": len(products),
            "generated": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors if errors else None,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"Batch datasheet generation failed: {str(e)}",
            title="PIM Content Generation Error"
        )
        return {"success": False, "error": str(e)}


def generate_catalog(
    products=None,
    product_family=None,
    product_filters=None,
    template=None,
    layout="grid",
    title=None,
    subtitle=None,
    output_format="pdf",
    language=None,
    include_cover=True,
    include_toc=True,
    include_index=False,
    include_prices=True,
    price_list=None,
    sort_by="product_name",
    sort_order="asc",
    async_generation=True
):
    """Generate a print catalog with multiple products.

    Creates a comprehensive product catalog document with configurable
    layout, cover page, table of contents, and product listings.

    Args:
        products: JSON list of Product Master names (optional)
        product_family: Filter products by family (optional)
        product_filters: JSON dict of additional filters (optional)
        template: Catalog Template name (optional)
        layout: Catalog layout - 'grid', 'list', 'detailed', 'compact'
        title: Catalog title (auto-generated if not provided)
        subtitle: Catalog subtitle (optional)
        output_format: Output format - 'pdf' or 'html' (default: pdf)
        language: Language code for localized content (optional)
        include_cover: Include cover page (default: True)
        include_toc: Include table of contents (default: True)
        include_index: Include product index at end (default: False)
        include_prices: Include product prices (default: True)
        price_list: Price list to use for pricing (optional)
        sort_by: Field to sort products by (default: product_name)
        sort_order: Sort order - 'asc' or 'desc' (default: asc)
        async_generation: Run as background job (default: True)

    Returns:
        dict: Generation result with status, file_url, or job_id

    Example:
        >>> # Generate catalog for a product family
        >>> result = generate_catalog(
        ...     product_family="Electronics",
        ...     layout="grid",
        ...     title="Electronics Catalog 2024"
        ... )

        >>> # With specific products
        >>> result = generate_catalog(
        ...     products=["PROD-001", "PROD-002", "PROD-003"],
        ...     layout="detailed"
        ... )
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted to generate catalogs"), frappe.PermissionError)

    try:
        # Parse JSON parameters
        if products and isinstance(products, str):
            products = json.loads(products)

        if product_filters and isinstance(product_filters, str):
            product_filters = json.loads(product_filters)

        # Validate layout
        if layout not in CATALOG_LAYOUTS:
            frappe.throw(
                _("Unsupported layout: {0}. Supported: {1}").format(
                    layout,
                    ", ".join(CATALOG_LAYOUTS.keys())
                )
            )

        # Validate output format
        output_format = output_format.lower()
        if output_format not in OUTPUT_FORMATS:
            frappe.throw(
                _("Unsupported output format: {0}").format(output_format)
            )

        # Get products to include
        if not products:
            products = _get_products_for_catalog(
                product_family=product_family,
                filters=product_filters,
                sort_by=sort_by,
                sort_order=sort_order
            )

        if not products:
            return {
                "success": False,
                "error": "No products found matching the specified criteria"
            }

        # Async generation for large catalogs
        if async_generation or len(products) > 20:
            return _enqueue_catalog_generation(
                products=products,
                template=template,
                layout=layout,
                title=title,
                subtitle=subtitle,
                output_format=output_format,
                language=language,
                include_cover=include_cover,
                include_toc=include_toc,
                include_index=include_index,
                include_prices=include_prices,
                price_list=price_list,
                sort_by=sort_by,
                sort_order=sort_order
            )

        # Auto-generate title if not provided
        if not title:
            if product_family:
                title = f"{product_family} Catalog"
            else:
                title = f"Product Catalog {datetime.now().strftime('%Y')}"

        # Build catalog configuration
        catalog_config = {
            "title": title,
            "subtitle": subtitle,
            "layout": layout,
            "layout_config": CATALOG_LAYOUTS[layout],
            "include_cover": include_cover,
            "include_toc": include_toc,
            "include_index": include_index,
            "include_prices": include_prices,
            "price_list": price_list,
            "language": language,
            "generated_at": datetime.now().isoformat()
        }

        # Get product data for all products
        products_data = []
        for product_name in products:
            product_data = _get_product_data_for_catalog(
                product_name,
                include_prices=include_prices,
                price_list=price_list
            )
            if product_data:
                products_data.append(product_data)

        if not products_data:
            return {
                "success": False,
                "error": "Could not load product data"
            }

        # Generate the catalog
        if output_format == "pdf":
            file_url = _generate_pdf_catalog(products_data, catalog_config, template)
        else:
            file_url = _generate_html_catalog(products_data, catalog_config, template)

        # Log generation
        _log_content_generation(
            content_type="Catalog",
            product=None,
            template=template,
            output_format=output_format,
            file_url=file_url,
            product_count=len(products_data)
        )

        return {
            "success": True,
            "content_type": "catalog",
            "format": OUTPUT_FORMATS[output_format]["name"],
            "file_url": file_url,
            "title": title,
            "product_count": len(products_data),
            "layout": layout,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"Catalog generation failed: {str(e)}",
            title="PIM Content Generation Error"
        )
        return {
            "success": False,
            "error": str(e)
        }


def generate_datasheet_preview(
    product,
    template=None,
    output_format="html"
):
    """Generate a preview of a datasheet.

    Creates a quick preview of what the datasheet will look like
    without saving the file.

    Args:
        product: Product Master name
        template: Datasheet Template name (optional)
        output_format: Preview format (default: html for quick rendering)

    Returns:
        dict: Preview result with HTML content or status
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        # Get template
        template_doc = _get_datasheet_template(product, template)
        if not template_doc:
            return {
                "success": False,
                "error": "No suitable template found"
            }

        # Get product data
        product_data = _get_product_data_for_datasheet(product, template_doc)

        # Generate HTML preview
        html_content = _render_datasheet_html(product_data, template_doc)

        return {
            "success": True,
            "content_type": "preview",
            "html": html_content,
            "product": product,
            "template": template_doc.name
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def get_generation_status(job_id):
    """Get status of an async content generation job.

    Args:
        job_id: Background job ID

    Returns:
        dict: Job status and result if complete
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        # Get job status from RQ
        from frappe.utils.background_jobs import get_job_status

        status = get_job_status(job_id)

        if not status:
            return {
                "job_id": job_id,
                "status": "not_found",
                "message": "Job not found"
            }

        result = {
            "job_id": job_id,
            "status": status.get("status", "unknown"),
            "progress": status.get("progress", 0)
        }

        if status.get("status") == "finished":
            result["result"] = status.get("result")
        elif status.get("status") == "failed":
            result["error"] = status.get("exc_info")

        return result

    except Exception as e:
        return {
            "job_id": job_id,
            "status": "error",
            "error": str(e)
        }


def get_content_history(
    content_type=None,
    product=None,
    limit=20
):
    """Get history of generated content.

    Args:
        content_type: Filter by type - 'Datasheet' or 'Catalog' (optional)
        product: Filter by product name (optional)
        limit: Maximum records to return (default: 20)

    Returns:
        list: Content generation history records
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    filters = {}
    if content_type:
        filters["content_type"] = content_type
    if product:
        filters["product"] = product

    try:
        # Try to get from PIM Content Log if it exists
        return frappe.get_all(
            "PIM Content Log",
            filters=filters,
            fields=[
                "name", "content_type", "product", "template",
                "output_format", "file_url", "product_count",
                "creation", "owner"
            ],
            limit=limit,
            order_by="creation desc"
        )
    except frappe.exceptions.DoesNotExistError:
        return []


def get_available_templates(template_type="datasheet", product=None):
    """Get available templates for content generation.

    Args:
        template_type: Type of template - 'datasheet' or 'catalog'
        product: Product name to filter applicable templates (optional)

    Returns:
        list: Available template records
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Datasheet Template", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    if template_type == "datasheet":
        if product:
            # Get templates applicable to this product
            from frappe_pim.pim.doctype.datasheet_template.datasheet_template import (
                get_templates_for_product
            )
            return get_templates_for_product(product)
        else:
            return frappe.get_all(
                "Datasheet Template",
                filters={"enabled": 1},
                fields=[
                    "name", "template_name", "template_code", "is_default",
                    "page_size", "page_orientation", "output_format"
                ],
                order_by="sort_order asc"
            )
    elif template_type == "catalog":
        # Return catalog template options
        return [
            {"name": "default", "template_name": "Default Catalog Template"},
            {"name": "minimal", "template_name": "Minimal Catalog"},
            {"name": "professional", "template_name": "Professional Catalog"},
            {"name": "technical", "template_name": "Technical Catalog"}
        ]
    else:
        return []


def get_catalog_layouts():
    """Get available catalog layout options.

    Returns:
        dict: Dictionary of available layouts with descriptions
    """
    return {
        "success": True,
        "layouts": CATALOG_LAYOUTS,
        "layout_list": list(CATALOG_LAYOUTS.keys())
    }


def get_output_formats():
    """Get available output formats.

    Returns:
        dict: Dictionary of available output formats
    """
    return {
        "success": True,
        "formats": OUTPUT_FORMATS,
        "format_list": list(OUTPUT_FORMATS.keys())
    }


def download_content(file_url=None, job_id=None):
    """Get download information for generated content.

    Args:
        file_url: Direct file URL
        job_id: Job ID to get result file from

    Returns:
        dict: Download information
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Product Master", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        if file_url:
            return {
                "success": True,
                "download_url": file_url,
                "filename": file_url.split("/")[-1]
            }

        if job_id:
            status = get_generation_status(job_id)
            if status.get("status") == "finished" and status.get("result"):
                result = status["result"]
                if result.get("file_url"):
                    return {
                        "success": True,
                        "download_url": result["file_url"],
                        "filename": result["file_url"].split("/")[-1]
                    }

            return {
                "success": False,
                "error": "Content not ready for download",
                "status": status.get("status")
            }

        return {"success": False, "error": "File URL or job ID required"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _get_datasheet_template(product_name, template_name=None):
    """Get datasheet template for a product.

    Args:
        product_name: Product Master name
        template_name: Specific template name (optional)

    Returns:
        Document: Datasheet Template document or None
    """
    import frappe

    if template_name:
        try:
            return frappe.get_doc("Datasheet Template", template_name)
        except frappe.DoesNotExistError:
            return None

    # Find best template for product
    try:
        from frappe_pim.pim.doctype.datasheet_template.datasheet_template import (
            get_template_for_product
        )
        return get_template_for_product(product_name)
    except ImportError:
        # Fallback to default template
        template_name = frappe.db.get_value(
            "Datasheet Template",
            {"is_default": 1, "enabled": 1},
            "name"
        )
        if template_name:
            return frappe.get_doc("Datasheet Template", template_name)
        return None


def _get_product_data_for_datasheet(product_name, template_doc):
    """Get product data formatted for datasheet generation.

    Args:
        product_name: Product Master name
        template_doc: Datasheet Template document

    Returns:
        dict: Product data for rendering
    """
    import frappe

    try:
        product = frappe.get_doc("Product Master", product_name)

        data = {
            "name": product.name,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "short_description": product.short_description,
            "long_description": product.long_description,
            "product_family": product.product_family,
            "brand": product.get("brand"),
            "status": product.status,
            "image": product.image,
            "completeness_score": product.completeness_score
        }

        # Get sections config
        sections = template_doc.get_sections_config()

        # Add attributes if enabled
        if sections.get("attributes", {}).get("enabled"):
            data["attributes"] = _get_product_attributes(product, template_doc)

        # Add dimensions if enabled
        if sections.get("dimensions", {}).get("enabled"):
            data["dimensions"] = _get_product_dimensions(product)

        # Add pricing if enabled
        if sections.get("pricing", {}).get("enabled"):
            price_list = sections["pricing"].get("price_list")
            data["pricing"] = _get_product_pricing(product, price_list)

        # Add media
        if sections.get("images", {}).get("enabled"):
            data["media"] = _get_product_media(product, sections["images"])

        # Add GS1 data if enabled
        if sections.get("gs1", {}).get("show_gs1"):
            data["gs1"] = _get_product_gs1_data(product)

        # Add nutrition if enabled
        if sections.get("nutrition", {}).get("enabled"):
            data["nutrition"] = _get_product_nutrition(product)

        return data

    except Exception as e:
        import frappe
        frappe.log_error(
            message=f"Error getting product data for {product_name}: {str(e)}",
            title="PIM Content Generation Error"
        )
        return None


def _get_product_data_for_catalog(product_name, include_prices=True, price_list=None):
    """Get product data formatted for catalog generation.

    Args:
        product_name: Product Master name
        include_prices: Include pricing information
        price_list: Specific price list to use

    Returns:
        dict: Product data for catalog
    """
    import frappe

    try:
        product = frappe.get_doc("Product Master", product_name)

        data = {
            "name": product.name,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "short_description": product.short_description,
            "product_family": product.product_family,
            "brand": product.get("brand"),
            "image": product.image,
            "status": product.status
        }

        if include_prices:
            data["pricing"] = _get_product_pricing(product, price_list)

        # Get key attributes for catalog listing
        data["key_attributes"] = _get_key_attributes(product)

        return data

    except Exception:
        return None


def _get_products_for_catalog(
    product_family=None,
    filters=None,
    sort_by="product_name",
    sort_order="asc"
):
    """Get list of products for catalog generation.

    Args:
        product_family: Filter by family
        filters: Additional filters dict
        sort_by: Field to sort by
        sort_order: Sort direction

    Returns:
        list: Product names
    """
    import frappe

    query_filters = {"status": ["in", ["Active", "Published"]]}

    if product_family:
        query_filters["product_family"] = product_family

    if filters:
        query_filters.update(filters)

    products = frappe.get_all(
        "Product Master",
        filters=query_filters,
        pluck="name",
        order_by=f"{sort_by} {sort_order}"
    )

    return products


def _get_product_attributes(product, template_doc):
    """Get product attributes based on template settings.

    Args:
        product: Product Master document
        template_doc: Datasheet Template document

    Returns:
        list: Attribute data
    """
    attributes = []
    sections = template_doc.get_sections_config()
    attr_config = sections.get("attributes", {})

    selected_attrs = attr_config.get("selected", [])
    hide_empty = attr_config.get("hide_empty", True)

    for attr_value in (product.get("attribute_values") or []):
        attr_code = attr_value.get("attribute")

        # Filter by selection if configured
        if selected_attrs and attr_code not in selected_attrs:
            continue

        # Get value
        value = (
            attr_value.get("value_text") or
            attr_value.get("value_int") or
            attr_value.get("value_float") or
            attr_value.get("value_date") or
            attr_value.get("value_link")
        )

        if attr_value.get("value_boolean") is not None:
            value = "Yes" if attr_value.get("value_boolean") else "No"

        # Skip empty if configured
        if hide_empty and not value:
            continue

        attributes.append({
            "code": attr_code,
            "label": attr_value.get("attribute_label", attr_code),
            "value": value,
            "unit": attr_value.get("unit")
        })

    return attributes


def _get_product_dimensions(product):
    """Get product dimension data.

    Args:
        product: Product Master document

    Returns:
        dict: Dimension data
    """
    return {
        "length": product.get("length"),
        "width": product.get("width"),
        "height": product.get("height"),
        "weight": product.get("weight_per_unit"),
        "length_unit": product.get("length_unit", "mm"),
        "weight_unit": product.get("weight_unit", "kg")
    }


def _get_product_pricing(product, price_list=None):
    """Get product pricing information.

    Args:
        product: Product Master document
        price_list: Specific price list name

    Returns:
        dict: Pricing data
    """
    import frappe

    pricing = {
        "standard_rate": product.get("standard_rate"),
        "currency": product.get("currency", "USD")
    }

    # Try to get from Item Price if ERPNext integration
    if price_list:
        try:
            item_price = frappe.db.get_value(
                "Item Price",
                {
                    "item_code": product.name,
                    "price_list": price_list,
                    "selling": 1
                },
                ["price_list_rate", "currency"],
                as_dict=True
            )
            if item_price:
                pricing["price_list_rate"] = item_price.price_list_rate
                pricing["currency"] = item_price.currency
        except Exception:
            pass

    return pricing


def _get_product_media(product, media_config):
    """Get product media for datasheet.

    Args:
        product: Product Master document
        media_config: Media section configuration

    Returns:
        list: Media items
    """
    media_list = []
    max_images = media_config.get("max_images", 4)

    # Primary image
    if product.get("image"):
        media_list.append({
            "url": product.image,
            "is_primary": True,
            "type": "image"
        })

    # Additional media from child table
    for media in (product.get("media") or []):
        if len(media_list) >= max_images:
            break

        media_list.append({
            "url": media.get("file_url"),
            "is_primary": False,
            "type": media.get("media_type", "image")
        })

    return media_list


def _get_product_gs1_data(product):
    """Get GS1/GTIN data for product.

    Args:
        product: Product Master document

    Returns:
        dict: GS1 data
    """
    return {
        "gtin": product.get("gtin"),
        "ean": product.get("ean"),
        "upc": product.get("upc"),
        "mpn": product.get("mpn"),
        "brand": product.get("brand"),
        "manufacturer": product.get("manufacturer"),
        "country_of_origin": product.get("country_of_origin")
    }


def _get_product_nutrition(product):
    """Get nutrition facts for product.

    Args:
        product: Product Master document

    Returns:
        dict: Nutrition data or None
    """
    import frappe

    try:
        nutrition = frappe.db.get_value(
            "Nutrition Facts",
            {"product": product.name},
            "*",
            as_dict=True
        )
        return nutrition
    except Exception:
        return None


def _get_key_attributes(product, limit=5):
    """Get key attributes for catalog listing.

    Args:
        product: Product Master document
        limit: Maximum attributes to return

    Returns:
        list: Key attribute data
    """
    attributes = []

    for attr_value in (product.get("attribute_values") or [])[:limit]:
        value = (
            attr_value.get("value_text") or
            attr_value.get("value_int") or
            attr_value.get("value_float")
        )

        if value:
            attributes.append({
                "label": attr_value.get("attribute_label", attr_value.get("attribute")),
                "value": str(value)
            })

    return attributes


def _generate_pdf_datasheet(product_data, template_doc, language=None):
    """Generate PDF datasheet.

    Args:
        product_data: Product data dictionary
        template_doc: Datasheet Template document
        language: Language code

    Returns:
        str: File URL
    """
    import frappe

    # Generate HTML first
    html_content = _render_datasheet_html(product_data, template_doc, language)

    # Convert to PDF using Frappe's PDF generation
    from frappe.utils.pdf import get_pdf

    pdf_content = get_pdf(html_content)

    # Generate filename
    filename = template_doc.generate_filename(product_data)
    filename = f"{filename}.pdf"

    # Save file
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": pdf_content,
        "is_private": 1,
        "folder": "Home/Datasheets"
    })

    try:
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        file_doc.folder = "Home"
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()

    return file_doc.file_url


def _generate_html_datasheet(product_data, template_doc, language=None):
    """Generate HTML datasheet.

    Args:
        product_data: Product data dictionary
        template_doc: Datasheet Template document
        language: Language code

    Returns:
        str: File URL
    """
    import frappe

    html_content = _render_datasheet_html(product_data, template_doc, language)

    # Generate filename
    filename = template_doc.generate_filename(product_data)
    filename = f"{filename}.html"

    # Save file
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": html_content,
        "is_private": 1,
        "folder": "Home/Datasheets"
    })

    try:
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        file_doc.folder = "Home"
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()

    return file_doc.file_url


def _render_datasheet_html(product_data, template_doc, language=None):
    """Render datasheet HTML from template.

    Args:
        product_data: Product data dictionary
        template_doc: Datasheet Template document
        language: Language code

    Returns:
        str: Rendered HTML
    """
    import frappe

    # Get template configuration
    config = template_doc.to_render_config()
    style = config.get("style", {})
    sections = config.get("sections", {})
    header = config.get("header", {})
    footer = config.get("footer", {})

    # Build HTML
    html_parts = []

    # HTML header
    html_parts.append(f"""<!DOCTYPE html>
<html lang="{language or 'en'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{product_data.get('product_name', 'Datasheet')}</title>
    <style>
        body {{
            font-family: {style.get('body_font', 'Helvetica')}, sans-serif;
            font-size: {style.get('base_font_size', 10)}pt;
            color: #333;
            margin: 0;
            padding: 20mm;
        }}
        h1, h2, h3 {{
            font-family: {style.get('heading_font', 'Helvetica')}, sans-serif;
            color: {style.get('primary_color', '#1F272E')};
        }}
        .header {{
            border-bottom: 2px solid {style.get('primary_color', '#1F272E')};
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .product-header {{
            display: flex;
            align-items: flex-start;
        }}
        .product-image {{
            max-width: 200px;
            margin-right: 20px;
        }}
        .product-info h1 {{
            margin: 0 0 10px 0;
        }}
        .section {{
            margin: 20px 0;
        }}
        .section h2 {{
            font-size: 14pt;
            border-bottom: 1px solid #ddd;
            padding-bottom: 5px;
        }}
        .attributes-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .attributes-table td {{
            padding: 5px 10px;
            border-bottom: 1px solid #eee;
        }}
        .attributes-table td:first-child {{
            font-weight: bold;
            width: 40%;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 10px;
            border-top: 1px solid #ddd;
            font-size: 9pt;
            color: #666;
        }}
        {style.get('custom_css', '')}
    </style>
</head>
<body>
""")

    # Header
    if header.get("enabled"):
        html_parts.append('<div class="header">')
        if header.get("logo"):
            html_parts.append(f'<img src="{header["logo"]}" alt="Logo" style="max-height: 40px;">')
        if header.get("text"):
            html_parts.append(f'<span>{header["text"]}</span>')
        html_parts.append('</div>')

    # Product header
    html_parts.append('<div class="product-header">')
    if product_data.get("image") and sections.get("images", {}).get("enabled"):
        html_parts.append(f'<img class="product-image" src="{product_data["image"]}" alt="Product">')
    html_parts.append('<div class="product-info">')
    html_parts.append(f'<h1>{product_data.get("product_name", "")}</h1>')
    if sections.get("product_header", {}).get("show_code"):
        html_parts.append(f'<p><strong>Product Code:</strong> {product_data.get("product_code", "")}</p>')
    html_parts.append('</div>')
    html_parts.append('</div>')

    # Description
    if sections.get("description", {}).get("enabled") and product_data.get("short_description"):
        html_parts.append('<div class="section">')
        heading = sections["description"].get("heading", "Description")
        html_parts.append(f'<h2>{heading}</h2>')
        html_parts.append(f'<p>{product_data.get("short_description", "")}</p>')
        if product_data.get("long_description"):
            html_parts.append(f'<p>{product_data.get("long_description", "")}</p>')
        html_parts.append('</div>')

    # Attributes
    if sections.get("attributes", {}).get("enabled") and product_data.get("attributes"):
        html_parts.append('<div class="section">')
        heading = sections["attributes"].get("heading", "Specifications")
        html_parts.append(f'<h2>{heading}</h2>')
        html_parts.append('<table class="attributes-table">')
        for attr in product_data["attributes"]:
            unit = f" {attr.get('unit')}" if attr.get("unit") else ""
            html_parts.append(f'<tr><td>{attr["label"]}</td><td>{attr["value"]}{unit}</td></tr>')
        html_parts.append('</table>')
        html_parts.append('</div>')

    # Dimensions
    if sections.get("dimensions", {}).get("enabled") and product_data.get("dimensions"):
        dims = product_data["dimensions"]
        if any([dims.get("length"), dims.get("width"), dims.get("height"), dims.get("weight")]):
            html_parts.append('<div class="section">')
            heading = sections["dimensions"].get("heading", "Dimensions")
            html_parts.append(f'<h2>{heading}</h2>')
            html_parts.append('<table class="attributes-table">')
            if dims.get("length"):
                html_parts.append(f'<tr><td>Length</td><td>{dims["length"]} {dims.get("length_unit", "mm")}</td></tr>')
            if dims.get("width"):
                html_parts.append(f'<tr><td>Width</td><td>{dims["width"]} {dims.get("length_unit", "mm")}</td></tr>')
            if dims.get("height"):
                html_parts.append(f'<tr><td>Height</td><td>{dims["height"]} {dims.get("length_unit", "mm")}</td></tr>')
            if dims.get("weight"):
                html_parts.append(f'<tr><td>Weight</td><td>{dims["weight"]} {dims.get("weight_unit", "kg")}</td></tr>')
            html_parts.append('</table>')
            html_parts.append('</div>')

    # Footer
    if footer.get("enabled"):
        html_parts.append('<div class="footer">')
        if footer.get("text"):
            html_parts.append(f'<span>{footer["text"]}</span>')
        if footer.get("show_date"):
            html_parts.append(f'<span style="float: right;">Generated: {datetime.now().strftime("%Y-%m-%d")}</span>')
        html_parts.append('</div>')

    html_parts.append('</body></html>')

    return "\n".join(html_parts)


def _generate_pdf_catalog(products_data, catalog_config, template=None):
    """Generate PDF catalog.

    Args:
        products_data: List of product data dictionaries
        catalog_config: Catalog configuration
        template: Optional template name

    Returns:
        str: File URL
    """
    import frappe

    # Generate HTML first
    html_content = _render_catalog_html(products_data, catalog_config)

    # Convert to PDF
    from frappe.utils.pdf import get_pdf

    pdf_content = get_pdf(html_content)

    # Generate filename
    title_slug = frappe.scrub(catalog_config.get("title", "catalog"))[:30]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{title_slug}_{timestamp}.pdf"

    # Save file
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": pdf_content,
        "is_private": 1,
        "folder": "Home/Catalogs"
    })

    try:
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        file_doc.folder = "Home"
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()

    return file_doc.file_url


def _generate_html_catalog(products_data, catalog_config, template=None):
    """Generate HTML catalog.

    Args:
        products_data: List of product data dictionaries
        catalog_config: Catalog configuration
        template: Optional template name

    Returns:
        str: File URL
    """
    import frappe

    html_content = _render_catalog_html(products_data, catalog_config)

    # Generate filename
    title_slug = frappe.scrub(catalog_config.get("title", "catalog"))[:30]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{title_slug}_{timestamp}.html"

    # Save file
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": html_content,
        "is_private": 1,
        "folder": "Home/Catalogs"
    })

    try:
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        file_doc.folder = "Home"
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()

    return file_doc.file_url


def _render_catalog_html(products_data, catalog_config):
    """Render catalog HTML.

    Args:
        products_data: List of product data dictionaries
        catalog_config: Catalog configuration

    Returns:
        str: Rendered HTML
    """
    title = catalog_config.get("title", "Product Catalog")
    subtitle = catalog_config.get("subtitle", "")
    layout = catalog_config.get("layout", "grid")
    include_cover = catalog_config.get("include_cover", True)
    include_toc = catalog_config.get("include_toc", True)
    include_prices = catalog_config.get("include_prices", True)

    # Layout-specific styles
    layout_styles = {
        "grid": "display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;",
        "list": "display: flex; flex-direction: column; gap: 20px;",
        "detailed": "display: flex; flex-direction: column; gap: 40px;",
        "compact": "display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; font-size: 9pt;"
    }

    html_parts = []

    # HTML header
    html_parts.append(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20mm;
            color: #333;
        }}
        .cover {{
            text-align: center;
            page-break-after: always;
            padding-top: 30%;
        }}
        .cover h1 {{
            font-size: 32pt;
            margin-bottom: 10px;
        }}
        .cover p {{
            font-size: 14pt;
            color: #666;
        }}
        .toc {{
            page-break-after: always;
        }}
        .toc h2 {{
            border-bottom: 2px solid #333;
            padding-bottom: 10px;
        }}
        .toc ul {{
            list-style: none;
            padding: 0;
        }}
        .toc li {{
            padding: 5px 0;
            border-bottom: 1px dotted #ccc;
        }}
        .products {{
            {layout_styles.get(layout, layout_styles['grid'])}
        }}
        .product-card {{
            border: 1px solid #ddd;
            padding: 15px;
            background: #fff;
        }}
        .product-card img {{
            max-width: 100%;
            height: auto;
        }}
        .product-card h3 {{
            margin: 10px 0 5px;
            font-size: 12pt;
        }}
        .product-card .code {{
            color: #666;
            font-size: 9pt;
        }}
        .product-card .description {{
            font-size: 10pt;
            margin: 10px 0;
        }}
        .product-card .price {{
            font-weight: bold;
            color: #2e7d32;
        }}
        .product-card .attributes {{
            font-size: 9pt;
            color: #666;
        }}
        .footer {{
            margin-top: 30px;
            text-align: center;
            font-size: 9pt;
            color: #666;
        }}
        @media print {{
            .product-card {{ page-break-inside: avoid; }}
        }}
    </style>
</head>
<body>
""")

    # Cover page
    if include_cover:
        html_parts.append('<div class="cover">')
        html_parts.append(f'<h1>{title}</h1>')
        if subtitle:
            html_parts.append(f'<p>{subtitle}</p>')
        html_parts.append(f'<p>Generated: {datetime.now().strftime("%B %Y")}</p>')
        html_parts.append(f'<p>{len(products_data)} Products</p>')
        html_parts.append('</div>')

    # Table of contents
    if include_toc and len(products_data) > 10:
        html_parts.append('<div class="toc">')
        html_parts.append('<h2>Table of Contents</h2>')
        html_parts.append('<ul>')
        for i, product in enumerate(products_data, 1):
            html_parts.append(
                f'<li>{i}. {product.get("product_name", product.get("name"))}</li>'
            )
        html_parts.append('</ul>')
        html_parts.append('</div>')

    # Products
    html_parts.append('<div class="products">')
    for product in products_data:
        html_parts.append('<div class="product-card">')

        if product.get("image"):
            html_parts.append(f'<img src="{product["image"]}" alt="{product.get("product_name", "")}">')

        html_parts.append(f'<h3>{product.get("product_name", "")}</h3>')
        html_parts.append(f'<p class="code">{product.get("product_code", "")}</p>')

        if product.get("short_description"):
            desc = product["short_description"][:150]
            if len(product["short_description"]) > 150:
                desc += "..."
            html_parts.append(f'<p class="description">{desc}</p>')

        if include_prices and product.get("pricing"):
            pricing = product["pricing"]
            rate = pricing.get("price_list_rate") or pricing.get("standard_rate")
            if rate:
                currency = pricing.get("currency", "USD")
                html_parts.append(f'<p class="price">{currency} {rate:,.2f}</p>')

        if product.get("key_attributes"):
            attrs = " | ".join([
                f"{a['label']}: {a['value']}"
                for a in product["key_attributes"][:3]
            ])
            html_parts.append(f'<p class="attributes">{attrs}</p>')

        html_parts.append('</div>')

    html_parts.append('</div>')

    # Footer
    html_parts.append('<div class="footer">')
    html_parts.append(f'<p>{title} | Generated on {datetime.now().strftime("%Y-%m-%d")}</p>')
    html_parts.append('</div>')

    html_parts.append('</body></html>')

    return "\n".join(html_parts)


def _enqueue_datasheet_generation(**kwargs):
    """Enqueue datasheet generation as background job.

    Returns:
        dict: Job status with job_id
    """
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.content.generate_datasheet",
        queue="default",
        timeout=600,
        **kwargs,
        async_generation=False
    )

    return {
        "success": True,
        "async": True,
        "content_type": "datasheet",
        "message": "Datasheet generation job queued",
        "job_id": str(job.id) if hasattr(job, 'id') else str(job)
    }


def _enqueue_batch_datasheet_generation(**kwargs):
    """Enqueue batch datasheet generation as background job.

    Returns:
        dict: Job status with job_id
    """
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.content.generate_datasheets_batch",
        queue="long",
        timeout=3600,
        **kwargs,
        async_generation=False
    )

    return {
        "success": True,
        "async": True,
        "content_type": "datasheet_batch",
        "message": "Batch datasheet generation job queued",
        "job_id": str(job.id) if hasattr(job, 'id') else str(job)
    }


def _enqueue_catalog_generation(**kwargs):
    """Enqueue catalog generation as background job.

    Returns:
        dict: Job status with job_id
    """
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.content.generate_catalog",
        queue="long",
        timeout=3600,
        **kwargs,
        async_generation=False
    )

    return {
        "success": True,
        "async": True,
        "content_type": "catalog",
        "message": "Catalog generation job queued",
        "job_id": str(job.id) if hasattr(job, 'id') else str(job)
    }


def _log_content_generation(
    content_type,
    product=None,
    template=None,
    output_format=None,
    file_url=None,
    product_count=None
):
    """Log content generation for tracking.

    Args:
        content_type: Type of content generated
        product: Product name (for datasheets)
        template: Template used
        output_format: Output format
        file_url: Generated file URL
        product_count: Number of products (for catalogs)
    """
    import frappe

    try:
        # Try to create log if DocType exists
        log_doc = frappe.get_doc({
            "doctype": "PIM Content Log",
            "content_type": content_type,
            "product": product,
            "template": template,
            "output_format": output_format,
            "file_url": file_url,
            "product_count": product_count
        })
        log_doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        # Log DocType might not exist, skip logging
        pass


# ============================================================================
# Whitelist Wrapper
# ============================================================================

def _wrap_for_whitelist():
    """Add @frappe.whitelist() decorators at runtime."""
    import frappe

    global generate_datasheet, generate_datasheets_batch, generate_catalog
    global generate_datasheet_preview, get_generation_status, get_content_history
    global get_available_templates, get_catalog_layouts, get_output_formats
    global download_content

    generate_datasheet = frappe.whitelist()(generate_datasheet)
    generate_datasheets_batch = frappe.whitelist()(generate_datasheets_batch)
    generate_catalog = frappe.whitelist()(generate_catalog)
    generate_datasheet_preview = frappe.whitelist()(generate_datasheet_preview)
    get_generation_status = frappe.whitelist()(get_generation_status)
    get_content_history = frappe.whitelist()(get_content_history)
    get_available_templates = frappe.whitelist()(get_available_templates)
    get_catalog_layouts = frappe.whitelist()(get_catalog_layouts)
    get_output_formats = frappe.whitelist()(get_output_formats)
    download_content = frappe.whitelist()(download_content)


# Apply whitelist decorators if frappe is available
try:
    _wrap_for_whitelist()
except ImportError:
    pass  # frappe not available, decorators will be added when module is used
