"""EDIFACT Export Module for Traditional EDI Systems

This module provides functionality for generating UN/EDIFACT compliant
messages for electronic data interchange. EDIFACT (Electronic Data
Interchange for Administration, Commerce and Transport) is the international
EDI standard developed under the United Nations.

The module supports:
- PRICAT (Price/Catalogue) messages for product catalogs
- PRODAT (Product Data) messages for detailed product specifications
- Service segments (UNA, UNB, UNZ) for interchange control
- Configurable character sets (UNOA, UNOB, UNOC)
- Multiple product lines with hierarchical structure
- Pricing, identification, and description segments
- Trading partner identification via GLN/DUNS

Usage:
    from frappe_pim.pim.export.edifact import export_pricat

    edi_content = export_pricat(
        profile_name="my_edi_profile",
        save_file=True
    )

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from datetime import datetime
import re


# EDIFACT delimiters (default UNA segment values)
COMPONENT_SEPARATOR = ":"    # Separates components within a data element
ELEMENT_SEPARATOR = "+"      # Separates data elements
DECIMAL_MARK = "."           # Decimal notation
ESCAPE_CHARACTER = "?"       # Release character
RESERVED = " "               # Reserved for future use
SEGMENT_TERMINATOR = "'"     # Segment terminator

# Default UNA service string
DEFAULT_UNA = "UNA:+.? '"

# EDIFACT syntax identifiers
SYNTAX_UNOA = "UNOA"  # Level A - uppercase letters, digits, space, some punctuation
SYNTAX_UNOB = "UNOB"  # Level B - Level A + lowercase
SYNTAX_UNOC = "UNOC"  # Level C - ISO 8859-1 Latin alphabet
SYNTAX_VERSION = "4"   # EDIFACT version 4

# Message type identifiers
MESSAGE_PRICAT = "PRICAT"  # Price/Catalogue message
MESSAGE_PRODAT = "PRODAT"  # Product Data message

# Message version/release
MESSAGE_VERSION = "D"    # Draft directory
MESSAGE_RELEASE = "01B"  # Release 01B
MESSAGE_AGENCY = "UN"    # United Nations

# Qualifier codes
PARTY_QUALIFIER_SUPPLIER = "SU"
PARTY_QUALIFIER_BUYER = "BY"
PARTY_QUALIFIER_MANUFACTURER = "MF"

# ID type qualifiers
ID_QUALIFIER_GLN = "9"    # GS1 GLN
ID_QUALIFIER_DUNS = "22"  # Dun & Bradstreet
ID_QUALIFIER_EAN = "EN"   # EAN/GTIN
ID_QUALIFIER_SKU = "SA"   # Supplier's article number

# Price type qualifiers
PRICE_NET = "AAA"         # Net price
PRICE_GROSS = "AAB"       # Gross price
PRICE_LIST = "AAE"        # List price
PRICE_SRP = "SRP"         # Suggested retail price

# Date/time function qualifiers
DTM_DOCUMENT = "137"      # Document date
DTM_VALIDITY_START = "194"  # Start date/time
DTM_VALIDITY_END = "206"    # End date/time


def export_pricat(
    profile_name=None,
    products=None,
    sender_id=None,
    sender_qualifier=None,
    recipient_id=None,
    recipient_qualifier=None,
    supplier_gln=None,
    supplier_name=None,
    buyer_gln=None,
    buyer_name=None,
    currency="EUR",
    interchange_ref=None,
    message_ref=None,
    syntax_id=None,
    include_prices=True,
    include_descriptions=True,
    validity_start=None,
    validity_end=None,
    line_width=None,
    save_file=False
):
    """Generate UN/EDIFACT PRICAT (Price/Catalogue) message.

    This function creates an EDIFACT PRICAT message containing product
    catalog information. It can either use an Export Profile configuration
    or accept parameters directly.

    Args:
        profile_name: Name of Export Profile DocType to use for settings
        products: List of Product Master/Variant names to export (optional)
        sender_id: Interchange sender identification
        sender_qualifier: Sender ID qualifier (9=GLN, 22=DUNS, etc.)
        recipient_id: Interchange recipient identification
        recipient_qualifier: Recipient ID qualifier
        supplier_gln: Supplier's GLN for NAD segment
        supplier_name: Supplier's name for NAD segment
        buyer_gln: Buyer's GLN for NAD segment (optional)
        buyer_name: Buyer's name for NAD segment (optional)
        currency: ISO 4217 currency code (default: EUR)
        interchange_ref: Interchange control reference (auto-generated if None)
        message_ref: Message reference number (auto-generated if None)
        syntax_id: Syntax identifier (UNOA, UNOB, or UNOC)
        include_prices: Include PRI segments with pricing
        include_descriptions: Include IMD segments with descriptions
        validity_start: Catalogue validity start date (datetime or string)
        validity_end: Catalogue validity end date (datetime or string)
        line_width: Optional line width for segment wrapping (None = no wrap)
        save_file: Save to file and return file path

    Returns:
        str: EDIFACT message content, or file path if save_file=True

    Raises:
        ValueError: If required parameters are missing

    Example:
        >>> edi = export_pricat(
        ...     profile_name="standard_edi",
        ...     save_file=True
        ... )
        >>> print(edi)  # Returns file path
    """
    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    # Override config with explicit parameters
    sender_id = sender_id or config.get("sender_id", "SENDER001")
    sender_qualifier = sender_qualifier or config.get("sender_qualifier", ID_QUALIFIER_GLN)
    recipient_id = recipient_id or config.get("recipient_id", "RECIPIENT001")
    recipient_qualifier = recipient_qualifier or config.get("recipient_qualifier", ID_QUALIFIER_GLN)
    supplier_gln = supplier_gln or config.get("supplier_gln", sender_id)
    supplier_name = supplier_name or config.get("supplier_name", "Default Supplier")
    buyer_gln = buyer_gln or config.get("buyer_gln")
    buyer_name = buyer_name or config.get("buyer_name")
    currency = config.get("currency", currency)
    syntax_id = syntax_id or config.get("syntax_id", SYNTAX_UNOC)
    include_prices = config.get("include_prices", include_prices)
    include_descriptions = config.get("include_descriptions", include_descriptions)
    validity_start = validity_start or config.get("validity_start")
    validity_end = validity_end or config.get("validity_end")
    line_width = line_width or config.get("line_width")

    # Generate references if not provided
    timestamp = datetime.now()
    if not interchange_ref:
        interchange_ref = timestamp.strftime("%Y%m%d%H%M%S")
    if not message_ref:
        message_ref = "1"

    # Get products to export
    if products is None:
        products = _get_products_for_export(config)

    # Build EDIFACT message
    segments = _build_pricat_message(
        products=products,
        sender_id=sender_id,
        sender_qualifier=sender_qualifier,
        recipient_id=recipient_id,
        recipient_qualifier=recipient_qualifier,
        supplier_gln=supplier_gln,
        supplier_name=supplier_name,
        buyer_gln=buyer_gln,
        buyer_name=buyer_name,
        currency=currency,
        interchange_ref=interchange_ref,
        message_ref=message_ref,
        syntax_id=syntax_id,
        include_prices=include_prices,
        include_descriptions=include_descriptions,
        validity_start=validity_start,
        validity_end=validity_end,
        timestamp=timestamp
    )

    # Join segments into message
    edi_content = _segments_to_string(segments, line_width=line_width)

    # Save to file if requested
    if save_file:
        return _save_export_file(
            edi_content,
            profile_name=profile_name,
            message_type=MESSAGE_PRICAT
        )

    return edi_content


def export_prodat(
    profile_name=None,
    products=None,
    sender_id=None,
    sender_qualifier=None,
    recipient_id=None,
    recipient_qualifier=None,
    supplier_gln=None,
    supplier_name=None,
    currency="EUR",
    interchange_ref=None,
    message_ref=None,
    syntax_id=None,
    include_measurements=True,
    include_attributes=True,
    line_width=None,
    save_file=False
):
    """Generate UN/EDIFACT PRODAT (Product Data) message.

    This function creates an EDIFACT PRODAT message containing detailed
    product specification data. PRODAT is used for exchanging more detailed
    product information than PRICAT.

    Args:
        profile_name: Name of Export Profile DocType to use for settings
        products: List of Product Master/Variant names to export (optional)
        sender_id: Interchange sender identification
        sender_qualifier: Sender ID qualifier
        recipient_id: Interchange recipient identification
        recipient_qualifier: Recipient ID qualifier
        supplier_gln: Supplier's GLN for NAD segment
        supplier_name: Supplier's name for NAD segment
        currency: ISO 4217 currency code (default: EUR)
        interchange_ref: Interchange control reference
        message_ref: Message reference number
        syntax_id: Syntax identifier (UNOA, UNOB, or UNOC)
        include_measurements: Include MEA segments with dimensions
        include_attributes: Include CCI segments with characteristics
        line_width: Optional line width for segment wrapping
        save_file: Save to file and return file path

    Returns:
        str: EDIFACT message content, or file path if save_file=True

    Example:
        >>> edi = export_prodat(
        ...     sender_id="4012345000001",
        ...     recipient_id="4012345000002",
        ...     products=["PROD-001", "PROD-002"]
        ... )
    """
    # Load settings from profile if provided
    config = _load_profile_config(profile_name) if profile_name else {}

    # Override config with explicit parameters
    sender_id = sender_id or config.get("sender_id", "SENDER001")
    sender_qualifier = sender_qualifier or config.get("sender_qualifier", ID_QUALIFIER_GLN)
    recipient_id = recipient_id or config.get("recipient_id", "RECIPIENT001")
    recipient_qualifier = recipient_qualifier or config.get("recipient_qualifier", ID_QUALIFIER_GLN)
    supplier_gln = supplier_gln or config.get("supplier_gln", sender_id)
    supplier_name = supplier_name or config.get("supplier_name", "Default Supplier")
    currency = config.get("currency", currency)
    syntax_id = syntax_id or config.get("syntax_id", SYNTAX_UNOC)
    include_measurements = config.get("include_measurements", include_measurements)
    include_attributes = config.get("include_attributes", include_attributes)
    line_width = line_width or config.get("line_width")

    # Generate references if not provided
    timestamp = datetime.now()
    if not interchange_ref:
        interchange_ref = timestamp.strftime("%Y%m%d%H%M%S")
    if not message_ref:
        message_ref = "1"

    # Get products to export
    if products is None:
        products = _get_products_for_export(config)

    # Build EDIFACT message
    segments = _build_prodat_message(
        products=products,
        sender_id=sender_id,
        sender_qualifier=sender_qualifier,
        recipient_id=recipient_id,
        recipient_qualifier=recipient_qualifier,
        supplier_gln=supplier_gln,
        supplier_name=supplier_name,
        currency=currency,
        interchange_ref=interchange_ref,
        message_ref=message_ref,
        syntax_id=syntax_id,
        include_measurements=include_measurements,
        include_attributes=include_attributes,
        timestamp=timestamp
    )

    # Join segments into message
    edi_content = _segments_to_string(segments, line_width=line_width)

    # Save to file if requested
    if save_file:
        return _save_export_file(
            edi_content,
            profile_name=profile_name,
            message_type=MESSAGE_PRODAT
        )

    return edi_content


def export_pricat_async(profile_name, callback=None):
    """Queue PRICAT export as background job.

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
        "frappe_pim.pim.export.edifact.export_pricat",
        queue="long",
        timeout=3600,
        profile_name=profile_name,
        save_file=True
    )

    return job.id if hasattr(job, 'id') else str(job)


def export_prodat_async(profile_name, callback=None):
    """Queue PRODAT export as background job.

    For large product datasets, this function queues the export as a
    background job to avoid timeout issues.

    Args:
        profile_name: Name of Export Profile DocType
        callback: Optional callback function name to call on completion

    Returns:
        str: Background job ID
    """
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.export.edifact.export_prodat",
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
        "sender_id": profile.get("edifact_sender_id"),
        "sender_qualifier": profile.get("edifact_sender_qualifier"),
        "recipient_id": profile.get("edifact_recipient_id"),
        "recipient_qualifier": profile.get("edifact_recipient_qualifier"),
        "supplier_gln": profile.get("edifact_supplier_gln") or profile.get("gs1_gln"),
        "supplier_name": profile.get("edifact_supplier_name"),
        "buyer_gln": profile.get("edifact_buyer_gln"),
        "buyer_name": profile.get("edifact_buyer_name"),
        "syntax_id": profile.get("edifact_syntax_id"),
        "include_prices": profile.get("include_prices", True),
        "include_descriptions": profile.get("include_descriptions", True),
        "include_measurements": profile.get("include_measurements", True),
        "include_attributes": profile.get("include_attributes", True),
        "validity_start": profile.get("validity_start"),
        "validity_end": profile.get("validity_end"),
        "line_width": profile.get("edifact_line_width"),
        "product_family": profile.get("product_family"),
        "status_filter": profile.get("status_filter"),
        "completeness_threshold": profile.get("completeness_threshold", 0),
        "output_filename": profile.get("output_filename"),
    }

    # Get currency from export_currency link
    if profile.get("export_currency"):
        config["currency"] = profile.export_currency

    return config


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


def _build_pricat_message(
    products,
    sender_id,
    sender_qualifier,
    recipient_id,
    recipient_qualifier,
    supplier_gln,
    supplier_name,
    buyer_gln,
    buyer_name,
    currency,
    interchange_ref,
    message_ref,
    syntax_id,
    include_prices,
    include_descriptions,
    validity_start,
    validity_end,
    timestamp
):
    """Build complete PRICAT message structure.

    Args:
        products: List of product names to include
        sender_id: Interchange sender identification
        sender_qualifier: Sender ID qualifier
        recipient_id: Interchange recipient identification
        recipient_qualifier: Recipient ID qualifier
        supplier_gln: Supplier's GLN
        supplier_name: Supplier's name
        buyer_gln: Buyer's GLN (optional)
        buyer_name: Buyer's name (optional)
        currency: ISO 4217 currency code
        interchange_ref: Interchange control reference
        message_ref: Message reference number
        syntax_id: Syntax identifier
        include_prices: Include pricing segments
        include_descriptions: Include description segments
        validity_start: Catalogue validity start date
        validity_end: Catalogue validity end date
        timestamp: Generation timestamp

    Returns:
        list: List of segment strings
    """
    segments = []

    # UNA - Service String Advice (defines delimiters)
    segments.append(DEFAULT_UNA)

    # UNB - Interchange Header
    segments.append(_build_unb_segment(
        syntax_id=syntax_id,
        sender_id=sender_id,
        sender_qualifier=sender_qualifier,
        recipient_id=recipient_id,
        recipient_qualifier=recipient_qualifier,
        interchange_ref=interchange_ref,
        timestamp=timestamp
    ))

    # UNH - Message Header
    segments.append(_build_unh_segment(
        message_ref=message_ref,
        message_type=MESSAGE_PRICAT
    ))

    # BGM - Beginning of Message
    segments.append(_build_bgm_segment(
        document_code="9",  # Price/sales catalogue
        document_number=interchange_ref
    ))

    # DTM - Document date
    segments.append(_build_dtm_segment(
        qualifier=DTM_DOCUMENT,
        date_value=timestamp
    ))

    # DTM - Validity period (if provided)
    if validity_start:
        segments.append(_build_dtm_segment(
            qualifier=DTM_VALIDITY_START,
            date_value=validity_start
        ))
    if validity_end:
        segments.append(_build_dtm_segment(
            qualifier=DTM_VALIDITY_END,
            date_value=validity_end
        ))

    # NAD - Supplier name and address
    segments.append(_build_nad_segment(
        party_qualifier=PARTY_QUALIFIER_SUPPLIER,
        party_id=supplier_gln,
        id_qualifier=ID_QUALIFIER_GLN,
        party_name=supplier_name
    ))

    # NAD - Buyer name and address (if provided)
    if buyer_gln:
        segments.append(_build_nad_segment(
            party_qualifier=PARTY_QUALIFIER_BUYER,
            party_id=buyer_gln,
            id_qualifier=ID_QUALIFIER_GLN,
            party_name=buyer_name
        ))

    # CUX - Currencies
    segments.append(_build_cux_segment(currency=currency))

    # Line items
    line_number = 0
    for product_name in products:
        line_number += 1
        line_segments = _build_pricat_line_item(
            product_name=product_name,
            line_number=line_number,
            currency=currency,
            include_prices=include_prices,
            include_descriptions=include_descriptions
        )
        segments.extend(line_segments)

    # UNS - Section control (summary section)
    segments.append("UNS+S'")

    # UNT - Message Trailer
    # Count segments excluding UNA, UNB, UNZ
    segment_count = len(segments) - 1  # UNA doesn't count, will add UNT
    segments.append(_build_unt_segment(
        segment_count=segment_count,
        message_ref=message_ref
    ))

    # UNZ - Interchange Trailer
    segments.append(_build_unz_segment(
        message_count=1,
        interchange_ref=interchange_ref
    ))

    return segments


def _build_prodat_message(
    products,
    sender_id,
    sender_qualifier,
    recipient_id,
    recipient_qualifier,
    supplier_gln,
    supplier_name,
    currency,
    interchange_ref,
    message_ref,
    syntax_id,
    include_measurements,
    include_attributes,
    timestamp
):
    """Build complete PRODAT message structure.

    Args:
        products: List of product names to include
        sender_id: Interchange sender identification
        sender_qualifier: Sender ID qualifier
        recipient_id: Interchange recipient identification
        recipient_qualifier: Recipient ID qualifier
        supplier_gln: Supplier's GLN
        supplier_name: Supplier's name
        currency: ISO 4217 currency code
        interchange_ref: Interchange control reference
        message_ref: Message reference number
        syntax_id: Syntax identifier
        include_measurements: Include measurement segments
        include_attributes: Include characteristic segments
        timestamp: Generation timestamp

    Returns:
        list: List of segment strings
    """
    segments = []

    # UNA - Service String Advice
    segments.append(DEFAULT_UNA)

    # UNB - Interchange Header
    segments.append(_build_unb_segment(
        syntax_id=syntax_id,
        sender_id=sender_id,
        sender_qualifier=sender_qualifier,
        recipient_id=recipient_id,
        recipient_qualifier=recipient_qualifier,
        interchange_ref=interchange_ref,
        timestamp=timestamp
    ))

    # UNH - Message Header
    segments.append(_build_unh_segment(
        message_ref=message_ref,
        message_type=MESSAGE_PRODAT
    ))

    # BGM - Beginning of Message
    segments.append(_build_bgm_segment(
        document_code="6",  # Product data
        document_number=interchange_ref
    ))

    # DTM - Document date
    segments.append(_build_dtm_segment(
        qualifier=DTM_DOCUMENT,
        date_value=timestamp
    ))

    # NAD - Supplier name and address
    segments.append(_build_nad_segment(
        party_qualifier=PARTY_QUALIFIER_SUPPLIER,
        party_id=supplier_gln,
        id_qualifier=ID_QUALIFIER_GLN,
        party_name=supplier_name
    ))

    # CUX - Currencies
    segments.append(_build_cux_segment(currency=currency))

    # Line items
    line_number = 0
    for product_name in products:
        line_number += 1
        line_segments = _build_prodat_line_item(
            product_name=product_name,
            line_number=line_number,
            include_measurements=include_measurements,
            include_attributes=include_attributes
        )
        segments.extend(line_segments)

    # UNS - Section control (summary section)
    segments.append("UNS+S'")

    # UNT - Message Trailer
    segment_count = len(segments) - 1
    segments.append(_build_unt_segment(
        segment_count=segment_count,
        message_ref=message_ref
    ))

    # UNZ - Interchange Trailer
    segments.append(_build_unz_segment(
        message_count=1,
        interchange_ref=interchange_ref
    ))

    return segments


def _build_unb_segment(
    syntax_id,
    sender_id,
    sender_qualifier,
    recipient_id,
    recipient_qualifier,
    interchange_ref,
    timestamp
):
    """Build UNB (Interchange Header) segment.

    Args:
        syntax_id: Syntax identifier (UNOA, UNOB, UNOC)
        sender_id: Sender identification
        sender_qualifier: Sender qualifier code
        recipient_id: Recipient identification
        recipient_qualifier: Recipient qualifier code
        interchange_ref: Interchange control reference
        timestamp: Preparation date/time

    Returns:
        str: UNB segment string
    """
    date_str = timestamp.strftime("%y%m%d")
    time_str = timestamp.strftime("%H%M")

    return (
        f"UNB+{syntax_id}:{SYNTAX_VERSION}+"
        f"{_escape(sender_id)}:{sender_qualifier}+"
        f"{_escape(recipient_id)}:{recipient_qualifier}+"
        f"{date_str}:{time_str}+"
        f"{_escape(interchange_ref)}'"
    )


def _build_unh_segment(message_ref, message_type):
    """Build UNH (Message Header) segment.

    Args:
        message_ref: Message reference number
        message_type: Message type identifier (PRICAT, PRODAT, etc.)

    Returns:
        str: UNH segment string
    """
    return (
        f"UNH+{_escape(message_ref)}+"
        f"{message_type}:{MESSAGE_VERSION}:{MESSAGE_RELEASE}:{MESSAGE_AGENCY}'"
    )


def _build_bgm_segment(document_code, document_number, message_function="9"):
    """Build BGM (Beginning of Message) segment.

    Args:
        document_code: Document/message name code
        document_number: Document/message number
        message_function: Message function code (9=Original)

    Returns:
        str: BGM segment string
    """
    return f"BGM+{document_code}+{_escape(document_number)}+{message_function}'"


def _build_dtm_segment(qualifier, date_value):
    """Build DTM (Date/Time/Period) segment.

    Args:
        qualifier: Date/time qualifier code
        date_value: Date value (datetime object or string)

    Returns:
        str: DTM segment string
    """
    if isinstance(date_value, datetime):
        date_str = date_value.strftime("%Y%m%d")
    elif isinstance(date_value, str):
        # Try to parse common formats
        date_str = date_value.replace("-", "").replace("/", "")[:8]
    else:
        date_str = str(date_value)

    return f"DTM+{qualifier}:{date_str}:102'"  # 102 = CCYYMMDD format


def _build_nad_segment(party_qualifier, party_id, id_qualifier, party_name=None):
    """Build NAD (Name and Address) segment.

    Args:
        party_qualifier: Party qualifier (SU=Supplier, BY=Buyer, etc.)
        party_id: Party identification
        id_qualifier: ID code qualifier
        party_name: Party name (optional)

    Returns:
        str: NAD segment string
    """
    segment = f"NAD+{party_qualifier}+{_escape(party_id)}::{id_qualifier}"
    if party_name:
        # Party name in position 4 (skip positions 2-3)
        segment += f"++{_escape(party_name)}"
    segment += "'"
    return segment


def _build_cux_segment(currency, rate_type="2"):
    """Build CUX (Currencies) segment.

    Args:
        currency: ISO 4217 currency code
        rate_type: Currency usage code qualifier (2=Reference currency)

    Returns:
        str: CUX segment string
    """
    return f"CUX+{rate_type}:{currency}:4'"  # 4 = Invoicing currency


def _build_unt_segment(segment_count, message_ref):
    """Build UNT (Message Trailer) segment.

    Args:
        segment_count: Number of segments in message
        message_ref: Message reference number

    Returns:
        str: UNT segment string
    """
    return f"UNT+{segment_count}+{_escape(message_ref)}'"


def _build_unz_segment(message_count, interchange_ref):
    """Build UNZ (Interchange Trailer) segment.

    Args:
        message_count: Number of messages in interchange
        interchange_ref: Interchange control reference

    Returns:
        str: UNZ segment string
    """
    return f"UNZ+{message_count}+{_escape(interchange_ref)}'"


def _build_pricat_line_item(
    product_name,
    line_number,
    currency,
    include_prices,
    include_descriptions
):
    """Build line item segments for PRICAT message.

    Args:
        product_name: Name of Product Variant to export
        line_number: Line item number
        currency: Currency code
        include_prices: Include PRI segments
        include_descriptions: Include IMD segments

    Returns:
        list: List of segment strings for line item
    """
    import frappe

    segments = []

    try:
        product = frappe.get_doc("Product Variant", product_name)
    except Exception:
        try:
            product = frappe.get_doc("Product Master", product_name)
        except Exception:
            return segments

    # LIN - Line item
    sku = product.get("variant_code") or product.get("product_code") or product.name
    barcode = product.get("barcode") or product.get("ean")

    lin_segment = f"LIN+{line_number}++{_escape(sku)}:{ID_QUALIFIER_SKU}'"
    segments.append(lin_segment)

    # PIA - Additional product identification (GTIN/EAN)
    if barcode:
        segments.append(f"PIA+5+{_escape(barcode)}:{ID_QUALIFIER_EAN}::9'")

    # Manufacturer part number
    mpn = product.get("manufacturer_part_number")
    if mpn:
        segments.append(f"PIA+1+{_escape(mpn)}:MF'")

    # IMD - Item description
    if include_descriptions:
        product_name_text = product.get("variant_name") or product.get("product_name") or sku

        # Product name (type F = free-form, qualifier 79 = product description)
        segments.append(f"IMD+F++:::{_escape(product_name_text)}'")

        # Full description
        description = product.get("description") or product.get("short_description")
        if description:
            clean_desc = _clean_text(description)
            # Split long descriptions into multiple segments (max 70 chars per line)
            desc_parts = _split_text(clean_desc, max_length=70)
            for part in desc_parts[:3]:  # Max 3 description lines
                segments.append(f"IMD+A++:::{_escape(part)}'")

    # QTY - Minimum order quantity
    min_qty = product.get("minimum_order_qty") or 1
    segments.append(f"QTY+53:{min_qty}'")  # 53 = Minimum order quantity

    # PRI - Price details
    if include_prices:
        price = product.get("price") or product.get("standard_rate")
        if price:
            # AAA = Net price, CA = Catalogue/list price
            segments.append(f"PRI+{PRICE_NET}:{float(price):.2f}:CA'")

    return segments


def _build_prodat_line_item(
    product_name,
    line_number,
    include_measurements,
    include_attributes
):
    """Build line item segments for PRODAT message.

    Args:
        product_name: Name of Product Variant to export
        line_number: Line item number
        include_measurements: Include MEA segments
        include_attributes: Include CCI segments

    Returns:
        list: List of segment strings for line item
    """
    import frappe

    segments = []

    try:
        product = frappe.get_doc("Product Variant", product_name)
    except Exception:
        try:
            product = frappe.get_doc("Product Master", product_name)
        except Exception:
            return segments

    # LIN - Line item
    sku = product.get("variant_code") or product.get("product_code") or product.name
    barcode = product.get("barcode") or product.get("ean")

    lin_segment = f"LIN+{line_number}++{_escape(sku)}:{ID_QUALIFIER_SKU}'"
    segments.append(lin_segment)

    # PIA - Additional product identification
    if barcode:
        segments.append(f"PIA+5+{_escape(barcode)}:{ID_QUALIFIER_EAN}::9'")

    mpn = product.get("manufacturer_part_number")
    if mpn:
        segments.append(f"PIA+1+{_escape(mpn)}:MF'")

    # IMD - Item description (always included in PRODAT)
    product_name_text = product.get("variant_name") or product.get("product_name") or sku
    segments.append(f"IMD+F++:::{_escape(product_name_text)}'")

    description = product.get("description") or product.get("short_description")
    if description:
        clean_desc = _clean_text(description)
        desc_parts = _split_text(clean_desc, max_length=70)
        for part in desc_parts[:3]:
            segments.append(f"IMD+A++:::{_escape(part)}'")

    # MEA - Measurements
    if include_measurements:
        # Weight
        weight = product.get("weight") or product.get("net_weight")
        if weight:
            weight_uom = product.get("weight_uom", "KGM")  # Default kilogram
            uom_code = _get_edi_uom_code(weight_uom)
            segments.append(f"MEA+PD+AAB+{uom_code}:{float(weight):.3f}'")  # AAB = Net weight

        # Dimensions
        length = product.get("length")
        width = product.get("width")
        height = product.get("height")
        dimension_uom = product.get("dimension_uom", "CMT")  # Default centimeter
        dim_uom_code = _get_edi_uom_code(dimension_uom)

        if length:
            segments.append(f"MEA+PD+LN+{dim_uom_code}:{float(length):.2f}'")  # LN = Length
        if width:
            segments.append(f"MEA+PD+WD+{dim_uom_code}:{float(width):.2f}'")  # WD = Width
        if height:
            segments.append(f"MEA+PD+HT+{dim_uom_code}:{float(height):.2f}'")  # HT = Height

    # CCI/CAV - Characteristics (attributes)
    if include_attributes:
        attribute_values = product.get("attribute_values") or []
        for attr_value in attribute_values[:20]:  # Limit to 20 attributes
            attr_segments = _build_attribute_segments(attr_value)
            segments.extend(attr_segments)

    return segments


def _build_attribute_segments(attr_value):
    """Build CCI/CAV segments for a product attribute.

    Args:
        attr_value: Product Attribute Value row

    Returns:
        list: List of CCI/CAV segment strings
    """
    import frappe

    segments = []

    attr_code = attr_value.get("attribute")
    if not attr_code:
        return segments

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

    # Get value
    value = _get_attribute_value(attr_value)
    if value is None:
        return segments

    attr_name = attr_meta.get("attribute_name", attr_code)

    # CCI - Characteristic identification
    segments.append(f"CCI+++{_escape(attr_name)}'")

    # CAV - Characteristic value
    segments.append(f"CAV+{_escape(str(value))}'")

    return segments


def _get_attribute_value(attr_value):
    """Extract value from EAV attribute value row.

    Args:
        attr_value: Product Attribute Value row

    Returns:
        Value or None if no value set
    """
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
                return "YES" if value else "NO"
            if isinstance(value, str) and not value.strip():
                continue
            return value

    return None


def _escape(text):
    """Escape special EDIFACT characters in text.

    Args:
        text: Text to escape

    Returns:
        str: Escaped text
    """
    if text is None:
        return ""

    text = str(text)

    # Escape release character first, then other special characters
    text = text.replace(ESCAPE_CHARACTER, ESCAPE_CHARACTER + ESCAPE_CHARACTER)
    text = text.replace(COMPONENT_SEPARATOR, ESCAPE_CHARACTER + COMPONENT_SEPARATOR)
    text = text.replace(ELEMENT_SEPARATOR, ESCAPE_CHARACTER + ELEMENT_SEPARATOR)
    text = text.replace(SEGMENT_TERMINATOR, ESCAPE_CHARACTER + SEGMENT_TERMINATOR)

    return text


def _clean_text(html_text):
    """Remove HTML tags and normalize whitespace.

    Args:
        html_text: Text possibly containing HTML

    Returns:
        str: Clean text
    """
    if not html_text:
        return ""

    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', str(html_text))
    # Normalize whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _split_text(text, max_length=70):
    """Split text into chunks of maximum length.

    Args:
        text: Text to split
        max_length: Maximum length per chunk

    Returns:
        list: List of text chunks
    """
    if not text:
        return []

    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break

        # Find last space within limit
        split_pos = text.rfind(' ', 0, max_length)
        if split_pos == -1:
            split_pos = max_length

        parts.append(text[:split_pos].strip())
        text = text[split_pos:].strip()

    return parts


def _get_edi_uom_code(uom):
    """Convert UOM to UN/ECE Recommendation 20 code.

    Args:
        uom: Unit of measure string

    Returns:
        str: UN/ECE code
    """
    uom_map = {
        "kg": "KGM",
        "kilogram": "KGM",
        "g": "GRM",
        "gram": "GRM",
        "lb": "LBR",
        "pound": "LBR",
        "oz": "ONZ",
        "ounce": "ONZ",
        "m": "MTR",
        "meter": "MTR",
        "cm": "CMT",
        "centimeter": "CMT",
        "mm": "MMT",
        "millimeter": "MMT",
        "in": "INH",
        "inch": "INH",
        "ft": "FOT",
        "foot": "FOT",
        "l": "LTR",
        "liter": "LTR",
        "ml": "MLT",
        "milliliter": "MLT",
        "pcs": "C62",
        "piece": "C62",
        "ea": "C62",
        "each": "C62",
    }

    uom_lower = str(uom).lower().strip() if uom else ""
    return uom_map.get(uom_lower, uom.upper() if uom else "C62")


def _segments_to_string(segments, line_width=None):
    """Join segments into EDIFACT message string.

    Args:
        segments: List of segment strings
        line_width: Optional line width (None = no wrapping)

    Returns:
        str: Complete EDIFACT message
    """
    if line_width:
        # Wrap long segments
        wrapped = []
        for segment in segments:
            if len(segment) > line_width:
                # Split at segment terminator position if needed
                wrapped.append(segment)
            else:
                wrapped.append(segment)
        return '\n'.join(wrapped)
    else:
        # Standard format: segments separated by newlines for readability
        return '\n'.join(segments)


def _save_export_file(content, profile_name=None, message_type=None):
    """Save export content to file.

    Args:
        content: EDIFACT content string
        profile_name: Export profile name (for filename)
        message_type: Message type (PRICAT, PRODAT, etc.)

    Returns:
        str: File path of saved file
    """
    import frappe

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name_part = profile_name or message_type or "edifact"
    filename = f"{name_part}_{timestamp}.edi"

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


def validate_edifact(edi_content):
    """Validate EDIFACT message structure.

    Args:
        edi_content: EDIFACT message content string

    Returns:
        tuple: (is_valid, errors_list)
    """
    errors = []

    if not edi_content:
        return False, ["Empty EDIFACT content"]

    lines = edi_content.strip().split('\n')

    # Check UNA (optional but if present, must be correct format)
    una_found = False
    for line in lines:
        if line.startswith("UNA"):
            una_found = True
            if len(line) < 9:
                errors.append("Invalid UNA segment length")
            break

    # Check for required segments
    unb_found = False
    unh_found = False
    unt_found = False
    unz_found = False

    for line in lines:
        if line.startswith("UNB+"):
            unb_found = True
        elif line.startswith("UNH+"):
            unh_found = True
        elif line.startswith("UNT+"):
            unt_found = True
        elif line.startswith("UNZ+"):
            unz_found = True

    if not unb_found:
        errors.append("Missing UNB (Interchange Header) segment")
    if not unh_found:
        errors.append("Missing UNH (Message Header) segment")
    if not unt_found:
        errors.append("Missing UNT (Message Trailer) segment")
    if not unz_found:
        errors.append("Missing UNZ (Interchange Trailer) segment")

    # Check segment terminators
    for idx, line in enumerate(lines):
        line = line.strip()
        if line and not line.startswith("UNA"):
            if not line.endswith(SEGMENT_TERMINATOR):
                errors.append(f"Line {idx + 1}: Missing segment terminator")

    return len(errors) == 0, errors


def get_segment_count(edi_content):
    """Count number of segments in EDIFACT message.

    Args:
        edi_content: EDIFACT message content string

    Returns:
        int: Number of segments (excluding UNA)
    """
    if not edi_content:
        return 0

    count = 0
    for line in edi_content.strip().split('\n'):
        line = line.strip()
        if line and not line.startswith("UNA"):
            count += 1

    return count


def get_line_item_count(edi_content):
    """Count number of line items (LIN segments) in EDIFACT message.

    Args:
        edi_content: EDIFACT message content string

    Returns:
        int: Number of LIN segments
    """
    if not edi_content:
        return 0

    count = 0
    for line in edi_content.strip().split('\n'):
        if line.strip().startswith("LIN+"):
            count += 1

    return count


def parse_unb_segment(unb_segment):
    """Parse UNB segment to extract interchange details.

    Args:
        unb_segment: UNB segment string

    Returns:
        dict: Parsed interchange details
    """
    result = {
        "syntax_id": None,
        "syntax_version": None,
        "sender_id": None,
        "sender_qualifier": None,
        "recipient_id": None,
        "recipient_qualifier": None,
        "date": None,
        "time": None,
        "interchange_ref": None
    }

    if not unb_segment or not unb_segment.startswith("UNB+"):
        return result

    # Remove segment tag and terminator
    content = unb_segment[4:].rstrip(SEGMENT_TERMINATOR)

    # Split elements
    elements = content.split(ELEMENT_SEPARATOR)

    if len(elements) >= 1:
        syntax_parts = elements[0].split(COMPONENT_SEPARATOR)
        result["syntax_id"] = syntax_parts[0] if syntax_parts else None
        result["syntax_version"] = syntax_parts[1] if len(syntax_parts) > 1 else None

    if len(elements) >= 2:
        sender_parts = elements[1].split(COMPONENT_SEPARATOR)
        result["sender_id"] = sender_parts[0] if sender_parts else None
        result["sender_qualifier"] = sender_parts[1] if len(sender_parts) > 1 else None

    if len(elements) >= 3:
        recipient_parts = elements[2].split(COMPONENT_SEPARATOR)
        result["recipient_id"] = recipient_parts[0] if recipient_parts else None
        result["recipient_qualifier"] = recipient_parts[1] if len(recipient_parts) > 1 else None

    if len(elements) >= 4:
        datetime_parts = elements[3].split(COMPONENT_SEPARATOR)
        result["date"] = datetime_parts[0] if datetime_parts else None
        result["time"] = datetime_parts[1] if len(datetime_parts) > 1 else None

    if len(elements) >= 5:
        result["interchange_ref"] = elements[4]

    return result
