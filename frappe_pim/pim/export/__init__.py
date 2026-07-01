"""PIM Export Module

This module provides export functionality for generating product catalogs
in various formats including BMEcat 2005, cXML, GS1 XML, UBL, EDIFACT,
XLSX, CSV, JSON, and XML.

Available submodules:
- bmecat: BMEcat 2005/1.2 XML catalog generation
- cxml: cXML catalog and PunchOut support
- gs1_xml: GS1 XML for GDSN data pool synchronization
- ubl: UBL 2.x Catalogue, Invoice, and Order documents
- edifact: EDIFACT PRICAT and PRODAT messages
- xlsx: Excel XLSX export with write_only mode for large catalogs

Note: frappe imports are deferred to function level to allow module
import without Frappe being available (e.g., for testing/verification).
"""

from frappe_pim.pim.export.bmecat import export_catalog as export_bmecat_catalog
from frappe_pim.pim.export.cxml import (
    export_catalog as export_cxml_catalog,
    handle_punchout_setup,
    generate_punchout_order_message,
)
from frappe_pim.pim.export.gs1_xml import (
    export_catalogue_item_notification as export_gs1_cin,
    export_trade_item as export_gs1_trade_item,
    validate_gtin,
    validate_gs1_xml,
)
from frappe_pim.pim.export.ubl import (
    export_catalogue as export_ubl_catalogue,
    export_invoice as export_ubl_invoice,
    export_order as export_ubl_order,
)
from frappe_pim.pim.export.edifact import (
    export_pricat as export_edifact_pricat,
    export_prodat as export_edifact_prodat,
    validate_edifact,
)
from frappe_pim.pim.export.xlsx import (
    export_catalog as export_xlsx_catalog,
    export_single_sheet as export_xlsx_sheet,
    validate_xlsx,
    get_sheet_count as get_xlsx_sheet_count,
    get_row_count as get_xlsx_row_count,
    read_xlsx_products,
)

# Legacy alias for backward compatibility
export_catalog = export_bmecat_catalog

__all__ = [
    "export_catalog",
    "export_bmecat_catalog",
    "export_cxml_catalog",
    "handle_punchout_setup",
    "generate_punchout_order_message",
    "export_gs1_cin",
    "export_gs1_trade_item",
    "validate_gtin",
    "validate_gs1_xml",
    "export_ubl_catalogue",
    "export_ubl_invoice",
    "export_ubl_order",
    "export_edifact_pricat",
    "export_edifact_prodat",
    "validate_edifact",
    "export_xlsx_catalog",
    "export_xlsx_sheet",
    "validate_xlsx",
    "get_xlsx_sheet_count",
    "get_xlsx_row_count",
    "read_xlsx_products",
]
