"""UBL 2.x Export Module for Electronic Business Documents

This module provides functionality for generating UBL (Universal Business Language)
2.x compliant XML documents for B2B e-commerce and procurement. UBL is an OASIS
standard widely used for electronic document exchange.

The module supports:
- UBL 2.1/2.3 Catalogue documents for product data exchange
- CatalogueLines with item details and pricing
- Party information (supplier/buyer)
- Multi-language descriptions
- Item classifications (UNSPSC, commodity codes)
- Additional item properties (attributes)
- Item location quantities and pricing tiers
- Attachments and media references

Usage:
    from frappe_pim.pim.export.ubl import export_catalogue

    xml_content = export_catalogue(
        profile_name="my_ubl_profile",
        save_file=True
    )

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

import uuid
from datetime import datetime


# UBL 2.1 Namespaces
UBL_VERSION = "2.1"
UBL_NS = "urn:oasis:names:specification:ubl:schema:xsd:Catalogue-2"
CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

UBL_NSMAP = {
    None: UBL_NS,
    "cac": CAC_NS,
    "cbc": CBC_NS,
    "xsi": XSI_NS
}

# Schema location for validation
UBL_SCHEMA_LOCATION = (
    "urn:oasis:names:specification:ubl:schema:xsd:Catalogue-2 "
    "http://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-Catalogue-2.1.xsd"
)


def export_catalogue(
    profile_name=None,
    products=None,
    supplier_id=None,
    supplier_name=None,
    supplier_country="TR",
    buyer_id=None,
    buyer_name=None,
    catalogue_id=None,
    catalogue_name=None,
    currency="EUR",
    language="en",
    issue_date=None,
    validity_start=None,
    validity_end=None,
    include_prices=True,
    include_media=True,
    include_classifications=True,
    include_properties=True,
    ubl_version="2.1",
    pretty_print=True,
    save_file=False
):
    """Generate UBL 2.x Catalogue XML document.

    This function creates a UBL compliant XML document containing
    product catalog information. It can either use an Export Profile
    configuration or accept parameters directly.

    Args:
        profile_name: Name of Export Profile DocType to use for settings
        products: List of Product Master/Variant names to export (optional)
        supplier_id: Supplier party identifier (GLN, DUNS, or custom)
        supplier_name: Supplier party name
        supplier_country: Supplier country code (ISO 3166-1 alpha-2)
        buyer_id: Buyer party identifier (optional for open catalogues)
        buyer_name: Buyer party name
        catalogue_id: Unique identifier for the catalogue
        catalogue_name: Human-readable catalogue name
        currency: ISO 4217 currency code (default: EUR)
        language: ISO 639-1 language code (default: en)
        issue_date: Catalogue issue date (default: today)
        validity_start: Validity period start date
        validity_end: Validity period end date
        include_prices: Include pricing information
        include_media: Include media/attachment references
        include_classifications: Include commodity classifications
        include_properties: Include additional item properties
        ubl_version: UBL version string (2.1 or 2.3)
        pretty_print: Format XML with indentation
        save_file: Save to file and return file path

    Returns:
        str: XML content as string, or file path if save_file=True

    Raises:
        ValueError: If required parameters are missing
        ImportError: If lxml is not installed

    Example:
        >>> xml = export_catalogue(
        ...     profile_name="standard_ubl",
        ...     save_file=True
        ... )
        >>> print(xml)  # Returns file path
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for UBL export. "
            "Install with: pip install lxml"
        )

    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    # Override config with explicit parameters
    supplier_id = supplier_id or config.get("supplier_id", "SUPPLIER001")
    supplier_name = supplier_name or config.get("supplier_name", "Default Supplier")
    supplier_country = config.get("supplier_country", supplier_country)
    buyer_id = buyer_id or config.get("buyer_id")
    buyer_name = buyer_name or config.get("buyer_name")
    catalogue_id = catalogue_id or config.get("catalogue_id") or _generate_catalogue_id()
    catalogue_name = catalogue_name or config.get("catalogue_name", f"Product Catalogue {catalogue_id}")
    currency = config.get("currency", currency)
    language = config.get("language", language)
    include_prices = config.get("include_prices", include_prices)
    include_media = config.get("include_media", include_media)
    include_classifications = config.get("include_classifications", include_classifications)
    include_properties = config.get("include_properties", include_properties)
    ubl_version = config.get("ubl_version", ubl_version)
    pretty_print = config.get("pretty_print", pretty_print)

    # Set dates
    issue_date = issue_date or config.get("issue_date") or datetime.now().date()
    validity_start = validity_start or config.get("validity_start")
    validity_end = validity_end or config.get("validity_end")

    # Get products to export
    if products is None:
        products = _get_products_for_export(config)

    # Build XML document
    root = _build_ubl_catalogue(
        products=products,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        supplier_country=supplier_country,
        buyer_id=buyer_id,
        buyer_name=buyer_name,
        catalogue_id=catalogue_id,
        catalogue_name=catalogue_name,
        currency=currency,
        language=language,
        issue_date=issue_date,
        validity_start=validity_start,
        validity_end=validity_end,
        include_prices=include_prices,
        include_media=include_media,
        include_classifications=include_classifications,
        include_properties=include_properties,
        ubl_version=ubl_version
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
            catalogue_id=catalogue_id
        )

    return xml_content


def export_catalogue_async(profile_name, callback=None):
    """Queue catalogue export as background job.

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
        "frappe_pim.pim.export.ubl.export_catalogue",
        queue="long",
        timeout=3600,
        profile_name=profile_name,
        save_file=True
    )

    return job.id if hasattr(job, 'id') else str(job)


def export_invoice(
    profile_name=None,
    invoice_id=None,
    invoice_items=None,
    supplier_id=None,
    supplier_name=None,
    buyer_id=None,
    buyer_name=None,
    currency="EUR",
    issue_date=None,
    due_date=None,
    tax_rate=None,
    pretty_print=True,
    save_file=False
):
    """Generate UBL 2.x Invoice XML document.

    This function creates a UBL compliant Invoice document for
    B2B transaction processing.

    Args:
        profile_name: Name of Export Profile DocType
        invoice_id: Unique invoice identifier
        invoice_items: List of invoice line items
        supplier_id: Supplier party identifier
        supplier_name: Supplier party name
        buyer_id: Buyer party identifier
        buyer_name: Buyer party name
        currency: ISO 4217 currency code
        issue_date: Invoice issue date
        due_date: Payment due date
        tax_rate: Default tax rate percentage
        pretty_print: Format XML with indentation
        save_file: Save to file and return file path

    Returns:
        str: XML content as string, or file path if save_file=True
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for UBL export. "
            "Install with: pip install lxml"
        )

    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    # Override config with explicit parameters
    supplier_id = supplier_id or config.get("supplier_id", "SUPPLIER001")
    supplier_name = supplier_name or config.get("supplier_name", "Default Supplier")
    buyer_id = buyer_id or config.get("buyer_id", "BUYER001")
    buyer_name = buyer_name or config.get("buyer_name", "Buyer")
    currency = config.get("currency", currency)
    invoice_id = invoice_id or _generate_document_id("INV")
    issue_date = issue_date or datetime.now().date()
    due_date = due_date or issue_date
    tax_rate = tax_rate or config.get("tax_rate", 18.0)

    # Build invoice document
    root = _build_ubl_invoice(
        invoice_id=invoice_id,
        invoice_items=invoice_items or [],
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        buyer_id=buyer_id,
        buyer_name=buyer_name,
        currency=currency,
        issue_date=issue_date,
        due_date=due_date,
        tax_rate=tax_rate
    )

    # Serialize to XML string
    xml_content = etree.tostring(
        root,
        encoding="unicode",
        pretty_print=pretty_print,
        xml_declaration=True
    )

    if not xml_content.startswith("<?xml"):
        xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_content

    if save_file:
        return _save_export_file(
            xml_content,
            profile_name=profile_name,
            catalogue_id=invoice_id,
            file_prefix="ubl_invoice"
        )

    return xml_content


def export_order(
    profile_name=None,
    order_id=None,
    order_items=None,
    supplier_id=None,
    supplier_name=None,
    buyer_id=None,
    buyer_name=None,
    currency="EUR",
    issue_date=None,
    delivery_date=None,
    pretty_print=True,
    save_file=False
):
    """Generate UBL 2.x Order XML document.

    This function creates a UBL compliant Order document for
    B2B purchase order processing.

    Args:
        profile_name: Name of Export Profile DocType
        order_id: Unique order identifier
        order_items: List of order line items
        supplier_id: Supplier party identifier
        supplier_name: Supplier party name
        buyer_id: Buyer party identifier
        buyer_name: Buyer party name
        currency: ISO 4217 currency code
        issue_date: Order issue date
        delivery_date: Requested delivery date
        pretty_print: Format XML with indentation
        save_file: Save to file and return file path

    Returns:
        str: XML content as string, or file path if save_file=True
    """
    try:
        from lxml import etree
    except ImportError:
        raise ImportError(
            "lxml is required for UBL export. "
            "Install with: pip install lxml"
        )

    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    # Override config with explicit parameters
    supplier_id = supplier_id or config.get("supplier_id", "SUPPLIER001")
    supplier_name = supplier_name or config.get("supplier_name", "Default Supplier")
    buyer_id = buyer_id or config.get("buyer_id", "BUYER001")
    buyer_name = buyer_name or config.get("buyer_name", "Buyer")
    currency = config.get("currency", currency)
    order_id = order_id or _generate_document_id("ORD")
    issue_date = issue_date or datetime.now().date()
    delivery_date = delivery_date or issue_date

    # Build order document
    root = _build_ubl_order(
        order_id=order_id,
        order_items=order_items or [],
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        buyer_id=buyer_id,
        buyer_name=buyer_name,
        currency=currency,
        issue_date=issue_date,
        delivery_date=delivery_date
    )

    # Serialize to XML string
    xml_content = etree.tostring(
        root,
        encoding="unicode",
        pretty_print=pretty_print,
        xml_declaration=True
    )

    if not xml_content.startswith("<?xml"):
        xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_content

    if save_file:
        return _save_export_file(
            xml_content,
            profile_name=profile_name,
            catalogue_id=order_id,
            file_prefix="ubl_order"
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
        "supplier_id": profile.get("ubl_supplier_id") or profile.get("supplier_id"),
        "supplier_name": profile.get("ubl_supplier_name") or profile.get("supplier_name"),
        "supplier_country": profile.get("ubl_supplier_country") or profile.get("supplier_country"),
        "buyer_id": profile.get("ubl_buyer_id"),
        "buyer_name": profile.get("ubl_buyer_name"),
        "catalogue_id": profile.get("ubl_catalogue_id") or profile.get("catalog_id"),
        "catalogue_name": profile.get("ubl_catalogue_name"),
        "include_prices": profile.get("include_prices", True),
        "include_media": profile.get("include_media", True),
        "include_classifications": profile.get("include_classifications", True),
        "include_properties": profile.get("include_properties", True),
        "ubl_version": profile.get("ubl_version", "2.1"),
        "pretty_print": profile.get("pretty_print", True),
        "product_family": profile.get("product_family"),
        "status_filter": profile.get("status_filter"),
        "completeness_threshold": profile.get("completeness_threshold", 0),
        "output_filename": profile.get("output_filename"),
        "tax_rate": profile.get("default_tax_rate"),
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


def _generate_catalogue_id():
    """Generate unique catalogue identifier.

    Returns:
        str: Unique catalogue ID
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique = uuid.uuid4().hex[:8].upper()
    return f"CAT-{timestamp}-{unique}"


def _generate_document_id(prefix="DOC"):
    """Generate unique document identifier.

    Args:
        prefix: Document type prefix

    Returns:
        str: Unique document ID
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{timestamp}-{unique}"


def _build_ubl_catalogue(
    products,
    supplier_id,
    supplier_name,
    supplier_country,
    buyer_id,
    buyer_name,
    catalogue_id,
    catalogue_name,
    currency,
    language,
    issue_date,
    validity_start,
    validity_end,
    include_prices,
    include_media,
    include_classifications,
    include_properties,
    ubl_version
):
    """Build complete UBL Catalogue document structure.

    Args:
        products: List of product names to include
        supplier_id: Supplier identifier
        supplier_name: Supplier display name
        supplier_country: Supplier country code
        buyer_id: Buyer identifier (optional)
        buyer_name: Buyer display name (optional)
        catalogue_id: Catalogue identifier
        catalogue_name: Catalogue display name
        currency: ISO 4217 currency code
        language: ISO 639-1 language code
        issue_date: Catalogue issue date
        validity_start: Validity period start
        validity_end: Validity period end
        include_prices: Include price elements
        include_media: Include media elements
        include_classifications: Include classification elements
        include_properties: Include property elements
        ubl_version: UBL version string

    Returns:
        etree.Element: Root Catalogue element
    """
    from lxml import etree

    # Create root element with namespaces
    root = etree.Element(
        "Catalogue",
        nsmap=UBL_NSMAP
    )

    # Add schema location
    root.set(
        f"{{{XSI_NS}}}schemaLocation",
        UBL_SCHEMA_LOCATION
    )

    # UBL Version ID
    ubl_version_elem = etree.SubElement(root, f"{{{CBC_NS}}}UBLVersionID")
    ubl_version_elem.text = ubl_version

    # Customization ID
    customization = etree.SubElement(root, f"{{{CBC_NS}}}CustomizationID")
    customization.text = "urn:frappe-pim:ubl:catalogue:1.0"

    # Profile ID
    profile = etree.SubElement(root, f"{{{CBC_NS}}}ProfileID")
    profile.text = "urn:fdc:peppol.eu:poacc:bis:catalogue_only:3"

    # ID (Catalogue ID)
    id_elem = etree.SubElement(root, f"{{{CBC_NS}}}ID")
    id_elem.text = catalogue_id

    # UUID
    uuid_elem = etree.SubElement(root, f"{{{CBC_NS}}}UUID")
    uuid_elem.text = str(uuid.uuid4())

    # Action Code (Add for new catalogues)
    action_code = etree.SubElement(root, f"{{{CBC_NS}}}ActionCode")
    action_code.text = "Add"

    # Name
    name_elem = etree.SubElement(root, f"{{{CBC_NS}}}Name")
    name_elem.text = catalogue_name

    # Issue Date
    issue_date_elem = etree.SubElement(root, f"{{{CBC_NS}}}IssueDate")
    issue_date_elem.text = _format_date(issue_date)

    # Issue Time
    issue_time = etree.SubElement(root, f"{{{CBC_NS}}}IssueTime")
    issue_time.text = datetime.now().strftime("%H:%M:%S")

    # Validity Period
    if validity_start or validity_end:
        _add_validity_period(root, validity_start, validity_end)

    # Description
    desc_elem = etree.SubElement(root, f"{{{CBC_NS}}}Description")
    desc_elem.set("languageID", language)
    desc_elem.text = f"Product catalogue generated by Frappe PIM"

    # Version ID
    version = etree.SubElement(root, f"{{{CBC_NS}}}VersionID")
    version.text = "1"

    # Line Count Code
    line_count = etree.SubElement(root, f"{{{CBC_NS}}}LineCountNumeric")
    line_count.text = str(len(products))

    # Trading Terms (optional default currency)
    trading_terms = etree.SubElement(root, f"{{{CAC_NS}}}TradingTerms")
    ref_elem = etree.SubElement(trading_terms, f"{{{CBC_NS}}}Reference")
    ref_elem.text = f"Default currency: {currency}"

    # Provider Party (Supplier)
    _add_party(
        root,
        party_type="ProviderParty",
        party_id=supplier_id,
        party_name=supplier_name,
        country_code=supplier_country
    )

    # Receiver Party (Buyer) - optional
    if buyer_id or buyer_name:
        _add_party(
            root,
            party_type="ReceiverParty",
            party_id=buyer_id or "BUYER",
            party_name=buyer_name or "Buyer",
            country_code=supplier_country
        )

    # Seller Supplier Party
    seller_party = etree.SubElement(root, f"{{{CAC_NS}}}SellerSupplierParty")
    _add_party_details(
        seller_party,
        party_id=supplier_id,
        party_name=supplier_name,
        country_code=supplier_country
    )

    # Catalogue Lines
    for idx, product_name in enumerate(products, start=1):
        _add_catalogue_line(
            parent=root,
            product_name=product_name,
            line_number=idx,
            currency=currency,
            language=language,
            include_prices=include_prices,
            include_media=include_media,
            include_classifications=include_classifications,
            include_properties=include_properties
        )

    return root


def _build_ubl_invoice(
    invoice_id,
    invoice_items,
    supplier_id,
    supplier_name,
    buyer_id,
    buyer_name,
    currency,
    issue_date,
    due_date,
    tax_rate
):
    """Build UBL Invoice document structure.

    Args:
        invoice_id: Invoice identifier
        invoice_items: List of invoice line items
        supplier_id: Supplier identifier
        supplier_name: Supplier name
        buyer_id: Buyer identifier
        buyer_name: Buyer name
        currency: Currency code
        issue_date: Invoice issue date
        due_date: Payment due date
        tax_rate: Tax rate percentage

    Returns:
        etree.Element: Root Invoice element
    """
    from lxml import etree

    # Invoice namespace
    invoice_ns = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
    nsmap = {
        None: invoice_ns,
        "cac": CAC_NS,
        "cbc": CBC_NS,
        "xsi": XSI_NS
    }

    root = etree.Element("Invoice", nsmap=nsmap)

    # UBL Version
    version = etree.SubElement(root, f"{{{CBC_NS}}}UBLVersionID")
    version.text = UBL_VERSION

    # ID
    id_elem = etree.SubElement(root, f"{{{CBC_NS}}}ID")
    id_elem.text = invoice_id

    # Issue Date
    issue_elem = etree.SubElement(root, f"{{{CBC_NS}}}IssueDate")
    issue_elem.text = _format_date(issue_date)

    # Due Date
    due_elem = etree.SubElement(root, f"{{{CBC_NS}}}DueDate")
    due_elem.text = _format_date(due_date)

    # Invoice Type Code
    type_code = etree.SubElement(root, f"{{{CBC_NS}}}InvoiceTypeCode")
    type_code.text = "380"  # Commercial Invoice

    # Document Currency
    doc_currency = etree.SubElement(root, f"{{{CBC_NS}}}DocumentCurrencyCode")
    doc_currency.text = currency

    # Supplier Party
    supplier = etree.SubElement(root, f"{{{CAC_NS}}}AccountingSupplierParty")
    _add_party_details(supplier, supplier_id, supplier_name)

    # Buyer Party
    buyer = etree.SubElement(root, f"{{{CAC_NS}}}AccountingCustomerParty")
    _add_party_details(buyer, buyer_id, buyer_name)

    # Tax Total
    subtotal = sum(float(item.get("price", 0)) * int(item.get("quantity", 1)) for item in invoice_items)
    tax_amount = subtotal * (tax_rate / 100)
    _add_tax_total(root, tax_amount, tax_rate, currency)

    # Legal Monetary Total
    _add_monetary_total(root, subtotal, tax_amount, currency)

    # Invoice Lines
    for idx, item in enumerate(invoice_items, start=1):
        _add_invoice_line(root, item, idx, currency, tax_rate)

    return root


def _build_ubl_order(
    order_id,
    order_items,
    supplier_id,
    supplier_name,
    buyer_id,
    buyer_name,
    currency,
    issue_date,
    delivery_date
):
    """Build UBL Order document structure.

    Args:
        order_id: Order identifier
        order_items: List of order line items
        supplier_id: Supplier identifier
        supplier_name: Supplier name
        buyer_id: Buyer identifier
        buyer_name: Buyer name
        currency: Currency code
        issue_date: Order issue date
        delivery_date: Requested delivery date

    Returns:
        etree.Element: Root Order element
    """
    from lxml import etree

    # Order namespace
    order_ns = "urn:oasis:names:specification:ubl:schema:xsd:Order-2"
    nsmap = {
        None: order_ns,
        "cac": CAC_NS,
        "cbc": CBC_NS,
        "xsi": XSI_NS
    }

    root = etree.Element("Order", nsmap=nsmap)

    # UBL Version
    version = etree.SubElement(root, f"{{{CBC_NS}}}UBLVersionID")
    version.text = UBL_VERSION

    # ID
    id_elem = etree.SubElement(root, f"{{{CBC_NS}}}ID")
    id_elem.text = order_id

    # Issue Date
    issue_elem = etree.SubElement(root, f"{{{CBC_NS}}}IssueDate")
    issue_elem.text = _format_date(issue_date)

    # Document Currency
    doc_currency = etree.SubElement(root, f"{{{CBC_NS}}}DocumentCurrencyCode")
    doc_currency.text = currency

    # Buyer Party
    buyer = etree.SubElement(root, f"{{{CAC_NS}}}BuyerCustomerParty")
    _add_party_details(buyer, buyer_id, buyer_name)

    # Seller Party
    seller = etree.SubElement(root, f"{{{CAC_NS}}}SellerSupplierParty")
    _add_party_details(seller, supplier_id, supplier_name)

    # Delivery
    delivery = etree.SubElement(root, f"{{{CAC_NS}}}Delivery")
    req_delivery = etree.SubElement(delivery, f"{{{CAC_NS}}}RequestedDeliveryPeriod")
    start_date = etree.SubElement(req_delivery, f"{{{CBC_NS}}}StartDate")
    start_date.text = _format_date(delivery_date)

    # Order Lines
    for idx, item in enumerate(order_items, start=1):
        _add_order_line(root, item, idx, currency)

    return root


def _add_party(parent, party_type, party_id, party_name, country_code="TR"):
    """Add a Party element to parent.

    Args:
        parent: Parent XML element
        party_type: Type of party (ProviderParty, ReceiverParty)
        party_id: Party identifier
        party_name: Party display name
        country_code: ISO country code
    """
    from lxml import etree

    party_wrapper = etree.SubElement(parent, f"{{{CAC_NS}}}{party_type}")
    _add_party_details(party_wrapper, party_id, party_name, country_code)


def _add_party_details(parent, party_id, party_name, country_code="TR"):
    """Add Party details to parent element.

    Args:
        parent: Parent XML element
        party_id: Party identifier
        party_name: Party display name
        country_code: ISO country code
    """
    from lxml import etree

    party = etree.SubElement(parent, f"{{{CAC_NS}}}Party")

    # Endpoint ID (electronic address)
    endpoint = etree.SubElement(party, f"{{{CBC_NS}}}EndpointID")
    endpoint.set("schemeID", "0088")  # GLN scheme
    endpoint.text = party_id

    # Party Identification
    party_ident = etree.SubElement(party, f"{{{CAC_NS}}}PartyIdentification")
    id_elem = etree.SubElement(party_ident, f"{{{CBC_NS}}}ID")
    id_elem.set("schemeID", "0088")
    id_elem.text = party_id

    # Party Name
    party_name_elem = etree.SubElement(party, f"{{{CAC_NS}}}PartyName")
    name_elem = etree.SubElement(party_name_elem, f"{{{CBC_NS}}}Name")
    name_elem.text = party_name

    # Postal Address
    postal_address = etree.SubElement(party, f"{{{CAC_NS}}}PostalAddress")
    country = etree.SubElement(postal_address, f"{{{CAC_NS}}}Country")
    country_id = etree.SubElement(country, f"{{{CBC_NS}}}IdentificationCode")
    country_id.text = country_code


def _add_validity_period(parent, start_date, end_date):
    """Add ValidityPeriod element.

    Args:
        parent: Parent XML element
        start_date: Period start date
        end_date: Period end date
    """
    from lxml import etree

    validity = etree.SubElement(parent, f"{{{CAC_NS}}}ValidityPeriod")

    if start_date:
        start_elem = etree.SubElement(validity, f"{{{CBC_NS}}}StartDate")
        start_elem.text = _format_date(start_date)

    if end_date:
        end_elem = etree.SubElement(validity, f"{{{CBC_NS}}}EndDate")
        end_elem.text = _format_date(end_date)


def _add_catalogue_line(
    parent,
    product_name,
    line_number,
    currency,
    language,
    include_prices,
    include_media,
    include_classifications,
    include_properties
):
    """Add CatalogueLine element for a product.

    Args:
        parent: Parent Catalogue element
        product_name: Name of Product Variant to export
        line_number: Line number in catalogue
        currency: ISO 4217 currency code
        language: ISO 639-1 language code
        include_prices: Include price elements
        include_media: Include media elements
        include_classifications: Include classification elements
        include_properties: Include property elements

    Returns:
        etree.Element: CatalogueLine element or None
    """
    import frappe
    from lxml import etree

    product = _get_product_doc(product_name)
    if not product:
        return None

    catalogue_line = etree.SubElement(parent, f"{{{CAC_NS}}}CatalogueLine")

    # ID (line number)
    id_elem = etree.SubElement(catalogue_line, f"{{{CBC_NS}}}ID")
    id_elem.text = str(line_number)

    # Action Code
    action = etree.SubElement(catalogue_line, f"{{{CBC_NS}}}ActionCode")
    action.text = "Add"

    # Orderable Indicator
    orderable = etree.SubElement(catalogue_line, f"{{{CBC_NS}}}OrderableIndicator")
    orderable.text = "true" if product.get("is_sales_item", True) else "false"

    # Orderable Unit
    orderable_unit = etree.SubElement(catalogue_line, f"{{{CBC_NS}}}OrderableUnit")
    orderable_unit.text = _map_uom_to_unece(product.get("stock_uom", "Nos"))

    # Content Unit Quantity
    content_qty = etree.SubElement(catalogue_line, f"{{{CBC_NS}}}ContentUnitQuantity")
    content_qty.set("unitCode", _map_uom_to_unece(product.get("stock_uom", "Nos")))
    content_qty.text = "1"

    # Order Quantity Increment
    order_increment = etree.SubElement(catalogue_line, f"{{{CBC_NS}}}OrderQuantityIncrementNumeric")
    order_increment.text = "1"

    # Minimum Order Quantity
    min_qty = product.get("minimum_order_qty") or 1
    min_qty_elem = etree.SubElement(catalogue_line, f"{{{CBC_NS}}}MinimumOrderQuantity")
    min_qty_elem.set("unitCode", _map_uom_to_unece(product.get("stock_uom", "Nos")))
    min_qty_elem.text = str(min_qty)

    # Required Item Location Quantity (pricing)
    if include_prices:
        _add_item_location_quantity(catalogue_line, product, currency)

    # Item
    _add_item(
        parent=catalogue_line,
        product=product,
        language=language,
        include_media=include_media,
        include_classifications=include_classifications,
        include_properties=include_properties
    )

    return catalogue_line


def _add_item(
    parent,
    product,
    language,
    include_media,
    include_classifications,
    include_properties
):
    """Add Item element with product details.

    Args:
        parent: Parent CatalogueLine element
        product: Product document
        language: ISO 639-1 language code
        include_media: Include media elements
        include_classifications: Include classification elements
        include_properties: Include property elements

    Returns:
        etree.Element: Item element
    """
    from lxml import etree

    item = etree.SubElement(parent, f"{{{CAC_NS}}}Item")

    # Description
    desc_text = product.get("description") or product.get("short_description")
    if desc_text:
        desc = etree.SubElement(item, f"{{{CBC_NS}}}Description")
        desc.set("languageID", language)
        desc.text = _clean_html(desc_text)[:2000]  # UBL limit

    # Pack Quantity
    pack_qty = etree.SubElement(item, f"{{{CBC_NS}}}PackQuantity")
    pack_qty.set("unitCode", _map_uom_to_unece(product.get("stock_uom", "Nos")))
    pack_qty.text = "1"

    # Pack Size (numeric)
    pack_size = etree.SubElement(item, f"{{{CBC_NS}}}PackSizeNumeric")
    pack_size.text = "1"

    # Name
    name_elem = etree.SubElement(item, f"{{{CBC_NS}}}Name")
    name_elem.set("languageID", language)
    name_elem.text = (
        product.get("variant_name") or
        product.get("product_name") or
        product.name
    )[:200]

    # Keyword (for search)
    keywords = product.get("search_keywords") or product.get("item_group")
    if keywords:
        keyword_elem = etree.SubElement(item, f"{{{CBC_NS}}}Keyword")
        keyword_elem.set("languageID", language)
        keyword_elem.text = keywords[:100]

    # Brand Name
    brand = product.get("brand") or product.get("manufacturer")
    if brand:
        brand_elem = etree.SubElement(item, f"{{{CBC_NS}}}BrandName")
        brand_elem.text = brand

    # Model Name
    model = product.get("model") or product.get("manufacturer_part_number")
    if model:
        model_elem = etree.SubElement(item, f"{{{CBC_NS}}}ModelName")
        model_elem.text = model

    # Buyer's Item Identification
    buyer_item_id = product.get("customer_code")
    if buyer_item_id:
        buyers_item = etree.SubElement(item, f"{{{CAC_NS}}}BuyersItemIdentification")
        id_elem = etree.SubElement(buyers_item, f"{{{CBC_NS}}}ID")
        id_elem.text = buyer_item_id

    # Seller's Item Identification (SKU)
    sku = product.get("variant_code") or product.get("product_code") or product.name
    sellers_item = etree.SubElement(item, f"{{{CAC_NS}}}SellersItemIdentification")
    id_elem = etree.SubElement(sellers_item, f"{{{CBC_NS}}}ID")
    id_elem.text = sku

    # Manufacturer's Item Identification
    mfg_part = product.get("manufacturer_part_number")
    if mfg_part:
        mfg_item = etree.SubElement(item, f"{{{CAC_NS}}}ManufacturersItemIdentification")
        id_elem = etree.SubElement(mfg_item, f"{{{CBC_NS}}}ID")
        id_elem.text = mfg_part

    # Standard Item Identification (GTIN/EAN)
    barcode = product.get("barcode") or product.get("ean") or product.get("gtin")
    if barcode:
        std_item = etree.SubElement(item, f"{{{CAC_NS}}}StandardItemIdentification")
        id_elem = etree.SubElement(std_item, f"{{{CBC_NS}}}ID")
        id_elem.set("schemeID", "GTIN")
        id_elem.text = barcode

    # Item Specification Document Reference (media)
    if include_media:
        _add_document_references(item, product)

    # Origin Country
    origin_country = product.get("country_of_origin")
    if origin_country:
        origin = etree.SubElement(item, f"{{{CAC_NS}}}OriginCountry")
        country_id = etree.SubElement(origin, f"{{{CBC_NS}}}IdentificationCode")
        country_id.text = origin_country[:2].upper()

    # Commodity Classification
    if include_classifications:
        _add_commodity_classifications(item, product)

    # Additional Item Properties
    if include_properties:
        _add_additional_properties(item, product, language)

    # Manufacturer Party
    manufacturer = product.get("manufacturer")
    if manufacturer:
        _add_manufacturer_party(item, manufacturer)

    return item


def _add_item_location_quantity(parent, product, currency):
    """Add RequiredItemLocationQuantity element with pricing.

    Args:
        parent: Parent CatalogueLine element
        product: Product document
        currency: Currency code
    """
    from lxml import etree

    price_value = product.get("price") or product.get("standard_rate")
    if not price_value:
        return

    item_loc_qty = etree.SubElement(parent, f"{{{CAC_NS}}}RequiredItemLocationQuantity")

    # Lead Time Measure
    lead_time = product.get("lead_time_days")
    if lead_time:
        lead_measure = etree.SubElement(item_loc_qty, f"{{{CBC_NS}}}LeadTimeMeasure")
        lead_measure.set("unitCode", "DAY")
        lead_measure.text = str(int(lead_time))

    # Price
    price = etree.SubElement(item_loc_qty, f"{{{CAC_NS}}}Price")

    # Price Amount
    price_amount = etree.SubElement(price, f"{{{CBC_NS}}}PriceAmount")
    price_amount.set("currencyID", currency)
    price_amount.text = f"{float(price_value):.2f}"

    # Base Quantity
    base_qty = etree.SubElement(price, f"{{{CBC_NS}}}BaseQuantity")
    base_qty.set("unitCode", _map_uom_to_unece(product.get("stock_uom", "Nos")))
    base_qty.text = "1"

    # Price Type (net/gross)
    price_type = etree.SubElement(price, f"{{{CBC_NS}}}PriceTypeCode")
    price_type.text = "01"  # Catalogue price

    # Ordering Period (if applicable)
    validity_days = product.get("price_validity_days")
    if validity_days:
        order_period = etree.SubElement(price, f"{{{CBC_NS}}}OrderableUnitFactorRate")
        order_period.text = "1"


def _add_document_references(parent, product):
    """Add ItemSpecificationDocumentReference elements for media.

    Args:
        parent: Parent Item element
        product: Product document
    """
    from lxml import etree

    # Primary image
    primary_image = product.get("image")
    if primary_image:
        doc_ref = etree.SubElement(parent, f"{{{CAC_NS}}}ItemSpecificationDocumentReference")
        id_elem = etree.SubElement(doc_ref, f"{{{CBC_NS}}}ID")
        id_elem.text = "PRIMARY_IMAGE"
        attachment = etree.SubElement(doc_ref, f"{{{CAC_NS}}}Attachment")
        ext_ref = etree.SubElement(attachment, f"{{{CAC_NS}}}ExternalReference")
        uri = etree.SubElement(ext_ref, f"{{{CBC_NS}}}URI")
        uri.text = _get_full_url(primary_image)

    # Additional media
    media_list = product.get("media") or []
    for idx, media in enumerate(media_list[:10]):  # Limit to 10
        media_url = media.get("file_url") or media.get("url")
        if media_url:
            doc_ref = etree.SubElement(parent, f"{{{CAC_NS}}}ItemSpecificationDocumentReference")
            id_elem = etree.SubElement(doc_ref, f"{{{CBC_NS}}}ID")
            id_elem.text = f"MEDIA_{idx + 1}"
            doc_type = etree.SubElement(doc_ref, f"{{{CBC_NS}}}DocumentTypeCode")
            doc_type.text = media.get("media_type", "Image")
            attachment = etree.SubElement(doc_ref, f"{{{CAC_NS}}}Attachment")
            ext_ref = etree.SubElement(attachment, f"{{{CAC_NS}}}ExternalReference")
            uri = etree.SubElement(ext_ref, f"{{{CBC_NS}}}URI")
            uri.text = _get_full_url(media_url)


def _add_commodity_classifications(parent, product):
    """Add CommodityClassification elements.

    Args:
        parent: Parent Item element
        product: Product document
    """
    from lxml import etree

    # UNSPSC
    unspsc = product.get("unspsc_code") or product.get("commodity_code")
    if unspsc:
        classification = etree.SubElement(parent, f"{{{CAC_NS}}}CommodityClassification")
        item_class = etree.SubElement(classification, f"{{{CBC_NS}}}ItemClassificationCode")
        item_class.set("listID", "UNSPSC")
        item_class.text = unspsc

    # HS Code (harmonized system)
    hs_code = product.get("customs_tariff_number") or product.get("hs_code")
    if hs_code:
        classification = etree.SubElement(parent, f"{{{CAC_NS}}}CommodityClassification")
        item_class = etree.SubElement(classification, f"{{{CBC_NS}}}ItemClassificationCode")
        item_class.set("listID", "HS")
        item_class.text = hs_code

    # Category
    category = product.get("item_group") or product.get("product_category")
    if category:
        classification = etree.SubElement(parent, f"{{{CAC_NS}}}CommodityClassification")
        item_class = etree.SubElement(classification, f"{{{CBC_NS}}}ItemClassificationCode")
        item_class.set("listID", "CATEGORY")
        item_class.text = category


def _add_additional_properties(parent, product, language):
    """Add AdditionalItemProperty elements for attributes.

    Args:
        parent: Parent Item element
        product: Product document
        language: Language code
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

        # Add property
        prop = etree.SubElement(parent, f"{{{CAC_NS}}}AdditionalItemProperty")

        # Name
        name_elem = etree.SubElement(prop, f"{{{CBC_NS}}}Name")
        name_elem.set("languageID", language)
        name_elem.text = attr_meta.get("attribute_name", attr_code)

        # Value
        value_elem = etree.SubElement(prop, f"{{{CBC_NS}}}Value")
        value_elem.set("languageID", language)
        value_elem.text = str(value)

        # Value Qualifier (unit)
        unit = attr_meta.get("unit")
        if unit:
            qualifier = etree.SubElement(prop, f"{{{CBC_NS}}}ValueQualifier")
            qualifier.text = unit


def _add_manufacturer_party(parent, manufacturer_name):
    """Add ManufacturerParty element.

    Args:
        parent: Parent Item element
        manufacturer_name: Manufacturer name string
    """
    from lxml import etree

    mfg_party = etree.SubElement(parent, f"{{{CAC_NS}}}ManufacturerParty")
    party_name = etree.SubElement(mfg_party, f"{{{CAC_NS}}}PartyName")
    name_elem = etree.SubElement(party_name, f"{{{CBC_NS}}}Name")
    name_elem.text = manufacturer_name


def _add_tax_total(parent, tax_amount, tax_rate, currency):
    """Add TaxTotal element for invoice.

    Args:
        parent: Parent element
        tax_amount: Total tax amount
        tax_rate: Tax rate percentage
        currency: Currency code
    """
    from lxml import etree

    tax_total = etree.SubElement(parent, f"{{{CAC_NS}}}TaxTotal")

    # Tax Amount
    amount = etree.SubElement(tax_total, f"{{{CBC_NS}}}TaxAmount")
    amount.set("currencyID", currency)
    amount.text = f"{tax_amount:.2f}"

    # Tax Subtotal
    tax_subtotal = etree.SubElement(tax_total, f"{{{CAC_NS}}}TaxSubtotal")

    taxable = etree.SubElement(tax_subtotal, f"{{{CBC_NS}}}TaxableAmount")
    taxable.set("currencyID", currency)
    taxable.text = f"{(tax_amount / (tax_rate / 100)):.2f}"

    subtotal_amount = etree.SubElement(tax_subtotal, f"{{{CBC_NS}}}TaxAmount")
    subtotal_amount.set("currencyID", currency)
    subtotal_amount.text = f"{tax_amount:.2f}"

    # Tax Category
    tax_category = etree.SubElement(tax_subtotal, f"{{{CAC_NS}}}TaxCategory")
    id_elem = etree.SubElement(tax_category, f"{{{CBC_NS}}}ID")
    id_elem.text = "S"  # Standard rate
    percent = etree.SubElement(tax_category, f"{{{CBC_NS}}}Percent")
    percent.text = f"{tax_rate:.2f}"
    tax_scheme = etree.SubElement(tax_category, f"{{{CAC_NS}}}TaxScheme")
    scheme_id = etree.SubElement(tax_scheme, f"{{{CBC_NS}}}ID")
    scheme_id.text = "VAT"


def _add_monetary_total(parent, subtotal, tax_amount, currency):
    """Add LegalMonetaryTotal element for invoice.

    Args:
        parent: Parent element
        subtotal: Subtotal amount before tax
        tax_amount: Tax amount
        currency: Currency code
    """
    from lxml import etree

    total = etree.SubElement(parent, f"{{{CAC_NS}}}LegalMonetaryTotal")

    line_ext = etree.SubElement(total, f"{{{CBC_NS}}}LineExtensionAmount")
    line_ext.set("currencyID", currency)
    line_ext.text = f"{subtotal:.2f}"

    tax_excl = etree.SubElement(total, f"{{{CBC_NS}}}TaxExclusiveAmount")
    tax_excl.set("currencyID", currency)
    tax_excl.text = f"{subtotal:.2f}"

    tax_incl = etree.SubElement(total, f"{{{CBC_NS}}}TaxInclusiveAmount")
    tax_incl.set("currencyID", currency)
    tax_incl.text = f"{(subtotal + tax_amount):.2f}"

    payable = etree.SubElement(total, f"{{{CBC_NS}}}PayableAmount")
    payable.set("currencyID", currency)
    payable.text = f"{(subtotal + tax_amount):.2f}"


def _add_invoice_line(parent, item, line_number, currency, tax_rate):
    """Add InvoiceLine element.

    Args:
        parent: Parent element
        item: Line item dictionary
        line_number: Line number
        currency: Currency code
        tax_rate: Tax rate percentage
    """
    from lxml import etree

    line = etree.SubElement(parent, f"{{{CAC_NS}}}InvoiceLine")

    # ID
    id_elem = etree.SubElement(line, f"{{{CBC_NS}}}ID")
    id_elem.text = str(line_number)

    # Invoiced Quantity
    qty = etree.SubElement(line, f"{{{CBC_NS}}}InvoicedQuantity")
    qty.set("unitCode", item.get("uom", "EA"))
    qty.text = str(item.get("quantity", 1))

    # Line Extension Amount
    line_amount = float(item.get("price", 0)) * int(item.get("quantity", 1))
    amount = etree.SubElement(line, f"{{{CBC_NS}}}LineExtensionAmount")
    amount.set("currencyID", currency)
    amount.text = f"{line_amount:.2f}"

    # Tax Total for line
    tax_amount = line_amount * (tax_rate / 100)
    _add_tax_total(line, tax_amount, tax_rate, currency)

    # Item
    item_elem = etree.SubElement(line, f"{{{CAC_NS}}}Item")
    name = etree.SubElement(item_elem, f"{{{CBC_NS}}}Name")
    name.text = item.get("name", item.get("sku", "Item"))

    sellers_item = etree.SubElement(item_elem, f"{{{CAC_NS}}}SellersItemIdentification")
    seller_id = etree.SubElement(sellers_item, f"{{{CBC_NS}}}ID")
    seller_id.text = item.get("sku", "")

    # Price
    price = etree.SubElement(line, f"{{{CAC_NS}}}Price")
    price_amount = etree.SubElement(price, f"{{{CBC_NS}}}PriceAmount")
    price_amount.set("currencyID", currency)
    price_amount.text = f"{float(item.get('price', 0)):.2f}"


def _add_order_line(parent, item, line_number, currency):
    """Add OrderLine element.

    Args:
        parent: Parent element
        item: Line item dictionary
        line_number: Line number
        currency: Currency code
    """
    from lxml import etree

    line = etree.SubElement(parent, f"{{{CAC_NS}}}OrderLine")

    # Line Item
    line_item = etree.SubElement(line, f"{{{CAC_NS}}}LineItem")

    # ID
    id_elem = etree.SubElement(line_item, f"{{{CBC_NS}}}ID")
    id_elem.text = str(line_number)

    # Quantity
    qty = etree.SubElement(line_item, f"{{{CBC_NS}}}Quantity")
    qty.set("unitCode", item.get("uom", "EA"))
    qty.text = str(item.get("quantity", 1))

    # Line Extension Amount
    line_amount = float(item.get("price", 0)) * int(item.get("quantity", 1))
    amount = etree.SubElement(line_item, f"{{{CBC_NS}}}LineExtensionAmount")
    amount.set("currencyID", currency)
    amount.text = f"{line_amount:.2f}"

    # Price
    price = etree.SubElement(line_item, f"{{{CAC_NS}}}Price")
    price_amount = etree.SubElement(price, f"{{{CBC_NS}}}PriceAmount")
    price_amount.set("currencyID", currency)
    price_amount.text = f"{float(item.get('price', 0)):.2f}"

    # Item
    item_elem = etree.SubElement(line_item, f"{{{CAC_NS}}}Item")
    name = etree.SubElement(item_elem, f"{{{CBC_NS}}}Name")
    name.text = item.get("name", item.get("sku", "Item"))

    sellers_item = etree.SubElement(item_elem, f"{{{CAC_NS}}}SellersItemIdentification")
    seller_id = etree.SubElement(sellers_item, f"{{{CBC_NS}}}ID")
    seller_id.text = item.get("sku", "")


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
                return "true" if value else "false"
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
        "Mm": "MMT",
        "Inch": "INH",
        "Feet": "FOT",
        "Sq. Meter": "MTK",
        "Sq. Feet": "FTK",
        "Cubic Meter": "MTQ",
        "Hour": "HUR",
        "Day": "DAY"
    }

    return uom_map.get(frappe_uom, "EA")


def _format_date(date_value):
    """Format date value to ISO 8601 date string.

    Args:
        date_value: Date object, datetime object, or string

    Returns:
        str: ISO 8601 date string (YYYY-MM-DD)
    """
    if not date_value:
        return datetime.now().strftime("%Y-%m-%d")

    if isinstance(date_value, str):
        return date_value[:10]

    if hasattr(date_value, 'strftime'):
        return date_value.strftime("%Y-%m-%d")

    return str(date_value)[:10]


def _save_export_file(content, profile_name=None, catalogue_id=None, file_prefix="ubl_catalogue"):
    """Save export content to file.

    Args:
        content: XML content string
        profile_name: Export profile name (for filename)
        catalogue_id: Catalogue ID (for filename)
        file_prefix: Prefix for filename

    Returns:
        str: File path of saved file
    """
    import frappe

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name_part = profile_name or catalogue_id or file_prefix
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


def validate_ubl_catalogue(xml_content):
    """Validate UBL Catalogue document structure.

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
        if not root_tag.endswith("Catalogue"):
            errors.append(f"Root element must be Catalogue, got {root_tag}")

        # Check for UBLVersionID
        version = doc.find(f".//{{{CBC_NS}}}UBLVersionID")
        if version is None:
            errors.append("Missing required UBLVersionID element")

        # Check for ID
        id_elem = doc.find(f".//{{{CBC_NS}}}ID")
        if id_elem is None:
            errors.append("Missing required ID element")

        # Check for ProviderParty
        provider = doc.find(f".//{{{CAC_NS}}}ProviderParty")
        if provider is None:
            errors.append("Missing required ProviderParty element")

        # Check for at least one CatalogueLine
        lines = doc.findall(f".//{{{CAC_NS}}}CatalogueLine")
        if not lines:
            errors.append("Catalogue must contain at least one CatalogueLine")

        return len(errors) == 0, errors

    except etree.XMLSyntaxError as e:
        return False, [f"XML Syntax Error: {str(e)}"]
    except Exception as e:
        return False, [f"Validation Error: {str(e)}"]


def get_catalogue_line_count(xml_content):
    """Count number of catalogue lines in UBL Catalogue.

    Args:
        xml_content: XML content string

    Returns:
        int: Number of CatalogueLine elements
    """
    from lxml import etree

    try:
        doc = etree.fromstring(
            xml_content.encode() if isinstance(xml_content, str) else xml_content
        )
        lines = doc.findall(f".//{{{CAC_NS}}}CatalogueLine")
        return len(lines)
    except Exception:
        return 0


def get_supported_document_types():
    """Get list of supported UBL document types.

    Returns:
        list: List of supported document type dictionaries
    """
    return [
        {
            "type": "Catalogue",
            "description": "Product catalogue for B2B catalog exchange",
            "export_function": "export_catalogue"
        },
        {
            "type": "Invoice",
            "description": "Commercial invoice for billing",
            "export_function": "export_invoice"
        },
        {
            "type": "Order",
            "description": "Purchase order for procurement",
            "export_function": "export_order"
        }
    ]
