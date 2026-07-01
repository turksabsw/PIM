# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductTranslationItem(Document):
    """Product Translation Item child table for storing multi-language product content.

    This child table allows storing translations for various product fields
    across different languages. It supports:
    - Translation of multiple fields (name, description, SEO metadata, etc.)
    - Verification workflow for quality assurance
    - Tracking of translation source (manual, machine, professional)
    - Audit trail of who translated and verified content

    Key Features:
    - Links to Frappe's Language DocType for standardized language codes
    - Multiple fields can be translated per language
    - Verification flag and metadata for quality control
    - Notes field for translator/reviewer communication
    """

    pass
