"""BMEcat 2005 XML Export Module

This module provides functionality for generating BMEcat 2005 compliant
XML product catalogs. BMEcat is a German standard for electronic product
data exchange, widely used in B2B e-commerce.

The module supports:
- BMEcat 2005 full catalog export (T_NEW_CATALOG transaction)
- Product variants with attributes
- Multi-language descriptions
- Media/image references
- Pricing information
- Feature/attribute mapping

Usage:
    from frappe_pim.pim.export.bmecat import export_catalog

    xml_content = export_catalog(
        profile_name="my_bmecat_profile",
        save_file=True
    )

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from datetime import datetime


# BMEcat 2005 namespace
BMECAT_NS = "http://www.bmecat.org/bmecat/2005"
BMECAT_NSMAP = {
    None: BMECAT_NS,
    "xsi": "http://www.w3.org/2001/XMLSchema-instance"
}


def export_catalog(
    profile_name=None,
    products=None,
    supplier_id=None,
    supplier_name=None,
    catalog_id=None,
    catalog_version=None,
    language="deu",
    territory="DE",
    currency="EUR",
    include_prices=True,
    include_media=True,
    include_variants=True,
    pretty_print=True,
    save_file=False
):
    """Generate BMEcat 2005 XML catalog.

    This function creates a BMEcat 2005 compliant XML document containing
    product information. It can either use an Export Profile configuration
    or accept parameters directly.

    Args:
        profile_name: Name of Export Profile DocType to use for settings
        products: List of Product Master/Variant names to export (optional)
        supplier_id: SUPPLIER_ID element value
        supplier_name: SUPPLIER_NAME element value
        catalog_id: CATALOG_ID element value
        catalog_version: CATALOG_VERSION element value
        language: ISO 639 language code (default: deu for German)
        territory: ISO 3166 territory code (default: DE)
        currency: ISO 4217 currency code (default: EUR)
        include_prices: Include pricing information
        include_media: Include media/image references
        include_variants: Include product variants
        pretty_print: Format XML with indentation
        save_file: Save to file and return file path

    Returns:
        str: XML content as string, or file path if save_file=True

    Raises:
        ValueError: If required parameters are missing

    Example:
        >>> xml = export_catalog(
        ...     profile_name="standard_bmecat",
        ...     save_file=True
        ... )
        >>> print(xml)  # Returns file path
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for BMEcat export. "
            "Install with: pip install lxml"
        )

    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    # Override config with explicit parameters
    supplier_id = supplier_id or config.get("supplier_id", "SUPPLIER001")
    supplier_name = supplier_name or config.get("supplier_name", "Default Supplier")
    catalog_id = catalog_id or config.get("catalog_id", "CATALOG001")
    catalog_version = catalog_version or config.get("catalog_version", "1.0")
    language = config.get("language", language)
    currency = config.get("currency", currency)
    include_prices = config.get("include_prices", include_prices)
    include_media = config.get("include_media", include_media)
    include_variants = config.get("include_variants", include_variants)
    pretty_print = config.get("pretty_print", pretty_print)

    # Get products to export
    if products is None:
        products = _get_products_for_export(config)

    # Build XML document
    root = _build_bmecat_document(
        products=products,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        catalog_id=catalog_id,
        catalog_version=catalog_version,
        language=language,
        territory=territory,
        currency=currency,
        include_prices=include_prices,
        include_media=include_media,
        include_variants=include_variants
    )

    # Serialize to XML string
    xml_content = etree.tostring(
        root,
        encoding="unicode",
        pretty_print=pretty_print,
        xml_declaration=True
    )

    # Prepend XML declaration with encoding if not present
    if not xml_content.startswith("<?xml"):
        xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_content

    # Save to file if requested
    if save_file:
        return _save_export_file(
            xml_content,
            profile_name=profile_name,
            catalog_id=catalog_id
        )

    return xml_content


def export_catalog_async(profile_name, callback=None):
    """Queue catalog export as background job.

    For large catalogs, this function queues the export as a background
    job to avoid timeout issues.

    Args:
        profile_name: Name of Export Profile DocType
        callback: Optional callback function name to call on completion

    Returns:
        str: Background job ID
    """
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.export.bmecat.export_catalog",
        queue="long",
        timeout=3600,
        profile_name=profile_name,
        save_file=True
    )

    return job.id if hasattr(job, 'id') else str(job)


def _load_profile_config(profile_name):
    """Load export configuration from Export Profile DocType.

    Args:
        profile_name: Name of Export Profile document

    Returns:
        dict: Configuration dictionary
    """
    import frappe

    if not profile_name:
        return {}

    try:
        profile = frappe.get_doc("Export Profile", profile_name)
    except Exception:
        return {}

    # Map profile fields to config
    config = {
        "supplier_id": profile.get("bmecat_supplier_id"),
        "supplier_name": profile.get("bmecat_supplier_name"),
        "catalog_id": profile.get("bmecat_catalog_id"),
        "catalog_version": profile.get("bmecat_catalog_version"),
        "include_prices": profile.get("include_prices", True),
        "include_media": profile.get("include_media", True),
        "include_variants": profile.get("include_variants", True),
        "pretty_print": profile.get("pretty_print", True),
        "product_family": profile.get("product_family"),
        "status_filter": profile.get("status_filter"),
        "completeness_threshold": profile.get("completeness_threshold", 0),
        "output_filename": profile.get("output_filename"),
    }

    # Get language from export_language link
    if profile.get("export_language"):
        config["language"] = _get_language_code(profile.export_language)

    # Get currency from export_currency link
    if profile.get("export_currency"):
        config["currency"] = profile.export_currency

    return config


def _get_language_code(language_name):
    """Convert Frappe language name to ISO 639 code.

    Args:
        language_name: Frappe Language document name

    Returns:
        str: ISO 639 language code (3-letter)
    """
    # Map common language names to ISO 639-2 codes
    language_map = {
        "en": "eng",
        "de": "deu",
        "fr": "fra",
        "es": "spa",
        "it": "ita",
        "nl": "nld",
        "pl": "pol",
        "tr": "tur",
        "ru": "rus",
        "zh": "zho",
        "ja": "jpn",
        "ko": "kor"
    }

    # Extract 2-letter code from language name
    code = language_name.lower()[:2] if language_name else "en"
    return language_map.get(code, "eng")


def _get_products_for_export(config):
    """Get list of products matching export filter criteria.

    Args:
        config: Export configuration dictionary

    Returns:
        list: List of product names to export
    """
    import frappe

    filters = {}

    if config.get("product_family"):
        filters["product_family"] = config["product_family"]

    if config.get("status_filter"):
        filters["status"] = config["status_filter"]

    # Get products that meet completeness threshold
    products = frappe.get_all(
        "Product Variant",
        filters=filters,
        fields=["name", "completeness_score"],
        order_by="modified desc"
    )

    # Filter by completeness threshold
    threshold = config.get("completeness_threshold", 0)
    if threshold > 0:
        products = [
            p for p in products
            if (p.get("completeness_score") or 0) >= threshold
        ]

    return [p["name"] for p in products]


def _build_bmecat_document(
    products,
    supplier_id,
    supplier_name,
    catalog_id,
    catalog_version,
    language,
    territory,
    currency,
    include_prices,
    include_media,
    include_variants
):
    """Build complete BMEcat XML document structure.

    Args:
        products: List of product names to include
        supplier_id: Supplier identifier
        supplier_name: Supplier display name
        catalog_id: Catalog identifier
        catalog_version: Catalog version string
        language: ISO 639 language code
        territory: ISO 3166 territory code
        currency: ISO 4217 currency code
        include_prices: Include price elements
        include_media: Include media elements
        include_variants: Include variant products

    Returns:
        etree.Element: Root BMECAT element
    """
    from lxml import etree

    # Create root element with namespace
    root = etree.Element(
        "BMECAT",
        nsmap=BMECAT_NSMAP,
        version="2005"
    )

    # Add schema location
    root.set(
        "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation",
        "http://www.bmecat.org/bmecat/2005 bmecat_2005.xsd"
    )

    # Build HEADER section
    header = _build_header(
        root,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        catalog_id=catalog_id,
        catalog_version=catalog_version,
        language=language,
        territory=territory,
        currency=currency
    )

    # Build T_NEW_CATALOG transaction
    t_new_catalog = etree.SubElement(root, "T_NEW_CATALOG")

    # Add articles
    for product_name in products:
        _add_article(
            t_new_catalog,
            product_name=product_name,
            language=language,
            currency=currency,
            include_prices=include_prices,
            include_media=include_media
        )

    return root


def _build_header(
    parent,
    supplier_id,
    supplier_name,
    catalog_id,
    catalog_version,
    language,
    territory,
    currency
):
    """Build HEADER section of BMEcat document.

    Args:
        parent: Parent XML element
        supplier_id: Supplier identifier
        supplier_name: Supplier display name
        catalog_id: Catalog identifier
        catalog_version: Catalog version string
        language: ISO 639 language code
        territory: ISO 3166 territory code
        currency: ISO 4217 currency code

    Returns:
        etree.Element: HEADER element
    """
    from lxml import etree

    header = etree.SubElement(parent, "HEADER")

    # Generator info
    generator = etree.SubElement(header, "GENERATOR_INFO")
    generator.text = "Frappe PIM BMEcat Exporter"

    # Catalog info
    catalog = etree.SubElement(header, "CATALOG")

    lang_elem = etree.SubElement(catalog, "LANGUAGE")
    lang_elem.text = language

    catalog_id_elem = etree.SubElement(catalog, "CATALOG_ID")
    catalog_id_elem.text = catalog_id

    catalog_version_elem = etree.SubElement(catalog, "CATALOG_VERSION")
    catalog_version_elem.text = catalog_version

    catalog_name = etree.SubElement(catalog, "CATALOG_NAME")
    catalog_name.text = f"Product Catalog {catalog_id}"

    gen_date = etree.SubElement(catalog, "GENERATION_DATE")
    gen_date.text = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    territory_elem = etree.SubElement(catalog, "TERRITORY")
    territory_elem.text = territory

    currency_elem = etree.SubElement(catalog, "CURRENCY")
    currency_elem.text = currency

    # Supplier info
    supplier = etree.SubElement(header, "SUPPLIER")

    supplier_id_elem = etree.SubElement(supplier, "SUPPLIER_ID")
    supplier_id_elem.text = supplier_id

    supplier_name_elem = etree.SubElement(supplier, "SUPPLIER_NAME")
    supplier_name_elem.text = supplier_name

    return header


def _add_article(
    parent,
    product_name,
    language,
    currency,
    include_prices,
    include_media
):
    """Add an ARTICLE element for a product.

    Args:
        parent: Parent XML element (T_NEW_CATALOG)
        product_name: Name of Product Variant to export
        language: ISO 639 language code
        currency: ISO 4217 currency code
        include_prices: Include price elements
        include_media: Include media elements

    Returns:
        etree.Element: ARTICLE element or None if product not found
    """
    import frappe
    from lxml import etree

    try:
        product = frappe.get_doc("Product Variant", product_name)
    except Exception:
        # Try Product Master if variant not found
        try:
            product = frappe.get_doc("Product Master", product_name)
        except Exception:
            return None

    article = etree.SubElement(parent, "ARTICLE")
    article.set("mode", "new")

    # Supplier article ID (SKU)
    supplier_aid = etree.SubElement(article, "SUPPLIER_AID")
    sku = product.get("variant_code") or product.get("product_code") or product.name
    supplier_aid.text = sku

    # Article details
    details = etree.SubElement(article, "ARTICLE_DETAILS")

    # Description short (required)
    desc_short = etree.SubElement(details, "DESCRIPTION_SHORT")
    desc_short.text = product.get("variant_name") or product.get("product_name") or sku

    # Description long
    desc_long_text = product.get("description") or product.get("short_description")
    if desc_long_text:
        desc_long = etree.SubElement(details, "DESCRIPTION_LONG")
        desc_long.text = _clean_html(desc_long_text)

    # EAN/GTIN
    barcode = product.get("barcode") or product.get("ean")
    if barcode:
        ean = etree.SubElement(details, "EAN")
        ean.text = barcode

    # Manufacturer article ID
    manufacturer_aid = product.get("manufacturer_part_number")
    if manufacturer_aid:
        man_aid = etree.SubElement(details, "MANUFACTURER_AID")
        man_aid.text = manufacturer_aid

    # Article features (attributes)
    _add_article_features(article, product, language)

    # Order details
    _add_order_details(article, product)

    # Price details
    if include_prices:
        _add_price_details(article, product, currency)

    # Media/images
    if include_media:
        _add_mime_info(article, product)

    return article


def _add_article_features(parent, product, language):
    """Add ARTICLE_FEATURES element with product attributes.

    Args:
        parent: Parent ARTICLE element
        product: Product document
        language: ISO 639 language code
    """
    import frappe
    from lxml import etree

    attribute_values = product.get("attribute_values") or []
    if not attribute_values:
        return

    features = etree.SubElement(parent, "ARTICLE_FEATURES")

    for attr_value in attribute_values:
        attr_code = attr_value.get("attribute")
        if not attr_code:
            continue

        # Get attribute metadata
        try:
            attr_meta = frappe.get_cached_value(
                "PIM Attribute",
                attr_code,
                ["attribute_name", "data_type", "unit"],
                as_dict=True
            )
        except Exception:
            attr_meta = {"attribute_name": attr_code}

        # Get value based on data type
        value = _get_attribute_value(attr_value)
        if value is None:
            continue

        feature = etree.SubElement(features, "FEATURE")

        # Feature name
        fname = etree.SubElement(feature, "FNAME")
        fname.text = attr_meta.get("attribute_name", attr_code)

        # Feature value
        fvalue = etree.SubElement(feature, "FVALUE")
        fvalue.text = str(value)

        # Unit (if applicable)
        unit = attr_meta.get("unit")
        if unit:
            funit = etree.SubElement(feature, "FUNIT")
            funit.text = unit


def _add_order_details(parent, product):
    """Add ARTICLE_ORDER_DETAILS element.

    Args:
        parent: Parent ARTICLE element
        product: Product document
    """
    from lxml import etree

    order_details = etree.SubElement(parent, "ARTICLE_ORDER_DETAILS")

    # Order unit (default: piece)
    order_unit = etree.SubElement(order_details, "ORDER_UNIT")
    order_unit.text = product.get("stock_uom") or "C62"  # C62 = piece in UN/CEFACT

    # Content unit
    content_unit = etree.SubElement(order_details, "CONTENT_UNIT")
    content_unit.text = product.get("stock_uom") or "C62"

    # Number of content units per order unit
    no_cu = etree.SubElement(order_details, "NO_CU_PER_OU")
    no_cu.text = "1"

    # Minimum order quantity
    min_qty = product.get("minimum_order_qty") or 1
    quantity_min = etree.SubElement(order_details, "QUANTITY_MIN")
    quantity_min.text = str(min_qty)


def _add_price_details(parent, product, currency):
    """Add ARTICLE_PRICE_DETAILS element.

    Args:
        parent: Parent ARTICLE element
        product: Product document
        currency: ISO 4217 currency code
    """
    from lxml import etree

    price_value = product.get("price") or product.get("standard_rate")
    if not price_value:
        return

    price_details = etree.SubElement(parent, "ARTICLE_PRICE_DETAILS")

    article_price = etree.SubElement(price_details, "ARTICLE_PRICE")
    article_price.set("price_type", "net_list")

    # Price amount
    price_amount = etree.SubElement(article_price, "PRICE_AMOUNT")
    price_amount.text = f"{float(price_value):.2f}"

    # Price currency
    price_currency = etree.SubElement(article_price, "PRICE_CURRENCY")
    price_currency.text = currency

    # Tax rate (if available)
    tax_rate = product.get("tax_rate")
    if tax_rate:
        tax = etree.SubElement(article_price, "TAX")
        tax.text = f"{float(tax_rate):.2f}"

    # Price factor (quantity)
    price_factor = etree.SubElement(article_price, "PRICE_FACTOR")
    price_factor.text = "1"

    # Lower bound (minimum quantity for this price)
    lower_bound = etree.SubElement(article_price, "LOWER_BOUND")
    lower_bound.text = "1"


def _add_mime_info(parent, product):
    """Add MIME_INFO element with media references.

    Args:
        parent: Parent ARTICLE element
        product: Product document
    """
    import frappe
    from lxml import etree

    # Collect all media URLs
    media_list = []

    # Primary image
    primary_image = product.get("image")
    if primary_image:
        media_list.append({
            "url": _get_full_url(primary_image),
            "type": "image/jpeg",
            "purpose": "normal"
        })

    # Additional media from child table
    additional_media = product.get("media") or []
    for media in additional_media:
        media_url = media.get("file_url") or media.get("url")
        if media_url:
            media_list.append({
                "url": _get_full_url(media_url),
                "type": _get_mime_type(media_url),
                "purpose": media.get("media_type", "normal").lower()
            })

    if not media_list:
        return

    mime_info = etree.SubElement(parent, "MIME_INFO")

    for idx, media in enumerate(media_list):
        mime = etree.SubElement(mime_info, "MIME")

        # MIME type
        mime_type = etree.SubElement(mime, "MIME_TYPE")
        mime_type.text = media["type"]

        # MIME source (URL)
        mime_source = etree.SubElement(mime, "MIME_SOURCE")
        mime_source.text = media["url"]

        # MIME purpose
        mime_purpose = etree.SubElement(mime, "MIME_PURPOSE")
        mime_purpose.text = media["purpose"]

        # Order (for primary images)
        if idx == 0:
            mime_order = etree.SubElement(mime, "MIME_ORDER")
            mime_order.text = "1"


def _get_attribute_value(attr_value):
    """Extract value from EAV attribute value row.

    Args:
        attr_value: Product Attribute Value row

    Returns:
        Value or None if no value set
    """
    # Check value columns in order of preference
    value_fields = [
        "value_text",
        "value_data",
        "value_int",
        "value_float",
        "value_date",
        "value_datetime",
        "value_link",
        "value_boolean"
    ]

    for field in value_fields:
        value = attr_value.get(field)
        if value is not None:
            if isinstance(value, bool):
                return "yes" if value else "no"
            if isinstance(value, str) and not value.strip():
                continue
            return value

    return None


def _clean_html(html_text):
    """Remove HTML tags from text.

    Args:
        html_text: Text possibly containing HTML

    Returns:
        str: Clean text without HTML tags
    """
    if not html_text:
        return ""

    import re
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', str(html_text))
    # Normalize whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _get_full_url(file_path):
    """Convert file path to full URL.

    Args:
        file_path: Relative file path

    Returns:
        str: Full URL to file
    """
    import frappe

    if not file_path:
        return ""

    # Already a full URL
    if file_path.startswith(("http://", "https://")):
        return file_path

    # Get site URL
    try:
        site_url = frappe.utils.get_url()
    except Exception:
        site_url = ""

    # Ensure path starts with /
    if not file_path.startswith("/"):
        file_path = "/" + file_path

    return f"{site_url}{file_path}"


def _get_mime_type(file_path):
    """Determine MIME type from file extension.

    Args:
        file_path: File path or URL

    Returns:
        str: MIME type string
    """
    if not file_path:
        return "application/octet-stream"

    ext = file_path.lower().split(".")[-1] if "." in file_path else ""

    mime_types = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
        "pdf": "application/pdf",
        "mp4": "video/mp4",
        "webm": "video/webm"
    }

    return mime_types.get(ext, "application/octet-stream")


def _save_export_file(content, profile_name=None, catalog_id=None):
    """Save export content to file.

    Args:
        content: XML content string
        profile_name: Export profile name (for filename)
        catalog_id: Catalog ID (for filename)

    Returns:
        str: File path of saved file
    """
    import frappe

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name_part = profile_name or catalog_id or "bmecat"
    filename = f"{name_part}_{timestamp}.xml"

    # Create file record
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": content,
        "is_private": 1,
        "folder": "Home/Exports"
    })

    try:
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        # Folder might not exist, try without folder
        file_doc.folder = "Home"
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()

    # Update Export Profile if name provided
    if profile_name:
        try:
            frappe.db.set_value(
                "Export Profile",
                profile_name,
                {
                    "last_export": datetime.now(),
                    "last_file": file_doc.file_url,
                    "export_status": "Completed"
                },
                update_modified=True
            )
            frappe.db.commit()
        except Exception:
            pass

    return file_doc.file_url


def validate_bmecat_xml(xml_content):
    """Validate BMEcat XML against schema.

    Args:
        xml_content: XML content string

    Returns:
        tuple: (is_valid, errors_list)
    """
    from lxml import etree

    try:
        # Parse the XML
        doc = etree.fromstring(xml_content.encode() if isinstance(xml_content, str) else xml_content)

        # Basic structure validation
        errors = []

        # Check root element
        if doc.tag != f"{{{BMECAT_NS}}}BMECAT" and doc.tag != "BMECAT":
            errors.append("Root element must be BMECAT")

        # Check for required HEADER
        header = doc.find(".//HEADER", namespaces={"": BMECAT_NS})
        if header is None:
            header = doc.find(".//HEADER")
        if header is None:
            errors.append("Missing required HEADER element")

        # Check for T_NEW_CATALOG
        catalog = doc.find(".//T_NEW_CATALOG", namespaces={"": BMECAT_NS})
        if catalog is None:
            catalog = doc.find(".//T_NEW_CATALOG")
        if catalog is None:
            errors.append("Missing T_NEW_CATALOG transaction element")

        return len(errors) == 0, errors

    except etree.XMLSyntaxError as e:
        return False, [f"XML Syntax Error: {str(e)}"]
    except Exception as e:
        return False, [f"Validation Error: {str(e)}"]


def get_article_count(xml_content):
    """Count number of articles in BMEcat XML.

    Args:
        xml_content: XML content string

    Returns:
        int: Number of ARTICLE elements
    """
    from lxml import etree

    try:
        doc = etree.fromstring(xml_content.encode() if isinstance(xml_content, str) else xml_content)
        articles = doc.findall(".//ARTICLE", namespaces={"": BMECAT_NS})
        if not articles:
            articles = doc.findall(".//ARTICLE")
        return len(articles)
    except Exception:
        return 0
