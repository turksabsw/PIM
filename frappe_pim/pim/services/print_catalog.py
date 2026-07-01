"""Print Catalog Generator Service

This module provides services for generating print-ready product catalogs using
Frappe's print format system with PDF output. It enables marketing teams to create
professional product catalogs for various purposes:

- Product brochures and lookbooks
- Price lists for distribution
- Technical specification sheets
- Trade show materials
- Partner/retailer catalogs

The service supports:
- Multiple catalog layouts (grid, list, detailed)
- Configurable page sizes (A4, Letter, A3, custom)
- Custom print formats via Frappe Print Format DocType
- Product filtering and sorting
- Multi-language content
- Cover pages and table of contents
- Product grouping by category/brand/family
- Media/image inclusion with configurable quality
- Pricing and specification display options
- Background PDF generation for large catalogs

Usage:
    from frappe_pim.pim.services.print_catalog import generate_catalog

    pdf_path = generate_catalog(
        profile_name="product_brochure",
        save_file=True
    )

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Constants and Enums
# =============================================================================

class CatalogLayout(Enum):
    """Catalog layout styles."""
    GRID = "grid"  # Multiple products per page in grid format
    LIST = "list"  # One product per row, compact
    DETAILED = "detailed"  # One product per page, full details
    GALLERY = "gallery"  # Image-focused layout
    PRICE_LIST = "price_list"  # Compact price list format
    SPEC_SHEET = "spec_sheet"  # Technical specification focus


class PageSize(Enum):
    """Standard page sizes."""
    A4 = "A4"  # 210mm x 297mm
    A3 = "A3"  # 297mm x 420mm
    A5 = "A5"  # 148mm x 210mm
    LETTER = "Letter"  # 8.5" x 11"
    LEGAL = "Legal"  # 8.5" x 14"
    TABLOID = "Tabloid"  # 11" x 17"


class PageOrientation(Enum):
    """Page orientation."""
    PORTRAIT = "Portrait"
    LANDSCAPE = "Landscape"


class CatalogStatus(Enum):
    """Catalog generation status."""
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class SortOrder(Enum):
    """Product sort order options."""
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    CODE_ASC = "code_asc"
    CODE_DESC = "code_desc"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    CATEGORY = "category"
    BRAND = "brand"
    FAMILY = "family"
    MODIFIED_DESC = "modified_desc"


# Page size dimensions in mm
PAGE_DIMENSIONS = {
    PageSize.A4: (210, 297),
    PageSize.A3: (297, 420),
    PageSize.A5: (148, 210),
    PageSize.LETTER: (216, 279),
    PageSize.LEGAL: (216, 356),
    PageSize.TABLOID: (279, 432),
}

# Default products per page by layout
PRODUCTS_PER_PAGE = {
    CatalogLayout.GRID: 6,
    CatalogLayout.LIST: 10,
    CatalogLayout.DETAILED: 1,
    CatalogLayout.GALLERY: 4,
    CatalogLayout.PRICE_LIST: 20,
    CatalogLayout.SPEC_SHEET: 1,
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class CatalogConfig:
    """Configuration for print catalog generation."""
    title: str = "Product Catalog"
    subtitle: Optional[str] = None
    layout: CatalogLayout = CatalogLayout.GRID
    page_size: PageSize = PageSize.A4
    orientation: PageOrientation = PageOrientation.PORTRAIT
    language: str = "en"
    currency: str = "EUR"
    include_cover: bool = True
    include_toc: bool = True
    include_prices: bool = True
    include_descriptions: bool = True
    include_specifications: bool = True
    include_images: bool = True
    include_barcodes: bool = False
    group_by: Optional[str] = None  # category, brand, family
    sort_by: SortOrder = SortOrder.NAME_ASC
    products_per_page: Optional[int] = None
    image_quality: int = 85  # JPEG quality 1-100
    margin_mm: int = 15
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    custom_css: Optional[str] = None
    print_format: Optional[str] = None  # Custom Frappe Print Format name

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "layout": self.layout.value,
            "page_size": self.page_size.value,
            "orientation": self.orientation.value,
            "language": self.language,
            "currency": self.currency,
            "include_cover": self.include_cover,
            "include_toc": self.include_toc,
            "include_prices": self.include_prices,
            "include_descriptions": self.include_descriptions,
            "include_specifications": self.include_specifications,
            "include_images": self.include_images,
            "include_barcodes": self.include_barcodes,
            "group_by": self.group_by,
            "sort_by": self.sort_by.value,
            "products_per_page": self.products_per_page,
            "image_quality": self.image_quality,
            "margin_mm": self.margin_mm,
            "header_text": self.header_text,
            "footer_text": self.footer_text,
            "print_format": self.print_format,
        }


@dataclass
class CatalogProduct:
    """Product data for catalog rendering."""
    name: str
    code: str
    title: str
    short_description: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    currency: str = "EUR"
    image_url: Optional[str] = None
    barcode: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    family: Optional[str] = None
    specifications: Dict[str, Any] = field(default_factory=dict)
    additional_images: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "code": self.code,
            "title": self.title,
            "short_description": self.short_description,
            "description": self.description,
            "price": self.price,
            "currency": self.currency,
            "image_url": self.image_url,
            "barcode": self.barcode,
            "brand": self.brand,
            "category": self.category,
            "family": self.family,
            "specifications": self.specifications,
            "additional_images": self.additional_images,
        }


@dataclass
class CatalogResult:
    """Result of catalog generation."""
    success: bool
    catalog_id: str
    status: CatalogStatus
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    page_count: int = 0
    product_count: int = 0
    file_size_bytes: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    generation_time_seconds: float = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "catalog_id": self.catalog_id,
            "status": self.status.value,
            "file_path": self.file_path,
            "file_url": self.file_url,
            "page_count": self.page_count,
            "product_count": self.product_count,
            "file_size_bytes": self.file_size_bytes,
            "errors": self.errors,
            "warnings": self.warnings,
            "generation_time_seconds": self.generation_time_seconds,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# Print Catalog Service
# =============================================================================

class PrintCatalogService:
    """Service for generating print-ready product catalogs.

    This service uses Frappe's print format system to generate PDF catalogs
    with professional layouts suitable for print production.

    Attributes:
        config: Catalog configuration
        products: List of products to include
    """

    def __init__(self, config: Optional[CatalogConfig] = None):
        """Initialize the print catalog service.

        Args:
            config: Catalog configuration (uses defaults if not provided)
        """
        self.config = config or CatalogConfig()
        self._products: List[CatalogProduct] = []

    def load_products(
        self,
        product_names: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[CatalogProduct]:
        """Load products for the catalog.

        Args:
            product_names: Specific product names to include
            filters: Frappe filter dictionary for product query
            limit: Maximum number of products

        Returns:
            List of CatalogProduct instances
        """
        import frappe

        self._products = []

        if product_names:
            # Load specific products
            for name in product_names:
                product = self._load_product(name)
                if product:
                    self._products.append(product)
        else:
            # Query products with filters
            query_filters = filters or {}
            products = frappe.get_all(
                "Product Variant",
                filters=query_filters,
                fields=["name"],
                limit=limit,
                order_by=self._get_order_by()
            )

            for p in products:
                product = self._load_product(p["name"])
                if product:
                    self._products.append(product)

        # Apply sorting
        self._sort_products()

        return self._products

    def _load_product(self, product_name: str) -> Optional[CatalogProduct]:
        """Load a single product and convert to CatalogProduct.

        Args:
            product_name: Product Variant or Product Master name

        Returns:
            CatalogProduct instance or None if not found
        """
        import frappe

        try:
            # Try Product Variant first
            try:
                doc = frappe.get_doc("Product Variant", product_name)
            except Exception:
                # Fall back to Product Master
                doc = frappe.get_doc("Product Master", product_name)

            # Extract specifications from attribute values
            specs = {}
            attribute_values = doc.get("attribute_values") or []
            for attr_val in attribute_values:
                attr_code = attr_val.get("attribute")
                value = self._extract_attribute_value(attr_val)
                if attr_code and value is not None:
                    # Get attribute display name
                    try:
                        attr_name = frappe.get_cached_value(
                            "PIM Attribute", attr_code, "attribute_name"
                        ) or attr_code
                    except Exception:
                        attr_name = attr_code
                    specs[attr_name] = value

            # Get additional images
            additional_images = []
            media_list = doc.get("media") or []
            for media in media_list:
                url = media.get("file_url") or media.get("url")
                if url:
                    additional_images.append(self._get_full_url(url))

            return CatalogProduct(
                name=doc.name,
                code=doc.get("variant_code") or doc.get("product_code") or doc.name,
                title=doc.get("variant_name") or doc.get("product_name") or doc.name,
                short_description=doc.get("short_description"),
                description=self._clean_html(doc.get("description")),
                price=doc.get("price") or doc.get("standard_rate"),
                currency=doc.get("currency") or self.config.currency,
                image_url=self._get_full_url(doc.get("image")),
                barcode=doc.get("barcode") or doc.get("gtin"),
                brand=doc.get("brand"),
                category=doc.get("item_group") or doc.get("category"),
                family=doc.get("product_family"),
                specifications=specs,
                additional_images=additional_images,
            )

        except Exception:
            return None

    def _extract_attribute_value(self, attr_val: Dict) -> Any:
        """Extract value from attribute value row.

        Args:
            attr_val: Attribute value dictionary

        Returns:
            Extracted value or None
        """
        value_fields = [
            "value_text", "value_data", "value_int", "value_float",
            "value_date", "value_datetime", "value_link", "value_boolean"
        ]

        for field_name in value_fields:
            value = attr_val.get(field_name)
            if value is not None:
                if isinstance(value, bool):
                    return "Yes" if value else "No"
                if isinstance(value, str) and not value.strip():
                    continue
                return value

        return None

    def _get_order_by(self) -> str:
        """Get SQL order by clause based on sort configuration."""
        sort_map = {
            SortOrder.NAME_ASC: "variant_name asc",
            SortOrder.NAME_DESC: "variant_name desc",
            SortOrder.CODE_ASC: "variant_code asc",
            SortOrder.CODE_DESC: "variant_code desc",
            SortOrder.PRICE_ASC: "price asc",
            SortOrder.PRICE_DESC: "price desc",
            SortOrder.CATEGORY: "item_group asc, variant_name asc",
            SortOrder.BRAND: "brand asc, variant_name asc",
            SortOrder.FAMILY: "product_family asc, variant_name asc",
            SortOrder.MODIFIED_DESC: "modified desc",
        }
        return sort_map.get(self.config.sort_by, "variant_name asc")

    def _sort_products(self):
        """Sort loaded products based on configuration."""
        if not self._products:
            return

        if self.config.sort_by == SortOrder.NAME_ASC:
            self._products.sort(key=lambda p: p.title.lower())
        elif self.config.sort_by == SortOrder.NAME_DESC:
            self._products.sort(key=lambda p: p.title.lower(), reverse=True)
        elif self.config.sort_by == SortOrder.CODE_ASC:
            self._products.sort(key=lambda p: p.code.lower())
        elif self.config.sort_by == SortOrder.CODE_DESC:
            self._products.sort(key=lambda p: p.code.lower(), reverse=True)
        elif self.config.sort_by == SortOrder.PRICE_ASC:
            self._products.sort(key=lambda p: p.price or 0)
        elif self.config.sort_by == SortOrder.PRICE_DESC:
            self._products.sort(key=lambda p: p.price or 0, reverse=True)
        elif self.config.sort_by == SortOrder.CATEGORY:
            self._products.sort(key=lambda p: (p.category or "", p.title.lower()))
        elif self.config.sort_by == SortOrder.BRAND:
            self._products.sort(key=lambda p: (p.brand or "", p.title.lower()))
        elif self.config.sort_by == SortOrder.FAMILY:
            self._products.sort(key=lambda p: (p.family or "", p.title.lower()))

    def _group_products(self) -> Dict[str, List[CatalogProduct]]:
        """Group products based on configuration.

        Returns:
            Dictionary mapping group names to product lists
        """
        if not self.config.group_by or not self._products:
            return {"": self._products}

        groups: Dict[str, List[CatalogProduct]] = {}

        for product in self._products:
            if self.config.group_by == "category":
                group_name = product.category or "Uncategorized"
            elif self.config.group_by == "brand":
                group_name = product.brand or "Other Brands"
            elif self.config.group_by == "family":
                group_name = product.family or "Other Products"
            else:
                group_name = ""

            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(product)

        return dict(sorted(groups.items()))

    def generate_pdf(
        self,
        output_path: Optional[str] = None,
        save_file: bool = False
    ) -> CatalogResult:
        """Generate the PDF catalog.

        Args:
            output_path: Path to save the PDF file
            save_file: Whether to save as Frappe File document

        Returns:
            CatalogResult with generation status and file path
        """
        import time

        start_time = time.time()
        catalog_id = str(uuid.uuid4())[:8]
        errors = []
        warnings = []

        if not self._products:
            return CatalogResult(
                success=False,
                catalog_id=catalog_id,
                status=CatalogStatus.FAILED,
                errors=["No products loaded for catalog generation"]
            )

        try:
            # Generate HTML content
            html_content = self._generate_html()

            # Convert HTML to PDF
            pdf_content, page_count = self._html_to_pdf(html_content)

            if not pdf_content:
                return CatalogResult(
                    success=False,
                    catalog_id=catalog_id,
                    status=CatalogStatus.FAILED,
                    errors=["Failed to generate PDF content"]
                )

            file_path = None
            file_url = None

            # Save to file if requested
            if save_file:
                file_url = self._save_pdf_file(pdf_content, catalog_id)
                file_path = file_url
            elif output_path:
                with open(output_path, "wb") as f:
                    f.write(pdf_content)
                file_path = output_path

            generation_time = time.time() - start_time

            return CatalogResult(
                success=True,
                catalog_id=catalog_id,
                status=CatalogStatus.COMPLETED,
                file_path=file_path,
                file_url=file_url,
                page_count=page_count,
                product_count=len(self._products),
                file_size_bytes=len(pdf_content),
                warnings=warnings,
                generation_time_seconds=generation_time,
            )

        except Exception as e:
            return CatalogResult(
                success=False,
                catalog_id=catalog_id,
                status=CatalogStatus.FAILED,
                errors=[f"Catalog generation failed: {str(e)}"],
                generation_time_seconds=time.time() - start_time,
            )

    def _generate_html(self) -> str:
        """Generate HTML content for the catalog.

        Returns:
            HTML string ready for PDF conversion
        """
        import frappe

        # Check for custom print format
        if self.config.print_format:
            return self._generate_from_print_format()

        # Generate default HTML template
        html_parts = []

        # Add document header with styles
        html_parts.append(self._get_html_header())

        # Add cover page
        if self.config.include_cover:
            html_parts.append(self._generate_cover_page())

        # Add table of contents
        if self.config.include_toc and self.config.group_by:
            html_parts.append(self._generate_toc())

        # Add product pages
        grouped_products = self._group_products()
        for group_name, products in grouped_products.items():
            if group_name and self.config.group_by:
                html_parts.append(self._generate_group_header(group_name))

            html_parts.append(self._generate_product_pages(products))

        # Close document
        html_parts.append(self._get_html_footer())

        return "\n".join(html_parts)

    def _generate_from_print_format(self) -> str:
        """Generate HTML using a custom Frappe Print Format.

        Returns:
            HTML string from print format
        """
        import frappe

        # Create context for print format
        context = {
            "config": self.config.to_dict(),
            "products": [p.to_dict() for p in self._products],
            "grouped_products": {
                k: [p.to_dict() for p in v]
                for k, v in self._group_products().items()
            },
            "generation_date": datetime.now().strftime("%Y-%m-%d"),
            "product_count": len(self._products),
        }

        try:
            # Get the print format
            print_format = frappe.get_doc("Print Format", self.config.print_format)

            # Render the template
            from frappe.utils.jinja import get_jinja_env

            env = get_jinja_env()
            template = env.from_string(print_format.html or "")
            html = template.render(context)

            return html

        except Exception as e:
            # Fall back to default template
            return self._generate_html()

    def _get_html_header(self) -> str:
        """Get HTML document header with styles."""
        page_size = self.config.page_size.value
        orientation = self.config.orientation.value.lower()
        margin = self.config.margin_mm

        custom_css = self.config.custom_css or ""

        return f"""
<!DOCTYPE html>
<html lang="{self.config.language}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self.config.title}</title>
    <style>
        @page {{
            size: {page_size} {orientation};
            margin: {margin}mm;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            font-size: 10pt;
            line-height: 1.4;
            color: #333;
        }}

        .page {{
            page-break-after: always;
            min-height: 100vh;
            position: relative;
        }}

        .page:last-child {{
            page-break-after: avoid;
        }}

        /* Cover Page */
        .cover-page {{
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            padding: 40mm 20mm;
        }}

        .cover-title {{
            font-size: 36pt;
            font-weight: bold;
            color: #1a1a1a;
            margin-bottom: 10mm;
        }}

        .cover-subtitle {{
            font-size: 18pt;
            color: #666;
            margin-bottom: 30mm;
        }}

        .cover-meta {{
            font-size: 12pt;
            color: #999;
        }}

        /* Table of Contents */
        .toc {{
            padding: 20mm 10mm;
        }}

        .toc-title {{
            font-size: 24pt;
            font-weight: bold;
            margin-bottom: 10mm;
            border-bottom: 2px solid #333;
            padding-bottom: 5mm;
        }}

        .toc-item {{
            display: flex;
            justify-content: space-between;
            padding: 2mm 0;
            border-bottom: 1px dotted #ccc;
        }}

        /* Group Header */
        .group-header {{
            font-size: 20pt;
            font-weight: bold;
            color: #1a1a1a;
            padding: 10mm 0 5mm 0;
            border-bottom: 2px solid #333;
            margin-bottom: 10mm;
            page-break-after: avoid;
        }}

        /* Product Grid Layout */
        .product-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10mm;
            padding: 5mm 0;
        }}

        .product-card {{
            border: 1px solid #e0e0e0;
            border-radius: 3mm;
            padding: 5mm;
            background: #fff;
            page-break-inside: avoid;
        }}

        .product-image {{
            width: 100%;
            height: 40mm;
            object-fit: contain;
            background: #f9f9f9;
            border-radius: 2mm;
            margin-bottom: 3mm;
        }}

        .product-title {{
            font-size: 12pt;
            font-weight: bold;
            margin-bottom: 2mm;
            color: #1a1a1a;
        }}

        .product-code {{
            font-size: 9pt;
            color: #666;
            margin-bottom: 2mm;
        }}

        .product-description {{
            font-size: 9pt;
            color: #444;
            margin-bottom: 3mm;
            max-height: 15mm;
            overflow: hidden;
        }}

        .product-price {{
            font-size: 14pt;
            font-weight: bold;
            color: #2563eb;
        }}

        .product-barcode {{
            font-size: 8pt;
            color: #666;
            font-family: monospace;
        }}

        /* Product List Layout */
        .product-list {{
            width: 100%;
        }}

        .product-list-item {{
            display: flex;
            align-items: center;
            padding: 3mm 0;
            border-bottom: 1px solid #e0e0e0;
            page-break-inside: avoid;
        }}

        .product-list-image {{
            width: 20mm;
            height: 20mm;
            object-fit: contain;
            margin-right: 5mm;
            background: #f9f9f9;
        }}

        .product-list-info {{
            flex: 1;
        }}

        .product-list-price {{
            text-align: right;
            font-weight: bold;
            min-width: 25mm;
        }}

        /* Detailed Layout */
        .product-detailed {{
            padding: 10mm;
            page-break-inside: avoid;
        }}

        .product-detailed-header {{
            display: flex;
            margin-bottom: 10mm;
        }}

        .product-detailed-image {{
            width: 80mm;
            height: 80mm;
            object-fit: contain;
            background: #f9f9f9;
            border-radius: 3mm;
            margin-right: 10mm;
        }}

        .product-detailed-info {{
            flex: 1;
        }}

        .product-detailed-title {{
            font-size: 18pt;
            font-weight: bold;
            margin-bottom: 5mm;
        }}

        .product-detailed-code {{
            font-size: 11pt;
            color: #666;
            margin-bottom: 5mm;
        }}

        .product-detailed-price {{
            font-size: 20pt;
            font-weight: bold;
            color: #2563eb;
            margin-bottom: 5mm;
        }}

        .product-detailed-description {{
            font-size: 10pt;
            line-height: 1.6;
            margin-bottom: 10mm;
        }}

        /* Specifications Table */
        .specs-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 9pt;
        }}

        .specs-table th,
        .specs-table td {{
            padding: 2mm 3mm;
            text-align: left;
            border-bottom: 1px solid #e0e0e0;
        }}

        .specs-table th {{
            background: #f5f5f5;
            font-weight: 600;
            width: 35%;
        }}

        /* Price List Layout */
        .price-list-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 9pt;
        }}

        .price-list-table th {{
            background: #333;
            color: #fff;
            padding: 3mm;
            text-align: left;
        }}

        .price-list-table td {{
            padding: 2mm 3mm;
            border-bottom: 1px solid #e0e0e0;
        }}

        .price-list-table tr:nth-child(even) {{
            background: #f9f9f9;
        }}

        /* Header/Footer */
        .page-header {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            padding: 3mm 0;
            font-size: 8pt;
            color: #999;
            border-bottom: 1px solid #e0e0e0;
        }}

        .page-footer {{
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 3mm 0;
            font-size: 8pt;
            color: #999;
            border-top: 1px solid #e0e0e0;
            text-align: center;
        }}

        /* Custom CSS */
        {custom_css}
    </style>
</head>
<body>
"""

    def _get_html_footer(self) -> str:
        """Get HTML document footer."""
        return """
</body>
</html>
"""

    def _generate_cover_page(self) -> str:
        """Generate cover page HTML."""
        subtitle = f'<div class="cover-subtitle">{self.config.subtitle}</div>' if self.config.subtitle else ""
        date_str = datetime.now().strftime("%B %Y")

        return f"""
<div class="page cover-page">
    <div class="cover-title">{self.config.title}</div>
    {subtitle}
    <div class="cover-meta">
        {len(self._products)} Products | {date_str}
    </div>
</div>
"""

    def _generate_toc(self) -> str:
        """Generate table of contents HTML."""
        grouped = self._group_products()

        toc_items = []
        for group_name, products in grouped.items():
            if group_name:
                toc_items.append(
                    f'<div class="toc-item">'
                    f'<span>{group_name}</span>'
                    f'<span>{len(products)} products</span>'
                    f'</div>'
                )

        return f"""
<div class="page toc">
    <div class="toc-title">Contents</div>
    {"".join(toc_items)}
</div>
"""

    def _generate_group_header(self, group_name: str) -> str:
        """Generate group header HTML."""
        return f"""
<div class="group-header">{group_name}</div>
"""

    def _generate_product_pages(self, products: List[CatalogProduct]) -> str:
        """Generate product pages based on layout.

        Args:
            products: List of products to render

        Returns:
            HTML string for product pages
        """
        layout = self.config.layout

        if layout == CatalogLayout.GRID:
            return self._generate_grid_layout(products)
        elif layout == CatalogLayout.LIST:
            return self._generate_list_layout(products)
        elif layout == CatalogLayout.DETAILED:
            return self._generate_detailed_layout(products)
        elif layout == CatalogLayout.GALLERY:
            return self._generate_gallery_layout(products)
        elif layout == CatalogLayout.PRICE_LIST:
            return self._generate_price_list_layout(products)
        elif layout == CatalogLayout.SPEC_SHEET:
            return self._generate_spec_sheet_layout(products)
        else:
            return self._generate_grid_layout(products)

    def _generate_grid_layout(self, products: List[CatalogProduct]) -> str:
        """Generate grid layout HTML."""
        cards = []

        for product in products:
            image_html = ""
            if self.config.include_images and product.image_url:
                image_html = f'<img class="product-image" src="{product.image_url}" alt="{product.title}">'

            desc_html = ""
            if self.config.include_descriptions and product.short_description:
                desc_html = f'<div class="product-description">{product.short_description}</div>'

            price_html = ""
            if self.config.include_prices and product.price:
                price_html = f'<div class="product-price">{product.currency} {product.price:.2f}</div>'

            barcode_html = ""
            if self.config.include_barcodes and product.barcode:
                barcode_html = f'<div class="product-barcode">{product.barcode}</div>'

            cards.append(f"""
<div class="product-card">
    {image_html}
    <div class="product-title">{product.title}</div>
    <div class="product-code">{product.code}</div>
    {desc_html}
    {price_html}
    {barcode_html}
</div>
""")

        return f"""
<div class="product-grid">
    {"".join(cards)}
</div>
"""

    def _generate_list_layout(self, products: List[CatalogProduct]) -> str:
        """Generate list layout HTML."""
        rows = []

        for product in products:
            image_html = ""
            if self.config.include_images and product.image_url:
                image_html = f'<img class="product-list-image" src="{product.image_url}" alt="{product.title}">'

            price_html = ""
            if self.config.include_prices and product.price:
                price_html = f'{product.currency} {product.price:.2f}'

            rows.append(f"""
<div class="product-list-item">
    {image_html}
    <div class="product-list-info">
        <div class="product-title">{product.title}</div>
        <div class="product-code">{product.code}</div>
    </div>
    <div class="product-list-price">{price_html}</div>
</div>
""")

        return f"""
<div class="product-list">
    {"".join(rows)}
</div>
"""

    def _generate_detailed_layout(self, products: List[CatalogProduct]) -> str:
        """Generate detailed layout HTML (one product per page)."""
        pages = []

        for product in products:
            image_html = ""
            if self.config.include_images and product.image_url:
                image_html = f'<img class="product-detailed-image" src="{product.image_url}" alt="{product.title}">'

            price_html = ""
            if self.config.include_prices and product.price:
                price_html = f'<div class="product-detailed-price">{product.currency} {product.price:.2f}</div>'

            desc_html = ""
            if self.config.include_descriptions and product.description:
                desc_html = f'<div class="product-detailed-description">{product.description}</div>'

            specs_html = ""
            if self.config.include_specifications and product.specifications:
                spec_rows = "".join([
                    f'<tr><th>{k}</th><td>{v}</td></tr>'
                    for k, v in product.specifications.items()
                ])
                specs_html = f"""
<table class="specs-table">
    <thead><tr><th colspan="2">Specifications</th></tr></thead>
    <tbody>{spec_rows}</tbody>
</table>
"""

            pages.append(f"""
<div class="page product-detailed">
    <div class="product-detailed-header">
        {image_html}
        <div class="product-detailed-info">
            <div class="product-detailed-title">{product.title}</div>
            <div class="product-detailed-code">SKU: {product.code}</div>
            {price_html}
        </div>
    </div>
    {desc_html}
    {specs_html}
</div>
""")

        return "".join(pages)

    def _generate_gallery_layout(self, products: List[CatalogProduct]) -> str:
        """Generate gallery layout HTML (image-focused)."""
        # Similar to grid but with larger images
        cards = []

        for product in products:
            image_html = ""
            if self.config.include_images and product.image_url:
                image_html = f'<img class="product-image" style="height: 60mm;" src="{product.image_url}" alt="{product.title}">'

            price_html = ""
            if self.config.include_prices and product.price:
                price_html = f'<div class="product-price">{product.currency} {product.price:.2f}</div>'

            cards.append(f"""
<div class="product-card" style="text-align: center;">
    {image_html}
    <div class="product-title">{product.title}</div>
    {price_html}
</div>
""")

        return f"""
<div class="product-grid">
    {"".join(cards)}
</div>
"""

    def _generate_price_list_layout(self, products: List[CatalogProduct]) -> str:
        """Generate price list layout HTML (compact tabular)."""
        rows = []

        for product in products:
            price_display = f"{product.currency} {product.price:.2f}" if product.price else "-"
            brand_display = product.brand or "-"

            rows.append(f"""
<tr>
    <td>{product.code}</td>
    <td>{product.title}</td>
    <td>{brand_display}</td>
    <td style="text-align: right;">{price_display}</td>
</tr>
""")

        return f"""
<table class="price-list-table">
    <thead>
        <tr>
            <th>Code</th>
            <th>Product</th>
            <th>Brand</th>
            <th style="text-align: right;">Price</th>
        </tr>
    </thead>
    <tbody>
        {"".join(rows)}
    </tbody>
</table>
"""

    def _generate_spec_sheet_layout(self, products: List[CatalogProduct]) -> str:
        """Generate specification sheet layout HTML."""
        # Similar to detailed but with emphasis on specs
        return self._generate_detailed_layout(products)

    def _html_to_pdf(self, html_content: str) -> Tuple[bytes, int]:
        """Convert HTML to PDF using Frappe's PDF generation.

        Args:
            html_content: HTML string to convert

        Returns:
            Tuple of (PDF bytes, page count)
        """
        import frappe
        from frappe.utils.pdf import get_pdf

        try:
            # Use Frappe's PDF generation (uses wkhtmltopdf or weasyprint)
            pdf_content = get_pdf(html_content)

            # Estimate page count (rough approximation)
            # A more accurate count would require parsing the PDF
            page_count = max(1, len(self._products) // (
                self.config.products_per_page or
                PRODUCTS_PER_PAGE.get(self.config.layout, 6)
            ))

            if self.config.include_cover:
                page_count += 1
            if self.config.include_toc and self.config.group_by:
                page_count += 1

            return pdf_content, page_count

        except Exception as e:
            # Log error and return empty result
            frappe.log_error(
                message=f"PDF generation failed: {str(e)}",
                title="Print Catalog Error"
            )
            return b"", 0

    def _save_pdf_file(self, pdf_content: bytes, catalog_id: str) -> str:
        """Save PDF content as Frappe File.

        Args:
            pdf_content: PDF bytes
            catalog_id: Catalog identifier for filename

        Returns:
            File URL
        """
        import frappe

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"catalog_{catalog_id}_{timestamp}.pdf"

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
            # Folder might not exist
            file_doc.folder = "Home"
            file_doc.insert(ignore_permissions=True)
            frappe.db.commit()

        return file_doc.file_url

    def _clean_html(self, html_text: Optional[str]) -> str:
        """Remove HTML tags from text.

        Args:
            html_text: Text possibly containing HTML

        Returns:
            Clean text without HTML tags
        """
        if not html_text:
            return ""

        import re
        clean = re.sub(r'<[^>]+>', '', str(html_text))
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    def _get_full_url(self, file_path: Optional[str]) -> str:
        """Convert file path to full URL.

        Args:
            file_path: Relative file path

        Returns:
            Full URL to file
        """
        import frappe

        if not file_path:
            return ""

        if file_path.startswith(("http://", "https://")):
            return file_path

        try:
            site_url = frappe.utils.get_url()
        except Exception:
            site_url = ""

        if not file_path.startswith("/"):
            file_path = "/" + file_path

        return f"{site_url}{file_path}"


# =============================================================================
# Public API Functions
# =============================================================================

def generate_catalog(
    profile_name: Optional[str] = None,
    products: Optional[List[str]] = None,
    title: str = "Product Catalog",
    layout: str = "grid",
    page_size: str = "A4",
    orientation: str = "Portrait",
    language: str = "en",
    currency: str = "EUR",
    include_cover: bool = True,
    include_toc: bool = True,
    include_prices: bool = True,
    include_images: bool = True,
    group_by: Optional[str] = None,
    sort_by: str = "name_asc",
    save_file: bool = False,
    async_generate: bool = False
) -> Dict[str, Any]:
    """Generate a print catalog PDF.

    This is the main API function for generating product catalogs.

    Args:
        profile_name: Export profile name to load settings from
        products: List of product names to include
        title: Catalog title
        layout: Layout style (grid, list, detailed, gallery, price_list, spec_sheet)
        page_size: Page size (A4, A3, A5, Letter, Legal, Tabloid)
        orientation: Page orientation (Portrait, Landscape)
        language: Language code for content
        currency: Currency code for prices
        include_cover: Include cover page
        include_toc: Include table of contents
        include_prices: Show prices
        include_images: Include product images
        group_by: Group products by (category, brand, family)
        sort_by: Sort order for products
        save_file: Save PDF as Frappe File
        async_generate: Generate in background job

    Returns:
        Dictionary with generation result
    """
    import frappe

    if async_generate:
        job = frappe.enqueue(
            "frappe_pim.pim.services.print_catalog._generate_catalog_job",
            queue="long",
            timeout=3600,
            profile_name=profile_name,
            products=products,
            title=title,
            layout=layout,
            page_size=page_size,
            orientation=orientation,
            language=language,
            currency=currency,
            include_cover=include_cover,
            include_toc=include_toc,
            include_prices=include_prices,
            include_images=include_images,
            group_by=group_by,
            sort_by=sort_by,
            save_file=True
        )
        return {
            "success": True,
            "job_id": job.id if hasattr(job, "id") else str(job),
            "status": "queued"
        }

    # Load config from profile or create from parameters
    config = _load_profile_config(profile_name) if profile_name else CatalogConfig(
        title=title,
        layout=CatalogLayout(layout),
        page_size=PageSize(page_size),
        orientation=PageOrientation(orientation),
        language=language,
        currency=currency,
        include_cover=include_cover,
        include_toc=include_toc,
        include_prices=include_prices,
        include_images=include_images,
        group_by=group_by,
        sort_by=SortOrder(sort_by),
    )

    # Create service and load products
    service = PrintCatalogService(config)

    if products:
        service.load_products(product_names=products)
    else:
        # Load all products with optional profile filters
        filters = _get_profile_filters(profile_name) if profile_name else {}
        service.load_products(filters=filters)

    # Generate PDF
    result = service.generate_pdf(save_file=save_file)

    return result.to_dict()


def generate_catalog_async(profile_name: str, callback: Optional[str] = None) -> str:
    """Queue catalog generation as background job.

    Args:
        profile_name: Export profile name
        callback: Optional callback function name

    Returns:
        Background job ID
    """
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.services.print_catalog.generate_catalog",
        queue="long",
        timeout=3600,
        profile_name=profile_name,
        save_file=True
    )

    return job.id if hasattr(job, "id") else str(job)


def get_catalog_layouts() -> List[Dict[str, str]]:
    """Get available catalog layout options.

    Returns:
        List of layout dictionaries with name and description
    """
    return [
        {"value": "grid", "label": "Grid", "description": "Multiple products per page in grid format"},
        {"value": "list", "label": "List", "description": "Compact list with one product per row"},
        {"value": "detailed", "label": "Detailed", "description": "One product per page with full details"},
        {"value": "gallery", "label": "Gallery", "description": "Image-focused layout"},
        {"value": "price_list", "label": "Price List", "description": "Compact tabular price list"},
        {"value": "spec_sheet", "label": "Spec Sheet", "description": "Technical specification focus"},
    ]


def get_page_sizes() -> List[Dict[str, str]]:
    """Get available page size options.

    Returns:
        List of page size dictionaries
    """
    return [
        {"value": "A4", "label": "A4 (210mm x 297mm)"},
        {"value": "A3", "label": "A3 (297mm x 420mm)"},
        {"value": "A5", "label": "A5 (148mm x 210mm)"},
        {"value": "Letter", "label": "Letter (8.5\" x 11\")"},
        {"value": "Legal", "label": "Legal (8.5\" x 14\")"},
        {"value": "Tabloid", "label": "Tabloid (11\" x 17\")"},
    ]


def get_sort_options() -> List[Dict[str, str]]:
    """Get available sort order options.

    Returns:
        List of sort option dictionaries
    """
    return [
        {"value": "name_asc", "label": "Name (A-Z)"},
        {"value": "name_desc", "label": "Name (Z-A)"},
        {"value": "code_asc", "label": "Product Code (A-Z)"},
        {"value": "code_desc", "label": "Product Code (Z-A)"},
        {"value": "price_asc", "label": "Price (Low to High)"},
        {"value": "price_desc", "label": "Price (High to Low)"},
        {"value": "category", "label": "Category"},
        {"value": "brand", "label": "Brand"},
        {"value": "family", "label": "Product Family"},
        {"value": "modified_desc", "label": "Recently Modified"},
    ]


def preview_catalog(
    products: List[str],
    layout: str = "grid",
    limit: int = 4
) -> str:
    """Generate HTML preview of catalog layout.

    Args:
        products: List of product names
        layout: Layout style
        limit: Max products to show in preview

    Returns:
        HTML preview string
    """
    config = CatalogConfig(
        layout=CatalogLayout(layout),
        include_cover=False,
        include_toc=False,
    )

    service = PrintCatalogService(config)
    service.load_products(product_names=products[:limit])

    return service._generate_html()


# =============================================================================
# Helper Functions (Private)
# =============================================================================

def _load_profile_config(profile_name: str) -> CatalogConfig:
    """Load catalog configuration from Export Profile.

    Args:
        profile_name: Export Profile document name

    Returns:
        CatalogConfig instance
    """
    import frappe

    try:
        profile = frappe.get_doc("Export Profile", profile_name)
    except Exception:
        return CatalogConfig()

    # Map profile fields to config
    layout = CatalogLayout.GRID
    try:
        layout = CatalogLayout(profile.get("catalog_layout", "grid"))
    except ValueError:
        pass

    page_size = PageSize.A4
    try:
        page_size = PageSize(profile.get("page_size", "A4"))
    except ValueError:
        pass

    orientation = PageOrientation.PORTRAIT
    try:
        orientation = PageOrientation(profile.get("page_orientation", "Portrait"))
    except ValueError:
        pass

    sort_by = SortOrder.NAME_ASC
    try:
        sort_by = SortOrder(profile.get("sort_order", "name_asc"))
    except ValueError:
        pass

    return CatalogConfig(
        title=profile.get("catalog_title") or "Product Catalog",
        subtitle=profile.get("catalog_subtitle"),
        layout=layout,
        page_size=page_size,
        orientation=orientation,
        language=profile.get("export_language") or "en",
        currency=profile.get("export_currency") or "EUR",
        include_cover=profile.get("include_cover_page", True),
        include_toc=profile.get("include_toc", True),
        include_prices=profile.get("include_prices", True),
        include_descriptions=profile.get("include_descriptions", True),
        include_specifications=profile.get("include_specifications", True),
        include_images=profile.get("include_images", True),
        include_barcodes=profile.get("include_barcodes", False),
        group_by=profile.get("group_products_by"),
        sort_by=sort_by,
        products_per_page=profile.get("products_per_page"),
        image_quality=profile.get("image_quality") or 85,
        margin_mm=profile.get("page_margin_mm") or 15,
        header_text=profile.get("header_text"),
        footer_text=profile.get("footer_text"),
        custom_css=profile.get("custom_css"),
        print_format=profile.get("print_format"),
    )


def _get_profile_filters(profile_name: str) -> Dict[str, Any]:
    """Get product filters from Export Profile.

    Args:
        profile_name: Export Profile document name

    Returns:
        Filter dictionary for product query
    """
    import frappe

    try:
        profile = frappe.get_doc("Export Profile", profile_name)
    except Exception:
        return {}

    filters = {}

    if profile.get("product_family"):
        filters["product_family"] = profile.product_family

    if profile.get("status_filter"):
        filters["status"] = profile.status_filter

    return filters


def _generate_catalog_job(
    profile_name: Optional[str] = None,
    products: Optional[List[str]] = None,
    title: str = "Product Catalog",
    layout: str = "grid",
    page_size: str = "A4",
    orientation: str = "Portrait",
    language: str = "en",
    currency: str = "EUR",
    include_cover: bool = True,
    include_toc: bool = True,
    include_prices: bool = True,
    include_images: bool = True,
    group_by: Optional[str] = None,
    sort_by: str = "name_asc",
    save_file: bool = True
):
    """Background job for catalog generation.

    Args:
        Same as generate_catalog
    """
    import frappe

    try:
        result = generate_catalog(
            profile_name=profile_name,
            products=products,
            title=title,
            layout=layout,
            page_size=page_size,
            orientation=orientation,
            language=language,
            currency=currency,
            include_cover=include_cover,
            include_toc=include_toc,
            include_prices=include_prices,
            include_images=include_images,
            group_by=group_by,
            sort_by=sort_by,
            save_file=save_file,
            async_generate=False
        )

        # Log result
        if result.get("success"):
            frappe.publish_realtime(
                event="catalog_generated",
                message={
                    "catalog_id": result.get("catalog_id"),
                    "file_url": result.get("file_url"),
                    "product_count": result.get("product_count"),
                },
                user=frappe.session.user
            )

    except Exception as e:
        frappe.log_error(
            message=f"Catalog generation job failed: {str(e)}",
            title="Print Catalog Job Error"
        )


# =============================================================================
# Frappe API Wrappers
# =============================================================================

def _wrap_for_whitelist():
    """Wrap functions for Frappe whitelist at runtime."""
    import frappe

    functions = [
        "generate_catalog",
        "generate_catalog_async",
        "get_catalog_layouts",
        "get_page_sizes",
        "get_sort_options",
        "preview_catalog",
    ]

    module = __import__(__name__)
    for name in __name__.split('.')[1:]:
        module = getattr(module, name)

    for func_name in functions:
        func = getattr(module, func_name)
        if not getattr(func, "_whitelisted", False):
            whitelisted = frappe.whitelist()(func)
            setattr(module, func_name, whitelisted)


# Apply whitelist decorators when module is loaded in Frappe context
try:
    _wrap_for_whitelist()
except Exception:
    pass  # Not in Frappe context
