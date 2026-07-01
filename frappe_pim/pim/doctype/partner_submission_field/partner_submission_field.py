"""Partner Submission Field DocType Controller

Child table for tracking individual field changes in partner submissions.
Each row represents a single field update proposed by the partner.
"""

import frappe
from frappe.model.document import Document


class PartnerSubmissionField(Document):
    """Controller for Partner Submission Field child table.

    Tracks individual field-level changes with per-field approval capability.
    """

    def validate(self):
        """Validate the field change entry."""
        self.validate_field_name()
        self.set_field_label()

    def validate_field_name(self):
        """Validate that field_name is provided."""
        if not self.field_name:
            frappe.throw("Field name is required")

    def set_field_label(self):
        """Set field label if not provided."""
        if self.field_label:
            return

        # Try to get label from Product Master doctype
        try:
            meta = frappe.get_meta("Product Master")
            field = meta.get_field(self.field_name)
            if field:
                self.field_label = field.label
            else:
                # Use field_name as fallback
                self.field_label = self.field_name.replace("_", " ").title()
        except Exception:
            self.field_label = self.field_name.replace("_", " ").title()

    def approve(self):
        """Mark this field as approved."""
        self.approval_status = "Approved"

    def reject(self, note: str = None):
        """Mark this field as rejected.

        Args:
            note: Optional reviewer note explaining rejection
        """
        self.approval_status = "Rejected"
        if note:
            self.reviewer_note = note
