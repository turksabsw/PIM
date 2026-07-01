# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductCollection(Document):
    """Product Collection DocType for collection-level product grouping.

    Collections provide a flexible way to group products that may span
    multiple families or categories. Common use cases include:
    - Seasonal collections (Summer 2026, Holiday Collection)
    - Promotional groupings (Best Sellers, New Arrivals)
    - Brand lines (Premium Line, Budget Line)
    - Thematic groups (Eco-Friendly, Professional Series)

    Collections support:
    - Hierarchical organization via parent_collection
    - Validity dates for time-limited collections
    - Display ordering for merchandising control
    - Optional linking to Product Family for hierarchy integration
    """

    def validate(self):
        """Validate the Product Collection document."""
        self.validate_circular_reference()
        self.validate_dates()

    def validate_circular_reference(self):
        """Prevent circular references in parent collection hierarchy."""
        if not self.parent_collection:
            return

        import frappe

        # Check for direct self-reference
        if self.parent_collection == self.name:
            frappe.throw("A collection cannot be its own parent")

        # Check for circular reference in hierarchy
        visited = set([self.name])
        current = self.parent_collection

        while current:
            if current in visited:
                frappe.throw(
                    "Circular reference detected in collection hierarchy. "
                    f"Collection '{current}' appears multiple times in the chain."
                )
            visited.add(current)

            parent_doc = frappe.get_value(
                "Product Collection", current, "parent_collection"
            )
            current = parent_doc

    def validate_dates(self):
        """Validate that valid_from is before valid_to if both are set."""
        import frappe

        if self.valid_from and self.valid_to:
            if self.valid_from > self.valid_to:
                frappe.throw("'Valid From' date must be before 'Valid To' date")
