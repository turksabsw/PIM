"""
Allergen Item Controller

Child table DocType for storing allergen information in Nutrition Facts.
Each allergen item represents a GS1-compliant allergen declaration.
"""

import frappe
from frappe.model.document import Document


class AllergenItem(Document):
    """Allergen Item child table controller.

    Stores individual allergen declarations for a product's nutrition facts.
    Follows GS1 allergen type codes and containment levels.
    """

    pass
