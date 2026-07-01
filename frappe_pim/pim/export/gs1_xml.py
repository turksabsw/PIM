"""GS1 XML Export Module for GDSN Data Pool Synchronization

This module provides functionality for generating GS1 XML compliant
documents for the Global Data Synchronization Network (GDSN). GDSN is
the worldwide standard for product data synchronization between trading
partners using certified data pools.

The module supports:
- GS1 XML 3.1 trade item messages
- CIN (Catalogue Item Notification) documents
- Trade item hierarchies (each, case, pallet)
- GPC (Global Product Classification) codes
- Target market specifications
- Trade item measurements and dimensions
- Brand owner and information provider details
- GTIN validation and formatting
- Data pool recipient configuration

Usage:
    from frappe_pim.pim.export.gs1_xml import export_catalogue_item_notification

    xml_content = export_catalogue_item_notification(
        profile_name="my_gdsn_profile",
        save_file=True
    )

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import uuid
from datetime import datetime


# GS1 XML 3.1 namespaces
GS1_NS = "urn:gs1:gdsn:catalogue_item_notification:xsd:3"
GS1_SHARED_NS = "urn:gs1:shared:shared_common:xsd:3"
GS1_GDSN_NS = "urn:gs1:gdsn:gdsn_common:xsd:3"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

GS1_NSMAP = {
    None: GS1_NS,
    "sh": GS1_SHARED_NS,
    "gdsn": GS1_GDSN_NS,
    "xsi": XSI_NS
}

# GS1 Schema location
GS1_SCHEMA_LOCATION = (
    "urn:gs1:gdsn:catalogue_item_notification:xsd:3 "
    "http://www.gs1globalregistry.net/3.1/schemas/gs1/gdsn/CatalogueItemNotification.xsd"
)

# GS1 Document command types
GS1_COMMAND_ADD = "ADD"
GS1_COMMAND_CHANGE = "CHANGE_BY_REFRESH"
GS1_COMMAND_DELETE = "DELETE"
GS1_COMMAND_CORRECT = "CORRECT"

# Default data pool GLN
DEFAULT_DATA_POOL_GLN = "0000000000000"


def export_catalogue_item_notification(
    profile_name=None,
    products=None,
    gln_brand_owner=None,
    gln_information_provider=None,
    gln_data_recipient=None,
    data_pool_gln=None,
    target_market="US",
    document_command=None,
    language="en",
    include_hierarchy=True,
    include_measurements=True,
    include_packaging=True,
    include_prices=False,
    pretty_print=True,
    save_file=False
):
    """Generate GS1 Catalogue Item Notification (CIN) XML document.

    This function creates a GS1 XML compliant CIN document for
    synchronizing product data through the GDSN network. It can
    either use an Export Profile configuration or accept parameters directly.

    Args:
        profile_name: Name of Export Profile DocType to use for settings
        products: List of Product Master/Variant names to export (optional)
        gln_brand_owner: GLN of the brand owner (13-digit)
        gln_information_provider: GLN of the information provider (13-digit)
        gln_data_recipient: GLN of the data recipient (13-digit)
        data_pool_gln: GLN of the source data pool
        target_market: ISO 3166-1 numeric country code or "001" for global
        document_command: ADD, CHANGE_BY_REFRESH, DELETE, or CORRECT
        language: ISO 639-1 language code
        include_hierarchy: Include trade item hierarchy information
        include_measurements: Include dimensions and weight
        include_packaging: Include packaging information
        include_prices: Include suggested retail price (SRP)
        pretty_print: Format XML with indentation
        save_file: Save to file and return file path

    Returns:
        str: XML content as string, or file path if save_file=True

    Raises:
        ValueError: If required parameters are missing
        ImportError: If lxml is not installed

    Example:
        >>> xml = export_catalogue_item_notification(
        ...     profile_name="gdsn_export",
        ...     target_market="840",  # USA
        ...     save_file=True
        ... )
        >>> print(xml)  # Returns file path
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for GS1 XML export. "
            "Install with: pip install lxml"
        )

    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    # Override config with explicit parameters
    gln_brand_owner = gln_brand_owner or config.get("gln_brand_owner", "0000000000000")
    gln_information_provider = gln_information_provider or config.get(
        "gln_information_provider",
        gln_brand_owner
    )
    gln_data_recipient = gln_data_recipient or config.get("gln_data_recipient")
    data_pool_gln = data_pool_gln or config.get("data_pool_gln", DEFAULT_DATA_POOL_GLN)
    target_market = config.get("target_market", target_market)
    document_command = document_command or config.get("document_command", GS1_COMMAND_ADD)
    language = config.get("language", language)
    include_hierarchy = config.get("include_hierarchy", include_hierarchy)
    include_measurements = config.get("include_measurements", include_measurements)
    include_packaging = config.get("include_packaging", include_packaging)
    include_prices = config.get("include_prices", include_prices)
    pretty_print = config.get("pretty_print", pretty_print)

    # Get products to export
    if products is None:
        products = _get_products_for_export(config)

    # Build XML document
    root = _build_cin_document(
        products=products,
        gln_brand_owner=gln_brand_owner,
        gln_information_provider=gln_information_provider,
        gln_data_recipient=gln_data_recipient,
        data_pool_gln=data_pool_gln,
        target_market=target_market,
        document_command=document_command,
        language=language,
        include_hierarchy=include_hierarchy,
        include_measurements=include_measurements,
        include_packaging=include_packaging,
        include_prices=include_prices
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
            document_type="gs1_cin"
        )

    return xml_content


def export_catalogue_item_notification_async(profile_name, callback=None):
    """Queue CIN export as background job.

    For large catalogues, this function queues the export as a background
    job to avoid timeout issues.

    Args:
        profile_name: Name of Export Profile DocType
        callback: Optional callback function name to call on completion

    Returns:
        str: Background job ID
    """
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.export.gs1_xml.export_catalogue_item_notification",
        queue="long",
        timeout=3600,
        profile_name=profile_name,
        save_file=True
    )

    return job.id if hasattr(job, 'id') else str(job)


def export_trade_item(
    product_name,
    gln_brand_owner=None,
    gln_information_provider=None,
    target_market="US",
    language="en",
    include_measurements=True,
    include_packaging=True,
    pretty_print=True
):
    """Export a single product as GS1 Trade Item XML fragment.

    This function generates the tradeItem element for a single product,
    useful for testing or incremental synchronization.

    Args:
        product_name: Name of Product Variant or Product Master
        gln_brand_owner: GLN of the brand owner
        gln_information_provider: GLN of the information provider
        target_market: Target market code
        language: Language code for descriptions
        include_measurements: Include dimensions
        include_packaging: Include packaging info
        pretty_print: Format XML with indentation

    Returns:
        str: XML fragment as string

    Example:
        >>> xml = export_trade_item(
        ...     product_name="PROD-001",
        ...     gln_brand_owner="1234567890123"
        ... )
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for GS1 XML export. "
            "Install with: pip install lxml"
        )

    gln_brand_owner = gln_brand_owner or "0000000000000"
    gln_information_provider = gln_information_provider or gln_brand_owner

    # Create trade item element
    trade_item = _build_trade_item(
        product_name=product_name,
        gln_brand_owner=gln_brand_owner,
        gln_information_provider=gln_information_provider,
        target_market=target_market,
        language=language,
        include_measurements=include_measurements,
        include_packaging=include_packaging
    )

    if trade_item is None:
        return None

    # Serialize to XML string
    xml_content = etree.tostring(
        trade_item,
        encoding="unicode",
        pretty_print=pretty_print
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
        "gln_brand_owner": profile.get("gs1_gln_brand_owner"),
        "gln_information_provider": profile.get("gs1_gln_information_provider"),
        "gln_data_recipient": profile.get("gs1_gln_data_recipient"),
        "data_pool_gln": profile.get("gs1_data_pool_gln"),
        "target_market": profile.get("gs1_target_market", "US"),
        "document_command": profile.get("gs1_document_command", GS1_COMMAND_ADD),
        "include_hierarchy": profile.get("gs1_include_hierarchy", True),
        "include_measurements": profile.get("gs1_include_measurements", True),
        "include_packaging": profile.get("gs1_include_packaging", True),
        "include_prices": profile.get("gs1_include_prices", False),
        "pretty_print": profile.get("pretty_print", True),
        "product_family": profile.get("product_family"),
        "status_filter": profile.get("status_filter"),
        "completeness_threshold": profile.get("completeness_threshold", 0),
        "output_filename": profile.get("output_filename"),
    }

    # Get language from export_language link
    if profile.get("export_language"):
        config["language"] = _get_language_code(profile.export_language)

    return config


def _get_language_code(language_name):
    """Convert Frappe language name to ISO 639-1 code.

    Args:
        language_name: Frappe Language document name

    Returns:
        str: ISO 639-1 language code (2-letter)
    """
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


def _generate_document_id():
    """Generate unique document identifier.

    Returns:
        str: Unique document ID in GS1 format
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    unique = uuid.uuid4().hex[:8].upper()
    return f"CIN-{timestamp}-{unique}"


def _build_cin_document(
    products,
    gln_brand_owner,
    gln_information_provider,
    gln_data_recipient,
    data_pool_gln,
    target_market,
    document_command,
    language,
    include_hierarchy,
    include_measurements,
    include_packaging,
    include_prices
):
    """Build complete GS1 CIN document structure.

    Args:
        products: List of product names to include
        gln_brand_owner: Brand owner GLN
        gln_information_provider: Information provider GLN
        gln_data_recipient: Data recipient GLN
        data_pool_gln: Source data pool GLN
        target_market: Target market code
        document_command: Document command type
        language: Language code
        include_hierarchy: Include hierarchy info
        include_measurements: Include measurements
        include_packaging: Include packaging info
        include_prices: Include pricing

    Returns:
        etree.Element: Root catalogueItemNotification element
    """
    from lxml import etree

    # Create root element with namespaces
    root = etree.Element(
        "catalogueItemNotification",
        nsmap=GS1_NSMAP
    )

    # Add schema location
    root.set(
        f"{{{XSI_NS}}}schemaLocation",
        GS1_SCHEMA_LOCATION
    )

    # Add standard business document header
    _add_sbdh(
        root,
        sender_gln=gln_information_provider,
        receiver_gln=gln_data_recipient or data_pool_gln,
        document_id=_generate_document_id()
    )

    # Transaction element
    transaction = etree.SubElement(root, "transaction")

    # Transaction identification
    trans_id = etree.SubElement(
        transaction,
        f"{{{GS1_GDSN_NS}}}transactionIdentification"
    )
    entity_id = etree.SubElement(trans_id, f"{{{GS1_GDSN_NS}}}entityIdentification")
    entity_id.text = str(uuid.uuid4())
    content_owner = etree.SubElement(trans_id, f"{{{GS1_GDSN_NS}}}contentOwner")
    gln_elem = etree.SubElement(content_owner, f"{{{GS1_SHARED_NS}}}gln")
    gln_elem.text = gln_information_provider

    # Document command
    doc_cmd = etree.SubElement(transaction, f"{{{GS1_GDSN_NS}}}documentCommand")
    doc_cmd_header = etree.SubElement(doc_cmd, f"{{{GS1_GDSN_NS}}}documentCommandHeader")
    doc_cmd_header.set("type", document_command)

    # Document identification
    doc_id = etree.SubElement(doc_cmd_header, f"{{{GS1_GDSN_NS}}}documentCommandIdentification")
    entity_id = etree.SubElement(doc_id, f"{{{GS1_GDSN_NS}}}entityIdentification")
    entity_id.text = _generate_document_id()
    content_owner = etree.SubElement(doc_id, f"{{{GS1_GDSN_NS}}}contentOwner")
    gln_elem = etree.SubElement(content_owner, f"{{{GS1_SHARED_NS}}}gln")
    gln_elem.text = gln_information_provider

    # Document command operand (contains trade items)
    doc_operand = etree.SubElement(doc_cmd, f"{{{GS1_GDSN_NS}}}documentCommandOperand")

    # Catalogue item notification message
    cin_message = etree.SubElement(
        doc_operand,
        "catalogueItemNotificationMessage"
    )

    # CIN identification
    cin_id = etree.SubElement(cin_message, "catalogueItemNotificationIdentification")
    entity_id = etree.SubElement(cin_id, f"{{{GS1_GDSN_NS}}}entityIdentification")
    entity_id.text = _generate_document_id()
    content_owner = etree.SubElement(cin_id, f"{{{GS1_GDSN_NS}}}contentOwner")
    gln_elem = etree.SubElement(content_owner, f"{{{GS1_SHARED_NS}}}gln")
    gln_elem.text = gln_information_provider

    # Catalogue item
    for product_name in products:
        _add_catalogue_item(
            parent=cin_message,
            product_name=product_name,
            gln_brand_owner=gln_brand_owner,
            gln_information_provider=gln_information_provider,
            target_market=target_market,
            language=language,
            include_hierarchy=include_hierarchy,
            include_measurements=include_measurements,
            include_packaging=include_packaging,
            include_prices=include_prices
        )

    return root


def _add_sbdh(parent, sender_gln, receiver_gln, document_id):
    """Add Standard Business Document Header (SBDH).

    Args:
        parent: Parent XML element
        sender_gln: Sender GLN
        receiver_gln: Receiver GLN
        document_id: Document identifier
    """
    from lxml import etree

    # SBDH namespace
    sbdh_ns = "http://www.unece.org/cefact/namespaces/StandardBusinessDocumentHeader"

    sbdh = etree.SubElement(parent, f"{{{sbdh_ns}}}StandardBusinessDocumentHeader")

    # Header version
    version = etree.SubElement(sbdh, f"{{{sbdh_ns}}}HeaderVersion")
    version.text = "1.0"

    # Sender
    sender = etree.SubElement(sbdh, f"{{{sbdh_ns}}}Sender")
    sender_id = etree.SubElement(sender, f"{{{sbdh_ns}}}Identifier")
    sender_id.set("Authority", "GS1")
    sender_id.text = sender_gln
    contact = etree.SubElement(sender, f"{{{sbdh_ns}}}ContactInformation")
    contact_type = etree.SubElement(contact, f"{{{sbdh_ns}}}ContactTypeIdentifier")
    contact_type.text = "IT Support"

    # Receiver
    receiver = etree.SubElement(sbdh, f"{{{sbdh_ns}}}Receiver")
    receiver_id = etree.SubElement(receiver, f"{{{sbdh_ns}}}Identifier")
    receiver_id.set("Authority", "GS1")
    receiver_id.text = receiver_gln

    # Document identification
    doc_ident = etree.SubElement(sbdh, f"{{{sbdh_ns}}}DocumentIdentification")
    standard = etree.SubElement(doc_ident, f"{{{sbdh_ns}}}Standard")
    standard.text = "GS1"
    type_version = etree.SubElement(doc_ident, f"{{{sbdh_ns}}}TypeVersion")
    type_version.text = "3.1"
    instance_id = etree.SubElement(doc_ident, f"{{{sbdh_ns}}}InstanceIdentifier")
    instance_id.text = document_id
    doc_type = etree.SubElement(doc_ident, f"{{{sbdh_ns}}}Type")
    doc_type.text = "catalogueItemNotification"
    creation_dt = etree.SubElement(doc_ident, f"{{{sbdh_ns}}}CreationDateAndTime")
    creation_dt.text = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_catalogue_item(
    parent,
    product_name,
    gln_brand_owner,
    gln_information_provider,
    target_market,
    language,
    include_hierarchy,
    include_measurements,
    include_packaging,
    include_prices
):
    """Add catalogueItem element for a product.

    Args:
        parent: Parent catalogueItemNotificationMessage element
        product_name: Name of Product Variant to export
        gln_brand_owner: Brand owner GLN
        gln_information_provider: Information provider GLN
        target_market: Target market code
        language: Language code
        include_hierarchy: Include hierarchy info
        include_measurements: Include measurements
        include_packaging: Include packaging info
        include_prices: Include pricing

    Returns:
        etree.Element: catalogueItem element or None
    """
    from lxml import etree

    product = _get_product_doc(product_name)
    if not product:
        return None

    catalogue_item = etree.SubElement(parent, "catalogueItem")

    # Catalogue item state
    state = etree.SubElement(catalogue_item, "catalogueItemState")
    state_code = etree.SubElement(state, "catalogueItemStateCode")
    state_code.text = "IN_PROGRESS" if not product.get("is_published") else "FINAL"

    # Trade item
    _add_trade_item_wrapper(
        parent=catalogue_item,
        product=product,
        gln_brand_owner=gln_brand_owner,
        gln_information_provider=gln_information_provider,
        target_market=target_market,
        language=language,
        include_measurements=include_measurements,
        include_packaging=include_packaging,
        include_prices=include_prices
    )

    return catalogue_item


def _add_trade_item_wrapper(
    parent,
    product,
    gln_brand_owner,
    gln_information_provider,
    target_market,
    language,
    include_measurements,
    include_packaging,
    include_prices
):
    """Add tradeItem wrapper element.

    Args:
        parent: Parent catalogueItem element
        product: Product document
        gln_brand_owner: Brand owner GLN
        gln_information_provider: Information provider GLN
        target_market: Target market code
        language: Language code
        include_measurements: Include measurements
        include_packaging: Include packaging info
        include_prices: Include pricing
    """
    from lxml import etree

    trade_item = etree.SubElement(parent, "tradeItem")

    # GTIN
    gtin = _get_gtin(product)
    gtin_elem = etree.SubElement(trade_item, f"{{{GS1_SHARED_NS}}}gtin")
    gtin_elem.text = gtin

    # Information provider GLN
    info_provider = etree.SubElement(
        trade_item,
        f"{{{GS1_GDSN_NS}}}informationProviderOfTradeItem"
    )
    gln_elem = etree.SubElement(info_provider, f"{{{GS1_SHARED_NS}}}gln")
    gln_elem.text = gln_information_provider

    # Target market
    target = etree.SubElement(trade_item, f"{{{GS1_GDSN_NS}}}targetMarket")
    target_code = etree.SubElement(target, f"{{{GS1_GDSN_NS}}}targetMarketCountryCode")
    target_code.text = _convert_to_numeric_country_code(target_market)

    # Trade item information
    _add_trade_item_information(
        trade_item,
        product,
        gln_brand_owner,
        language,
        include_measurements,
        include_packaging,
        include_prices
    )


def _build_trade_item(
    product_name,
    gln_brand_owner,
    gln_information_provider,
    target_market,
    language,
    include_measurements,
    include_packaging
):
    """Build standalone tradeItem element.

    Args:
        product_name: Name of Product Variant
        gln_brand_owner: Brand owner GLN
        gln_information_provider: Information provider GLN
        target_market: Target market code
        language: Language code
        include_measurements: Include measurements
        include_packaging: Include packaging info

    Returns:
        etree.Element: tradeItem element or None
    """
    from lxml import etree

    product = _get_product_doc(product_name)
    if not product:
        return None

    # Create trade item element with namespace
    trade_item = etree.Element(
        "tradeItem",
        nsmap={
            None: GS1_NS,
            "sh": GS1_SHARED_NS,
            "gdsn": GS1_GDSN_NS
        }
    )

    # GTIN
    gtin = _get_gtin(product)
    gtin_elem = etree.SubElement(trade_item, f"{{{GS1_SHARED_NS}}}gtin")
    gtin_elem.text = gtin

    # Information provider GLN
    info_provider = etree.SubElement(
        trade_item,
        f"{{{GS1_GDSN_NS}}}informationProviderOfTradeItem"
    )
    gln_elem = etree.SubElement(info_provider, f"{{{GS1_SHARED_NS}}}gln")
    gln_elem.text = gln_information_provider

    # Target market
    target = etree.SubElement(trade_item, f"{{{GS1_GDSN_NS}}}targetMarket")
    target_code = etree.SubElement(target, f"{{{GS1_GDSN_NS}}}targetMarketCountryCode")
    target_code.text = _convert_to_numeric_country_code(target_market)

    # Trade item information
    _add_trade_item_information(
        trade_item,
        product,
        gln_brand_owner,
        language,
        include_measurements,
        include_packaging,
        include_prices=False
    )

    return trade_item


def _add_trade_item_information(
    parent,
    product,
    gln_brand_owner,
    language,
    include_measurements,
    include_packaging,
    include_prices
):
    """Add tradeItemInformation module.

    Args:
        parent: Parent tradeItem element
        product: Product document
        gln_brand_owner: Brand owner GLN
        language: Language code
        include_measurements: Include measurements
        include_packaging: Include packaging info
        include_prices: Include pricing
    """
    from lxml import etree

    # Extension element for modules
    extension = etree.SubElement(parent, f"{{{GS1_GDSN_NS}}}extension")

    # Trade item description module
    _add_trade_item_description(extension, product, language)

    # Trade item measurements module
    if include_measurements:
        _add_trade_item_measurements(extension, product)

    # Trade item hierarchy module
    _add_trade_item_hierarchy(extension, product)

    # GPC classification module
    _add_gpc_classification(extension, product)

    # Brand information module
    _add_brand_information(extension, product, gln_brand_owner, language)

    # Packaging information module
    if include_packaging:
        _add_packaging_information(extension, product, language)

    # Price information module
    if include_prices:
        _add_price_information(extension, product)

    # Certification information (if applicable)
    _add_certification_information(extension, product)


def _add_trade_item_description(parent, product, language):
    """Add tradeItemDescriptionModule.

    Args:
        parent: Parent extension element
        product: Product document
        language: Language code
    """
    from lxml import etree

    desc_ns = "urn:gs1:gdsn:trade_item_description:xsd:3"

    desc_module = etree.SubElement(parent, f"{{{desc_ns}}}tradeItemDescriptionModule")
    desc_info = etree.SubElement(desc_module, f"{{{desc_ns}}}tradeItemDescriptionInformation")

    # Brand name
    brand = product.get("brand")
    if brand:
        brand_elem = etree.SubElement(desc_info, "brandName")
        brand_elem.text = brand
        brand_elem.set("languageCode", language)

    # Product description (short)
    product_name = product.get("variant_name") or product.get("product_name") or product.name
    desc_short = etree.SubElement(desc_info, "descriptionShort")
    desc_short.text = product_name[:35]  # GS1 limit
    desc_short.set("languageCode", language)

    # Functional name
    func_name = etree.SubElement(desc_info, "functionalName")
    func_name.text = product_name[:35]
    func_name.set("languageCode", language)

    # Trade item description (long)
    description = product.get("description") or product.get("short_description")
    if description:
        desc_long = etree.SubElement(desc_info, "tradeItemDescription")
        desc_long.text = _clean_html(description)[:2500]  # GS1 limit
        desc_long.set("languageCode", language)

    # Regulated product name (if different from functional name)
    regulated_name = product.get("regulated_product_name")
    if regulated_name:
        reg_name = etree.SubElement(desc_info, "regulatedProductName")
        reg_name.text = regulated_name[:500]
        reg_name.set("languageCode", language)

    # Variant description
    variant_desc = product.get("variant_description")
    if variant_desc:
        var_elem = etree.SubElement(desc_info, "variantDescription")
        var_elem.text = variant_desc[:35]
        var_elem.set("languageCode", language)


def _add_trade_item_measurements(parent, product):
    """Add tradeItemMeasurementsModule.

    Args:
        parent: Parent extension element
        product: Product document
    """
    from lxml import etree

    meas_ns = "urn:gs1:gdsn:trade_item_measurements:xsd:3"

    meas_module = etree.SubElement(parent, f"{{{meas_ns}}}tradeItemMeasurementsModule")
    meas_info = etree.SubElement(meas_module, f"{{{meas_ns}}}tradeItemMeasurements")

    # Net weight
    net_weight = product.get("net_weight") or product.get("weight_per_unit")
    if net_weight:
        weight_elem = etree.SubElement(meas_info, "netWeight")
        weight_elem.text = f"{float(net_weight):.3f}"
        weight_elem.set("measurementUnitCode", _get_weight_uom(product))

    # Gross weight
    gross_weight = product.get("gross_weight")
    if gross_weight:
        weight_elem = etree.SubElement(meas_info, "grossWeight")
        weight_elem.text = f"{float(gross_weight):.3f}"
        weight_elem.set("measurementUnitCode", _get_weight_uom(product))

    # Net content
    net_content = product.get("net_content") or product.get("net_volume")
    if net_content:
        content_elem = etree.SubElement(meas_info, "netContent")
        content_elem.text = f"{float(net_content):.3f}"
        content_elem.set("measurementUnitCode", _get_volume_uom(product))

    # Dimensions
    _add_dimensions(meas_info, product)

    # Drained weight (for products in liquid)
    drained_weight = product.get("drained_weight")
    if drained_weight:
        drained_elem = etree.SubElement(meas_info, "drainedWeight")
        drained_elem.text = f"{float(drained_weight):.3f}"
        drained_elem.set("measurementUnitCode", _get_weight_uom(product))


def _add_dimensions(parent, product):
    """Add dimension elements for measurements.

    Args:
        parent: Parent tradeItemMeasurements element
        product: Product document
    """
    from lxml import etree

    # Height
    height = product.get("height")
    if height:
        elem = etree.SubElement(parent, "height")
        elem.text = f"{float(height):.3f}"
        elem.set("measurementUnitCode", _get_dimension_uom(product))

    # Width
    width = product.get("width")
    if width:
        elem = etree.SubElement(parent, "width")
        elem.text = f"{float(width):.3f}"
        elem.set("measurementUnitCode", _get_dimension_uom(product))

    # Depth
    depth = product.get("depth") or product.get("length")
    if depth:
        elem = etree.SubElement(parent, "depth")
        elem.text = f"{float(depth):.3f}"
        elem.set("measurementUnitCode", _get_dimension_uom(product))


def _add_trade_item_hierarchy(parent, product):
    """Add tradeItemHierarchyModule.

    Args:
        parent: Parent extension element
        product: Product document
    """
    from lxml import etree

    hier_ns = "urn:gs1:gdsn:trade_item_hierarchy:xsd:3"

    hier_module = etree.SubElement(parent, f"{{{hier_ns}}}tradeItemHierarchyModule")
    hier_info = etree.SubElement(hier_module, f"{{{hier_ns}}}tradeItemHierarchy")

    # Trade item unit descriptor (EACH, CASE, PALLET, etc.)
    unit_descriptor = product.get("trade_item_unit_descriptor") or "EACH"
    unit_elem = etree.SubElement(hier_info, "tradeItemUnitDescriptor")
    unit_elem.text = unit_descriptor.upper()

    # Is trade item a base unit
    is_base = product.get("is_base_unit", True)
    base_unit = etree.SubElement(hier_info, "isTradeItemABaseUnit")
    base_unit.text = "true" if is_base else "false"

    # Is trade item a consumer unit
    is_consumer = product.get("is_consumer_unit", True)
    consumer_unit = etree.SubElement(hier_info, "isTradeItemAConsumerUnit")
    consumer_unit.text = "true" if is_consumer else "false"

    # Is trade item a dispatch unit
    is_dispatch = product.get("is_dispatch_unit", False)
    dispatch_unit = etree.SubElement(hier_info, "isTradeItemADispatchUnit")
    dispatch_unit.text = "true" if is_dispatch else "false"

    # Is trade item an invoice unit
    is_invoice = product.get("is_invoice_unit", True)
    invoice_unit = etree.SubElement(hier_info, "isTradeItemAnInvoiceUnit")
    invoice_unit.text = "true" if is_invoice else "false"

    # Is trade item an orderable unit
    is_orderable = product.get("is_orderable_unit", True)
    orderable_unit = etree.SubElement(hier_info, "isTradeItemAnOrderableUnit")
    orderable_unit.text = "true" if is_orderable else "false"

    # Quantity of next lower level trade item
    qty_next = product.get("quantity_of_children") or product.get("packing_qty")
    if qty_next and int(qty_next) > 0:
        qty_elem = etree.SubElement(hier_info, "quantityOfNextLowerLevelTradeItem")
        qty_elem.text = str(int(qty_next))

        # Child GTIN (if specified)
        child_gtin = product.get("child_gtin") or product.get("inner_gtin")
        if child_gtin:
            child = etree.SubElement(hier_info, "childTradeItem")
            child_gtin_elem = etree.SubElement(child, f"{{{GS1_SHARED_NS}}}gtin")
            child_gtin_elem.text = _format_gtin(child_gtin)


def _add_gpc_classification(parent, product):
    """Add gdsnTradeItemClassificationModule with GPC codes.

    Args:
        parent: Parent extension element
        product: Product document
    """
    from lxml import etree

    class_ns = "urn:gs1:gdsn:gdsn_trade_item_classification:xsd:3"

    class_module = etree.SubElement(parent, f"{{{class_ns}}}gdsnTradeItemClassificationModule")

    # GPC category code
    gpc_code = product.get("gpc_code") or product.get("commodity_code")
    if gpc_code:
        gpc_elem = etree.SubElement(class_module, "gpcCategoryCode")
        gpc_elem.text = str(gpc_code)[:8].zfill(8)  # GPC is 8 digits

    # Additional classification codes (UNSPSC, HS, etc.)
    unspsc = product.get("unspsc_code")
    if unspsc:
        add_class = etree.SubElement(class_module, "additionalTradeItemClassification")
        add_class_code = etree.SubElement(add_class, "additionalTradeItemClassificationCode")
        add_class_code.text = unspsc
        add_class_sys = etree.SubElement(add_class, "additionalTradeItemClassificationSystemCode")
        add_class_sys.text = "UNSPSC"

    # HS Code
    hs_code = product.get("customs_tariff_number") or product.get("hs_code")
    if hs_code:
        add_class = etree.SubElement(class_module, "additionalTradeItemClassification")
        add_class_code = etree.SubElement(add_class, "additionalTradeItemClassificationCode")
        add_class_code.text = hs_code
        add_class_sys = etree.SubElement(add_class, "additionalTradeItemClassificationSystemCode")
        add_class_sys.text = "HS"


def _add_brand_information(parent, product, gln_brand_owner, language):
    """Add tradeItemBrandInformationModule.

    Args:
        parent: Parent extension element
        product: Product document
        gln_brand_owner: Brand owner GLN
        language: Language code
    """
    from lxml import etree

    brand_ns = "urn:gs1:gdsn:trade_item_brand_information:xsd:3"

    brand_module = etree.SubElement(parent, f"{{{brand_ns}}}tradeItemBrandInformationModule")

    # Brand owner
    brand_owner = etree.SubElement(brand_module, "brandOwner")
    gln_elem = etree.SubElement(brand_owner, f"{{{GS1_SHARED_NS}}}gln")
    gln_elem.text = gln_brand_owner

    # Brand owner name
    owner_name = product.get("brand_owner_name") or product.get("company_name")
    if owner_name:
        name_elem = etree.SubElement(brand_owner, "partyName")
        name_elem.text = owner_name
        name_elem.set("languageCode", language)

    # Sub-brand
    sub_brand = product.get("sub_brand")
    if sub_brand:
        sub_brand_elem = etree.SubElement(brand_module, "subBrand")
        sub_brand_elem.text = sub_brand
        sub_brand_elem.set("languageCode", language)


def _add_packaging_information(parent, product, language):
    """Add packagingInformationModule.

    Args:
        parent: Parent extension element
        product: Product document
        language: Language code
    """
    from lxml import etree

    pkg_ns = "urn:gs1:gdsn:packaging_information:xsd:3"

    pkg_module = etree.SubElement(parent, f"{{{pkg_ns}}}packagingInformationModule")
    pkg_info = etree.SubElement(pkg_module, f"{{{pkg_ns}}}packaging")

    # Packaging type code
    pkg_type = product.get("packaging_type_code") or _infer_packaging_type(product)
    if pkg_type:
        pkg_type_elem = etree.SubElement(pkg_info, "packagingTypeCode")
        pkg_type_elem.text = pkg_type

    # Packaging material
    pkg_material = product.get("packaging_material_type_code")
    if pkg_material:
        pkg_mat_elem = etree.SubElement(pkg_info, "packagingMaterialTypeCode")
        pkg_mat_elem.text = pkg_material

    # Packaging recycling scheme
    recycling = product.get("packaging_recycling_scheme_code")
    if recycling:
        recycling_elem = etree.SubElement(pkg_info, "packagingRecyclingSchemeCode")
        recycling_elem.text = recycling

    # Platform type code (for pallets)
    platform = product.get("platform_type_code")
    if platform:
        platform_elem = etree.SubElement(pkg_info, "platformTypeCode")
        platform_elem.text = platform

    # Packaging marked label accreditation
    label_accred = product.get("packaging_marked_label_accreditation_code")
    if label_accred:
        label_elem = etree.SubElement(pkg_info, "packagingMarkedLabelAccreditationCode")
        label_elem.text = label_accred


def _add_price_information(parent, product):
    """Add priceInformationModule.

    Args:
        parent: Parent extension element
        product: Product document
    """
    from lxml import etree

    price_ns = "urn:gs1:gdsn:price_information:xsd:3"

    price_value = product.get("suggested_retail_price") or product.get("price")
    if not price_value:
        return

    price_module = etree.SubElement(parent, f"{{{price_ns}}}priceInformationModule")
    price_info = etree.SubElement(price_module, f"{{{price_ns}}}tradeItemPrice")

    # Suggested retail price
    srp = etree.SubElement(price_info, "suggestedRetailPrice")
    srp.text = f"{float(price_value):.2f}"

    # Currency
    currency = product.get("currency") or "USD"
    currency_elem = etree.SubElement(price_info, "currencyCode")
    currency_elem.text = currency

    # Price basis quantity
    price_basis = etree.SubElement(price_info, "priceBasisQuantity")
    price_basis.text = "1"
    price_basis.set("measurementUnitCode", "EA")


def _add_certification_information(parent, product):
    """Add certificationInformationModule if applicable.

    Args:
        parent: Parent extension element
        product: Product document
    """
    from lxml import etree

    # Check for certifications
    certifications = product.get("certifications") or []
    if not certifications and not product.get("certification_agency"):
        return

    cert_ns = "urn:gs1:gdsn:certification_information:xsd:3"

    cert_module = etree.SubElement(parent, f"{{{cert_ns}}}certificationInformationModule")

    # Single certification from fields
    if product.get("certification_agency"):
        cert_info = etree.SubElement(cert_module, f"{{{cert_ns}}}certificationInformation")
        agency = etree.SubElement(cert_info, "certificationAgency")
        agency.text = product.get("certification_agency")

        cert_std = product.get("certification_standard")
        if cert_std:
            std_elem = etree.SubElement(cert_info, "certificationStandard")
            std_elem.text = cert_std

        cert_value = product.get("certification_value")
        if cert_value:
            value_elem = etree.SubElement(cert_info, "certificationValue")
            value_elem.text = cert_value

    # Multiple certifications from child table
    for cert in certifications:
        cert_info = etree.SubElement(cert_module, f"{{{cert_ns}}}certificationInformation")

        if cert.get("agency"):
            agency = etree.SubElement(cert_info, "certificationAgency")
            agency.text = cert.get("agency")

        if cert.get("standard"):
            std_elem = etree.SubElement(cert_info, "certificationStandard")
            std_elem.text = cert.get("standard")

        if cert.get("value"):
            value_elem = etree.SubElement(cert_info, "certificationValue")
            value_elem.text = cert.get("value")


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


def _get_gtin(product):
    """Get or generate GTIN for product.

    Args:
        product: Product document

    Returns:
        str: 14-digit GTIN
    """
    gtin = (
        product.get("gtin") or
        product.get("barcode") or
        product.get("ean")
    )

    if gtin:
        return _format_gtin(gtin)

    # Generate placeholder GTIN if none exists
    # In production, this should be a proper GS1 assigned GTIN
    return "00000000000000"


def _format_gtin(gtin):
    """Format GTIN to 14-digit standard format.

    Args:
        gtin: GTIN string (8, 12, 13, or 14 digits)

    Returns:
        str: 14-digit GTIN
    """
    if not gtin:
        return "00000000000000"

    # Remove any non-digit characters
    gtin = ''.join(filter(str.isdigit, str(gtin)))

    # Pad to 14 digits
    return gtin.zfill(14)


def _convert_to_numeric_country_code(code):
    """Convert ISO 3166-1 alpha-2 to numeric code.

    Args:
        code: Alpha-2 country code or numeric code

    Returns:
        str: ISO 3166-1 numeric code (3 digits)
    """
    # If already numeric, return as-is
    if code.isdigit():
        return code.zfill(3)

    # Common country code mappings
    alpha_to_numeric = {
        "US": "840",
        "GB": "826",
        "UK": "826",
        "DE": "276",
        "FR": "250",
        "IT": "380",
        "ES": "724",
        "NL": "528",
        "TR": "792",
        "CN": "156",
        "JP": "392",
        "KR": "410",
        "IN": "356",
        "BR": "076",
        "CA": "124",
        "AU": "036",
        "MX": "484",
        "RU": "643",
        "SA": "682",
        "AE": "784",
        "PL": "616",
        "SE": "752",
        "NO": "578",
        "DK": "208",
        "FI": "246",
        "BE": "056",
        "AT": "040",
        "CH": "756",
        "GR": "300",
        "PT": "620",
        "IE": "372",
        "CZ": "203",
        "HU": "348",
        "RO": "642",
        "BG": "100",
        "HR": "191",
        "SK": "703",
        "SI": "705"
    }

    return alpha_to_numeric.get(code.upper(), "001")  # 001 = Global


def _get_weight_uom(product):
    """Get GS1 measurement unit code for weight.

    Args:
        product: Product document

    Returns:
        str: GS1 UOM code
    """
    uom = product.get("weight_uom") or product.get("weight_per_unit_uom") or "Kg"

    uom_map = {
        "Kg": "KGM",
        "kg": "KGM",
        "Gram": "GRM",
        "gram": "GRM",
        "g": "GRM",
        "Lb": "LBR",
        "lb": "LBR",
        "Oz": "ONZ",
        "oz": "ONZ",
        "Mg": "MGM",
        "mg": "MGM"
    }

    return uom_map.get(uom, "KGM")


def _get_volume_uom(product):
    """Get GS1 measurement unit code for volume.

    Args:
        product: Product document

    Returns:
        str: GS1 UOM code
    """
    uom = product.get("volume_uom") or "Litre"

    uom_map = {
        "Litre": "LTR",
        "litre": "LTR",
        "L": "LTR",
        "l": "LTR",
        "Millilitre": "MLT",
        "ml": "MLT",
        "Gallon": "GLL",
        "gal": "GLL",
        "Fluid Oz": "OZA",
        "fl oz": "OZA",
        "Cubic Meter": "MTQ",
        "m3": "MTQ"
    }

    return uom_map.get(uom, "LTR")


def _get_dimension_uom(product):
    """Get GS1 measurement unit code for dimensions.

    Args:
        product: Product document

    Returns:
        str: GS1 UOM code
    """
    uom = product.get("dimension_uom") or product.get("length_uom") or "Cm"

    uom_map = {
        "Meter": "MTR",
        "m": "MTR",
        "Cm": "CMT",
        "cm": "CMT",
        "Mm": "MMT",
        "mm": "MMT",
        "Inch": "INH",
        "in": "INH",
        "Feet": "FOT",
        "ft": "FOT"
    }

    return uom_map.get(uom, "CMT")


def _infer_packaging_type(product):
    """Infer packaging type code from product data.

    Args:
        product: Product document

    Returns:
        str: GS1 packaging type code or None
    """
    # Check trade item unit descriptor
    unit_desc = product.get("trade_item_unit_descriptor", "").upper()

    unit_to_pkg = {
        "EACH": "NE",    # Not packed/unpackaged
        "PACK": "PK",    # Pack
        "CASE": "CS",    # Case
        "PALLET": "PX",  # Pallet
        "BOX": "BX",     # Box
        "BAG": "BG",     # Bag
        "CAN": "CA",     # Can
        "BOTTLE": "BO",  # Bottle
        "JAR": "JR",     # Jar
        "CARTON": "CT",  # Carton
        "TUBE": "TU",    # Tube
        "TRAY": "TR",    # Tray
        "DRUM": "DR"     # Drum
    }

    return unit_to_pkg.get(unit_desc)


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


def _save_export_file(content, profile_name=None, document_type="gs1_cin"):
    """Save export content to file.

    Args:
        content: XML content string
        profile_name: Export profile name (for filename)
        document_type: Document type for filename

    Returns:
        str: File path of saved file
    """
    import frappe

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name_part = profile_name or document_type
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


def validate_gtin(gtin):
    """Validate GTIN checksum using GS1 algorithm.

    Args:
        gtin: GTIN string (8, 12, 13, or 14 digits)

    Returns:
        tuple: (is_valid, error_message)
    """
    if not gtin:
        return False, "GTIN is required"

    # Remove non-digits
    gtin = ''.join(filter(str.isdigit, str(gtin)))

    # Check length
    if len(gtin) not in (8, 12, 13, 14):
        return False, f"GTIN must be 8, 12, 13, or 14 digits, got {len(gtin)}"

    # Pad to 14 digits for calculation
    gtin = gtin.zfill(14)

    # Calculate check digit
    total = 0
    for i, digit in enumerate(gtin[:-1]):
        weight = 3 if i % 2 == 0 else 1
        total += int(digit) * weight

    check_digit = (10 - (total % 10)) % 10

    if int(gtin[-1]) != check_digit:
        return False, f"Invalid check digit: expected {check_digit}, got {gtin[-1]}"

    return True, None


def validate_gs1_xml(xml_content):
    """Validate GS1 XML document structure.

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
        root_tag = doc.tag
        if not root_tag.endswith("catalogueItemNotification"):
            errors.append(f"Root element must be catalogueItemNotification, got {root_tag}")

        # Check for SBDH
        sbdh = doc.find(".//{http://www.unece.org/cefact/namespaces/StandardBusinessDocumentHeader}StandardBusinessDocumentHeader")
        if sbdh is None:
            errors.append("Missing Standard Business Document Header (SBDH)")

        # Check for transaction
        transaction = doc.find(".//transaction")
        if transaction is None:
            errors.append("Missing transaction element")

        # Check for at least one catalogue item
        catalogue_items = doc.findall(".//catalogueItem")
        if not catalogue_items:
            errors.append("No catalogueItem elements found")

        # Validate GTINs in document
        gtins = doc.findall(f".//{{{GS1_SHARED_NS}}}gtin")
        for gtin_elem in gtins:
            if gtin_elem.text:
                is_valid, error = validate_gtin(gtin_elem.text)
                if not is_valid and gtin_elem.text != "00000000000000":
                    errors.append(f"Invalid GTIN {gtin_elem.text}: {error}")

        return len(errors) == 0, errors

    except etree.XMLSyntaxError as e:
        return False, [f"XML Syntax Error: {str(e)}"]
    except Exception as e:
        return False, [f"Validation Error: {str(e)}"]


def get_trade_item_count(xml_content):
    """Count number of trade items in GS1 XML.

    Args:
        xml_content: XML content string

    Returns:
        int: Number of tradeItem elements
    """
    from lxml import etree

    try:
        doc = etree.fromstring(
            xml_content.encode() if isinstance(xml_content, str) else xml_content
        )
        items = doc.findall(".//tradeItem")
        return len(items)
    except Exception:
        return 0


def get_supported_target_markets():
    """Get list of supported target market codes.

    Returns:
        list: List of target market dictionaries
    """
    return [
        {"code": "001", "name": "Global"},
        {"code": "840", "name": "United States"},
        {"code": "826", "name": "United Kingdom"},
        {"code": "276", "name": "Germany"},
        {"code": "250", "name": "France"},
        {"code": "380", "name": "Italy"},
        {"code": "724", "name": "Spain"},
        {"code": "528", "name": "Netherlands"},
        {"code": "792", "name": "Turkey"},
        {"code": "156", "name": "China"},
        {"code": "392", "name": "Japan"},
        {"code": "410", "name": "South Korea"},
        {"code": "356", "name": "India"},
        {"code": "076", "name": "Brazil"},
        {"code": "124", "name": "Canada"},
        {"code": "036", "name": "Australia"},
    ]


def get_supported_document_commands():
    """Get list of supported GS1 document commands.

    Returns:
        list: List of document command dictionaries
    """
    return [
        {
            "code": GS1_COMMAND_ADD,
            "name": "Add",
            "description": "Add new trade item to data pool"
        },
        {
            "code": GS1_COMMAND_CHANGE,
            "name": "Change by Refresh",
            "description": "Update existing trade item (full replacement)"
        },
        {
            "code": GS1_COMMAND_DELETE,
            "name": "Delete",
            "description": "Remove trade item from data pool"
        },
        {
            "code": GS1_COMMAND_CORRECT,
            "name": "Correct",
            "description": "Correct trade item data"
        }
    ]
