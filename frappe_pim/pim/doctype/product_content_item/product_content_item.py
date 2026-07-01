# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductContentItem(Document):
    """Product Content Item child table for storing multiple HTML content blocks.

    This child table allows storing various types of content blocks per product,
    supporting different purposes like campaign text, technical tables, usage guides,
    marketing copy, and more. It supports:
    - Multiple content types (Campaign Text, Technical Table, Usage Guide, etc.)
    - Channel-specific content targeting
    - Variant-specific content
    - Locale-specific content for multi-language support
    - Time-limited content with validity dates (useful for campaigns)
    - Sort order for display priority

    Key Features:
    - Uses Frappe's Text Editor for rich HTML content
    - Links to Channel DocType for channel targeting
    - Links to Product Variant for variant-specific content
    - Links to Language for locale-specific content
    - Validity date range for time-limited content (e.g., promotions)
    - Active flag to enable/disable content blocks
    """

    pass
