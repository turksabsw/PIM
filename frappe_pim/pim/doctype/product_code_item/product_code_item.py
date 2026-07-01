# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductCodeItem(Document):
    """Product Code Item child table for storing multiple product/supplier/customer codes.

    This child table allows storing various code types linked to a product:
    - Product Code: Internal or external product codes
    - Supplier Code: Codes used by suppliers for ordering
    - Customer Code: Codes used by specific customers
    - Manufacturer Code: Codes assigned by manufacturers
    - Internal Code: Internal reference codes
    - Other: Any other code types

    The `is_primary` flag allows marking one code as the primary identifier
    for each code type.
    """

    pass
