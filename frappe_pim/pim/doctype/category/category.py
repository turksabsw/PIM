# Copyright (c) 2026, Frappe PIM Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Category name keywords that are incompatible with each industry sector.
# If a category's name contains any of these keywords, creation is blocked.
INDUSTRY_FORBIDDEN_KEYWORDS: dict = {
    "food": [
        "hardware", "electronic", "tool", "machinery", "software",
        "vehicle", "automotive", "pharmaceutical", "textile", "apparel", "clothing",
    ],
    "fashion": [
        "hardware", "industrial machinery", "pharmaceutical", "chemical",
        "vehicle", "automotive",
    ],
    "electronics": [
        "food", "beverage", "grocery", "apparel", "clothing", "pharmaceutical",
    ],
    "industrial": [
        "food", "beverage", "fashion", "apparel", "clothing", "cosmetic",
    ],
    "health_beauty": [
        "hardware", "industrial machinery", "vehicle", "automotive", "food", "beverage",
    ],
    "automotive": [
        "food", "beverage", "fashion", "apparel", "clothing", "cosmetic", "pharmaceutical",
    ],
}

INDUSTRY_LABELS: dict = {
    "food": "Food & Beverage",
    "fashion": "Fashion & Apparel",
    "electronics": "Electronics",
    "industrial": "Industrial",
    "health_beauty": "Health & Beauty",
    "automotive": "Automotive",
    "custom": "Custom",
}


class Category(Document):
    def validate(self):
        self._validate_industry_compatibility()

    def _validate_industry_compatibility(self):
        try:
            industry = frappe.db.get_single_value("Tenant Config", "selected_industry")
        except Exception:
            return  # Tenant Config unavailable — skip restriction

        if not industry or industry == "custom":
            return  # No restriction for custom or unset industry

        forbidden = INDUSTRY_FORBIDDEN_KEYWORDS.get(industry, [])
        if not forbidden:
            return

        category_name = (self.category_name or self.name or "").lower()
        for keyword in forbidden:
            if keyword.lower() in category_name:
                industry_label = INDUSTRY_LABELS.get(industry, industry)
                frappe.throw(
                    _(
                        "The category name '{0}' contains '{1}', which is not compatible "
                        "with your selected industry ({2}). "
                        "Please create categories relevant to your business."
                    ).format(self.category_name or self.name, keyword, industry_label),
                    title=_("Industry Restriction"),
                )
