"""cXML Export Module with PunchOut Catalog Support

This module provides functionality for generating cXML (commerce XML) compliant
documents for B2B e-procurement. cXML is an XML-based protocol for business
document exchange, widely used in enterprise procurement systems.

The module supports:
- cXML Index catalogs for product data exchange
- PunchOut catalog setup (PunchOutSetupRequest/Response)
- PunchOut order messages (PunchOutOrderMessage)
- Product items with pricing, classifications, and attributes
- Multi-language descriptions
- Media/image references

Usage:
    from frappe_pim.pim.export.cxml import export_catalog, handle_punchout_setup

    # Export catalog as cXML Index
    xml_content = export_catalog(
        profile_name="my_cxml_profile",
        save_file=True
    )

    # Handle PunchOut setup request
    response = handle_punchout_setup(
        request_xml=incoming_request,
        profile_name="my_cxml_profile"
    )

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import hashlib
import uuid
from datetime import datetime


# cXML DTD version
CXML_VERSION = "1.2.050"
CXML_DTD_URL = "http://xml.cxml.org/schemas/cXML/1.2.050/cXML.dtd"

# Default UNSPSC classification domain
DEFAULT_CLASSIFICATION_DOMAIN = "UNSPSC"


def export_catalog(
    profile_name=None,
    products=None,
    supplier_id=None,
    supplier_name=None,
    buyer_id=None,
    catalog_id=None,
    currency="USD",
    language="en",
    include_prices=True,
    include_media=True,
    include_classifications=True,
    include_punchout_items=False,
    punchout_url=None,
    pretty_print=True,
    save_file=False
):
    """Generate cXML Index catalog document.

    This function creates a cXML compliant XML document containing
    product catalog information in Index format. It can either use an
    Export Profile configuration or accept parameters directly.

    Args:
        profile_name: Name of Export Profile DocType to use for settings
        products: List of Product Master/Variant names to export (optional)
        supplier_id: Supplier DUNS or identifier (From/Identity)
        supplier_name: Supplier display name
        buyer_id: Buyer DUNS or identifier (To/Identity)
        catalog_id: Catalog identifier for the Index
        currency: ISO 4217 currency code (default: USD)
        language: ISO 639 language code (default: en)
        include_prices: Include pricing information
        include_media: Include media/image references
        include_classifications: Include UNSPSC/custom classifications
        include_punchout_items: Generate IndexItemPunchout elements
        punchout_url: Base URL for PunchOut catalog browsing
        pretty_print: Format XML with indentation
        save_file: Save to file and return file path

    Returns:
        str: XML content as string, or file path if save_file=True

    Raises:
        ValueError: If required parameters are missing
        ImportError: If lxml is not installed

    Example:
        >>> xml = export_catalog(
        ...     profile_name="standard_cxml",
        ...     save_file=True
        ... )
        >>> print(xml)  # Returns file path
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for cXML export. "
            "Install with: pip install lxml"
        )

    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    # Override config with explicit parameters
    supplier_id = supplier_id or config.get("supplier_id", "SUPPLIER001")
    supplier_name = supplier_name or config.get("supplier_name", "Default Supplier")
    buyer_id = buyer_id or config.get("buyer_id", "BUYER001")
    catalog_id = catalog_id or config.get("catalog_id", "CATALOG001")
    currency = config.get("currency", currency)
    language = config.get("language", language)
    include_prices = config.get("include_prices", include_prices)
    include_media = config.get("include_media", include_media)
    include_classifications = config.get("include_classifications", include_classifications)
    include_punchout_items = config.get("include_punchout_items", include_punchout_items)
    punchout_url = punchout_url or config.get("punchout_url")
    pretty_print = config.get("pretty_print", pretty_print)

    # Get products to export
    if products is None:
        products = _get_products_for_export(config)

    # Build XML document
    root = _build_cxml_index(
        products=products,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        buyer_id=buyer_id,
        catalog_id=catalog_id,
        currency=currency,
        language=language,
        include_prices=include_prices,
        include_media=include_media,
        include_classifications=include_classifications,
        include_punchout_items=include_punchout_items,
        punchout_url=punchout_url
    )

    # Serialize to XML string
    xml_content = etree.tostring(
        root,
        encoding="unicode",
        pretty_print=pretty_print,
        xml_declaration=True
    )

    # Add DOCTYPE declaration for cXML
    if not xml_content.startswith("<?xml"):
        xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_content

    # Insert DOCTYPE after XML declaration
    xml_lines = xml_content.split("\n", 1)
    if len(xml_lines) == 2:
        doctype = f'<!DOCTYPE cXML SYSTEM "{CXML_DTD_URL}">'
        xml_content = f"{xml_lines[0]}\n{doctype}\n{xml_lines[1]}"

    # Save to file if requested
    if save_file:
        return _save_export_file(
            xml_content,
            profile_name=profile_name,
            catalog_id=catalog_id,
            file_prefix="cxml"
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
        "frappe_pim.pim.export.cxml.export_catalog",
        queue="long",
        timeout=3600,
        profile_name=profile_name,
        save_file=True
    )

    return job.id if hasattr(job, 'id') else str(job)


def handle_punchout_setup(
    request_xml,
    profile_name=None,
    supplier_id=None,
    supplier_name=None,
    punchout_url=None,
    shared_secret=None
):
    """Handle incoming PunchOutSetupRequest and generate response.

    This function processes a PunchOutSetupRequest from a buyer's
    procurement system and returns a PunchOutSetupResponse with
    the URL for catalog browsing.

    Args:
        request_xml: Incoming cXML request as string
        profile_name: Name of Export Profile DocType for settings
        supplier_id: Supplier DUNS or identifier
        supplier_name: Supplier display name
        punchout_url: URL to redirect buyer for catalog browsing
        shared_secret: Shared secret for authentication validation

    Returns:
        str: cXML PunchOutSetupResponse XML string

    Raises:
        ValueError: If request validation fails
        ImportError: If lxml is not installed

    Example:
        >>> response = handle_punchout_setup(
        ...     request_xml=incoming_request,
        ...     profile_name="my_punchout_profile"
        ... )
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for cXML PunchOut. "
            "Install with: pip install lxml"
        )

    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    supplier_id = supplier_id or config.get("supplier_id", "SUPPLIER001")
    supplier_name = supplier_name or config.get("supplier_name", "Default Supplier")
    punchout_url = punchout_url or config.get("punchout_url")
    shared_secret = shared_secret or config.get("shared_secret")

    # Parse incoming request
    try:
        request_doc = etree.fromstring(
            request_xml.encode() if isinstance(request_xml, str) else request_xml
        )
    except etree.XMLSyntaxError as e:
        return _build_error_response(
            status_code="400",
            status_text="Bad Request",
            message=f"Invalid XML: {str(e)}"
        )

    # Extract request details
    request_info = _parse_punchout_request(request_doc)

    # Validate shared secret if configured
    if shared_secret:
        if request_info.get("shared_secret") != shared_secret:
            return _build_error_response(
                status_code="401",
                status_text="Unauthorized",
                message="Invalid shared secret"
            )

    # Validate required fields
    if not punchout_url:
        return _build_error_response(
            status_code="500",
            status_text="Internal Server Error",
            message="PunchOut URL not configured"
        )

    # Generate session ID for this PunchOut session
    session_id = _generate_session_id(request_info)

    # Build response URL with session parameters
    browser_url = _build_punchout_browser_url(
        base_url=punchout_url,
        session_id=session_id,
        buyer_cookie=request_info.get("buyer_cookie", ""),
        operation=request_info.get("operation", "create")
    )

    # Log the PunchOut session
    _log_punchout_session(
        session_id=session_id,
        request_info=request_info,
        browser_url=browser_url
    )

    # Build success response
    return _build_punchout_response(
        supplier_id=supplier_id,
        buyer_id=request_info.get("from_identity"),
        browser_url=browser_url,
        status_code="200",
        status_text="OK"
    )


def generate_punchout_order_message(
    session_id,
    cart_items,
    buyer_cookie=None,
    currency="USD"
):
    """Generate PunchOutOrderMessage for selected cart items.

    This function creates a cXML PunchOutOrderMessage that can be
    sent back to the buyer's procurement system after PunchOut
    session completion.

    Args:
        session_id: PunchOut session identifier
        cart_items: List of cart item dictionaries with product info
        buyer_cookie: Original BuyerCookie from setup request
        currency: ISO 4217 currency code

    Returns:
        str: cXML PunchOutOrderMessage XML string

    Example:
        >>> order_xml = generate_punchout_order_message(
        ...     session_id="session123",
        ...     cart_items=[
        ...         {"sku": "PROD001", "quantity": 2, "price": 99.99}
        ...     ]
        ... )
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for cXML PunchOut. "
            "Install with: pip install lxml"
        )

    # Create root cXML element
    root = _create_cxml_root()

    # Add Message element
    message = etree.SubElement(root, "Message")

    # Add PunchOutOrderMessage
    punchout_order = etree.SubElement(message, "PunchOutOrderMessage")

    # Add BuyerCookie
    if buyer_cookie:
        cookie_elem = etree.SubElement(punchout_order, "BuyerCookie")
        cookie_elem.text = buyer_cookie

    # Add PunchOutOrderMessageHeader
    header = etree.SubElement(punchout_order, "PunchOutOrderMessageHeader")
    header.set("operationAllowed", "create")

    # Total amount
    total = etree.SubElement(header, "Total")
    money = etree.SubElement(total, "Money")
    money.set("currency", currency)
    total_amount = sum(
        float(item.get("price", 0)) * int(item.get("quantity", 1))
        for item in cart_items
    )
    money.text = f"{total_amount:.2f}"

    # Add ItemIn elements for each cart item
    for item in cart_items:
        _add_item_in(punchout_order, item, currency)

    # Serialize to XML
    xml_content = etree.tostring(
        root,
        encoding="unicode",
        pretty_print=True,
        xml_declaration=True
    )

    return xml_content


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
        "supplier_id": profile.get("cxml_supplier_id") or profile.get("supplier_id"),
        "supplier_name": profile.get("cxml_supplier_name") or profile.get("supplier_name"),
        "buyer_id": profile.get("cxml_buyer_id"),
        "catalog_id": profile.get("cxml_catalog_id") or profile.get("catalog_id"),
        "include_prices": profile.get("include_prices", True),
        "include_media": profile.get("include_media", True),
        "include_classifications": profile.get("include_classifications", True),
        "include_punchout_items": profile.get("cxml_punchout_enabled", False),
        "punchout_url": profile.get("cxml_punchout_url"),
        "shared_secret": profile.get("cxml_shared_secret"),
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
    """Convert Frappe language name to ISO 639-1 code.

    Args:
        language_name: Frappe Language document name

    Returns:
        str: ISO 639-1 language code (2-letter)
    """
    # Extract 2-letter code from language name
    if not language_name:
        return "en"

    code = language_name.lower()[:2]
    return code if len(code) == 2 else "en"


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


def _generate_payload_id():
    """Generate unique payload ID for cXML document.

    Returns:
        str: Unique payload identifier
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    unique = uuid.uuid4().hex[:8]
    return f"{timestamp}.{unique}@frappe-pim"


def _create_cxml_root():
    """Create root cXML element with required attributes.

    Returns:
        etree.Element: Root cXML element
    """
    from lxml import etree

    root = etree.Element("cXML")
    root.set("version", CXML_VERSION)
    root.set("payloadID", _generate_payload_id())
    root.set("timestamp", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00"))
    root.set("{http://www.w3.org/XML/1998/namespace}lang", "en")

    return root


def _build_cxml_header(parent, from_id, to_id, sender_id, shared_secret=None):
    """Build cXML Header element with credentials.

    Args:
        parent: Parent cXML element
        from_id: From/Identity value (sender DUNS)
        to_id: To/Identity value (recipient DUNS)
        sender_id: Sender/Identity value
        shared_secret: Optional SharedSecret for authentication

    Returns:
        etree.Element: Header element
    """
    from lxml import etree

    header = etree.SubElement(parent, "Header")

    # From (sender)
    from_elem = etree.SubElement(header, "From")
    credential = etree.SubElement(from_elem, "Credential")
    credential.set("domain", "DUNS")
    identity = etree.SubElement(credential, "Identity")
    identity.text = from_id

    # To (recipient)
    to_elem = etree.SubElement(header, "To")
    credential = etree.SubElement(to_elem, "Credential")
    credential.set("domain", "DUNS")
    identity = etree.SubElement(credential, "Identity")
    identity.text = to_id

    # Sender
    sender = etree.SubElement(header, "Sender")
    credential = etree.SubElement(sender, "Credential")
    credential.set("domain", "DUNS")
    identity = etree.SubElement(credential, "Identity")
    identity.text = sender_id

    if shared_secret:
        secret_elem = etree.SubElement(credential, "SharedSecret")
        secret_elem.text = shared_secret

    # UserAgent
    user_agent = etree.SubElement(sender, "UserAgent")
    user_agent.text = "Frappe PIM cXML Exporter"

    return header


def _build_cxml_index(
    products,
    supplier_id,
    supplier_name,
    buyer_id,
    catalog_id,
    currency,
    language,
    include_prices,
    include_media,
    include_classifications,
    include_punchout_items,
    punchout_url
):
    """Build complete cXML Index document structure.

    Args:
        products: List of product names to include
        supplier_id: Supplier identifier
        supplier_name: Supplier display name
        buyer_id: Buyer identifier
        catalog_id: Catalog identifier
        currency: ISO 4217 currency code
        language: ISO 639-1 language code
        include_prices: Include price elements
        include_media: Include media elements
        include_classifications: Include classification elements
        include_punchout_items: Use IndexItemPunchout instead of IndexItem
        punchout_url: Base URL for PunchOut items

    Returns:
        etree.Element: Root cXML element
    """
    from lxml import etree

    # Create root element
    root = _create_cxml_root()

    # Add Header
    _build_cxml_header(
        parent=root,
        from_id=supplier_id,
        to_id=buyer_id,
        sender_id=supplier_id
    )

    # Add Message with Index
    message = etree.SubElement(root, "Message")

    # Add Index element
    index = etree.SubElement(message, "Index")

    # Add SupplierID
    supplier_elem = etree.SubElement(index, "SupplierID")
    supplier_elem.set("domain", "DUNS")
    supplier_elem.text = supplier_id

    # Add IndexItems for each product
    for product_name in products:
        if include_punchout_items and punchout_url:
            _add_index_item_punchout(
                parent=index,
                product_name=product_name,
                punchout_url=punchout_url,
                language=language,
                currency=currency,
                include_media=include_media,
                include_classifications=include_classifications
            )
        else:
            _add_index_item(
                parent=index,
                product_name=product_name,
                supplier_id=supplier_id,
                language=language,
                currency=currency,
                include_prices=include_prices,
                include_media=include_media,
                include_classifications=include_classifications
            )

    return root


def _add_index_item(
    parent,
    product_name,
    supplier_id,
    language,
    currency,
    include_prices,
    include_media,
    include_classifications
):
    """Add an IndexItem element for a product.

    Args:
        parent: Parent Index element
        product_name: Name of Product Variant to export
        supplier_id: Supplier identifier
        language: ISO 639-1 language code
        currency: ISO 4217 currency code
        include_prices: Include price elements
        include_media: Include media elements
        include_classifications: Include classification elements

    Returns:
        etree.Element: IndexItem element or None if product not found
    """
    import frappe
    from lxml import etree

    product = _get_product_doc(product_name)
    if not product:
        return None

    index_item = etree.SubElement(parent, "IndexItem")

    # Add IndexItemAdd (for new items)
    item_add = etree.SubElement(index_item, "IndexItemAdd")

    # ItemID
    item_id = etree.SubElement(item_add, "ItemID")
    supplier_part_id = etree.SubElement(item_id, "SupplierPartID")
    sku = product.get("variant_code") or product.get("product_code") or product.name
    supplier_part_id.text = sku

    # Optional SupplierPartAuxiliaryID
    aux_id = product.get("auxiliary_part_number")
    if aux_id:
        aux_elem = etree.SubElement(item_id, "SupplierPartAuxiliaryID")
        aux_elem.text = aux_id

    # ItemDetail
    _add_item_detail(
        parent=item_add,
        product=product,
        language=language,
        currency=currency,
        include_prices=include_prices,
        include_media=include_media,
        include_classifications=include_classifications
    )

    return index_item


def _add_index_item_punchout(
    parent,
    product_name,
    punchout_url,
    language,
    currency,
    include_media,
    include_classifications
):
    """Add an IndexItemPunchout element for PunchOut catalog.

    Args:
        parent: Parent Index element
        product_name: Name of Product Variant to export
        punchout_url: Base PunchOut URL
        language: ISO 639-1 language code
        currency: ISO 4217 currency code
        include_media: Include media elements
        include_classifications: Include classification elements

    Returns:
        etree.Element: IndexItemPunchout element or None if product not found
    """
    import frappe
    from lxml import etree

    product = _get_product_doc(product_name)
    if not product:
        return None

    index_item = etree.SubElement(parent, "IndexItemPunchout")

    # ItemID
    item_id = etree.SubElement(index_item, "ItemID")
    supplier_part_id = etree.SubElement(item_id, "SupplierPartID")
    sku = product.get("variant_code") or product.get("product_code") or product.name
    supplier_part_id.text = sku

    # PunchoutDetail with URL
    punchout_detail = etree.SubElement(index_item, "PunchoutDetail")
    punchout_detail.set("punchoutLevel", "product")

    # Build product-specific PunchOut URL
    product_url = f"{punchout_url.rstrip('/')}/product/{sku}"

    url_elem = etree.SubElement(punchout_detail, "URL")
    url_elem.text = product_url

    # ItemDetail (simplified for PunchOut)
    item_detail = etree.SubElement(index_item, "ItemDetail")

    # UnitPrice (indicative)
    unit_price = etree.SubElement(item_detail, "UnitPrice")
    money = etree.SubElement(unit_price, "Money")
    money.set("currency", currency)
    price_value = product.get("price") or product.get("standard_rate") or 0
    money.text = f"{float(price_value):.2f}"

    # Description
    _add_description(item_detail, product, language)

    # UnitOfMeasure
    uom = etree.SubElement(item_detail, "UnitOfMeasure")
    uom.text = _map_uom_to_unece(product.get("stock_uom", "Nos"))

    # Classifications
    if include_classifications:
        _add_classifications(item_detail, product)

    # Media
    if include_media:
        _add_extrinsic_media(index_item, product)

    return index_item


def _add_item_detail(
    parent,
    product,
    language,
    currency,
    include_prices,
    include_media,
    include_classifications
):
    """Add ItemDetail element with product information.

    Args:
        parent: Parent element (IndexItemAdd)
        product: Product document
        language: ISO 639-1 language code
        currency: ISO 4217 currency code
        include_prices: Include price elements
        include_media: Include media elements
        include_classifications: Include classification elements

    Returns:
        etree.Element: ItemDetail element
    """
    from lxml import etree

    item_detail = etree.SubElement(parent, "ItemDetail")

    # UnitPrice
    if include_prices:
        unit_price = etree.SubElement(item_detail, "UnitPrice")
        money = etree.SubElement(unit_price, "Money")
        money.set("currency", currency)
        price_value = product.get("price") or product.get("standard_rate") or 0
        money.text = f"{float(price_value):.2f}"

    # Description
    _add_description(item_detail, product, language)

    # UnitOfMeasure
    uom = etree.SubElement(item_detail, "UnitOfMeasure")
    uom.text = _map_uom_to_unece(product.get("stock_uom", "Nos"))

    # Classifications
    if include_classifications:
        _add_classifications(item_detail, product)

    # ManufacturerPartID
    manufacturer_part = product.get("manufacturer_part_number")
    if manufacturer_part:
        mfg_part = etree.SubElement(item_detail, "ManufacturerPartID")
        mfg_part.text = manufacturer_part

    # ManufacturerName
    manufacturer_name = product.get("manufacturer") or product.get("brand")
    if manufacturer_name:
        mfg_name = etree.SubElement(item_detail, "ManufacturerName")
        mfg_name.text = manufacturer_name

    # URL (product page)
    product_url = product.get("website_url") or product.get("route")
    if product_url:
        url_elem = etree.SubElement(item_detail, "URL")
        url_elem.text = _get_full_url(product_url)

    # LeadTime
    lead_time = product.get("lead_time_days")
    if lead_time:
        lead_time_elem = etree.SubElement(item_detail, "LeadTime")
        lead_time_elem.text = str(int(lead_time))

    # Extrinsic elements for custom attributes
    _add_extrinsic_attributes(item_detail, product)

    # Media
    if include_media:
        _add_extrinsic_media(parent, product)

    return item_detail


def _add_description(parent, product, language):
    """Add Description element with product descriptions.

    Args:
        parent: Parent ItemDetail element
        product: Product document
        language: ISO 639-1 language code
    """
    from lxml import etree

    description = etree.SubElement(parent, "Description")
    description.set("{http://www.w3.org/XML/1998/namespace}lang", language)

    # Short description
    short_name = etree.SubElement(description, "ShortName")
    short_name.text = (
        product.get("variant_name") or
        product.get("product_name") or
        product.name
    )[:50]  # cXML ShortName limit

    # Long description (full text)
    desc_text = product.get("description") or product.get("short_description")
    if desc_text:
        description.text = _clean_html(desc_text)


def _add_classifications(parent, product):
    """Add Classification elements for product categorization.

    Args:
        parent: Parent ItemDetail element
        product: Product document
    """
    from lxml import etree

    # UNSPSC classification
    unspsc = product.get("unspsc_code") or product.get("commodity_code")
    if unspsc:
        classification = etree.SubElement(parent, "Classification")
        classification.set("domain", "UNSPSC")
        classification.text = unspsc

    # GTIN/EAN as classification
    barcode = product.get("barcode") or product.get("ean") or product.get("gtin")
    if barcode:
        classification = etree.SubElement(parent, "Classification")
        classification.set("domain", "GTIN")
        classification.text = barcode

    # Item group as custom classification
    item_group = product.get("item_group") or product.get("product_category")
    if item_group:
        classification = etree.SubElement(parent, "Classification")
        classification.set("domain", "ProductCategory")
        classification.text = item_group


def _add_extrinsic_attributes(parent, product):
    """Add Extrinsic elements for custom product attributes.

    Args:
        parent: Parent ItemDetail element
        product: Product document
    """
    import frappe
    from lxml import etree

    attribute_values = product.get("attribute_values") or []

    for attr_value in attribute_values:
        attr_code = attr_value.get("attribute")
        if not attr_code:
            continue

        # Get value
        value = _get_attribute_value(attr_value)
        if value is None:
            continue

        # Get attribute name
        try:
            attr_name = frappe.get_cached_value(
                "PIM Attribute",
                attr_code,
                "attribute_name"
            ) or attr_code
        except Exception:
            attr_name = attr_code

        # Add as Extrinsic
        extrinsic = etree.SubElement(parent, "Extrinsic")
        extrinsic.set("name", attr_name)
        extrinsic.text = str(value)


def _add_extrinsic_media(parent, product):
    """Add Extrinsic elements for media/images.

    Args:
        parent: Parent element
        product: Product document
    """
    from lxml import etree

    # Primary image
    primary_image = product.get("image")
    if primary_image:
        extrinsic = etree.SubElement(parent, "Extrinsic")
        extrinsic.set("name", "ImageURL")
        extrinsic.text = _get_full_url(primary_image)

    # Additional images from media child table
    media_list = product.get("media") or []
    for idx, media in enumerate(media_list[:5]):  # Limit to 5 additional images
        media_url = media.get("file_url") or media.get("url")
        if media_url:
            extrinsic = etree.SubElement(parent, "Extrinsic")
            extrinsic.set("name", f"ImageURL{idx + 2}")
            extrinsic.text = _get_full_url(media_url)


def _add_item_in(parent, cart_item, currency):
    """Add ItemIn element for PunchOut order message.

    Args:
        parent: Parent PunchOutOrderMessage element
        cart_item: Cart item dictionary
        currency: ISO 4217 currency code
    """
    from lxml import etree

    item_in = etree.SubElement(parent, "ItemIn")
    item_in.set("quantity", str(cart_item.get("quantity", 1)))

    # ItemID
    item_id = etree.SubElement(item_in, "ItemID")
    supplier_part_id = etree.SubElement(item_id, "SupplierPartID")
    supplier_part_id.text = cart_item.get("sku", "")

    # ItemDetail
    item_detail = etree.SubElement(item_in, "ItemDetail")

    # UnitPrice
    unit_price = etree.SubElement(item_detail, "UnitPrice")
    money = etree.SubElement(unit_price, "Money")
    money.set("currency", currency)
    money.text = f"{float(cart_item.get('price', 0)):.2f}"

    # Description
    description = etree.SubElement(item_detail, "Description")
    description.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    short_name = etree.SubElement(description, "ShortName")
    short_name.text = cart_item.get("name", cart_item.get("sku", ""))[:50]

    # UnitOfMeasure
    uom = etree.SubElement(item_detail, "UnitOfMeasure")
    uom.text = cart_item.get("uom", "EA")

    # Classification (UNSPSC if available)
    unspsc = cart_item.get("unspsc")
    if unspsc:
        classification = etree.SubElement(item_detail, "Classification")
        classification.set("domain", "UNSPSC")
        classification.text = unspsc


def _parse_punchout_request(request_doc):
    """Parse incoming PunchOutSetupRequest.

    Args:
        request_doc: Parsed lxml document

    Returns:
        dict: Extracted request information
    """
    info = {}

    # Get From identity
    from_identity = request_doc.find(".//Header/From/Credential/Identity")
    if from_identity is not None:
        info["from_identity"] = from_identity.text

    # Get To identity
    to_identity = request_doc.find(".//Header/To/Credential/Identity")
    if to_identity is not None:
        info["to_identity"] = to_identity.text

    # Get Sender identity
    sender_identity = request_doc.find(".//Header/Sender/Credential/Identity")
    if sender_identity is not None:
        info["sender_identity"] = sender_identity.text

    # Get SharedSecret
    shared_secret = request_doc.find(".//Header/Sender/Credential/SharedSecret")
    if shared_secret is not None:
        info["shared_secret"] = shared_secret.text

    # Get BuyerCookie
    buyer_cookie = request_doc.find(".//Request/PunchOutSetupRequest/BuyerCookie")
    if buyer_cookie is not None:
        info["buyer_cookie"] = buyer_cookie.text

    # Get operation (create/inspect/edit)
    setup_request = request_doc.find(".//Request/PunchOutSetupRequest")
    if setup_request is not None:
        info["operation"] = setup_request.get("operation", "create")

    # Get BrowserFormPost URL
    browser_form_post = request_doc.find(
        ".//Request/PunchOutSetupRequest/BrowserFormPost/URL"
    )
    if browser_form_post is not None:
        info["browser_form_post_url"] = browser_form_post.text

    return info


def _build_punchout_response(
    supplier_id,
    buyer_id,
    browser_url,
    status_code="200",
    status_text="OK"
):
    """Build PunchOutSetupResponse XML.

    Args:
        supplier_id: Supplier DUNS identifier
        buyer_id: Buyer DUNS identifier
        browser_url: URL for catalog browsing
        status_code: HTTP-style status code
        status_text: Status description

    Returns:
        str: cXML response XML string
    """
    from lxml import etree

    root = _create_cxml_root()

    # Add Response element
    response = etree.SubElement(root, "Response")

    # Status
    status = etree.SubElement(response, "Status")
    status.set("code", status_code)
    status.set("text", status_text)

    if status_code == "200":
        # PunchOutSetupResponse
        punchout_response = etree.SubElement(response, "PunchOutSetupResponse")

        # StartPage URL
        start_page = etree.SubElement(punchout_response, "StartPage")
        url_elem = etree.SubElement(start_page, "URL")
        url_elem.text = browser_url

    # Serialize
    xml_content = etree.tostring(
        root,
        encoding="unicode",
        pretty_print=True,
        xml_declaration=True
    )

    return xml_content


def _build_error_response(status_code, status_text, message):
    """Build error response XML.

    Args:
        status_code: HTTP-style status code
        status_text: Status text
        message: Error message

    Returns:
        str: cXML error response XML string
    """
    from lxml import etree

    root = _create_cxml_root()

    response = etree.SubElement(root, "Response")

    status = etree.SubElement(response, "Status")
    status.set("code", status_code)
    status.set("text", status_text)
    status.text = message

    xml_content = etree.tostring(
        root,
        encoding="unicode",
        pretty_print=True,
        xml_declaration=True
    )

    return xml_content


def _generate_session_id(request_info):
    """Generate unique session ID for PunchOut session.

    Args:
        request_info: Parsed request information dict

    Returns:
        str: Unique session identifier
    """
    # Create hash from request info and timestamp
    data = f"{request_info.get('from_identity', '')}"
    data += f"{request_info.get('buyer_cookie', '')}"
    data += f"{datetime.utcnow().isoformat()}"
    data += uuid.uuid4().hex

    return hashlib.sha256(data.encode()).hexdigest()[:32]


def _build_punchout_browser_url(base_url, session_id, buyer_cookie, operation):
    """Build URL for PunchOut catalog browser.

    Args:
        base_url: Base PunchOut catalog URL
        session_id: Session identifier
        buyer_cookie: Buyer's cookie value
        operation: PunchOut operation (create/inspect/edit)

    Returns:
        str: Complete browser URL with parameters
    """
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

    # Parse base URL
    parsed = urlparse(base_url)

    # Build query parameters
    params = {
        "session_id": session_id,
        "operation": operation
    }
    if buyer_cookie:
        params["buyer_cookie"] = buyer_cookie

    # Merge with existing query params
    existing_params = parse_qs(parsed.query)
    for key, value in params.items():
        existing_params[key] = [value]

    # Rebuild URL
    new_query = urlencode(existing_params, doseq=True)
    new_parsed = parsed._replace(query=new_query)

    return urlunparse(new_parsed)


def _log_punchout_session(session_id, request_info, browser_url):
    """Log PunchOut session for tracking.

    Args:
        session_id: Session identifier
        request_info: Request information dict
        browser_url: Generated browser URL
    """
    try:
        import frappe

        # Try to create a log record
        frappe.get_doc({
            "doctype": "PIM Activity Log",
            "activity_type": "PunchOut Session",
            "reference_type": "Export Profile",
            "details": {
                "session_id": session_id,
                "from_identity": request_info.get("from_identity"),
                "buyer_cookie": request_info.get("buyer_cookie"),
                "operation": request_info.get("operation"),
                "browser_url": browser_url,
                "timestamp": datetime.utcnow().isoformat()
            }
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        # Logging failure should not break the flow
        pass


def _get_product_doc(product_name):
    """Get product document by name.

    Args:
        product_name: Product Variant or Product Master name

    Returns:
        Document or None if not found
    """
    import frappe

    try:
        return frappe.get_doc("Product Variant", product_name)
    except Exception:
        try:
            return frappe.get_doc("Product Master", product_name)
        except Exception:
            return None


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


def _map_uom_to_unece(frappe_uom):
    """Map Frappe UOM to UN/ECE Recommendation 20 code.

    Args:
        frappe_uom: Frappe unit of measure name

    Returns:
        str: UN/ECE code
    """
    uom_map = {
        "Nos": "EA",
        "Unit": "EA",
        "Each": "EA",
        "Piece": "EA",
        "Pcs": "EA",
        "Box": "BX",
        "Pair": "PR",
        "Set": "SET",
        "Dozen": "DZN",
        "Pack": "PK",
        "Kg": "KGM",
        "Gram": "GRM",
        "Litre": "LTR",
        "Meter": "MTR",
        "Cm": "CMT",
        "Inch": "INH",
        "Feet": "FOT",
        "Sq. Meter": "MTK",
        "Sq. Feet": "FTK",
        "Hour": "HUR",
        "Day": "DAY"
    }

    return uom_map.get(frappe_uom, "EA")


def _save_export_file(content, profile_name=None, catalog_id=None, file_prefix="cxml"):
    """Save export content to file.

    Args:
        content: XML content string
        profile_name: Export profile name (for filename)
        catalog_id: Catalog ID (for filename)
        file_prefix: Prefix for filename

    Returns:
        str: File path of saved file
    """
    import frappe

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name_part = profile_name or catalog_id or file_prefix
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


def validate_cxml(xml_content):
    """Validate cXML document structure.

    Args:
        xml_content: XML content string

    Returns:
        tuple: (is_valid, errors_list)
    """
    from lxml import etree

    try:
        # Parse the XML
        doc = etree.fromstring(
            xml_content.encode() if isinstance(xml_content, str) else xml_content
        )

        errors = []

        # Check root element
        if doc.tag != "cXML":
            errors.append("Root element must be cXML")

        # Check for required attributes
        if not doc.get("payloadID"):
            errors.append("Missing required payloadID attribute")

        if not doc.get("timestamp"):
            errors.append("Missing required timestamp attribute")

        # Check for Header or Response
        header = doc.find(".//Header")
        response = doc.find(".//Response")
        if header is None and response is None:
            errors.append("Missing Header element (required for requests)")

        return len(errors) == 0, errors

    except etree.XMLSyntaxError as e:
        return False, [f"XML Syntax Error: {str(e)}"]
    except Exception as e:
        return False, [f"Validation Error: {str(e)}"]


def get_item_count(xml_content):
    """Count number of items in cXML Index.

    Args:
        xml_content: XML content string

    Returns:
        int: Number of IndexItem/IndexItemPunchout elements
    """
    from lxml import etree

    try:
        doc = etree.fromstring(
            xml_content.encode() if isinstance(xml_content, str) else xml_content
        )

        index_items = doc.findall(".//IndexItem")
        punchout_items = doc.findall(".//IndexItemPunchout")

        return len(index_items) + len(punchout_items)
    except Exception:
        return 0
