# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductBarcodeItem(Document):
    """Product Barcode Item child table for storing multiple barcodes per product/variant.

    This child table allows storing various barcode types linked to a product:
    - EAN-13: European Article Number (13 digits)
    - UPC-A: Universal Product Code (12 digits)
    - EAN-8: Short EAN (8 digits)
    - UPC-E: Short UPC (6 digits)
    - Code 128: High-density alphanumeric barcode
    - Code 39: Alphanumeric barcode
    - QR Code: 2D matrix barcode
    - ISBN: International Standard Book Number
    - ISSN: International Standard Serial Number
    - GTIN-14: Global Trade Item Number (14 digits)
    - Other: Any other barcode types

    Barcodes can be:
    - Variant-specific (linked via apply_to_variant)
    - Unit-specific (linked via apply_to_uom for package-level barcodes)
    - Time-limited (using valid_from and valid_to dates)

    The `is_primary` flag allows marking one barcode as the primary identifier.
    """

    pass
