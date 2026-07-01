"""PIM Export API Endpoints

This module provides API endpoints for triggering product data exports
and downloading export results. Supports 10 feed formats including:
- BMEcat 2005 - B2B product catalog XML standard
- CSV - Comma-separated values
- TSV - Tab-separated values
- JSON - JavaScript Object Notation
- XML - Generic XML format
- cXML - Commerce XML for procurement
- UBL 2.x - Universal Business Language
- GS1 XML - GDSN data pool synchronization
- EDIFACT - UN/EDI standard for commerce
- XLSX - Microsoft Excel format

All API functions are decorated with @frappe.whitelist() for security
and require appropriate permissions.

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from datetime import datetime


# Supported export formats mapping
SUPPORTED_FORMATS = {
    "bmecat": {
        "name": "BMEcat 2005",
        "extension": "xml",
        "content_type": "application/xml",
        "description": "BMEcat 2005 B2B product catalog XML standard"
    },
    "bmecat_1.2": {
        "name": "BMEcat 1.2",
        "extension": "xml",
        "content_type": "application/xml",
        "description": "BMEcat 1.2 legacy format"
    },
    "csv": {
        "name": "CSV",
        "extension": "csv",
        "content_type": "text/csv",
        "description": "Comma-separated values"
    },
    "tsv": {
        "name": "TSV",
        "extension": "tsv",
        "content_type": "text/tab-separated-values",
        "description": "Tab-separated values"
    },
    "json": {
        "name": "JSON",
        "extension": "json",
        "content_type": "application/json",
        "description": "JavaScript Object Notation"
    },
    "xml": {
        "name": "XML",
        "extension": "xml",
        "content_type": "application/xml",
        "description": "Generic XML format"
    },
    "cxml": {
        "name": "cXML",
        "extension": "xml",
        "content_type": "application/xml",
        "description": "Commerce XML for e-procurement"
    },
    "ubl": {
        "name": "UBL 2.x",
        "extension": "xml",
        "content_type": "application/xml",
        "description": "Universal Business Language catalogue"
    },
    "gs1_xml": {
        "name": "GS1 XML",
        "extension": "xml",
        "content_type": "application/xml",
        "description": "GS1 XML for GDSN data pool synchronization"
    },
    "edifact": {
        "name": "EDIFACT",
        "extension": "edi",
        "content_type": "application/edifact",
        "description": "UN/EDIFACT electronic data interchange"
    },
    "xlsx": {
        "name": "XLSX",
        "extension": "xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "description": "Microsoft Excel format"
    }
}


def export_bmecat(
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
    async_export=False
):
    """Export products to BMEcat 2005 XML format.

    This is the main API endpoint for BMEcat exports. It can use an
    Export Profile for configuration or accept parameters directly.

    Args:
        profile_name: Name of Export Profile to use for settings
        products: JSON list of product names to export (optional)
        supplier_id: Supplier ID for BMEcat header
        supplier_name: Supplier name for BMEcat header
        catalog_id: Catalog ID for BMEcat header
        catalog_version: Catalog version string
        language: ISO 639 language code (default: deu)
        territory: ISO 3166 territory code (default: DE)
        currency: ISO 4217 currency code (default: EUR)
        include_prices: Include price details (default: True)
        include_media: Include media references (default: True)
        include_variants: Include product variants (default: True)
        async_export: Run export as background job (default: False)

    Returns:
        dict: Export result with status, file_url, or job_id

    Example:
        >>> # Using Export Profile
        >>> result = export_bmecat(profile_name="my_bmecat_profile")
        >>> print(result["file_url"])

        >>> # With direct parameters
        >>> result = export_bmecat(
        ...     supplier_id="MYCOMPANY",
        ...     supplier_name="My Company GmbH",
        ...     catalog_id="CAT2024",
        ...     products=["PROD-001", "PROD-002"]
        ... )
    """
    import frappe
    from frappe import _
    import json

    # Check permissions
    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    try:
        # Parse products list if JSON string
        if products and isinstance(products, str):
            products = json.loads(products)

        # Async export via background job
        if async_export:
            return _enqueue_bmecat_export(
                profile_name=profile_name,
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

        # Synchronous export
        from frappe_pim.pim.export.bmecat import export_catalog

        file_url = export_catalog(
            profile_name=profile_name,
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
            include_variants=include_variants,
            save_file=True
        )

        # Update profile status if using profile
        if profile_name:
            _update_profile_status(
                profile_name,
                status="Completed",
                file_url=file_url
            )

        return {
            "success": True,
            "format": "BMEcat 2005",
            "file_url": file_url,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"BMEcat export failed: {str(e)}",
            title="PIM Export Error"
        )

        if profile_name:
            _update_profile_status(
                profile_name,
                status="Failed",
                error=str(e)
            )

        return {
            "success": False,
            "error": str(e)
        }


def export_csv(
    profile_name=None,
    products=None,
    product_family=None,
    status_filter=None,
    completeness_threshold=0,
    delimiter=",",
    include_header=True,
    async_export=False
):
    """Export products to CSV format.

    Args:
        profile_name: Name of Export Profile to use
        products: JSON list of product names to export
        product_family: Filter by Product Family
        status_filter: Filter by product status
        completeness_threshold: Minimum completeness score (0-100)
        delimiter: CSV delimiter character (default: comma)
        include_header: Include column headers (default: True)
        async_export: Run as background job (default: False)

    Returns:
        dict: Export result with status and file_url
    """
    import frappe
    from frappe import _
    import json
    import csv
    from io import StringIO

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    try:
        if products and isinstance(products, str):
            products = json.loads(products)

        if async_export:
            return _enqueue_csv_export(
                profile_name=profile_name,
                products=products,
                product_family=product_family,
                status_filter=status_filter,
                completeness_threshold=completeness_threshold,
                delimiter=delimiter,
                include_header=include_header
            )

        # Get products to export
        if not products:
            products = _get_products_for_export(
                profile_name=profile_name,
                product_family=product_family,
                status_filter=status_filter,
                completeness_threshold=completeness_threshold
            )

        # Build CSV content
        output = StringIO()
        writer = csv.writer(output, delimiter=delimiter)

        # Get fields to export
        fields = _get_export_fields(profile_name)

        if include_header:
            writer.writerow(fields)

        # Write product rows
        for product_name in products:
            row = _get_product_row(product_name, fields)
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        # Save to file
        file_url = _save_export_file(
            csv_content,
            format_type="csv",
            profile_name=profile_name
        )

        if profile_name:
            _update_profile_status(profile_name, "Completed", file_url)

        return {
            "success": True,
            "format": "CSV",
            "file_url": file_url,
            "row_count": len(products),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"CSV export failed: {str(e)}",
            title="PIM Export Error"
        )
        return {"success": False, "error": str(e)}


def export_json(
    profile_name=None,
    products=None,
    product_family=None,
    status_filter=None,
    completeness_threshold=0,
    include_attributes=True,
    include_media=True,
    pretty_print=True,
    async_export=False
):
    """Export products to JSON format.

    Args:
        profile_name: Name of Export Profile to use
        products: JSON list of product names to export
        product_family: Filter by Product Family
        status_filter: Filter by product status
        completeness_threshold: Minimum completeness score
        include_attributes: Include EAV attributes (default: True)
        include_media: Include media references (default: True)
        pretty_print: Format with indentation (default: True)
        async_export: Run as background job (default: False)

    Returns:
        dict: Export result with status and file_url
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    try:
        if products and isinstance(products, str):
            products = json.loads(products)

        if async_export:
            return _enqueue_json_export(
                profile_name=profile_name,
                products=products,
                product_family=product_family,
                status_filter=status_filter,
                completeness_threshold=completeness_threshold,
                include_attributes=include_attributes,
                include_media=include_media,
                pretty_print=pretty_print
            )

        # Get products to export
        if not products:
            products = _get_products_for_export(
                profile_name=profile_name,
                product_family=product_family,
                status_filter=status_filter,
                completeness_threshold=completeness_threshold
            )

        # Build JSON structure
        export_data = {
            "metadata": {
                "format": "PIM Product Export",
                "version": "1.0",
                "generated_at": datetime.now().isoformat(),
                "product_count": len(products)
            },
            "products": []
        }

        for product_name in products:
            product_data = _get_product_json(
                product_name,
                include_attributes=include_attributes,
                include_media=include_media
            )
            if product_data:
                export_data["products"].append(product_data)

        # Serialize to JSON
        indent = 2 if pretty_print else None
        json_content = json.dumps(export_data, indent=indent, ensure_ascii=False)

        # Save to file
        file_url = _save_export_file(
            json_content,
            format_type="json",
            profile_name=profile_name
        )

        if profile_name:
            _update_profile_status(profile_name, "Completed", file_url)

        return {
            "success": True,
            "format": "JSON",
            "file_url": file_url,
            "product_count": len(products),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"JSON export failed: {str(e)}",
            title="PIM Export Error"
        )
        return {"success": False, "error": str(e)}


def export_tsv(
    profile_name=None,
    products=None,
    product_family=None,
    status_filter=None,
    completeness_threshold=0,
    include_header=True,
    async_export=False
):
    """Export products to TSV (Tab-Separated Values) format.

    Args:
        profile_name: Name of Export Profile to use
        products: JSON list of product names to export
        product_family: Filter by Product Family
        status_filter: Filter by product status
        completeness_threshold: Minimum completeness score (0-100)
        include_header: Include column headers (default: True)
        async_export: Run as background job (default: False)

    Returns:
        dict: Export result with status and file_url
    """
    # TSV is just CSV with tab delimiter
    return export_csv(
        profile_name=profile_name,
        products=products,
        product_family=product_family,
        status_filter=status_filter,
        completeness_threshold=completeness_threshold,
        delimiter="\t",
        include_header=include_header,
        async_export=async_export
    )


def export_cxml(
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
    async_export=False
):
    """Export products to cXML (Commerce XML) format.

    cXML is used for B2B e-procurement systems, supporting PunchOut
    catalog browsing and order messages.

    Args:
        profile_name: Name of Export Profile to use for settings
        products: JSON list of product names to export (optional)
        supplier_id: Supplier DUNS or identifier
        supplier_name: Supplier display name
        buyer_id: Buyer DUNS or identifier
        catalog_id: Catalog identifier
        currency: ISO 4217 currency code (default: USD)
        language: ISO 639 language code (default: en)
        include_prices: Include pricing information (default: True)
        include_media: Include media references (default: True)
        include_classifications: Include UNSPSC classifications (default: True)
        async_export: Run export as background job (default: False)

    Returns:
        dict: Export result with status, file_url, or job_id
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    try:
        if products and isinstance(products, str):
            products = json.loads(products)

        if async_export:
            return _enqueue_format_export(
                format_type="cxml",
                profile_name=profile_name,
                products=products,
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                buyer_id=buyer_id,
                catalog_id=catalog_id,
                currency=currency,
                language=language,
                include_prices=include_prices,
                include_media=include_media,
                include_classifications=include_classifications
            )

        from frappe_pim.pim.export.cxml import export_catalog as cxml_export_catalog

        file_url = cxml_export_catalog(
            profile_name=profile_name,
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
            save_file=True
        )

        if profile_name:
            _update_profile_status(profile_name, "Completed", file_url)

        return {
            "success": True,
            "format": "cXML",
            "file_url": file_url,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"cXML export failed: {str(e)}",
            title="PIM Export Error"
        )
        if profile_name:
            _update_profile_status(profile_name, "Failed", error=str(e))
        return {"success": False, "error": str(e)}


def export_ubl(
    profile_name=None,
    products=None,
    supplier_id=None,
    supplier_name=None,
    supplier_country="TR",
    buyer_id=None,
    buyer_name=None,
    catalogue_id=None,
    currency="EUR",
    language="en",
    include_prices=True,
    include_media=True,
    include_classifications=True,
    ubl_version="2.1",
    async_export=False
):
    """Export products to UBL 2.x (Universal Business Language) Catalogue format.

    UBL is an OASIS standard for electronic business documents, widely used
    in e-commerce and procurement.

    Args:
        profile_name: Name of Export Profile to use for settings
        products: JSON list of product names to export (optional)
        supplier_id: Supplier party identifier (GLN, DUNS, or custom)
        supplier_name: Supplier party name
        supplier_country: Supplier country code (ISO 3166-1 alpha-2)
        buyer_id: Buyer party identifier
        buyer_name: Buyer party name
        catalogue_id: Unique identifier for the catalogue
        currency: ISO 4217 currency code (default: EUR)
        language: ISO 639-1 language code (default: en)
        include_prices: Include pricing information (default: True)
        include_media: Include media references (default: True)
        include_classifications: Include commodity classifications (default: True)
        ubl_version: UBL version (default: 2.1)
        async_export: Run export as background job (default: False)

    Returns:
        dict: Export result with status, file_url, or job_id
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    try:
        if products and isinstance(products, str):
            products = json.loads(products)

        if async_export:
            return _enqueue_format_export(
                format_type="ubl",
                profile_name=profile_name,
                products=products,
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                supplier_country=supplier_country,
                buyer_id=buyer_id,
                buyer_name=buyer_name,
                catalogue_id=catalogue_id,
                currency=currency,
                language=language,
                include_prices=include_prices,
                include_media=include_media,
                include_classifications=include_classifications,
                ubl_version=ubl_version
            )

        from frappe_pim.pim.export.ubl import export_catalogue as ubl_export_catalogue

        file_url = ubl_export_catalogue(
            profile_name=profile_name,
            products=products,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_country=supplier_country,
            buyer_id=buyer_id,
            buyer_name=buyer_name,
            catalogue_id=catalogue_id,
            currency=currency,
            language=language,
            include_prices=include_prices,
            include_media=include_media,
            include_classifications=include_classifications,
            ubl_version=ubl_version,
            save_file=True
        )

        if profile_name:
            _update_profile_status(profile_name, "Completed", file_url)

        return {
            "success": True,
            "format": f"UBL {ubl_version}",
            "file_url": file_url,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"UBL export failed: {str(e)}",
            title="PIM Export Error"
        )
        if profile_name:
            _update_profile_status(profile_name, "Failed", error=str(e))
        return {"success": False, "error": str(e)}


def export_gs1_xml(
    profile_name=None,
    products=None,
    gln_brand_owner=None,
    gln_information_provider=None,
    gln_data_recipient=None,
    data_pool_gln=None,
    target_market="US",
    document_command="ADD",
    language="en",
    include_hierarchy=True,
    include_measurements=True,
    include_packaging=True,
    async_export=False
):
    """Export products to GS1 XML format for GDSN data pool synchronization.

    GS1 XML is the standard format for exchanging product data through
    the Global Data Synchronization Network (GDSN).

    Args:
        profile_name: Name of Export Profile to use for settings
        products: JSON list of product names to export (optional)
        gln_brand_owner: GLN of the brand owner (13-digit)
        gln_information_provider: GLN of the information provider (13-digit)
        gln_data_recipient: GLN of the data recipient (13-digit)
        data_pool_gln: GLN of the source data pool
        target_market: ISO 3166-1 numeric country code or "001" for global
        document_command: ADD, CHANGE_BY_REFRESH, DELETE, or CORRECT
        language: ISO 639-1 language code (default: en)
        include_hierarchy: Include trade item hierarchy information (default: True)
        include_measurements: Include dimensions and weight (default: True)
        include_packaging: Include packaging information (default: True)
        async_export: Run export as background job (default: False)

    Returns:
        dict: Export result with status, file_url, or job_id
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    try:
        if products and isinstance(products, str):
            products = json.loads(products)

        if async_export:
            return _enqueue_format_export(
                format_type="gs1_xml",
                profile_name=profile_name,
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
                include_packaging=include_packaging
            )

        from frappe_pim.pim.export.gs1_xml import (
            export_catalogue_item_notification as gs1_export_cin
        )

        file_url = gs1_export_cin(
            profile_name=profile_name,
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
            save_file=True
        )

        if profile_name:
            _update_profile_status(profile_name, "Completed", file_url)

        return {
            "success": True,
            "format": "GS1 XML",
            "file_url": file_url,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"GS1 XML export failed: {str(e)}",
            title="PIM Export Error"
        )
        if profile_name:
            _update_profile_status(profile_name, "Failed", error=str(e))
        return {"success": False, "error": str(e)}


def export_edifact(
    profile_name=None,
    products=None,
    sender_id=None,
    sender_qualifier="14",
    recipient_id=None,
    recipient_qualifier="14",
    supplier_gln=None,
    supplier_name=None,
    buyer_gln=None,
    buyer_name=None,
    currency="EUR",
    message_type="PRICAT",
    include_prices=True,
    include_descriptions=True,
    async_export=False
):
    """Export products to UN/EDIFACT format.

    EDIFACT is the international EDI standard for electronic document
    exchange in commerce and transport.

    Args:
        profile_name: Name of Export Profile to use for settings
        products: JSON list of product names to export (optional)
        sender_id: Interchange sender identification
        sender_qualifier: Sender ID qualifier (default: 14 for GLN)
        recipient_id: Interchange recipient identification
        recipient_qualifier: Recipient ID qualifier (default: 14 for GLN)
        supplier_gln: Supplier GLN (Global Location Number)
        supplier_name: Supplier name
        buyer_gln: Buyer GLN
        buyer_name: Buyer name
        currency: ISO 4217 currency code (default: EUR)
        message_type: PRICAT (Price/Catalogue) or PRODAT (Product Data)
        include_prices: Include pricing information (default: True)
        include_descriptions: Include product descriptions (default: True)
        async_export: Run export as background job (default: False)

    Returns:
        dict: Export result with status, file_url, or job_id
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    try:
        if products and isinstance(products, str):
            products = json.loads(products)

        if async_export:
            return _enqueue_format_export(
                format_type="edifact",
                profile_name=profile_name,
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
                message_type=message_type,
                include_prices=include_prices,
                include_descriptions=include_descriptions
            )

        if message_type.upper() == "PRODAT":
            from frappe_pim.pim.export.edifact import export_prodat as edi_export
        else:
            from frappe_pim.pim.export.edifact import export_pricat as edi_export

        file_url = edi_export(
            profile_name=profile_name,
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
            include_prices=include_prices,
            include_descriptions=include_descriptions,
            save_file=True
        )

        if profile_name:
            _update_profile_status(profile_name, "Completed", file_url)

        return {
            "success": True,
            "format": f"EDIFACT {message_type}",
            "file_url": file_url,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"EDIFACT export failed: {str(e)}",
            title="PIM Export Error"
        )
        if profile_name:
            _update_profile_status(profile_name, "Failed", error=str(e))
        return {"success": False, "error": str(e)}


def export_xlsx(
    profile_name=None,
    products=None,
    product_family=None,
    status_filter=None,
    completeness_threshold=0,
    include_variants=True,
    include_attributes=True,
    include_media=True,
    include_prices=True,
    freeze_panes=True,
    auto_filter=True,
    language=None,
    async_export=False
):
    """Export products to XLSX (Microsoft Excel) format.

    Uses openpyxl with write_only mode for memory-efficient handling
    of large catalogs (100k+ products).

    Args:
        profile_name: Name of Export Profile to use for settings
        products: JSON list of product names to export (optional)
        product_family: Filter by Product Family
        status_filter: Filter by product status
        completeness_threshold: Minimum completeness score (0-100)
        include_variants: Include variants sheet (default: True)
        include_attributes: Include attributes sheet (default: True)
        include_media: Include media sheet (default: True)
        include_prices: Include prices sheet (default: True)
        freeze_panes: Freeze header row (default: True)
        auto_filter: Enable auto-filter on headers (default: True)
        language: Export in specific language
        async_export: Run export as background job (default: False)

    Returns:
        dict: Export result with status, file_url, or job_id
    """
    import frappe
    from frappe import _
    import json

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    try:
        if products and isinstance(products, str):
            products = json.loads(products)

        if async_export:
            return _enqueue_format_export(
                format_type="xlsx",
                profile_name=profile_name,
                products=products,
                product_family=product_family,
                status_filter=status_filter,
                completeness_threshold=completeness_threshold,
                include_variants=include_variants,
                include_attributes=include_attributes,
                include_media=include_media,
                include_prices=include_prices,
                freeze_panes=freeze_panes,
                auto_filter=auto_filter,
                language=language
            )

        # Get products if not specified
        if not products:
            products = _get_products_for_export(
                profile_name=profile_name,
                product_family=product_family,
                status_filter=status_filter,
                completeness_threshold=completeness_threshold
            )

        from frappe_pim.pim.export.xlsx import export_catalog as xlsx_export_catalog

        file_url = xlsx_export_catalog(
            profile_name=profile_name,
            products=products,
            include_variants=include_variants,
            include_attributes=include_attributes,
            include_media=include_media,
            include_prices=include_prices,
            freeze_panes=freeze_panes,
            auto_filter=auto_filter,
            language=language,
            save_file=True
        )

        if profile_name:
            _update_profile_status(profile_name, "Completed", file_url)

        return {
            "success": True,
            "format": "XLSX",
            "file_url": file_url,
            "product_count": len(products) if products else 0,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"XLSX export failed: {str(e)}",
            title="PIM Export Error"
        )
        if profile_name:
            _update_profile_status(profile_name, "Failed", error=str(e))
        return {"success": False, "error": str(e)}


def generate_feed(profile):
    """Generate export feed for a profile (background job handler).

    This function is called by the scheduler or enqueued as a background
    job. It determines the export format and calls the appropriate
    export function.

    Supported formats:
    - BMEcat 2005, BMEcat 1.2: B2B product catalog XML standard
    - CSV: Comma-separated values
    - TSV: Tab-separated values
    - JSON: JavaScript Object Notation
    - XML: Generic XML format
    - cXML: Commerce XML for procurement
    - UBL 2.x: Universal Business Language
    - GS1 XML: GDSN data pool synchronization
    - EDIFACT: UN/EDI standard for commerce
    - XLSX: Microsoft Excel format

    Args:
        profile: Export Profile name

    Returns:
        dict: Export result with status and file_url
    """
    import frappe

    try:
        profile_doc = frappe.get_doc("Export Profile", profile)

        if not profile_doc.enabled:
            return {"success": False, "error": "Profile is disabled"}

        # Update status to running
        frappe.db.set_value(
            "Export Profile", profile,
            {"export_status": "Running", "error_message": None},
            update_modified=True
        )
        frappe.db.commit()

        # Determine format and call appropriate export function
        export_format = profile_doc.export_format

        if export_format in ["BMEcat 2005", "BMEcat 1.2"]:
            result = export_bmecat(profile_name=profile)
        elif export_format == "CSV":
            result = export_csv(profile_name=profile)
        elif export_format == "TSV":
            result = export_tsv(profile_name=profile)
        elif export_format == "JSON":
            result = export_json(profile_name=profile)
        elif export_format == "XML":
            result = _export_generic_xml(profile_name=profile)
        elif export_format == "cXML":
            result = export_cxml(profile_name=profile)
        elif export_format in ["UBL", "UBL 2.x", "UBL 2.1"]:
            result = export_ubl(profile_name=profile)
        elif export_format in ["GS1 XML", "GS1", "GDSN"]:
            result = export_gs1_xml(profile_name=profile)
        elif export_format in ["EDIFACT", "EDI"]:
            result = export_edifact(profile_name=profile)
        elif export_format in ["XLSX", "Excel"]:
            result = export_xlsx(profile_name=profile)
        else:
            result = {"success": False, "error": f"Unsupported format: {export_format}"}

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Feed generation failed for {profile}: {str(e)}",
            title="PIM Export Error"
        )
        _update_profile_status(profile, "Failed", error=str(e))
        return {"success": False, "error": str(e)}


def run_export(profile_name, async_mode=True):
    """Trigger export for a specific profile.

    This is a convenience endpoint that queues an export job for
    the specified profile.

    Args:
        profile_name: Name of the Export Profile
        async_mode: Run as background job (default: True)

    Returns:
        dict: Status with job_id if async, or result if sync
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        profile = frappe.get_doc("Export Profile", profile_name)

        if not profile.enabled:
            frappe.throw(_("Export profile is disabled"))

        if async_mode:
            # Enqueue background job
            job = frappe.enqueue(
                "frappe_pim.pim.api.export.generate_feed",
                queue="long",
                timeout=3600,
                profile=profile_name
            )

            # Update status
            frappe.db.set_value(
                "Export Profile", profile_name,
                {"export_status": "Queued"},
                update_modified=True
            )

            return {
                "success": True,
                "message": _("Export job queued"),
                "job_id": str(job.id) if hasattr(job, 'id') else str(job),
                "profile": profile_name
            }
        else:
            # Run synchronously
            return generate_feed(profile_name)

    except Exception as e:
        frappe.log_error(
            message=f"Failed to run export for {profile_name}: {str(e)}",
            title="PIM Export Error"
        )
        return {"success": False, "error": str(e)}


def get_export_status(profile_name):
    """Get current export status for a profile.

    Args:
        profile_name: Name of the Export Profile

    Returns:
        dict: Status information including last export and file URL
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        profile = frappe.get_doc("Export Profile", profile_name)

        return {
            "profile_name": profile_name,
            "export_status": profile.export_status or "Not Started",
            "last_export": profile.last_export,
            "last_file": profile.last_file,
            "error_message": profile.error_message,
            "format": profile.export_format,
            "enabled": profile.enabled
        }

    except frappe.DoesNotExistError:
        return {"success": False, "error": "Profile not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def download_export(profile_name=None, file_url=None):
    """Get download information for an export file.

    Args:
        profile_name: Get latest export file for this profile
        file_url: Direct file URL to download

    Returns:
        dict: Download information with URL and metadata
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        if file_url:
            # Direct file download
            return {
                "success": True,
                "download_url": file_url,
                "filename": file_url.split("/")[-1]
            }

        if profile_name:
            # Get latest file from profile
            profile = frappe.get_doc("Export Profile", profile_name)

            if not profile.last_file:
                return {
                    "success": False,
                    "error": "No export file available for this profile"
                }

            return {
                "success": True,
                "download_url": profile.last_file,
                "filename": profile.last_file.split("/")[-1],
                "last_export": profile.last_export,
                "format": profile.export_format
            }

        return {"success": False, "error": "Profile name or file URL required"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_export_profiles(enabled_only=True, format_filter=None):
    """Get list of export profiles.

    Args:
        enabled_only: Only return enabled profiles (default: True)
        format_filter: Filter by export format (optional)

    Returns:
        list: Export profile records
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    filters = {}

    if enabled_only:
        filters["enabled"] = 1

    if format_filter:
        filters["export_format"] = format_filter

    return frappe.get_all(
        "Export Profile",
        filters=filters,
        fields=[
            "name", "profile_name", "profile_code", "export_format",
            "enabled", "is_scheduled", "export_status", "last_export",
            "last_file", "sort_order"
        ],
        order_by="sort_order asc"
    )


def preview_export_data(profile_name, limit=10):
    """Preview products that would be exported.

    Returns a sample of products matching the profile's filter
    criteria without actually generating an export file.

    Args:
        profile_name: Name of the Export Profile
        limit: Maximum products to return (default: 10)

    Returns:
        dict: Preview data with product count and sample
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    try:
        profile = frappe.get_doc("Export Profile", profile_name)

        # Build filters from profile
        filters = profile.build_product_filters()

        # Get total count
        total_count = frappe.db.count("Product Master", filters)

        # Get preview sample
        preview = frappe.get_all(
            "Product Master",
            filters=filters,
            fields=[
                "name", "product_name", "product_code", "status",
                "completeness_score", "product_family"
            ],
            limit=limit,
            order_by="modified desc"
        )

        return {
            "profile_name": profile_name,
            "format": profile.export_format,
            "total_products": total_count,
            "preview": preview,
            "filters_applied": filters
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_export_history(profile_name=None, limit=20):
    """Get export history log.

    Args:
        profile_name: Filter by profile (optional)
        limit: Maximum records to return

    Returns:
        list: Export history records
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    filters = {}
    if profile_name:
        filters["export_profile"] = profile_name

    # Try to get from PIM Export Log if it exists
    try:
        return frappe.get_all(
            "PIM Export Log",
            filters=filters,
            fields=[
                "name", "export_profile", "export_format",
                "status", "file_url", "product_count",
                "creation", "error_message"
            ],
            limit=limit,
            order_by="creation desc"
        )
    except frappe.exceptions.DoesNotExistError:
        # Fallback if log DocType doesn't exist
        return []


def get_supported_formats():
    """Get list of all supported export formats.

    Returns:
        dict: Dictionary of supported formats with metadata
    """
    return {
        "success": True,
        "formats": SUPPORTED_FORMATS,
        "format_list": list(SUPPORTED_FORMATS.keys())
    }


def export_by_format(
    format_type,
    profile_name=None,
    products=None,
    async_export=False,
    **kwargs
):
    """Unified export function supporting all 10 feed formats.

    This is the main entry point for programmatic exports, allowing
    any format to be exported with a single function call.

    Supported formats:
    - bmecat, bmecat_1.2: BMEcat XML catalog standard
    - csv: Comma-separated values
    - tsv: Tab-separated values
    - json: JavaScript Object Notation
    - xml: Generic XML format
    - cxml: Commerce XML for procurement
    - ubl: Universal Business Language 2.x
    - gs1_xml: GS1 XML for GDSN
    - edifact: UN/EDIFACT EDI format
    - xlsx: Microsoft Excel format

    Args:
        format_type: Export format key (e.g., 'bmecat', 'csv', 'xlsx')
        profile_name: Name of Export Profile to use (optional)
        products: JSON list of product names to export (optional)
        async_export: Run as background job (default: False)
        **kwargs: Format-specific parameters passed to the export function

    Returns:
        dict: Export result with status, file_url, or job_id

    Example:
        >>> # Export to CSV
        >>> result = export_by_format('csv', profile_name='my_profile')

        >>> # Export to GS1 XML with specific parameters
        >>> result = export_by_format(
        ...     'gs1_xml',
        ...     gln_brand_owner='1234567890123',
        ...     target_market='US',
        ...     async_export=True
        ... )
    """
    import frappe
    from frappe import _

    if not frappe.has_permission("Export Profile", "read"):
        frappe.throw(_("Not permitted to run exports"), frappe.PermissionError)

    # Normalize format name
    format_key = format_type.lower().replace(" ", "_").replace(".", "_")

    # Map format aliases
    format_aliases = {
        "bmecat_2005": "bmecat",
        "bmecat_12": "bmecat_1.2",
        "tab": "tsv",
        "excel": "xlsx",
        "edi": "edifact",
        "gdsn": "gs1_xml",
        "gs1": "gs1_xml",
        "ubl_2": "ubl",
        "ubl_21": "ubl",
        "ubl_2_1": "ubl",
    }
    format_key = format_aliases.get(format_key, format_key)

    # Validate format
    if format_key not in SUPPORTED_FORMATS:
        return {
            "success": False,
            "error": f"Unsupported format: {format_type}. Supported formats: {', '.join(SUPPORTED_FORMATS.keys())}"
        }

    # Route to appropriate export function
    export_functions = {
        "bmecat": export_bmecat,
        "bmecat_1.2": export_bmecat,
        "csv": export_csv,
        "tsv": export_tsv,
        "json": export_json,
        "xml": _export_generic_xml,
        "cxml": export_cxml,
        "ubl": export_ubl,
        "gs1_xml": export_gs1_xml,
        "edifact": export_edifact,
        "xlsx": export_xlsx,
    }

    export_func = export_functions.get(format_key)
    if not export_func:
        return {"success": False, "error": f"Export function not found for format: {format_key}"}

    try:
        return export_func(
            profile_name=profile_name,
            products=products,
            async_export=async_export,
            **kwargs
        )
    except Exception as e:
        frappe.log_error(
            message=f"Export failed for format {format_type}: {str(e)}",
            title="PIM Export Error"
        )
        return {"success": False, "error": str(e)}


# ============================================================================
# Internal Helper Functions
# ============================================================================

def _enqueue_bmecat_export(**kwargs):
    """Enqueue BMEcat export as background job."""
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.export.export_bmecat",
        queue="long",
        timeout=3600,
        **kwargs,
        async_export=False  # Prevent infinite loop
    )

    return {
        "success": True,
        "async": True,
        "message": "Export job queued",
        "job_id": str(job.id) if hasattr(job, 'id') else str(job)
    }


def _enqueue_csv_export(**kwargs):
    """Enqueue CSV export as background job."""
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.export.export_csv",
        queue="long",
        timeout=1800,
        **kwargs,
        async_export=False
    )

    return {
        "success": True,
        "async": True,
        "message": "CSV export job queued",
        "job_id": str(job.id) if hasattr(job, 'id') else str(job)
    }


def _enqueue_json_export(**kwargs):
    """Enqueue JSON export as background job."""
    import frappe

    job = frappe.enqueue(
        "frappe_pim.pim.api.export.export_json",
        queue="long",
        timeout=1800,
        **kwargs,
        async_export=False
    )

    return {
        "success": True,
        "async": True,
        "message": "JSON export job queued",
        "job_id": str(job.id) if hasattr(job, 'id') else str(job)
    }


def _enqueue_format_export(format_type, **kwargs):
    """Enqueue export of any format as background job.

    Args:
        format_type: One of: cxml, ubl, gs1_xml, edifact, xlsx

    Returns:
        dict: Job status with job_id
    """
    import frappe

    # Map format to export function
    format_functions = {
        "cxml": "frappe_pim.pim.api.export.export_cxml",
        "ubl": "frappe_pim.pim.api.export.export_ubl",
        "gs1_xml": "frappe_pim.pim.api.export.export_gs1_xml",
        "edifact": "frappe_pim.pim.api.export.export_edifact",
        "xlsx": "frappe_pim.pim.api.export.export_xlsx",
    }

    export_function = format_functions.get(format_type)
    if not export_function:
        return {
            "success": False,
            "error": f"Unsupported async export format: {format_type}"
        }

    job = frappe.enqueue(
        export_function,
        queue="long",
        timeout=3600,
        **kwargs,
        async_export=False  # Prevent infinite loop
    )

    format_name = SUPPORTED_FORMATS.get(format_type, {}).get("name", format_type)

    return {
        "success": True,
        "async": True,
        "format": format_name,
        "message": f"{format_name} export job queued",
        "job_id": str(job.id) if hasattr(job, 'id') else str(job)
    }


def _get_products_for_export(
    profile_name=None,
    product_family=None,
    status_filter=None,
    completeness_threshold=0
):
    """Get list of product names matching export criteria.

    Args:
        profile_name: Export Profile to get filters from
        product_family: Filter by family
        status_filter: Filter by status
        completeness_threshold: Minimum completeness score

    Returns:
        list: List of product names
    """
    import frappe

    filters = {}

    # Load filters from profile if provided
    if profile_name:
        try:
            profile = frappe.get_doc("Export Profile", profile_name)
            if profile.product_family:
                filters["product_family"] = profile.product_family
            if profile.status_filter:
                filters["status"] = profile.status_filter
            if profile.completeness_threshold:
                completeness_threshold = profile.completeness_threshold
        except Exception:
            pass

    # Override with explicit parameters
    if product_family:
        filters["product_family"] = product_family
    if status_filter:
        filters["status"] = status_filter

    # Add completeness filter
    if completeness_threshold > 0:
        filters["completeness_score"] = [">=", completeness_threshold]

    # Get product names
    products = frappe.get_all(
        "Product Master",
        filters=filters,
        pluck="name",
        order_by="modified desc"
    )

    return products


def _get_export_fields(profile_name=None):
    """Get list of fields to include in export.

    Args:
        profile_name: Export Profile to get field configuration

    Returns:
        list: Field names to export
    """
    # Default fields for CSV export
    default_fields = [
        "name", "product_name", "product_code", "status",
        "short_description", "product_family", "completeness_score",
        "created", "modified"
    ]

    if not profile_name:
        return default_fields

    # Could extend to load custom field mapping from profile
    return default_fields


def _get_product_row(product_name, fields):
    """Get a product data row for CSV export.

    Args:
        product_name: Name of the Product Master
        fields: List of field names to include

    Returns:
        list: Row values
    """
    import frappe

    try:
        product = frappe.get_doc("Product Master", product_name)
        return [product.get(field, "") for field in fields]
    except Exception:
        return ["" for _ in fields]


def _get_product_json(product_name, include_attributes=True, include_media=True):
    """Get product data as JSON-serializable dict.

    Args:
        product_name: Name of the Product Master
        include_attributes: Include EAV attributes
        include_media: Include media references

    Returns:
        dict: Product data
    """
    import frappe

    try:
        product = frappe.get_doc("Product Master", product_name)

        data = {
            "name": product.name,
            "product_name": product.product_name,
            "product_code": product.product_code,
            "status": product.status,
            "short_description": product.short_description,
            "long_description": product.long_description,
            "product_family": product.product_family,
            "completeness_score": product.completeness_score,
            "created": product.creation.isoformat() if product.creation else None,
            "modified": product.modified.isoformat() if product.modified else None
        }

        if include_attributes:
            data["attributes"] = _get_product_attributes(product)

        if include_media:
            data["media"] = _get_product_media(product)

        return data

    except Exception:
        return None


def _get_product_attributes(product):
    """Get product attributes as dict.

    Args:
        product: Product Master document

    Returns:
        dict: Attribute name -> value mapping
    """
    attributes = {}

    for attr_value in (product.get("attribute_values") or []):
        attr_code = attr_value.get("attribute")
        if not attr_code:
            continue

        # Get the value from appropriate column
        value = (
            attr_value.get("value_text") or
            attr_value.get("value_int") or
            attr_value.get("value_float") or
            attr_value.get("value_date") or
            attr_value.get("value_link")
        )

        if attr_value.get("value_boolean") is not None:
            value = attr_value.get("value_boolean")

        attributes[attr_code] = value

    return attributes


def _get_product_media(product):
    """Get product media as list.

    Args:
        product: Product Master document

    Returns:
        list: Media items
    """
    media_list = []

    # Primary image
    if product.get("image"):
        media_list.append({
            "type": "image",
            "url": product.image,
            "is_primary": True
        })

    # Additional media from child table
    for media in (product.get("media") or []):
        media_list.append({
            "type": media.get("media_type", "image"),
            "url": media.get("file_url"),
            "is_primary": False
        })

    return media_list


def _export_generic_xml(profile_name):
    """Export to generic XML format.

    Args:
        profile_name: Export Profile name

    Returns:
        dict: Export result
    """
    import frappe

    try:
        from lxml import etree
    except ImportError:
        return {"success": False, "error": "lxml is required for XML export"}

    try:
        products = _get_products_for_export(profile_name=profile_name)

        # Build XML
        root = etree.Element("products")

        for product_name in products:
            product_data = _get_product_json(product_name)
            if product_data:
                product_elem = etree.SubElement(root, "product")
                product_elem.set("id", product_name)

                for key, value in product_data.items():
                    if value is not None and key not in ["attributes", "media"]:
                        elem = etree.SubElement(product_elem, key)
                        elem.text = str(value)

        xml_content = etree.tostring(
            root,
            encoding="unicode",
            pretty_print=True,
            xml_declaration=True
        )

        file_url = _save_export_file(xml_content, "xml", profile_name)

        if profile_name:
            _update_profile_status(profile_name, "Completed", file_url)

        return {
            "success": True,
            "format": "XML",
            "file_url": file_url,
            "product_count": len(products),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        frappe.log_error(
            message=f"XML export failed: {str(e)}",
            title="PIM Export Error"
        )
        return {"success": False, "error": str(e)}


def _save_export_file(content, format_type, profile_name=None):
    """Save export content to file.

    Args:
        content: File content string
        format_type: File format (csv, json, xml)
        profile_name: Export profile name for filename

    Returns:
        str: File URL
    """
    import frappe

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name_part = profile_name or "pim_export"
    filename = f"{name_part}_{timestamp}.{format_type}"

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
        # Folder might not exist
        file_doc.folder = "Home"
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()

    return file_doc.file_url


def _update_profile_status(profile_name, status, file_url=None, error=None):
    """Update export profile status.

    Args:
        profile_name: Export Profile name
        status: New status (Running, Completed, Failed)
        file_url: URL of generated file
        error: Error message if failed
    """
    import frappe

    try:
        updates = {
            "export_status": status,
            "last_export": datetime.now() if status == "Completed" else None
        }

        if file_url:
            updates["last_file"] = file_url

        if error:
            updates["error_message"] = error[:500]  # Limit error length

        frappe.db.set_value(
            "Export Profile",
            profile_name,
            updates,
            update_modified=True
        )
        frappe.db.commit()

    except Exception:
        pass  # Don't fail export if status update fails


# Make functions available for frappe.whitelist()
# These need to be wrapped for @frappe.whitelist() decorator
def _wrap_for_whitelist():
    """Wrapper to add @frappe.whitelist() decorators at runtime."""
    import frappe

    # Add whitelist decorators
    global export_bmecat, export_csv, export_json, run_export
    global get_export_status, download_export, get_export_profiles
    global preview_export_data, get_export_history, generate_feed
    # New format-specific export functions
    global export_tsv, export_cxml, export_ubl, export_gs1_xml
    global export_edifact, export_xlsx
    # Unified export functions
    global export_by_format, get_supported_formats

    # Original exports
    export_bmecat = frappe.whitelist()(export_bmecat)
    export_csv = frappe.whitelist()(export_csv)
    export_json = frappe.whitelist()(export_json)

    # New format exports (all 10 formats)
    export_tsv = frappe.whitelist()(export_tsv)
    export_cxml = frappe.whitelist()(export_cxml)
    export_ubl = frappe.whitelist()(export_ubl)
    export_gs1_xml = frappe.whitelist()(export_gs1_xml)
    export_edifact = frappe.whitelist()(export_edifact)
    export_xlsx = frappe.whitelist()(export_xlsx)

    # Unified export and format listing
    export_by_format = frappe.whitelist()(export_by_format)
    get_supported_formats = frappe.whitelist()(get_supported_formats)

    # Export management functions
    run_export = frappe.whitelist()(run_export)
    get_export_status = frappe.whitelist()(get_export_status)
    download_export = frappe.whitelist()(download_export)
    get_export_profiles = frappe.whitelist()(get_export_profiles)
    preview_export_data = frappe.whitelist()(preview_export_data)
    get_export_history = frappe.whitelist()(get_export_history)
    generate_feed = frappe.whitelist(allow_guest=False)(generate_feed)


# Try to add whitelist decorators if frappe is available
try:
    _wrap_for_whitelist()
except ImportError:
    pass  # frappe not available, decorators will be added when module is used
